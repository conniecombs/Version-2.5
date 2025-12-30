# Plugin Development Guide
## Connie's Uploader Ultimate - Plugin System

This guide explains how to create custom image hosting service plugins for Connie's Uploader Ultimate.

---

## Table of Contents
1. [Overview](#overview)
2. [Getting Started](#getting-started)
3. [Plugin Interface](#plugin-interface)
4. [Creating Your First Plugin](#creating-your-first-plugin)
5. [Plugin Metadata](#plugin-metadata)
6. [Implementing Required Methods](#implementing-required-methods)
7. [Optional Features](#optional-features)
8. [Testing Your Plugin](#testing-your-plugin)
9. [Examples](#examples)
10. [Best Practices](#best-practices)
11. [Troubleshooting](#troubleshooting)

---

## Overview

The plugin system allows developers to add support for new image hosting services without modifying the core application code. Plugins are automatically discovered, loaded, and integrated into the UI.

### Benefits
- ✅ **Hot-Loading**: Plugins are loaded at runtime
- ✅ **Isolated**: Plugins are independent modules
- ✅ **Type-Safe**: Strong interface contract with validation
- ✅ **UI Integration**: Automatic credential field generation
- ✅ **Gallery Support**: Optional gallery/album creation
- ✅ **Progress Tracking**: Built-in progress callback support

---

## Getting Started

### Prerequisites
- Python 3.8+
- Basic understanding of HTTP requests
- Familiarity with the target image hosting service's API

### Plugin Directory Structure
```
Version-2.5/
├── plugins/
│   ├── your_service_plugin.py    # Your plugin file
│   ├── imgur_plugin.py            # Example: Imgur
│   └── catbox_plugin.py           # Example: Catbox
└── modules/
    └── plugin_interface.py        # Base interface
```

### File Naming Convention
Plugin files **must** end with `_plugin.py`:
- ✅ `imgur_plugin.py`
- ✅ `catbox_plugin.py`
- ✅ `my_awesome_service_plugin.py`
- ❌ `imgur.py` (won't be detected)
- ❌ `plugin_imgur.py` (wrong pattern)

---

## Plugin Interface

All plugins must inherit from `ImageHostPlugin` and implement two required methods:

```python
from modules.plugin_interface import ImageHostPlugin, UploadResult, UploadException

class MyServicePlugin(ImageHostPlugin):
    """Your plugin implementation"""

    # Required metadata
    name = "MyService"
    version = "1.0.0"

    def upload(self, file_path, progress_callback=None):
        """Upload implementation"""
        pass

    def validate_credentials(self):
        """Credential validation"""
        pass
```

---

## Creating Your First Plugin

Let's create a simple plugin step-by-step.

### Step 1: Create Plugin File

Create `plugins/example_plugin.py`:

```python
from pathlib import Path
from typing import Optional, Callable
import httpx
from loguru import logger

from modules.plugin_interface import ImageHostPlugin, UploadResult, UploadException


class ExamplePlugin(ImageHostPlugin):
    """
    Example image hosting plugin.

    Replace this with your service's description.
    """

    # Plugin metadata
    name = "Example"
    version = "1.0.0"
    author = "Your Name"
    description = "Upload images to example.com"
    service_url = "https://example.com"

    # Capabilities
    supports_galleries = False
    supports_private = False
    requires_authentication = True
    max_file_size_mb = 10
    allowed_formats = ['jpg', 'jpeg', 'png', 'gif']
    max_concurrent_uploads = 3

    def __init__(self, credentials: dict = None, config: dict = None):
        """Initialize plugin with credentials"""
        super().__init__(credentials, config)

        # Get credentials
        self.api_key = self.credentials.get('api_key', '')

        # Create HTTP client
        self.client = httpx.Client(
            headers={'Authorization': f'Bearer {self.api_key}'},
            timeout=60.0
        )

    def upload(
        self,
        file_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> UploadResult:
        """
        Upload image to service.

        Args:
            file_path: Path to image file
            progress_callback: Optional callback(bytes_sent, total_bytes)

        Returns:
            UploadResult with URLs

        Raises:
            UploadException: If upload fails
        """
        # Validate file
        is_valid, error = self.validate_file(file_path)
        if not is_valid:
            raise UploadException(error)

        try:
            # Read file
            with open(file_path, 'rb') as f:
                files = {'image': (file_path.name, f, 'image/*')}

                # Upload to service
                response = self.client.post(
                    'https://api.example.com/upload',
                    files=files
                )

            # Check response
            if response.status_code != 200:
                raise UploadException(f"Upload failed: HTTP {response.status_code}")

            # Parse response
            data = response.json()

            # Extract URLs (adjust based on your service's response format)
            image_url = data['image_url']
            thumb_url = data.get('thumbnail_url', image_url)

            logger.info(f"Successfully uploaded to Example: {image_url}")

            return UploadResult(
                image_url=image_url,
                thumb_url=thumb_url,
                metadata={
                    'id': data.get('id'),
                    'size': file_path.stat().st_size
                }
            )

        except httpx.HTTPError as e:
            raise UploadException(f"Network error: {e}") from e
        except Exception as e:
            if isinstance(e, UploadException):
                raise
            raise UploadException(f"Unexpected error: {e}") from e

    def validate_credentials(self) -> bool:
        """
        Validate API key by testing authentication.

        Returns:
            True if credentials are valid
        """
        if not self.api_key:
            return False

        try:
            # Test API endpoint (adjust based on your service)
            response = self.client.get('https://api.example.com/auth/test')
            return response.status_code == 200

        except Exception as e:
            logger.error(f"Credential validation failed: {e}")
            return False

    def get_credential_fields(self) -> dict:
        """
        Define credential fields for UI generation.

        Returns:
            Dictionary of field metadata
        """
        return {
            'api_key': {
                'label': 'API Key',
                'type': 'password',
                'required': True,
                'placeholder': 'Enter your API key',
                'help_url': 'https://example.com/api',
                'help_text': 'Get your API key from the dashboard'
            }
        }

    def cleanup(self):
        """Close HTTP client"""
        if self.client:
            try:
                self.client.close()
            except:
                pass
```

### Step 2: Test Your Plugin

Create a test file `test_example_plugin.py`:

```python
from pathlib import Path
from plugins.example_plugin import ExamplePlugin

def test_plugin_loads():
    """Test plugin can be instantiated"""
    plugin = ExamplePlugin(credentials={'api_key': 'test123'})

    assert plugin.name == "Example"
    assert plugin.version == "1.0.0"
    assert plugin.api_key == 'test123'

    plugin.cleanup()

if __name__ == '__main__':
    test_plugin_loads()
    print("✓ Plugin loads successfully!")
```

### Step 3: Verify Auto-Discovery

Run this script to verify your plugin is discovered:

```python
from pathlib import Path
from modules.plugin_manager import PluginManager

plugin_dir = Path('plugins')
manager = PluginManager(plugin_dir)

print(f"Loaded {len(manager)} plugins:")
for plugin_info in manager.list_plugins():
    print(f"  - {plugin_info['name']} v{plugin_info['version']}")
```

Expected output:
```
Loaded 3 plugins:
  - Example v1.0.0
  - Imgur v1.0.0
  - Catbox v1.0.0
```

---

## Plugin Metadata

### Required Metadata

```python
class MyPlugin(ImageHostPlugin):
    # Required: Display name
    name = "MyService"

    # Required: Semantic version
    version = "1.0.0"

    # Optional but recommended
    author = "Your Name"
    description = "Short description of the service"
    service_url = "https://myservice.com"
```

### Capability Flags

```python
class MyPlugin(ImageHostPlugin):
    # Does service support galleries/albums?
    supports_galleries = True

    # Does service support private uploads?
    supports_private = True

    # Does service require authentication?
    requires_authentication = True

    # Maximum file size in MB
    max_file_size_mb = 20

    # Allowed file formats
    allowed_formats = ['jpg', 'jpeg', 'png', 'gif', 'webp']

    # Recommended max concurrent uploads
    max_concurrent_uploads = 5
```

---

## Implementing Required Methods

### 1. `upload()` - Required

Upload a file and return URLs:

```python
def upload(
    self,
    file_path: Path,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> UploadResult:
    """
    Upload image to service.

    Args:
        file_path: Path to image file
        progress_callback: Optional callback(bytes_sent, total_bytes)

    Returns:
        UploadResult(image_url, thumb_url, metadata)

    Raises:
        UploadException: If upload fails
    """
    # 1. Validate file
    is_valid, error = self.validate_file(file_path)
    if not is_valid:
        raise UploadException(error)

    # 2. Read and upload file
    with open(file_path, 'rb') as f:
        response = self.client.post(
            'https://api.service.com/upload',
            files={'file': f}
        )

    # 3. Check response
    if response.status_code != 200:
        raise UploadException(f"Upload failed: {response.status_code}")

    # 4. Parse response
    data = response.json()

    # 5. Return result
    return UploadResult(
        image_url=data['url'],
        thumb_url=data.get('thumbnail', data['url']),
        metadata={'id': data['id']}
    )
```

### 2. `validate_credentials()` - Required

Verify credentials are correct:

```python
def validate_credentials(self) -> bool:
    """
    Validate credentials by testing API access.

    Returns:
        True if credentials are valid
    """
    if not self.api_key:
        return False

    try:
        # Make a test API call
        response = self.client.get('https://api.service.com/user')
        return response.status_code == 200
    except:
        return False
```

---

## Optional Features

### Gallery Support

If your service supports galleries/albums:

```python
class MyPlugin(ImageHostPlugin):
    supports_galleries = True

    def create_gallery(
        self,
        gallery_name: str,
        image_urls: list
    ) -> Optional[str]:
        """
        Create gallery with uploaded images.

        Args:
            gallery_name: Gallery title
            image_urls: List of uploaded image URLs

        Returns:
            Gallery URL if successful
        """
        # Extract image IDs from URLs
        image_ids = [url.split('/')[-1] for url in image_urls]

        # Create gallery via API
        response = self.client.post(
            'https://api.service.com/gallery',
            json={
                'title': gallery_name,
                'images': image_ids
            }
        )

        if response.status_code == 200:
            data = response.json()
            return data['gallery_url']

        return None
```

### Image Deletion

If your service supports deletion:

```python
def delete_image(self, image_url: str) -> bool:
    """
    Delete an uploaded image.

    Args:
        image_url: URL of image to delete

    Returns:
        True if deletion successful
    """
    # Extract image ID
    image_id = image_url.split('/')[-1]

    try:
        response = self.client.delete(
            f'https://api.service.com/images/{image_id}'
        )
        return response.status_code == 200
    except:
        return False
```

### Credential Field Definition

Generate UI fields automatically:

```python
def get_credential_fields(self) -> dict:
    """
    Define credential fields for UI.

    Returns:
        Field metadata dictionary
    """
    return {
        'api_key': {
            'label': 'API Key',
            'type': 'password',  # 'text', 'password', 'email'
            'required': True,
            'placeholder': 'Enter your API key',
            'help_url': 'https://service.com/api',
            'help_text': 'Get API key from settings page'
        },
        'username': {
            'label': 'Username',
            'type': 'text',
            'required': False,
            'placeholder': 'optional'
        }
    }
```

### Upload Options

Provide configurable upload options:

```python
def get_upload_options(self) -> dict:
    """
    Define upload options for UI.

    Returns:
        Option metadata dictionary
    """
    return {
        'private': {
            'label': 'Make Private',
            'type': 'bool',
            'default': False,
            'help_text': 'Only you can view the image'
        },
        'quality': {
            'label': 'Image Quality',
            'type': 'choice',
            'choices': ['original', 'high', 'medium', 'low'],
            'default': 'original',
            'help_text': 'Compression quality'
        },
        'title': {
            'label': 'Image Title',
            'type': 'text',
            'default': '',
            'help_text': 'Optional title'
        }
    }
```

---

## Testing Your Plugin

### Unit Testing

Create comprehensive tests:

```python
# tests/test_my_plugin.py
import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from plugins.my_service_plugin import MyServicePlugin

class TestMyServicePlugin:
    @pytest.fixture
    def plugin(self):
        return MyServicePlugin(credentials={'api_key': 'test123'})

    def test_plugin_metadata(self, plugin):
        """Test plugin metadata is correct"""
        assert plugin.name == "MyService"
        assert plugin.version == "1.0.0"
        assert plugin.requires_authentication is True

    def test_validate_credentials_valid(self, plugin):
        """Test credential validation with valid key"""
        with patch.object(plugin.client, 'get') as mock_get:
            mock_get.return_value.status_code = 200

            assert plugin.validate_credentials() is True

    def test_validate_credentials_invalid(self, plugin):
        """Test credential validation with invalid key"""
        with patch.object(plugin.client, 'get') as mock_get:
            mock_get.return_value.status_code = 401

            assert plugin.validate_credentials() is False

    @patch('httpx.Client.post')
    def test_upload_success(self, mock_post, plugin, tmp_path):
        """Test successful upload"""
        # Create test image
        test_img = tmp_path / "test.jpg"
        test_img.write_bytes(b'fake image data')

        # Mock response
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'image_url': 'https://service.com/img123.jpg',
            'thumbnail_url': 'https://service.com/thumb123.jpg',
            'id': '123'
        }

        # Upload
        result = plugin.upload(test_img)

        # Assertions
        assert result.image_url == 'https://service.com/img123.jpg'
        assert result.thumb_url == 'https://service.com/thumb123.jpg'
        assert result.metadata['id'] == '123'

    def test_upload_invalid_file(self, plugin, tmp_path):
        """Test upload with invalid file"""
        invalid_file = tmp_path / "test.exe"
        invalid_file.write_bytes(b'fake data')

        from modules.plugin_interface import UploadException

        with pytest.raises(UploadException):
            plugin.upload(invalid_file)
```

### Integration Testing

Test with the actual service (use test/sandbox endpoints):

```python
def test_real_upload():
    """Integration test with real API"""
    plugin = MyServicePlugin(credentials={
        'api_key': 'YOUR_TEST_API_KEY'
    })

    test_image = Path('tests/fixtures/test_image.jpg')

    result = plugin.upload(test_image)

    assert result.image_url.startswith('https://')
    assert result.thumb_url.startswith('https://')

    # Cleanup
    plugin.delete_image(result.image_url)
    plugin.cleanup()
```

---

## Examples

### Example 1: Simple Service (No Authentication)

```python
class SimpleServicePlugin(ImageHostPlugin):
    name = "SimpleService"
    version = "1.0.0"
    requires_authentication = False

    def __init__(self, credentials=None, config=None):
        super().__init__(credentials, config)
        self.client = httpx.Client()

    def upload(self, file_path, progress_callback=None):
        with open(file_path, 'rb') as f:
            response = self.client.post(
                'https://simple.com/upload',
                files={'file': f}
            )

        url = response.text.strip()

        return UploadResult(
            image_url=url,
            thumb_url=url  # No separate thumbnail
        )

    def validate_credentials(self):
        return True  # No auth required
```

### Example 2: Service with Gallery Support

```python
class GalleryServicePlugin(ImageHostPlugin):
    name = "GalleryService"
    version = "1.0.0"
    supports_galleries = True

    def upload(self, file_path, progress_callback=None):
        # Upload implementation
        pass

    def create_gallery(self, gallery_name, image_urls):
        """Create album with uploaded images"""
        image_ids = [self._extract_id(url) for url in image_urls]

        response = self.client.post(
            'https://service.com/albums',
            json={'title': gallery_name, 'images': image_ids}
        )

        return response.json()['album_url']

    def _extract_id(self, url):
        """Extract image ID from URL"""
        return url.split('/')[-1].split('.')[0]
```

### Example 3: Service with Progress Tracking

```python
class ProgressServicePlugin(ImageHostPlugin):
    name = "ProgressService"
    version = "1.0.0"

    def upload(self, file_path, progress_callback=None):
        """Upload with progress tracking"""
        file_size = file_path.stat().st_size

        def monitor_progress(monitor):
            """Generator that yields chunks and reports progress"""
            bytes_sent = 0
            while True:
                chunk = monitor.read(8192)
                if not chunk:
                    break

                bytes_sent += len(chunk)

                # Report progress
                if progress_callback:
                    progress_callback(bytes_sent, file_size)

                yield chunk

        with open(file_path, 'rb') as f:
            response = self.client.post(
                'https://service.com/upload',
                content=monitor_progress(f)
            )

        # Parse response...
```

---

## Best Practices

### 1. Error Handling

Always wrap API calls in try/except:

```python
def upload(self, file_path, progress_callback=None):
    try:
        response = self.client.post(...)
        # ...
    except httpx.TimeoutException as e:
        raise UploadException(f"Upload timeout: {e}") from e
    except httpx.NetworkError as e:
        raise UploadException(f"Network error: {e}") from e
    except Exception as e:
        if isinstance(e, UploadException):
            raise
        raise UploadException(f"Unexpected error: {e}") from e
```

### 2. Logging

Use loguru for consistent logging:

```python
from loguru import logger

def upload(self, file_path, progress_callback=None):
    logger.debug(f"Uploading {file_path.name} to {self.name}")

    result = ...  # Upload logic

    logger.info(f"✓ Uploaded to {self.name}: {result.image_url}")

    return result
```

### 3. Resource Cleanup

Always implement cleanup:

```python
def cleanup(self):
    """Close connections and free resources"""
    if self.client:
        try:
            self.client.close()
        except:
            pass

    logger.debug(f"Cleaned up {self.name} plugin")
```

### 4. File Validation

Use the built-in validation:

```python
def upload(self, file_path, progress_callback=None):
    # Validate file before uploading
    is_valid, error = self.validate_file(file_path)
    if not is_valid:
        raise UploadException(error)

    # Continue with upload...
```

### 5. Credential Security

Never log credentials:

```python
# Bad
logger.info(f"Using API key: {self.api_key}")

# Good
logger.info("Using API key: ***")
```

### 6. HTTP Client Configuration

Configure timeouts and retries:

```python
def __init__(self, credentials=None, config=None):
    super().__init__(credentials, config)

    self.client = httpx.Client(
        timeout=httpx.Timeout(60.0, connect=10.0),
        follow_redirects=True,
        http2=True
    )
```

### 7. Response Parsing

Handle various response formats:

```python
def upload(self, file_path, progress_callback=None):
    response = self.client.post(...)

    # Handle JSON responses
    if response.headers.get('content-type') == 'application/json':
        data = response.json()
        return UploadResult(data['url'], data['thumb'])

    # Handle plain text responses
    url = response.text.strip()
    return UploadResult(url, url)
```

---

## Troubleshooting

### Plugin Not Loading

**Problem**: Plugin doesn't appear in service list

**Solutions**:
1. Check file naming: Must end with `_plugin.py`
2. Verify plugin is in `plugins/` directory
3. Check for syntax errors: `python plugins/your_plugin.py`
4. Ensure required methods are implemented
5. Check logs for loading errors

### Credential Validation Fails

**Problem**: `validate_credentials()` always returns False

**Solutions**:
1. Test API endpoint manually (curl/Postman)
2. Check authentication headers
3. Verify credentials are passed correctly
4. Add debug logging to see actual response

### Upload Errors

**Problem**: Uploads fail with exceptions

**Solutions**:
1. Test file validation: `plugin.validate_file(path)`
2. Check file size limits
3. Verify file format is supported
4. Inspect API response: `print(response.text)`
5. Check network connectivity

### Import Errors

**Problem**: `ModuleNotFoundError` when importing plugin

**Solutions**:
1. Ensure dependencies are installed
2. Check Python path
3. Run from project root directory
4. Install missing packages: `pip install httpx`

---

## Plugin Distribution

### Sharing Your Plugin

1. **GitHub Repository**:
   ```
   my-service-plugin/
   ├── README.md
   ├── requirements.txt
   ├── my_service_plugin.py
   └── tests/
       └── test_my_service.py
   ```

2. **Installation Instructions**:
   ```bash
   # Clone plugin
   git clone https://github.com/user/my-service-plugin

   # Install dependencies
   pip install -r requirements.txt

   # Copy to plugins directory
   cp my_service_plugin.py /path/to/Version-2.5/plugins/
   ```

3. **Documentation**:
   - Service API documentation link
   - How to get credentials
   - Supported features
   - Known limitations

---

## Reference

### Complete Plugin Template

```python
from pathlib import Path
from typing import Optional, Callable
import httpx
from loguru import logger

from modules.plugin_interface import ImageHostPlugin, UploadResult, UploadException


class TemplatePlugin(ImageHostPlugin):
    """Plugin template - replace with your service"""

    # Required metadata
    name = "ServiceName"
    version = "1.0.0"
    author = "Your Name"
    description = "Service description"
    service_url = "https://service.com"

    # Capabilities
    supports_galleries = False
    supports_private = False
    requires_authentication = True
    max_file_size_mb = 10
    allowed_formats = ['jpg', 'jpeg', 'png', 'gif', 'webp']
    max_concurrent_uploads = 3

    def __init__(self, credentials: dict = None, config: dict = None):
        super().__init__(credentials, config)
        self.api_key = self.credentials.get('api_key', '')
        self.client = httpx.Client(
            headers={'Authorization': f'Bearer {self.api_key}'},
            timeout=60.0
        )

    def upload(
        self,
        file_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> UploadResult:
        # Validate
        is_valid, error = self.validate_file(file_path)
        if not is_valid:
            raise UploadException(error)

        try:
            # Upload
            with open(file_path, 'rb') as f:
                response = self.client.post(
                    'https://api.service.com/upload',
                    files={'image': f}
                )

            if response.status_code != 200:
                raise UploadException(f"Upload failed: {response.status_code}")

            data = response.json()

            return UploadResult(
                image_url=data['url'],
                thumb_url=data.get('thumbnail', data['url']),
                metadata={'id': data['id']}
            )

        except httpx.HTTPError as e:
            raise UploadException(f"Network error: {e}") from e
        except Exception as e:
            if isinstance(e, UploadException):
                raise
            raise UploadException(f"Unexpected error: {e}") from e

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False

        try:
            response = self.client.get('https://api.service.com/auth/test')
            return response.status_code == 200
        except:
            return False

    def get_credential_fields(self) -> dict:
        return {
            'api_key': {
                'label': 'API Key',
                'type': 'password',
                'required': True,
                'help_url': 'https://service.com/api',
                'help_text': 'Get your API key from the dashboard'
            }
        }

    def cleanup(self):
        if self.client:
            try:
                self.client.close()
            except:
                pass
```

---

## Support

- **Documentation**: See `FUTURE_IMPROVEMENTS.md`
- **Examples**: Check `plugins/imgur_plugin.py` and `plugins/catbox_plugin.py`
- **Tests**: See `tests/test_plugin_system.py`
- **Issues**: Report bugs and request features on GitHub

---

**Happy Plugin Development! 🚀**
