# settings_manager.py
import json
import os
from loguru import logger
from . import config

class SettingsManager:
    def __init__(self):
        self.filepath = config.SETTINGS_FILE
        self.defaults = {
            "service": "imx.to",
            "imx_thumb": "180",
            "imx_format": "Fixed Width",  # <--- NEW DEFAULT ADDED
            "imx_cover": False,
            "imx_links": False,
            "imx_threads": 5,
            
            "pix_content": "Safe",
            "pix_thumb": "200",
            "pix_cover": False,
            "pix_links": False,
            "pix_mk_gal": False,
            "pix_threads": 3,
            
            "turbo_content": "Safe",
            "turbo_thumb": "180",
            "turbo_threads": 2,
            
            "output_format": "BBCode",
            "auto_copy": False
        }

    def load(self):
        if not os.path.exists(self.filepath):
            return self.defaults
        try:
            with open(self.filepath, 'r') as f:
                data = json.load(f)
                # Merge loaded data with defaults to ensure new keys exist
                return {**self.defaults, **data}
        except Exception:
            return self.defaults

    def save(self, data):
        try:
            with open(self.filepath, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")