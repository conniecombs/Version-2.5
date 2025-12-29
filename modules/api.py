# modules/api.py
"""
API Module for Connie's Uploader.
Uses httpx for modern, resilient HTTP/2 networking.
"""

import os
import mimetypes
import abc
import re
import random
from urllib.parse import urlparse, parse_qs
from typing import Dict, Tuple, Optional, Any

import httpx
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor
from bs4 import BeautifulSoup
from . import config
from .error_handler import handle_authentication_error, handle_network_error, ErrorContext, ErrorSeverity, get_error_handler
from loguru import logger

def create_resilient_client(retries=None):
    """
    Creates an httpx.Client with automatic retries and HTTP/2 support.
    """
    if retries is None:
        retries = config.HTTP_RETRY_COUNT
    transport = httpx.HTTPTransport(retries=retries)
    # http2=True enables modern, faster connections.
    client = httpx.Client(transport=transport, http2=True, timeout=config.HTTP_TIMEOUT_SECONDS)
    client.headers.update({'User-Agent': config.USER_AGENT})
    return client

# --- Turbo Helper Functions ---

def turbo_login(user, password, client: httpx.Client = None):
    """Logs into TurboImageHost and returns the session cookies."""
    should_close = False
    if not client:
        client = create_resilient_client()
        should_close = True

    try:
        try:
            client.get(config.TURBO_LOGIN_URL)
        except Exception as e:
            logger.error(f"Turbo Login Page Error: {e}")
            return None

        payload = {
            "username": user,
            "password": password,
            "remember": "y",
            "login": "Login"
        }
        
        # httpx handles redirects differently; we disable them here to check for the redirect response
        r = client.post(config.TURBO_LOGIN_URL, data=payload, follow_redirects=False)
        
        if r.status_code in [301, 302] or "logout.tu" in r.text:
            return client.cookies
        else:
            error = ValueError("Invalid credentials")
            handle_authentication_error(error, "turboimagehost")
            return None
    except Exception as e:
        handle_network_error(e, "Login", "turboimagehost")
        return None
    finally:
        if should_close: client.close()

def get_turbo_config(client: httpx.Client = None):
    """Scrapes the main page to find the dynamic upload endpoint."""
    should_close = False
    if not client:
        client = create_resilient_client()
        should_close = True
    try:
        r = client.get(config.TURBO_HOME_URL)
        match = re.search(r"endpoint:\s*'([^']+)'", r.text)
        if match:
            return match.group(1)
        return "https://www.turboimagehost.com/upload_html5.tu"
    except Exception as e:
        logger.error(f"Failed to get Turbo config: {e}")
        return None
    finally:
        if should_close: client.close()

def generate_turbo_upload_id():
    chars = "0123456789abcdefghiklmnopqrstuvwxyz"
    return "".join(random.choice(chars) for _ in range(20))

# --- Vipr Helper Functions ---

def vipr_login(user, password, client: httpx.Client = None):
    """Logs into Vipr.im and returns the authenticated client."""
    should_close = False
    if not client:
        client = create_resilient_client()
        should_close = True 
    
    payload = {
        "op": "login",
        "redirect": "",
        "login": user,
        "password": password,
        "submit": "Login"
    }
    try:
        r = client.post(config.VIPR_LOGIN_URL, data=payload)
        if "op=logout" in r.text or "xfss" in client.cookies:
            return client
        else:
            logger.error("Vipr Login Failed: Check credentials.")
            if should_close: client.close()
            return None
    except Exception as e:
        logger.error(f"Vipr Login Error: {e}")
        if should_close: client.close()
        return None

def get_vipr_metadata(client: httpx.Client):
    """Scrapes Vipr homepage for upload URL, session ID, and galleries."""
    try:
        r = client.get(config.VIPR_HOME_URL)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        upload_url = None
        form = soup.find('form', attrs={'name': 'file'})
        if form:
            upload_url = form.get('action')
        
        if not upload_url:
            match = re.search(r'action="([^"]+upload\.cgi[^"]*)"', r.text)
            if match:
                upload_url = match.group(1)

        if not upload_url:
            return None
        
        sess_input = soup.find('input', attrs={'name': 'sess_id'})
        sess_id = sess_input.get('value') if sess_input else None
        
        galleries = []
        select_box = soup.find('select', attrs={'name': 'fld_id'})
        if select_box:
            options = select_box.find_all('option')
            for opt in options:
                val = opt.get('value')
                if val and val not in ['0', '000']:
                    galleries.append({'id': val, 'name': opt.text.strip()})
                    
        return {
            'upload_url': upload_url,
            'sess_id': sess_id,
            'galleries': galleries
        }
    except Exception as e:
        logger.error(f"Vipr Metadata Error: {e}")
        return None

