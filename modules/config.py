# modules/config.py
import sys
import re
from loguru import logger
import os

# --- Version ---
APP_VERSION = "2.1.0"
USER_AGENT = f"ConniesUploader/{APP_VERSION}"

# --- UI Configuration ---
# Tkinter can hit recursion limit when rendering thousands of widgets
# This value allows ~1000 file entries without stack overflow
RECURSION_LIMIT = 3000

# UI update intervals (milliseconds)
UI_UPDATE_INTERVAL_MS = 20  # Balance between responsiveness and CPU usage

# Queue batch processing limits
UI_QUEUE_BATCH_SIZE = 20      # Max UI updates per cycle
PROGRESS_QUEUE_BATCH_SIZE = 50  # Max progress updates per cycle
RESULT_QUEUE_BATCH_SIZE = 10   # Max result processing per cycle

# Thumbnail generation
THUMBNAIL_WORKER_THREADS = 4    # Max parallel thumbnail generation threads
THUMBNAIL_SLEEP_WITH_PREVIEW = 0.01   # Delay between thumbnails (with preview)
THUMBNAIL_SLEEP_NO_PREVIEW = 0.001    # Delay between thumbnails (no preview)

# --- Threading Configuration ---
DEFAULT_THREAD_LIMITS = {
    'imx': 5,        # IMX.to can handle more concurrent uploads
    'pixhost': 3,    # Pixhost is more rate-limited
    'turbo': 2,      # Turbo is conservative
    'vipr': 1        # Vipr is strictest, single-threaded recommended
}

# --- Network Configuration ---
HTTP_TIMEOUT_SECONDS = 60.0    # Default timeout for HTTP requests
HTTP_RETRY_COUNT = 3           # Number of retries for failed requests
UPLOAD_TIMEOUT_SECONDS = 300   # Extended timeout for large file uploads
UPLOAD_CHUNK_SIZE = 8192       # Bytes to read per chunk during upload

# --- Constants ---
IMX_URL = "https://api.imx.to/v1/upload.php"
PIX_URL = "https://api.pixhost.to/images"
PIX_COVERS_URL = "https://api.pixhost.to/covers"
PIX_GALLERIES_URL = "https://api.pixhost.to/galleries"
IMX_LOGIN_URL = "https://imx.to/login.php"
IMX_DASHBOARD_URL = "https://imx.to/user/dashboard"
IMX_GALLERY_ADD_URL = "https://imx.to/user/gallery/add"
IMX_GALLERY_EDIT_URL = "https://imx.to/user/gallery/edit"

# TURBO Constants
TURBO_HOME_URL = "https://www.turboimagehost.com/"
TURBO_LOGIN_URL = "https://www.turboimagehost.com/login.tu"

# VIPR Constants
VIPR_HOME_URL = "https://vipr.im/"
VIPR_LOGIN_URL = "https://vipr.im/"
VIPR_AJAX_URL = "https://vipr.im/"

SUPPORTED_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
SETTINGS_FILE = "user_settings.json"
CRASH_LOG_FILE = "crash_log.log"
UI_THUMB_SIZE = (40, 40)

# Keyring Services
KEYRING_SERVICE_API = "ImageUploader:imx_api_key"
KEYRING_SERVICE_USER = "ImageUploader:imx_username"
KEYRING_SERVICE_PASS = "ImageUploader:imx_password"
KEYRING_SERVICE_VIPR_USER = "ImageUploader:vipr_username"
KEYRING_SERVICE_VIPR_PASS = "ImageUploader:vipr_password"

# --- Logging Setup ---
logger.remove()
# Only log to stderr if it exists (fixes EXE crash)
if sys.stderr:
    logger.add(sys.stderr, level="INFO")
logger.add(CRASH_LOG_FILE, rotation="1 MB", retention="10 days", level="DEBUG", backtrace=True, diagnose=True)

def natural_sort_key(s: str):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)