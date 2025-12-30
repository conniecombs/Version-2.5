# modules/config_loader.py
"""
User-configurable settings loader with YAML support.
Provides runtime configuration separate from hardcoded constants.
"""
import os
import yaml
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from loguru import logger


@dataclass
class NetworkConfig:
    """Network-related configuration"""
    timeout_seconds: float = 60.0
    retry_count: int = 3
    upload_timeout_seconds: float = 300.0
    chunk_size: int = 8192
    http2_enabled: bool = True


@dataclass
class UIConfig:
    """UI-related configuration"""
    update_interval_ms: int = 20
    thumbnail_size: tuple = (40, 40)
    show_previews_default: bool = True
    recursion_limit: int = 3000


@dataclass
class ThreadingConfig:
    """Threading configuration per service"""
    imx_threads: int = 5
    pixhost_threads: int = 3
    turbo_threads: int = 2
    vipr_threads: int = 1
    thumbnail_workers: int = 4


@dataclass
class PerformanceConfig:
    """Performance tuning settings"""
    ui_queue_batch_size: int = 20
    progress_queue_batch_size: int = 50
    result_queue_batch_size: int = 10
    thumbnail_sleep_with_preview: float = 0.01
    thumbnail_sleep_no_preview: float = 0.001
    gc_threshold_files: int = 100  # Trigger GC after this many files