def create_vipr_gallery(client: httpx.Client, name):
    """Creates a new gallery via AJAX."""
    payload = {"op": "ajax_new_folder", "folder": name}
    headers = {
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': config.VIPR_HOME_URL,
        'Origin': config.VIPR_HOME_URL
    }
    try:
        r = client.post(config.VIPR_AJAX_URL, data=payload, headers=headers)
        if "option" in r.text.lower():
            match = re.search(r'value\s*=\s*[\'"]?(\d+)[\'"]?', r.text, re.IGNORECASE)
            if match:
                return match.group(1)
        logger.warning(f"Vipr Gallery created but ID not found. Resp: {r.text[:100]}")
        return None
    except Exception as e:
        logger.error(f"Vipr Gallery Create Error: {e}")
        return None

# --- Pixhost Gallery Helpers ---

def create_pixhost_gallery(name: str, client: httpx.Client = None) -> Optional[Dict[str, str]]:
    should_close = False
    if not client:
        client = create_resilient_client()
        should_close = True
    try:
        r = client.post(config.PIX_GALLERIES_URL, data={"gallery_name": name or "Untitled"})
        if r.status_code == 200:
            return r.json()
        logger.error(f"Pixhost Gallery Create Failed: {r.status_code} {r.text}")
        return None
    except Exception as e:
        logger.error(f"Pixhost Gallery Create Error: {e}")
        return None
    finally:
        if should_close: client.close()

def finalize_pixhost_gallery(upload_hash: str, gallery_hash: str, client: httpx.Client = None) -> bool:
    should_close = False
    if not client:
        client = create_resilient_client()
        should_close = True
    url = f"{config.PIX_GALLERIES_URL}/{gallery_hash}/finalize"
    payload = {'gallery_upload_hash': upload_hash}
    headers = {'Accept': 'application/json'}
    try:
        r = client.post(url, data=payload, headers=headers)
        return r.status_code == 200
    except Exception:
        return False
    finally:
        if should_close: client.close()

# --- IMX Gallery Creation Helpers ---

def create_imx_gallery(user, password, name, client: httpx.Client = None):
    """Logs in and creates a gallery on imx.to."""
    should_close = False
    if not client:
        client = create_resilient_client()
        should_close = True
    
    # 1. Login
    login_data = {"usr_email": user, "pwd": password, "remember": "1", "doLogin": "Login"}
    try:
        r = client.post(config.IMX_LOGIN_URL, data=login_data, follow_redirects=True)
        if str(r.url) != config.IMX_DASHBOARD_URL:
             pass
    except Exception as e:
        logger.error(f"IMX Login Error: {e}")
        if should_close: client.close()
        return None

    # 2. Create
    try:
        data = {"gallery_name": name, "submit_new_gallery": "Add"}
        resp = client.post(config.IMX_GALLERY_ADD_URL, data=data, follow_redirects=True)
        if "id=" in str(resp.url):
            gid = parse_qs(urlparse(str(resp.url)).query).get("id", [None])[0]
            if should_close: client.close()
            return gid
        logger.error(f"IMX Create Failed. URL: {resp.url}")
        if should_close: client.close()
        return None
    except Exception as e:
        logger.error(f"IMX Gallery Create Error: {e}")
        if should_close: client.close()
        return None

# --- Base Uploader Class ---

class BaseUploader(abc.ABC):
    def __init__(self, file_path: str, monitor_callback: Any):
        self.file_path = file_path
        self.basename = os.path.basename(file_path)
        self.mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
        self.file_obj = None
        self.monitor_callback = monitor_callback
        self.headers: Dict[str, str] = {
            'User-Agent': config.USER_AGENT
        }

    def get_monitor(self, fields: Dict[str, Any]) -> MultipartEncoderMonitor:
        encoder = MultipartEncoder(fields=fields)
        monitor = MultipartEncoderMonitor(encoder, self.monitor_callback)
        self.headers['Content-Type'] = monitor.content_type
        return monitor

    @abc.abstractmethod
    def get_request_params(self) -> Tuple[str, MultipartEncoderMonitor, Dict[str, str]]:
        pass

    @abc.abstractmethod
    def parse_response(self, data: Dict[str, Any]) -> Tuple[str, str]:
        pass

    def close(self) -> None:
        if self.file_obj:
            self.file_obj.close()

# --- Implementations ---

