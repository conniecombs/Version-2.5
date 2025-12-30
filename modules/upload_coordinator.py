# modules/upload_coordinator.py
"""
Upload Coordinator - Business Logic Layer

Coordinates upload workflow, file processing, and state management.
Separates business logic from UI concerns for better maintainability.
"""

import os
import gc
import queue
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any, Callable
from dataclasses import dataclass
from loguru import logger

from . import api
from .path_validator import PathValidator
from .app_state import AppState
from .upload_manager import UploadManager
from .template_manager import TemplateManager
from .config_loader import get_config_loader
from .upload_history import get_upload_history, UploadRecord


@dataclass
class UploadResult:
    """Represents a successful upload result"""
    file_path: str
    image_url: str
    thumb_url: str


@dataclass
class GroupContext:
    """Context information for a file group"""
    title: str
    files: List[str]
    gallery_id: str = ""


class UploadCoordinator:
    """
    Coordinates the upload workflow and manages business logic.

    Responsibilities:
    - Upload lifecycle management (start, stop, finish)
    - File state tracking
    - Gallery finalization
    - Output file generation
    - Progress tracking
    - Result processing
    """

    def __init__(self,
                 state: AppState,
                 upload_manager: UploadManager,
                 template_manager: TemplateManager):
        """
        Initialize the upload coordinator.

        Args:
            state: Application state manager
            upload_manager: Upload execution manager
            template_manager: Template formatting manager
        """
        self.state = state
        self.upload_manager = upload_manager
        self.template_manager = template_manager
        self.app_config = get_config_loader().config
        self.upload_history = get_upload_history()

        # Upload state
        self.is_uploading = False
        self.upload_total = 0
        self.upload_count = 0
        self.current_session_id: Optional[str] = None

        # Gallery and output management
        self.pix_galleries_to_finalize: List[Dict[str, Any]] = []
        self.clipboard_buffer: List[str] = []
        self.current_output_files: List[str] = []

        # UI callbacks (set by UI layer)
        self.on_upload_start: Optional[Callable] = None
        self.on_upload_finish: Optional[Callable] = None
        self.on_upload_progress: Optional[Callable[[int, int]]] = None
        self.on_status_update: Optional[Callable[[str]]] = None

    def filter_pending_files(self, groups) -> Dict[Any, List[str]]:
        """
        Filter files that are pending upload from all groups.

        Args:
            groups: List of file groups

        Returns:
            Dictionary mapping groups to their pending files
        """
        pending_by_group = {}
        for grp in groups:
            for fp in grp.files:
                if self.state.files.file_widgets[fp]['state'] == 'pending':
                    if grp not in pending_by_group:
                        pending_by_group[grp] = []
                    pending_by_group[grp].append(fp)

        return pending_by_group

    def start_upload(self, pending_by_group: Dict[Any, List[str]],
                    settings: Dict[str, Any],
                    credentials: Dict[str, str]) -> bool:
        """
        Start the upload process.

        Args:
            pending_by_group: Dictionary of groups to pending files
            settings: Upload configuration settings
            credentials: Service credentials

        Returns:
            True if upload started successfully
        """
        if not pending_by_group:
            logger.warning("No pending files to upload")
            return False

        try:
            # Reset state
            self.state.upload.cancel_event.clear()
            self.state.results.results.clear()

            # Reset result queue
            self.state.queues.result_queue = queue.Queue()
            self.upload_manager.result_queue = self.state.queues.result_queue

            # Clear buffers
            self.pix_galleries_to_finalize.clear()
            self.clipboard_buffer.clear()
            self.current_output_files.clear()

            # Set upload counts
            self.upload_total = sum(len(v) for v in pending_by_group.values())
            self.upload_count = 0
            self.is_uploading = True

            # Start upload history session
            service = settings.get('service', 'unknown')
            self.current_session_id = self.upload_history.start_session(service, self.upload_total)

            # Update file states to 'queued'
            for files in pending_by_group.values():
                for fp in files:
                    self.state.files.file_widgets[fp]['state'] = 'queued'

            # Notify UI
            if self.on_upload_start:
                self.on_upload_start()

            if self.on_status_update:
                self.on_status_update("Starting...")

            # Start the upload batch
            self.upload_manager.start_batch(pending_by_group, settings, credentials)

            logger.info(f"Upload started: {self.upload_total} files across {len(pending_by_group)} groups (session: {self.current_session_id})")
            return True

        except Exception as e:
            logger.error(f"Failed to start upload: {e}")
            self.is_uploading = False
            raise

    def stop_upload(self):
        """Stop the current upload process."""
        self.state.upload.cancel_event.set()
        logger.info("Upload stop requested")

        if self.on_status_update:
            self.on_status_update("Stopping...")

    def finish_upload(self):
        """
        Finalize the upload process.
        Handles gallery finalization, cleanup, and notifications.
        """
        # Finalize Pixhost galleries if needed
        if self.pix_galleries_to_finalize:
            if self.on_status_update:
                self.on_status_update("Finalizing Galleries...")

            client = api.create_resilient_client()
            for gal in self.pix_galleries_to_finalize:
                try:
                    api.finalize_pixhost_gallery(
                        gal.get('gallery_upload_hash'),
                        gal.get('gallery_hash'),
                        client=client
                    )
                    logger.info(f"Finalized Pixhost gallery: {gal.get('gallery_hash')}")
                except Exception as e:
                    logger.error(f"Failed to finalize gallery: {e}")
            client.close()

        # Update state
        self.is_uploading = False

        # Notify UI
        if self.on_upload_finish:
            self.on_upload_finish()

        if self.on_status_update:
            self.on_status_update("All batches finished.")

        # Memory cleanup
        self.state.results.results.clear()
        self.pix_galleries_to_finalize.clear()

        # Trigger GC for large batches
        if self.upload_total > self.app_config.performance.gc_threshold_files:
            gc.collect()
            logger.info(f"Memory cleanup: Processed {self.upload_total} files, triggered GC")

        # End upload history session
        status = 'completed' if self.upload_count >= self.upload_total else 'interrupted'
        self.upload_history.end_session(status)

        logger.info(f"Upload finished: {self.upload_count}/{self.upload_total} completed (session: {self.current_session_id})")

    def increment_upload_count(self) -> int:
        """
        Increment and return the current upload count.

        Returns:
            Updated upload count
        """
        self.upload_count += 1

        # Notify progress callback
        if self.on_upload_progress:
            self.on_upload_progress(self.upload_count, self.upload_total)

        return self.upload_count

    def register_pixhost_gallery(self, gallery_data: Dict[str, Any]):
        """
        Register a Pixhost gallery for finalization.

        Args:
            gallery_data: Gallery metadata
        """
        self.pix_galleries_to_finalize.append(gallery_data)
        logger.debug(f"Registered Pixhost gallery: {gallery_data.get('gallery_hash')}")

    def generate_group_output(self,
                             group_context: GroupContext,
                             template_name: str,
                             service_name: str,
                             auto_copy: bool = False) -> Optional[str]:
        """
        Generate output file for a group.

        Args:
            group_context: Group metadata
            template_name: Template to use for formatting
            service_name: Upload service used
            auto_copy: Whether to buffer text for clipboard

        Returns:
            Path to generated output file, or None if no results
        """
        # Build result map
        res_map = {r[0]: (r[1], r[2]) for r in self.state.results.results}

        # Get results for this group
        group_results = []
        for fp in group_context.files:
            if fp in res_map:
                group_results.append(res_map[fp])

        if not group_results:
            logger.warning(f"No successful uploads for group '{group_context.title}'. Output skipped.")
            return None

        # Build gallery link
        cover_url = group_results[0][1] if group_results else ""
        gal_link = self._build_gallery_link(service_name, group_context.gallery_id)

        # Build template context
        ctx = {
            "gallery_link": gal_link,
            "gallery_name": group_context.title,
            "gallery_id": group_context.gallery_id,
            "cover_url": cover_url
        }

        # Apply template
        text = self.template_manager.apply(template_name, ctx, group_results)

        # Buffer for clipboard if requested
        if auto_copy:
            self.clipboard_buffer.append(text)

        # Generate safe output file
        try:
            safe_title = PathValidator.safe_filename(group_context.title, max_length=50)
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            output_filename = f"{safe_title}_{ts}.txt"

            out_path = PathValidator.validate_output_path(
                os.path.join("Output", output_filename),
                create_parent=True
            )

            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)

            self.current_output_files.append(str(out_path))
            logger.info(f"Generated output: {out_path}")
            return str(out_path)

        except Exception as e:
            logger.error(f"Failed to generate output for '{group_context.title}': {e}")
            return None

    def _build_gallery_link(self, service: str, gallery_id: str) -> str:
        """
        Build gallery URL for a service.

        Args:
            service: Service name
            gallery_id: Gallery identifier

        Returns:
            Full gallery URL
        """
        if not gallery_id:
            return ""

        if service == "pixhost.to":
            return f"https://pixhost.to/gallery/{gallery_id}"
        elif service == "imx.to":
            return f"https://imx.to/g/{gallery_id}"
        elif service == "vipr.im":
            return f"https://vipr.im/f/{gallery_id}"
        elif service == "turboimagehost":
            return f"https://www.turboimagehost.com/g/{gallery_id}"

        return ""

    def get_clipboard_text(self) -> str:
        """
        Get all buffered clipboard text.

        Returns:
            Combined clipboard text
        """
        return "\n\n".join(self.clipboard_buffer)

    def get_upload_progress(self) -> Tuple[int, int]:
        """
        Get current upload progress.

        Returns:
            Tuple of (completed_count, total_count)
        """
        return (self.upload_count, self.upload_total)

    def clear_results(self):
        """Clear all upload results and output files."""
        self.state.results.results.clear()
        self.current_output_files.clear()
        self.clipboard_buffer.clear()
        logger.debug("Cleared upload results and output files")
