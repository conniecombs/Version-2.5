# Plugins Directory

This directory contains image hosting service plugins for Connie's Uploader Ultimate.

## Available Plugins

### 1. Imgur (`imgur_plugin.py`)
- **Description**: Upload images to Imgur.com
- **Authentication**: Requires Client ID
- **Galleries**: ✅ Supported
- **Max File Size**: 20MB
- **Formats**: jpg, jpeg, png, gif, webp, bmp, tiff

**Get Credentials**: [Imgur API Registration](https://api.imgur.com/oauth2/addclient)

### 2. Catbox (`catbox_plugin.py`)
- **Description**: Upload images to Catbox.moe
- **Authentication**: Optional (anonymous uploads supported)
- **Galleries**: ❌ Not supported
- **Max File Size**: 200MB
- **Formats**: jpg, jpeg, png, gif, webp, bmp, tiff, svg

**Get Credentials**: [Catbox Registration](https://catbox.moe/) (optional)

## Creating Your Own Plugin

See the [Plugin Development Guide](../PLUGIN_DEVELOPMENT_GUIDE.md) for detailed instructions.

### Quick Start

1. Create a new file ending with `_plugin.py` in this directory
2. Inherit from `ImageHostPlugin`
3. Implement required methods: `upload()` and `validate_credentials()`
4. Restart the application to load your plugin

### Template

```python
from modules.plugin_interface import ImageHostPlugin, UploadResult

class MyServicePlugin(ImageHostPlugin):
    name = "MyService"
    version = "1.0.0"

    def upload(self, file_path, progress_callback=None):
        # Implementation
        return UploadResult(image_url="...", thumb_url="...")

    def validate_credentials(self):
        # Validation
        return True
```

## Plugin Naming Convention

- ✅ Files **must** end with `_plugin.py`
- ✅ Examples: `imgur_plugin.py`, `catbox_plugin.py`, `my_service_plugin.py`
- ❌ Wrong: `imgur.py`, `plugin_imgur.py`

## Testing Plugins

Run tests for all plugins:

```bash
pytest tests/test_plugin_system.py -v
```

## Documentation

- **Full Guide**: [PLUGIN_DEVELOPMENT_GUIDE.md](../PLUGIN_DEVELOPMENT_GUIDE.md)
- **Examples**: See `imgur_plugin.py` and `catbox_plugin.py` in this directory
- **API Reference**: [modules/plugin_interface.py](../modules/plugin_interface.py)

## Contributing

Have a plugin to share? Submit a pull request or open an issue!

---

**Note**: Plugins are loaded automatically on application startup. No configuration needed.