class TurboUploader(BaseUploader):
    def __init__(self, file_path: str, monitor_callback: Any, 
                 upload_endpoint: str, upload_id: str, 
                 content_type: str, thumb_size: str, gallery_id: Optional[str] = None, client: httpx.Client = None):
        super().__init__(file_path, monitor_callback)
        self.endpoint = upload_endpoint
        self.upload_id = upload_id
        self.imcontent = "adult" if content_type == "Adult" else "all"
        self.thumb_size = thumb_size
        self.gallery_id = gallery_id
        self.client = client if client else create_resilient_client()

    def get_request_params(self):
        self.file_obj = open(self.file_path, 'rb')
        fields = {
            "qqfile": (self.basename, self.file_obj, self.mime_type),
            "qquuid": str(random.randint(100000, 999999)),
            "qqfilename": self.basename,
            "qqtotalfilesize": str(os.path.getsize(self.file_path)),
            "imcontent": self.imcontent,
            "thumb_size": self.thumb_size,
            "upload_id": self.upload_id,
        }
        if self.gallery_id:
            fields["album"] = self.gallery_id
        return self.endpoint, self.get_monitor(fields), self.headers

    def parse_response(self, data):
        # Turbo returns JSON sometimes, HTML others depending on endpoint
        if "url" in data and data["url"]:
            img_url = data["url"]
            thumb_url = data.get("thumbnailUrl", img_url.replace("/p/", "/t/"))
            return img_url, thumb_url

        if "id" in data:
            fid = data.get("id")
            name = data.get("qqfilename", self.basename)
            page_url = f"https://www.turboimagehost.com/p/{fid}/{name}.html"
            return self._scrape_page(page_url)
        
        if "newUrl" in data:
            return self._scrape_page(data["newUrl"])

        raise ValueError("Upload failed: No URL or ID in response. " + str(data))

    def _scrape_page(self, page_url):
        try:
            r = self.client.get(page_url)
            img_match = re.search(r'<img[^>]*src="([^"]+)"[^>]*class="image"[^>]*>', r.text)
            if img_match:
                return img_match.group(1), img_match.group(1)
            return page_url, page_url
        except Exception as e:
            logger.error(f"Failed to scrape Turbo page {page_url}: {e}")
            return page_url, page_url

class ImxUploader(BaseUploader):
    def __init__(self, api_key: Optional[str], file_path: str, monitor_callback: Any,
                 thumb_size_str: str, thumb_format_str: str, gallery_id: Optional[str]):
        super().__init__(file_path, monitor_callback)
        self.api_key = api_key
        size_to_api_map = {"100": "1", "180": "2", "250": "3", "300": "4", "600": "5", "150": "6"}
        self.thumb_size = size_to_api_map.get(thumb_size_str, "2")
        format_map = {
            "Fixed Width": "1", "Fixed Height": "4", "Proportional": "2", "Square": "3"
        }
        self.thumb_format = format_map.get(thumb_format_str, "1")
        self.gallery_id = gallery_id

    def get_request_params(self):
        self.file_obj = open(self.file_path, 'rb')
        url = config.IMX_URL
        self.headers['X-API-KEY'] = self.api_key or ""
        fields = {
            "image": (self.basename, self.file_obj, self.mime_type),
            "format": "json",
            "thumbnail_size": self.thumb_size,
            "thumbnail_format": self.thumb_format,  
        }
        if self.gallery_id:
            fields["gallery_id"] = self.gallery_id
        return url, self.get_monitor(fields), self.headers

    def parse_response(self, data):
        if data.get("status") == "success":
            data_obj = data.get("data", {})
            return data_obj.get("image_url"), data_obj.get("thumbnail_url")
        raise ValueError(data.get("message", "API returned status=error"))

class PixhostUploader(BaseUploader):
    def __init__(self, file_path: str, monitor_callback: Any, content_type_str: str, thumb_size_str: str,
                 gallery_hash: Optional[str] = None, gallery_upload_hash: Optional[str] = None, is_cover: bool = False):
        super().__init__(file_path, monitor_callback)
        content_map = {"Safe": "0", "Adult": "1"}
        self.content_type = content_map.get(content_type_str, "0")
        self.gallery_hash = gallery_hash
        self.gallery_upload_hash = gallery_upload_hash
        self.is_cover = is_cover
        valid_thumbs = ["150", "200", "250", "300", "350", "400", "450", "500"]
        self.thumb_size = thumb_size_str if thumb_size_str in valid_thumbs else "200"

    def get_request_params(self):
        self.file_obj = open(self.file_path, 'rb')
        if self.is_cover:
            url = config.PIX_COVERS_URL
            fields = {
                "img_left": (self.basename, self.file_obj, self.mime_type),
                "content_type": self.content_type,
            }
        else:
            url = config.PIX_URL
            fields = {
                "img": (self.basename, self.file_obj, self.mime_type),
                "content_type": self.content_type,
                "max_th_size": self.thumb_size,
            }

        if self.gallery_hash:
            fields["gallery_hash"] = self.gallery_hash
        if self.gallery_upload_hash:
            fields["gallery_upload_hash"] = self.gallery_upload_hash
            
        return url, self.get_monitor(fields), self.headers

    def parse_response(self, data):
        if "show_url" in data:
            return data.get("show_url"), data.get("th_url")
        raise ValueError(f"API Error: {data.get('error_msg', 'Unknown error')}")