@dataclass
class AppConfig:
    """
    Complete application configuration.
    Combines all configuration sections.
    """
    network: NetworkConfig = None
    ui: UIConfig = None
    threading: ThreadingConfig = None
    performance: PerformanceConfig = None

    def __post_init__(self):
        if self.network is None:
            self.network = NetworkConfig()
        if self.ui is None:
            self.ui = UIConfig()
        if self.threading is None:
            self.threading = ThreadingConfig()
        if self.performance is None:
            self.performance = PerformanceConfig()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for YAML serialization"""
        result = {
            'network': asdict(self.network),
            'ui': asdict(self.ui),
            'threading': asdict(self.threading),
            'performance': asdict(self.performance)
        }

        # Convert tuples to lists for YAML compatibility
        if isinstance(result['ui']['thumbnail_size'], tuple):
            result['ui']['thumbnail_size'] = list(result['ui']['thumbnail_size'])

        return result


class ConfigLoader:
    """
    Loads and manages user configuration from YAML files.

    Provides a layered configuration system:
    1. Default values (from dataclasses)
    2. User config file (optional, overrides defaults)
    3. Runtime overrides (optional, overrides everything)
    """

    DEFAULT_CONFIG_PATH = "config.yaml"
    USER_CONFIG_PATH = os.path.expanduser("~/.connies_uploader/config.yaml")

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize config loader.

        Args:
            config_path: Path to config file. If None, uses default locations.
        """
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> AppConfig:
        """Load configuration from file or use defaults"""
        config = AppConfig()

        # Try to load from file
        config_file = self._find_config_file()
        if config_file:
            try:
                with open(config_file, 'r') as f:
                    data = yaml.safe_load(f)
                    if data:
                        config = self._merge_config(config, data)
                        logger.info(f"Loaded configuration from: {config_file}")
            except Exception as e:
                logger.warning(f"Failed to load config from {config_file}: {e}")
                logger.info("Using default configuration")

        return config

    def _find_config_file(self) -> Optional[str]:
        """Find config file in order of precedence"""
        # 1. Explicitly specified path
        if self.config_path and os.path.exists(self.config_path):
            return self.config_path

        # 2. Current directory
        if os.path.exists(self.DEFAULT_CONFIG_PATH):
            return self.DEFAULT_CONFIG_PATH

        # 3. User home directory
        if os.path.exists(self.USER_CONFIG_PATH):
            return self.USER_CONFIG_PATH

        return None

    def _merge_config(self, base: AppConfig, overrides: Dict[str, Any]) -> AppConfig:
        """Merge override values into base config"""
        # Network settings
        if 'network' in overrides:
            for key, value in overrides['network'].items():
                if hasattr(base.network, key):
                    setattr(base.network, key, value)

        # UI settings
        if 'ui' in overrides:
            for key, value in overrides['ui'].items():
                if hasattr(base.ui, key):
                    # Handle tuple conversion for thumbnail_size
                    if key == 'thumbnail_size' and isinstance(value, list):
                        value = tuple(value)
                    setattr(base.ui, key, value)

        # Threading settings
        if 'threading' in overrides:
            for key, value in overrides['threading'].items():
                if hasattr(base.threading, key):
                    setattr(base.threading, key, value)

        # Performance settings
        if 'performance' in overrides:
            for key, value in overrides['performance'].items():
                if hasattr(base.performance, key):
                    setattr(base.performance, key, value)

        return base

    def save_config(self, path: Optional[str] = None) -> bool:
        """
        Save current configuration to YAML file.

        Args:
            path: Path to save config. If None, uses default location.

        Returns:
            True if saved successfully
        """
        save_path = path or self.config_path or self.DEFAULT_CONFIG_PATH

        try:
            # Create directory if needed
            os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)

            with open(save_path, 'w') as f:
                yaml.dump(self.config.to_dict(), f, default_flow_style=False, sort_keys=False)

            logger.info(f"Configuration saved to: {save_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to save config to {save_path}: {e}")
            return False

    def create_example_config(self, path: str = "config.example.yaml") -> bool:
        """
        Create an example configuration file with all options and comments.

        Args:
            path: Path to save example config

        Returns:
            True if created successfully
        """
        example = """# Connie's Uploader Ultimate - Configuration File
# All settings are optional. Remove or comment out to use defaults.

# Network Settings
network:
  timeout_seconds: 60.0          # Default timeout for HTTP requests
  retry_count: 3                  # Number of retries for failed requests
  upload_timeout_seconds: 300.0   # Extended timeout for large file uploads
  chunk_size: 8192                # Bytes to read per chunk during upload
  http2_enabled: true             # Enable HTTP/2 support

# UI Settings
ui:
  update_interval_ms: 20          # UI refresh rate (lower = more responsive, higher CPU)
  thumbnail_size: [40, 40]        # Thumbnail dimensions [width, height]
  show_previews_default: true     # Show image previews by default
  recursion_limit: 3000           # Python recursion limit for large file lists

# Threading Configuration
threading:
  imx_threads: 5                  # Concurrent uploads for IMX.to
  pixhost_threads: 3              # Concurrent uploads for Pixhost
  turbo_threads: 2                # Concurrent uploads for TurboImageHost
  vipr_threads: 1                 # Concurrent uploads for Vipr (keep at 1)
  thumbnail_workers: 4            # Parallel thumbnail generation threads

# Performance Tuning
performance:
  ui_queue_batch_size: 20         # Max UI updates per cycle
  progress_queue_batch_size: 50   # Max progress updates per cycle
  result_queue_batch_size: 10     # Max result processing per cycle
  thumbnail_sleep_with_preview: 0.01    # Delay between thumbnails (with preview)
  thumbnail_sleep_no_preview: 0.001     # Delay between thumbnails (no preview)
  gc_threshold_files: 100         # Trigger garbage collection after N files
"""

        try:
            with open(path, 'w') as f:
                f.write(example)
            logger.info(f"Example configuration created: {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to create example config: {e}")
            return False

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.

        Args:
            section: Config section (network, ui, threading, performance)
            key: Setting key
            default: Default value if not found

        Returns:
            Configuration value or default
        """
        section_obj = getattr(self.config, section, None)
        if section_obj is None:
            return default
        return getattr(section_obj, key, default)

    def set(self, section: str, key: str, value: Any) -> bool:
        """
        Set a configuration value at runtime.

        Args:
            section: Config section
            key: Setting key
            value: New value

        Returns:
            True if set successfully
        """
        section_obj = getattr(self.config, section, None)
        if section_obj is None:
            return False

        if hasattr(section_obj, key):
            setattr(section_obj, key, value)
            return True

        return False


# Global config loader instance
_config_loader: Optional[ConfigLoader] = None


def get_config_loader() -> ConfigLoader:
    """Get the global config loader instance (singleton)"""
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader()
    return _config_loader


def reload_config(config_path: Optional[str] = None):
    """Reload configuration from file"""
    global _config_loader
    _config_loader = ConfigLoader(config_path)
    return _config_loader
