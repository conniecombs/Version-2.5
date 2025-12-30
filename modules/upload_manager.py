# modules/upload_manager.py
import threading
import os
from concurrent.futures import ThreadPoolExecutor
from . import api
from . import config
from .config_loader import get_config_loader
from .error_handler import handle_upload_error, ErrorContext, ErrorSeverity, get_error_handler, handle_network_error
from .retry_utils import retry_on_network_error, RetryConfig, is_retryable_error
from loguru import logger

# Thread-local storage for HTTP clients (replaces the global one in main.py)
thread_local_data = threading.local()

# Load application configuration
_app_config = get_config_loader().config

def get_thread_client():
    if not hasattr(thread_local_data, "client"):
        thread_local_data.client = api.create_resilient_client()
    return thread_local_data.client

class UploadManager:
    def __init__(self, progress_queue, result_queue, cancel_event):
        self.progress_queue = progress_queue
        self.result_queue = result_queue
        self.cancel_event = cancel_event

    def start_batch(self, pending_by_group, cfg, creds):
        """
        Starts the upload batch in a separate thread to avoid freezing UI.
        """
        # Determine thread count based on service
        service_prefix = cfg['service'].split('.')[0]
        if service_prefix == 'turboimagehost':
            max_workers = cfg.get('turbo_threads', 2)
        else:
            max_workers = cfg.get(f"{service_prefix}_threads", 2)

        threading.Thread(
            target=self._run_executor, 
            args=(pending_by_group, cfg, creds, max_workers), 
            daemon=True
        ).start()

    def _run_executor(self, pending_by_group, base_cfg, creds, max_workers):
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for group, files in pending_by_group.items():
                    if self.cancel_event.is_set(): break
                    
                    # Prepare configuration for this group
                    current_cfg = base_cfg.copy()
                    current_pix_data = {}
                    client = get_thread_client()
                    
                    # --- Gallery Creation Logic ---
                    # (This logic is moved here from main.py to keep main clean)
                    if base_cfg['service'] == "pixhost.to":
                        if base_cfg.get('auto_gallery'):
                            clean_title = group.title.replace('[', '').replace(']', '').strip()
                            logger.info(f"Creating Pixhost gallery: {clean_title}")
                            new_data = api.create_pixhost_gallery(clean_title, client=client)
                            
                            if new_data: 
                                current_pix_data = new_data
                                # Signal main thread to register this gallery for finalization
                                self.progress_queue.put(('register_pix_gal', None, new_data))
                                group.gallery_id = new_data.get('gallery_hash', '')
                            else:
                                logger.warning(f"Failed to create gallery '{clean_title}'")

                        elif base_cfg.get('pix_gallery_hash'):
                            current_pix_data = {'gallery_hash': base_cfg['pix_gallery_hash']}
                            group.gallery_id = base_cfg['pix_gallery_hash']

                    elif base_cfg['service'] == "imx.to" and base_cfg.get('auto_gallery'):
                         gid = api.create_imx_gallery(creds.get('imx_user'), creds.get('imx_pass'), group.title, client=client)
                         if gid:
                             current_cfg['gallery_id'] = gid
                             group.gallery_id = gid

                    elif base_cfg['service'] == "vipr.im" and base_cfg.get('auto_gallery'):
                        # Vipr logic relies on session cookies, usually handled by client reuse
                        # For simplicity, we assume session is handled or passed
                        pass 

                    # Submit files to pool
                    for fp in files:
                        if self.cancel_event.is_set(): break
                        is_first = (fp == group.files[0])
                        executor.submit(
                            self._upload_task, 
                            fp, is_first, current_cfg, current_pix_data, 
                            creds, client
                        )
        except Exception as e:
            logger.error(f"Executor Error: {e}")
        finally:
            logger.info("Batch execution finished.")

    def _upload_task(self, fp, is_first, cfg, pix_data, creds, client):
        if self.cancel_event.is_set(): return
        
        self.progress_queue.put(('status', fp, 'Uploading'))
        
        try:
            # Progress Callback
            def cb(m):
                if self.cancel_event.is_set(): raise Exception("Cancelled")
                if m.len > 0: 
                    self.progress_queue.put(('prog', fp, (m.bytes_read/m.len)))

            uploader = None
            service = cfg['service']
            
            # Instantiate Uploader
            if service == "imx.to":
                th = "600" if (is_first and cfg['imx_cover']) else cfg['imx_thumb']
                uploader = api.ImxUploader(cfg['api_key'], fp, cb, th, cfg.get('imx_format', 'Fixed Width'), cfg.get('gallery_id'))
            
            elif service == "pixhost.to":
                is_cov = (is_first and cfg['pix_cover'])
                uploader = api.PixhostUploader(fp, cb, cfg['pix_content'], cfg['pix_thumb'], pix_data.get('gallery_hash'), pix_data.get('gallery_upload_hash'), is_cov)
            
            elif service == "turboimagehost":
                # Turbo needs cookies passed if logged in
                # In a robust app, you might pass cookies in creds or cfg
                th = "600" if (is_first and cfg.get('turbo_cover')) else cfg['turbo_thumb']
                # Note: We rely on the thread-local client having cookies if they were set globally, 
                # or we re-login. For now, we assume simple upload or anonymous.
                uploader = api.TurboUploader(fp, cb, config.TURBO_HOME_URL, api.generate_turbo_upload_id(), cfg['turbo_content'], th, cfg['turbo_gal_id'], client=client)
            
            elif service == "vipr.im":
                # Vipr logic is complex with sessions. 
                # Ideally pass session cookies in creds.
                th = "800x800" if (is_first and cfg.get('vipr_cover')) else cfg['vipr_thumb']
                uploader = api.ViprUploader(fp, cb, cfg.get('vipr_meta', {}).get('upload_url', config.VIPR_HOME_URL), "", th, cfg['vipr_gal_id'], client=client)

            # Execute Upload with retry logic
            if uploader:
                url, data, headers = uploader.get_request_params()

                def read_monitor_chunks(monitor):
                    while True:
                        chunk = monitor.read(_app_config.network.chunk_size)
                        if not chunk: break
                        yield chunk

                if 'Content-Length' not in headers and hasattr(data, 'len'):
                    headers['Content-Length'] = str(data.len)

                # Wrap upload in retry decorator with custom config
                retry_config = RetryConfig(
                    max_attempts=_app_config.network.retry_count,
                    base_delay=2.0,  # Start with 2 second delay
                    max_delay=30.0,  # Cap at 30 seconds
                    exponential_base=2.0  # Double the delay each retry
                )

                @retry_on_network_error(retry_config)
                def _perform_upload():
                    """Upload with automatic retry on network errors"""
                    self.progress_queue.put(('status', fp, 'Uploading'))
                    return client.post(
                        url,
                        headers=headers,
                        content=read_monitor_chunks(data),
                        timeout=_app_config.network.upload_timeout_seconds
                    )

                try:
                    r = _perform_upload()
                except Exception as retry_error:
                    # If retries exhausted, check if it was network error
                    if is_retryable_error(retry_error):
                        handle_network_error(retry_error, "Upload", service)
                    raise

                resp = r.text if service == 'vipr.im' else r.json()
                img, thumb = uploader.parse_response(resp)
                
                # Success
                self.result_queue.put((fp, img, thumb))
                self.progress_queue.put(('status', fp, 'Done'))
                
        except Exception as e:
            self.progress_queue.put(('status', fp, 'Failed'))
            # Use centralized error handler
            handle_upload_error(
                error=e,
                file_path=fp,
                service=cfg.get('service', 'unknown')
            )
        finally:
            if uploader: uploader.close()