class ViprUploader(BaseUploader):
    def __init__(self, file_path: str, monitor_callback: Any, 
                 upload_url: str, sess_id: str, 
                 thumb_size: str, gallery_id: str = "0", client: httpx.Client = None):
        super().__init__(file_path, monitor_callback)
        self.upload_url = upload_url
        self.sess_id = sess_id
        self.thumb_size = thumb_size
        self.gallery_id = gallery_id if gallery_id else "0"
        self.client = client if client else create_resilient_client()
        
        self.headers['Referer'] = config.VIPR_HOME_URL
        self.headers['Origin'] = config.VIPR_HOME_URL

    def get_request_params(self):
        self.file_obj = open(self.file_path, 'rb')
        uid = "".join([str(random.randint(0, 9)) for _ in range(12)])
        base_url = self.upload_url.split('?')[0]
        final_url = f"{base_url}?upload_id={uid}&js_on=1&utype=reg&upload_type=file"
        
        fields = {
            "upload_type": "file",
            "sess_id": self.sess_id,
            "file_0": (self.basename, self.file_obj, self.mime_type),
            "thumb_size": self.thumb_size,
            "fld_id": self.gallery_id,
            "tos": "1",
            "submit_btn": "Upload"
        }
        
        return final_url, self.get_monitor(fields), self.headers

    def parse_response(self, data):
        soup = BeautifulSoup(data, 'html.parser')
        
        # XFS Redirect Handling
        fn_match = re.search(r"<textarea name=['\"]fn['\"]>([^<]+)</textarea>", data, re.IGNORECASE)
        op_match = re.search(r"<textarea name=['\"]op['\"]>upload_result</textarea>", data, re.IGNORECASE)
        
        if op_match and fn_match:
            code = fn_match.group(1)
            payload = {'op': 'upload_result', 'fn': code, 'st': 'OK'}
            try:
                r = self.client.post(config.VIPR_HOME_URL, data=payload)
                return self.parse_response(r.text)
            except Exception as e:
                logger.error(f"Vipr Redirect Error: {e}")
                return (f"{config.VIPR_HOME_URL}i/{code}/{self.basename}", 
                        f"{config.VIPR_HOME_URL}th/{code}/{self.basename}")

        if soup.find('title') and "520" in soup.find('title').text:
             raise ValueError("Server returned Cloudflare 520 Error (Rejected).")
        
        img_url = None
        thumb_url = None
        
        clean_name = self.basename.replace(" ", "_")
        name_div = soup.find('div', string=re.compile(re.escape(clean_name), re.IGNORECASE))
        
        if name_div:
            block = name_div.find_parent('div', class_='grey_block')
            if block:
                img_tag = block.find('img', src=True)
                if img_tag and "/th/" in img_tag['src']:
                    thumb_url = img_tag['src']
                
                link_tag = block.find('a', href=True)
                if link_tag and "vipr.im" in link_tag['href']:
                    img_url = link_tag['href']

        if not thumb_url:
            thumb_match = re.search(r'https?://(?:[a-z0-9]+\.)?vipr\.im/th/[^"\s\'<>]+\.(?:jpg|jpeg|png|gif|bmp|webp)', data, re.IGNORECASE)
            if thumb_match:
                thumb_url = thumb_match.group(0)
        
        if not img_url:
             direct_match = re.search(r'https?://vipr\.im/[a-z0-9]+', data, re.IGNORECASE)
             if direct_match:
                 img_url = direct_match.group(0)
            
        if not img_url:
            snippet = data[:500].replace("\n", " ")
            logger.error(f"Vipr Parse Fail. Response snippet: {snippet}")
            raise ValueError("Could not parse upload result page (No links found).")
            
        return img_url, thumb_url or img_url