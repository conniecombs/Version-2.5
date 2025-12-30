"""
Plugin adapter for integrating plugins with the existing upload system.

This module provides a bridge between the existing upload manager/coordinator
and the new plugin system, allowing both legacy built-in services and new
plugins to coexist.
"""

from pathlib import Path
from typing import Optional, Dict, List, Any, Callable
from loguru import logger

from .plugin_manager import PluginManager
from .plugin_interface import ImageHostPlugin, UploadResult, UploadException


class ServiceRegistry:
    """
    Unified service registry for both built-in services and plugins.

    This class provides a single interface for working with image hosting services,
    abstracting away whether they are legacy built-in services or new plugins.
    """

    def __init__(self, plugin_dir: Path):
        """
        Initialize service registry.

        Args:
            plugin_dir: Directory containing plugin files
        """
        self.plugin_manager = PluginManager(plugin_dir, auto_load=True)

        # Built-in services (legacy)
        self.builtin_services = {
            'imx.to': {'name': 'imx.to', 'is_plugin': False},
            'pixhost.to': {'name': 'pixhost.to', 'is_plugin': False},
            'turboimagehost': {'name': 'turboimagehost', 'is_plugin': False},
            'vipr.im': {'name': 'vipr.im', 'is_plugin': False}
        }

    def get_service_names(self) -> List[str]:
        """
        Get list of all available services (built-in + plugins).

        Returns:
            List of service names
        """
        builtin_names = list(self.builtin_services.keys())
        plugin_names = self.plugin_manager.get_plugin_names()

        return builtin_names + plugin_names

    def is_plugin_service(self, service_name: str) -> bool:
        """
        Check if a service is a plugin (vs built-in).

        Args:
            service_name: Name of service

        Returns:
            True if service is a plugin
        """
        return self.plugin_manager.has_plugin(service_name)

    def is_builtin_service(self, service_name: str) -> bool:
        """
        Check if a service is built-in (legacy).

        Args:
            service_name: Name of service

        Returns:
            True if service is built-in
        """
        return service_name in self.builtin_services

    def has_service(self, service_name: str) -> bool:
        """
        Check if a service exists (built-in or plugin).

        Args:
            service_name: Name of service

        Returns:
            True if service exists
        """
        return self.is_builtin_service(service_name) or self.is_plugin_service(service_name)

    def get_plugin_instance(
        self,
        service_name: str,
        credentials: Dict = None,
        config: Dict = None
    ) -> Optional[ImageHostPlugin]:
        """
        Get a plugin instance for a service.

        Args:
            service_name: Name of plugin service
            credentials: Service credentials
            config: Optional configuration

        Returns:
            Plugin instance if service is a plugin, None otherwise
        """
        if not self.is_plugin_service(service_name):
            return None

        plugin_class = self.plugin_manager.get_plugin(service_name)
        if plugin_class:
            return plugin_class(credentials=credentials, config=config)

        return None

    def get_credential_fields(self, service_name: str) -> Dict:
        """
        Get credential fields for a service.

        Args:
            service_name: Name of service

        Returns:
            Dictionary of credential field metadata
        """
        if self.is_plugin_service(service_name):
            plugin_class = self.plugin_manager.get_plugin(service_name)
            if plugin_class:
                # Create temporary instance to get field info
                temp_instance = plugin_class()
                fields = temp_instance.get_credential_fields()
                temp_instance.cleanup()
                return fields

        # Return empty for built-in services (they have hardcoded UI)
        return {}

    def get_upload_options(self, service_name: str) -> Dict:
        """
        Get upload options for a service.

        Args:
            service_name: Name of service

        Returns:
            Dictionary of upload option metadata
        """
        if self.is_plugin_service(service_name):
            plugin_class = self.plugin_manager.get_plugin(service_name)
            if plugin_class:
                # Create temporary instance to get option info
                temp_instance = plugin_class()
                options = temp_instance.get_upload_options()
                temp_instance.cleanup()
                return options

        return {}

    def get_service_metadata(self, service_name: str) -> Optional[Dict]:
        """
        Get metadata for a service.

        Args:
            service_name: Name of service

        Returns:
            Service metadata dictionary
        """
        if self.is_plugin_service(service_name):
            return self.plugin_manager.get_plugin_metadata(service_name)

        if self.is_builtin_service(service_name):
            return {
                'name': service_name,
                'version': '2.5.0',
                'author': 'Connie Combs',
                'description': f'Built-in {service_name} uploader',
                'supports_galleries': service_name in ['pixhost.to', 'imx.to', 'vipr.im'],
                'requires_authentication': True,
                'max_concurrent_uploads': self._get_builtin_thread_count(service_name)
            }

        return None

    def _get_builtin_thread_count(self, service_name: str) -> int:
        """Get default thread count for built-in services."""
        defaults = {
            'imx.to': 5,
            'pixhost.to': 3,
            'turboimagehost': 2,
            'vipr.im': 1
        }
        return defaults.get(service_name, 2)

    def upload_via_plugin(
        self,
        service_name: str,
        file_path: Path,
        credentials: Dict,
        config: Dict = None,
        progress_callback: Optional[Callable] = None
    ) -> UploadResult:
        """
        Upload a file using a plugin service.

        Args:
            service_name: Name of plugin service
            file_path: Path to file to upload
            credentials: Service credentials
            config: Optional configuration
            progress_callback: Optional progress callback

        Returns:
            UploadResult from plugin

        Raises:
            UploadException: If upload fails
            ValueError: If service is not a plugin
        """
        if not self.is_plugin_service(service_name):
            raise ValueError(f"Service '{service_name}' is not a plugin")

        plugin = self.get_plugin_instance(service_name, credentials, config)
        if not plugin:
            raise UploadException(f"Failed to create plugin instance for {service_name}")

        try:
            result = plugin.upload(file_path, progress_callback)
            return result
        finally:
            plugin.cleanup()

    def validate_credentials(self, service_name: str, credentials: Dict) -> bool:
        """
        Validate credentials for a service.

        Args:
            service_name: Name of service
            credentials: Credentials to validate

        Returns:
            True if credentials are valid
        """
        if self.is_plugin_service(service_name):
            plugin = self.get_plugin_instance(service_name, credentials)
            if plugin:
                try:
                    return plugin.validate_credentials()
                finally:
                    plugin.cleanup()

        # Built-in services use their own validation logic
        return True

    def create_gallery(
        self,
        service_name: str,
        gallery_name: str,
        image_urls: List[str],
        credentials: Dict
    ) -> Optional[str]:
        """
        Create a gallery for uploaded images.

        Args:
            service_name: Name of service
            gallery_name: Gallery title
            image_urls: List of image URLs
            credentials: Service credentials

        Returns:
            Gallery URL if successful
        """
        if self.is_plugin_service(service_name):
            plugin = self.get_plugin_instance(service_name, credentials)
            if plugin:
                try:
                    return plugin.create_gallery(gallery_name, image_urls)
                finally:
                    plugin.cleanup()

        # Built-in services use their own gallery logic
        return None

    def supports_galleries(self, service_name: str) -> bool:
        """
        Check if service supports galleries.

        Args:
            service_name: Name of service

        Returns:
            True if service supports galleries
        """
        metadata = self.get_service_metadata(service_name)
        if metadata:
            return metadata.get('supports_galleries', False)
        return False

    def get_max_concurrent_uploads(self, service_name: str) -> int:
        """
        Get recommended max concurrent uploads for service.

        Args:
            service_name: Name of service

        Returns:
            Max concurrent upload count
        """
        metadata = self.get_service_metadata(service_name)
        if metadata:
            return metadata.get('max_concurrent_uploads', 3)
        return 3

    def reload_plugins(self):
        """Reload all plugins from disk."""
        self.plugin_manager.unload_all_plugins()
        self.plugin_manager.load_all_plugins()
        logger.info("Reloaded all plugins")

    def list_all_services(self) -> List[Dict]:
        """
        List all services with metadata.

        Returns:
            List of service metadata dictionaries
        """
        services = []

        # Add built-in services
        for name in self.builtin_services:
            services.append(self.get_service_metadata(name))

        # Add plugin services
        services.extend(self.plugin_manager.list_plugins())

        return services

    def __len__(self):
        """Return total number of available services."""
        return len(self.builtin_services) + len(self.plugin_manager)

    def __repr__(self):
        builtin_count = len(self.builtin_services)
        plugin_count = len(self.plugin_manager)
        return f"<ServiceRegistry: {builtin_count} built-in, {plugin_count} plugins>"


# Global service registry instance
_service_registry: Optional[ServiceRegistry] = None


def get_service_registry(plugin_dir: Path = None) -> ServiceRegistry:
    """
    Get or create the global service registry.

    Args:
        plugin_dir: Plugin directory (only used on first call)

    Returns:
        ServiceRegistry instance
    """
    global _service_registry

    if _service_registry is None:
        if plugin_dir is None:
            # Default to plugins/ in project root
            plugin_dir = Path(__file__).parent.parent / 'plugins'

        _service_registry = ServiceRegistry(plugin_dir)
        logger.info(f"Initialized service registry: {_service_registry}")

    return _service_registry