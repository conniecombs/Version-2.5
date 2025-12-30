"""
Unit tests for the plugin system.

Tests the plugin interface, plugin manager, and service registry.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import tempfile
import shutil

from modules.plugin_interface import ImageHostPlugin, UploadResult, UploadException
from modules.plugin_manager import PluginManager, PluginLoadError
from modules.plugin_adapter import ServiceRegistry


class TestPluginInterface:
    """Test the plugin interface base class"""

    def test_upload_result_creation(self):
        """Test creating an UploadResult"""
        result = UploadResult(
            image_url="https://example.com/image.jpg",
            thumb_url="https://example.com/thumb.jpg"
        )

        assert result.image_url == "https://example.com/image.jpg"
        assert result.thumb_url == "https://example.com/thumb.jpg"
        assert result.metadata == {}

    def test_upload_result_with_metadata(self):
        """Test UploadResult with metadata"""
        result = UploadResult(
            image_url="https://example.com/image.jpg",
            thumb_url="https://example.com/thumb.jpg",
            metadata={'id': '12345', 'views': 0}
        )

        assert result.metadata['id'] == '12345'
        assert result.metadata['views'] == 0

    def test_plugin_validate_file_missing(self, tmp_path):
        """Test file validation with missing file"""
        class TestPlugin(ImageHostPlugin):
            name = "Test"

            def upload(self, file_path, progress_callback=None):
                pass

            def validate_credentials(self):
                return True

        plugin = TestPlugin()
        missing_file = tmp_path / "missing.jpg"

        is_valid, error = plugin.validate_file(missing_file)

        assert not is_valid
        assert "does not exist" in error

    def test_plugin_validate_file_invalid_format(self, tmp_path):
        """Test file validation with invalid format"""
        class TestPlugin(ImageHostPlugin):
            name = "Test"
            allowed_formats = ['jpg', 'png']

            def upload(self, file_path, progress_callback=None):
                pass

            def validate_credentials(self):
                return True

        plugin = TestPlugin()
        test_file = tmp_path / "test.bmp"
        test_file.write_bytes(b'fake image data')

        is_valid, error = plugin.validate_file(test_file)

        assert not is_valid
        assert "not supported" in error

    def test_plugin_validate_file_too_large(self, tmp_path):
        """Test file validation with file too large"""
        class TestPlugin(ImageHostPlugin):
            name = "Test"
            max_file_size_mb = 1  # 1MB limit

            def upload(self, file_path, progress_callback=None):
                pass

            def validate_credentials(self):
                return True

        plugin = TestPlugin()
        test_file = tmp_path / "large.jpg"

        # Create file larger than 1MB
        test_file.write_bytes(b'x' * (2 * 1024 * 1024))  # 2MB

        is_valid, error = plugin.validate_file(test_file)

        assert not is_valid
        assert "too large" in error

    def test_plugin_validate_file_success(self, tmp_path):
        """Test successful file validation"""
        class TestPlugin(ImageHostPlugin):
            name = "Test"

            def upload(self, file_path, progress_callback=None):
                pass

            def validate_credentials(self):
                return True

        plugin = TestPlugin()
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b'fake image data')

        is_valid, error = plugin.validate_file(test_file)

        assert is_valid
        assert error is None


class TestPluginManager:
    """Test the plugin manager"""

    @pytest.fixture
    def plugin_dir(self, tmp_path):
        """Create temporary plugin directory"""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        return plugin_dir

    @pytest.fixture
    def sample_plugin_code(self):
        """Sample plugin code"""
        return '''
from modules.plugin_interface import ImageHostPlugin, UploadResult

class SamplePlugin(ImageHostPlugin):
    name = "Sample"
    version = "1.0.0"
    author = "Test"
    description = "Sample plugin for testing"

    def upload(self, file_path, progress_callback=None):
        return UploadResult(
            image_url="https://example.com/test.jpg",
            thumb_url="https://example.com/test_thumb.jpg"
        )

    def validate_credentials(self):
        return True
'''

    def test_plugin_manager_init_empty_dir(self, plugin_dir):
        """Test plugin manager with empty directory"""
        manager = PluginManager(plugin_dir, auto_load=True)

        assert len(manager) == 0
        assert manager.get_plugin_names() == []

    def test_plugin_manager_load_valid_plugin(self, plugin_dir, sample_plugin_code):
        """Test loading a valid plugin"""
        # Create plugin file
        plugin_file = plugin_dir / "sample_plugin.py"
        plugin_file.write_text(sample_plugin_code)

        manager = PluginManager(plugin_dir, auto_load=True)

        assert len(manager) == 1
        assert "Sample" in manager
        assert manager.has_plugin("Sample")

    def test_plugin_manager_get_plugin(self, plugin_dir, sample_plugin_code):
        """Test getting a plugin class"""
        plugin_file = plugin_dir / "sample_plugin.py"
        plugin_file.write_text(sample_plugin_code)

        manager = PluginManager(plugin_dir, auto_load=True)
        plugin_class = manager.get_plugin("Sample")

        assert plugin_class is not None
        assert plugin_class.name == "Sample"
        assert plugin_class.version == "1.0.0"

    def test_plugin_manager_plugin_metadata(self, plugin_dir, sample_plugin_code):
        """Test retrieving plugin metadata"""
        plugin_file = plugin_dir / "sample_plugin.py"
        plugin_file.write_text(sample_plugin_code)

        manager = PluginManager(plugin_dir, auto_load=True)
        metadata = manager.get_plugin_metadata("Sample")

        assert metadata is not None
        assert metadata['name'] == "Sample"
        assert metadata['version'] == "1.0.0"
        assert metadata['author'] == "Test"
        assert metadata['description'] == "Sample plugin for testing"

    def test_plugin_manager_list_plugins(self, plugin_dir, sample_plugin_code):
        """Test listing all plugins"""
        plugin_file = plugin_dir / "sample_plugin.py"
        plugin_file.write_text(sample_plugin_code)

        manager = PluginManager(plugin_dir, auto_load=True)
        plugins = manager.list_plugins()

        assert len(plugins) == 1
        assert plugins[0]['name'] == "Sample"

    def test_plugin_manager_invalid_plugin_missing_method(self, plugin_dir):
        """Test loading plugin with missing required method"""
        invalid_plugin = '''
from modules.plugin_interface import ImageHostPlugin

class InvalidPlugin(ImageHostPlugin):
    name = "Invalid"

    def validate_credentials(self):
        return True
    # Missing upload() method!
'''
        plugin_file = plugin_dir / "invalid_plugin.py"
        plugin_file.write_text(invalid_plugin)

        manager = PluginManager(plugin_dir, auto_load=True)

        # Plugin should not load due to missing method
        assert len(manager) == 0

    def test_plugin_manager_invalid_plugin_missing_name(self, plugin_dir):
        """Test loading plugin with missing name"""
        invalid_plugin = '''
from modules.plugin_interface import ImageHostPlugin, UploadResult

class NoNamePlugin(ImageHostPlugin):
    # Missing name attribute!

    def upload(self, file_path, progress_callback=None):
        return UploadResult("url", "thumb")

    def validate_credentials(self):
        return True
'''
        plugin_file = plugin_dir / "noname_plugin.py"
        plugin_file.write_text(invalid_plugin)

        manager = PluginManager(plugin_dir, auto_load=True)

        # Plugin should not load due to missing name
        assert len(manager) == 0

    def test_plugin_manager_unload_plugin(self, plugin_dir, sample_plugin_code):
        """Test unloading a plugin"""
        plugin_file = plugin_dir / "sample_plugin.py"
        plugin_file.write_text(sample_plugin_code)

        manager = PluginManager(plugin_dir, auto_load=True)
        assert "Sample" in manager

        manager.unload_plugin("Sample")
        assert "Sample" not in manager
        assert len(manager) == 0


class TestServiceRegistry:
    """Test the service registry"""

    @pytest.fixture
    def plugin_dir(self, tmp_path):
        """Create temporary plugin directory"""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        return plugin_dir

    @pytest.fixture
    def registry(self, plugin_dir):
        """Create service registry"""
        return ServiceRegistry(plugin_dir)

    def test_registry_init(self, registry):
        """Test registry initialization"""
        assert registry is not None
        assert len(registry.builtin_services) == 4

    def test_registry_get_builtin_services(self, registry):
        """Test getting built-in service names"""
        services = registry.get_service_names()

        assert 'imx.to' in services
        assert 'pixhost.to' in services
        assert 'turboimagehost' in services
        assert 'vipr.im' in services

    def test_registry_is_builtin_service(self, registry):
        """Test checking if service is built-in"""
        assert registry.is_builtin_service('imx.to')
        assert registry.is_builtin_service('pixhost.to')
        assert not registry.is_builtin_service('Imgur')

    def test_registry_has_service(self, registry):
        """Test checking if service exists"""
        assert registry.has_service('imx.to')
        assert not registry.has_service('NonExistent')

    def test_registry_get_service_metadata_builtin(self, registry):
        """Test getting metadata for built-in service"""
        metadata = registry.get_service_metadata('imx.to')

        assert metadata is not None
        assert metadata['name'] == 'imx.to'
        assert metadata['version'] == '2.5.0'
        assert metadata['supports_galleries'] is True

    def test_registry_supports_galleries(self, registry):
        """Test checking gallery support"""
        assert registry.supports_galleries('imx.to')
        assert registry.supports_galleries('pixhost.to')
        assert not registry.supports_galleries('turboimagehost')

    def test_registry_get_max_concurrent_uploads(self, registry):
        """Test getting max concurrent uploads"""
        assert registry.get_max_concurrent_uploads('imx.to') == 5
        assert registry.get_max_concurrent_uploads('pixhost.to') == 3
        assert registry.get_max_concurrent_uploads('vipr.im') == 1

    def test_registry_list_all_services(self, registry):
        """Test listing all services"""
        services = registry.list_all_services()

        assert len(services) >= 4  # At least 4 built-in services
        names = [s['name'] for s in services]
        assert 'imx.to' in names
        assert 'pixhost.to' in names


class TestPluginIntegration:
    """Integration tests for the complete plugin system"""

    @pytest.fixture
    def plugin_dir(self, tmp_path):
        """Create temporary plugin directory"""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        return plugin_dir

    @pytest.fixture
    def mock_plugin_code(self):
        """Mock plugin code that simulates upload"""
        return '''
from modules.plugin_interface import ImageHostPlugin, UploadResult
from pathlib import Path

class MockService(ImageHostPlugin):
    name = "MockService"
    version = "1.0.0"
    author = "Test"
    description = "Mock service for testing"
    supports_galleries = True
    requires_authentication = True

    def upload(self, file_path, progress_callback=None):
        # Simulate successful upload
        return UploadResult(
            image_url=f"https://mock.com/{file_path.name}",
            thumb_url=f"https://mock.com/thumb_{file_path.name}",
            metadata={'uploaded': True}
        )

    def validate_credentials(self):
        api_key = self.credentials.get('api_key')
        return api_key == 'valid_key'

    def get_credential_fields(self):
        return {
            'api_key': {
                'label': 'API Key',
                'type': 'password',
                'required': True
            }
        }

    def create_gallery(self, gallery_name, image_urls):
        return f"https://mock.com/gallery/{gallery_name}"
'''

    def test_end_to_end_plugin_upload(self, plugin_dir, mock_plugin_code, tmp_path):
        """Test complete plugin workflow: load, upload, validate"""
        # Create plugin
        plugin_file = plugin_dir / "mock_plugin.py"
        plugin_file.write_text(mock_plugin_code)

        # Create registry
        registry = ServiceRegistry(plugin_dir)

        # Verify plugin loaded
        assert "MockService" in registry.get_service_names()
        assert registry.is_plugin_service("MockService")

        # Create test image
        test_image = tmp_path / "test.jpg"
        test_image.write_bytes(b'fake image data')

        # Upload via plugin
        result = registry.upload_via_plugin(
            "MockService",
            test_image,
            credentials={'api_key': 'valid_key'}
        )

        assert result.image_url == "https://mock.com/test.jpg"
        assert result.thumb_url == "https://mock.com/thumb_test.jpg"
        assert result.metadata['uploaded'] is True

    def test_plugin_credential_validation(self, plugin_dir, mock_plugin_code):
        """Test plugin credential validation"""
        plugin_file = plugin_dir / "mock_plugin.py"
        plugin_file.write_text(mock_plugin_code)

        registry = ServiceRegistry(plugin_dir)

        # Valid credentials
        assert registry.validate_credentials(
            "MockService",
            {'api_key': 'valid_key'}
        )

        # Invalid credentials
        assert not registry.validate_credentials(
            "MockService",
            {'api_key': 'wrong_key'}
        )

    def test_plugin_gallery_creation(self, plugin_dir, mock_plugin_code):
        """Test plugin gallery creation"""
        plugin_file = plugin_dir / "mock_plugin.py"
        plugin_file.write_text(mock_plugin_code)

        registry = ServiceRegistry(plugin_dir)

        gallery_url = registry.create_gallery(
            "MockService",
            "Test Gallery",
            ["https://mock.com/img1.jpg", "https://mock.com/img2.jpg"],
            credentials={'api_key': 'valid_key'}
        )

        assert gallery_url == "https://mock.com/gallery/Test Gallery"

    def test_plugin_get_credential_fields(self, plugin_dir, mock_plugin_code):
        """Test retrieving credential fields from plugin"""
        plugin_file = plugin_dir / "mock_plugin.py"
        plugin_file.write_text(mock_plugin_code)

        registry = ServiceRegistry(plugin_dir)
        fields = registry.get_credential_fields("MockService")

        assert 'api_key' in fields
        assert fields['api_key']['label'] == 'API Key'
        assert fields['api_key']['type'] == 'password'
        assert fields['api_key']['required'] is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
