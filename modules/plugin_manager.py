"""
Plugin manager for discovering and loading image hosting plugins.

This module handles automatic plugin discovery, loading, validation,
and lifecycle management.
"""

import importlib.util
import inspect
from pathlib import Path
from typing import Dict, List, Optional, Type
from loguru import logger

from modules.plugin_interface import ImageHostPlugin


class PluginLoadError(Exception):
    """Exception raised when plugin loading fails"""
    pass


class PluginManager:
    """
    Manages plugin discovery, loading, and lifecycle.

    The PluginManager scans the plugins directory for Python files ending in
    '_plugin.py' and automatically loads classes that inherit from ImageHostPlugin.

    Example:
        plugin_dir = Path('plugins')
        manager = PluginManager(plugin_dir)

        # List available plugins
        for plugin_info in manager.list_plugins():
            print(f"{plugin_info['name']} v{plugin_info['version']}")

        # Get a plugin class
        ImgurPlugin = manager.get_plugin('Imgur')
        plugin_instance = ImgurPlugin(credentials={'client_id': '...'})
    """

    def __init__(self, plugin_dir: Path, auto_load: bool = True):
        """
        Initialize plugin manager.

        Args:
            plugin_dir: Directory containing plugin files
            auto_load: If True, automatically load plugins on initialization
        """
        self.plugin_dir = Path(plugin_dir)
        self.plugins: Dict[str, Type[ImageHostPlugin]] = {}
        self._plugin_metadata: Dict[str, Dict] = {}

        if auto_load:
            self.load_all_plugins()

    def load_all_plugins(self):
        """
        Discover and load all plugins from the plugin directory.

        Scans for files matching '*_plugin.py' and loads any ImageHostPlugin
        subclasses found within them.
        """
        if not self.plugin_dir.exists():
            logger.warning(f"Plugin directory not found: {self.plugin_dir}")
            self.plugin_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created plugin directory: {self.plugin_dir}")
            return

        if not self.plugin_dir.is_dir():
            logger.error(f"Plugin path is not a directory: {self.plugin_dir}")
            return

        plugin_files = list(self.plugin_dir.glob('*_plugin.py'))
        logger.info(f"Scanning for plugins in {self.plugin_dir}...")
        logger.info(f"Found {len(plugin_files)} potential plugin files")

        loaded_count = 0
        for plugin_file in plugin_files:
            try:
                plugin_class = self._load_plugin_file(plugin_file)
                if plugin_class:
                    self._register_plugin(plugin_class, plugin_file)
                    loaded_count += 1
                    logger.info(
                        f"✓ Loaded plugin: {plugin_class.name} v{plugin_class.version} "
                        f"by {plugin_class.author or 'Unknown'}"
                    )
            except Exception as e:
                logger.error(f"✗ Failed to load plugin from {plugin_file.name}: {e}")

        logger.info(f"Successfully loaded {loaded_count}/{len(plugin_files)} plugins")

    def _load_plugin_file(self, plugin_file: Path) -> Optional[Type[ImageHostPlugin]]:
        """
        Load a plugin class from a Python file.

        Args:
            plugin_file: Path to plugin Python file

        Returns:
            Plugin class if found, None otherwise

        Raises:
            PluginLoadError: If file cannot be loaded or is invalid
        """
        module_name = f"plugin_{plugin_file.stem}"

        try:
            # Load module from file
            spec = importlib.util.spec_from_file_location(module_name, plugin_file)
            if spec is None or spec.loader is None:
                raise PluginLoadError(f"Cannot load module spec from {plugin_file}")

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find ImageHostPlugin subclass
            plugin_class = self._find_plugin_class(module)

            if plugin_class is None:
                logger.warning(
                    f"No ImageHostPlugin subclass found in {plugin_file.name}"
                )
                return None

            # Validate plugin class
            self._validate_plugin_class(plugin_class, plugin_file)

            return plugin_class

        except Exception as e:
            raise PluginLoadError(f"Error loading {plugin_file.name}: {e}") from e

    def _find_plugin_class(self, module) -> Optional[Type[ImageHostPlugin]]:
        """
        Find ImageHostPlugin subclass in a module.

        Args:
            module: Python module to search

        Returns:
            Plugin class if found, None otherwise
        """
        for name, obj in inspect.getmembers(module, inspect.isclass):
            # Check if it's a subclass of ImageHostPlugin (but not the base class itself)
            if (issubclass(obj, ImageHostPlugin) and
                obj is not ImageHostPlugin and
                obj.__module__ == module.__name__):
                return obj

        return None

    def _validate_plugin_class(self, plugin_class: Type[ImageHostPlugin], source_file: Path):
        """
        Validate that a plugin class is properly implemented.

        Args:
            plugin_class: Plugin class to validate
            source_file: Source file path (for error messages)

        Raises:
            PluginLoadError: If validation fails
        """
        # Check required metadata
        if not plugin_class.name:
            raise PluginLoadError(
                f"Plugin in {source_file.name} missing required 'name' attribute"
            )

        if not plugin_class.version:
            raise PluginLoadError(
                f"Plugin '{plugin_class.name}' missing required 'version' attribute"
            )

        # Check required methods are implemented
        required_methods = ['upload', 'validate_credentials']
        for method_name in required_methods:
            method = getattr(plugin_class, method_name, None)
            if method is None:
                raise PluginLoadError(
                    f"Plugin '{plugin_class.name}' missing required method '{method_name}'"
                )

            # Check if method is still abstract (not implemented)
            if getattr(method, '__isabstractmethod__', False):
                raise PluginLoadError(
                    f"Plugin '{plugin_class.name}' has not implemented abstract method '{method_name}'"
                )

    def _register_plugin(self, plugin_class: Type[ImageHostPlugin], source_file: Path):
        """
        Register a validated plugin class.

        Args:
            plugin_class: Plugin class to register
            source_file: Source file path
        """
        plugin_name = plugin_class.name

        # Check for name conflicts
        if plugin_name in self.plugins:
            logger.warning(
                f"Plugin name conflict: '{plugin_name}' from {source_file.name} "
                f"overwrites existing plugin"
            )

        self.plugins[plugin_name] = plugin_class

        # Store metadata
        self._plugin_metadata[plugin_name] = {
            'class': plugin_class,
            'source_file': str(source_file),
            'name': plugin_class.name,
            'version': plugin_class.version,
            'author': plugin_class.author,
            'description': plugin_class.description,
            'service_url': plugin_class.service_url,
            'supports_galleries': plugin_class.supports_galleries,
            'supports_private': plugin_class.supports_private,
            'requires_authentication': plugin_class.requires_authentication,
            'max_file_size_mb': plugin_class.max_file_size_mb,
            'allowed_formats': plugin_class.allowed_formats or [],
            'max_concurrent_uploads': plugin_class.max_concurrent_uploads
        }

    def get_plugin(self, plugin_name: str) -> Optional[Type[ImageHostPlugin]]:
        """
        Get a plugin class by name.

        Args:
            plugin_name: Name of the plugin

        Returns:
            Plugin class if found, None otherwise

        Example:
            ImgurPlugin = manager.get_plugin('Imgur')
            if ImgurPlugin:
                instance = ImgurPlugin(credentials={'client_id': '...'})
        """
        return self.plugins.get(plugin_name)

    def has_plugin(self, plugin_name: str) -> bool:
        """
        Check if a plugin is loaded.

        Args:
            plugin_name: Name of the plugin

        Returns:
            True if plugin is loaded, False otherwise
        """
        return plugin_name in self.plugins

    def list_plugins(self) -> List[Dict]:
        """
        List all loaded plugins with metadata.

        Returns:
            List of plugin metadata dictionaries

        Example:
            for plugin in manager.list_plugins():
                print(f"{plugin['name']} - {plugin['description']}")
        """
        return [
            {
                'name': meta['name'],
                'version': meta['version'],
                'author': meta['author'],
                'description': meta['description'],
                'service_url': meta['service_url'],
                'supports_galleries': meta['supports_galleries'],
                'supports_private': meta['supports_private'],
                'requires_authentication': meta['requires_authentication'],
                'max_file_size_mb': meta['max_file_size_mb'],
                'max_concurrent_uploads': meta['max_concurrent_uploads']
            }
            for meta in self._plugin_metadata.values()
        ]

    def get_plugin_names(self) -> List[str]:
        """
        Get list of all loaded plugin names.

        Returns:
            List of plugin names

        Example:
            names = manager.get_plugin_names()
            # ['Imgur', 'Catbox', 'CustomService']
        """
        return list(self.plugins.keys())

    def get_plugin_metadata(self, plugin_name: str) -> Optional[Dict]:
        """
        Get detailed metadata for a specific plugin.

        Args:
            plugin_name: Name of the plugin

        Returns:
            Plugin metadata dictionary if found, None otherwise
        """
        return self._plugin_metadata.get(plugin_name)

    def reload_plugin(self, plugin_name: str) -> bool:
        """
        Reload a specific plugin from disk.

        Args:
            plugin_name: Name of the plugin to reload

        Returns:
            True if reload successful, False otherwise

        Note:
            This is useful during plugin development for testing changes
            without restarting the application.
        """
        metadata = self._plugin_metadata.get(plugin_name)
        if not metadata:
            logger.warning(f"Cannot reload unknown plugin: {plugin_name}")
            return False

        source_file = Path(metadata['source_file'])
        if not source_file.exists():
            logger.error(f"Plugin source file not found: {source_file}")
            return False

        try:
            # Unload old plugin
            self.unload_plugin(plugin_name)

            # Reload from file
            plugin_class = self._load_plugin_file(source_file)
            if plugin_class:
                self._register_plugin(plugin_class, source_file)
                logger.info(f"Reloaded plugin: {plugin_name}")
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to reload plugin {plugin_name}: {e}")
            return False

    def unload_plugin(self, plugin_name: str):
        """
        Unload a plugin.

        Args:
            plugin_name: Name of the plugin to unload
        """
        if plugin_name in self.plugins:
            del self.plugins[plugin_name]

        if plugin_name in self._plugin_metadata:
            del self._plugin_metadata[plugin_name]

    def unload_all_plugins(self):
        """Unload all plugins."""
        self.plugins.clear()
        self._plugin_metadata.clear()

    def get_plugins_by_capability(
        self,
        supports_galleries: Optional[bool] = None,
        supports_private: Optional[bool] = None,
        requires_authentication: Optional[bool] = None
    ) -> List[str]:
        """
        Get plugin names filtered by capabilities.

        Args:
            supports_galleries: Filter by gallery support
            supports_private: Filter by private upload support
            requires_authentication: Filter by authentication requirement

        Returns:
            List of plugin names matching the criteria

        Example:
            # Get all plugins that support galleries
            gallery_plugins = manager.get_plugins_by_capability(
                supports_galleries=True
            )
        """
        results = []

        for plugin_name, meta in self._plugin_metadata.items():
            matches = True

            if supports_galleries is not None:
                if meta['supports_galleries'] != supports_galleries:
                    matches = False

            if supports_private is not None:
                if meta['supports_private'] != supports_private:
                    matches = False

            if requires_authentication is not None:
                if meta['requires_authentication'] != requires_authentication:
                    matches = False

            if matches:
                results.append(plugin_name)

        return results

    def __len__(self):
        """Return number of loaded plugins."""
        return len(self.plugins)

    def __contains__(self, plugin_name: str):
        """Check if plugin is loaded."""
        return plugin_name in self.plugins

    def __repr__(self):
        return f"<PluginManager: {len(self.plugins)} plugins loaded>"
