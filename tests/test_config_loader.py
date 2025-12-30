"""
Unit tests for config_loader.py - Configuration Module

Tests YAML loading, merging, validation, and defaults.
"""

import pytest
import yaml
from pathlib import Path
from modules.config_loader import ConfigLoader, AppConfig, NetworkConfig, UIConfig


class TestConfigLoader:
    """Test suite for ConfigLoader."""

    @pytest.fixture
    def config_loader(self, tmp_path):
        """Create config loader with temporary directory."""
        config_file = tmp_path / "config.yaml"
        return ConfigLoader(config_path=str(config_file))

    @pytest.fixture
    def sample_config_file(self, tmp_path):
        """Create a sample config file."""
        config_file = tmp_path / "config.yaml"
        config_data = {
            'network': {
                'timeout_seconds': 120.0,
                'retry_count': 5
            },
            'ui': {
                'thumbnail_size': [60, 60],
                'update_interval_ms': 15
            }
        }

        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)

        return config_file

    def test_default_config_loads(self):
        """Test that default configuration loads without file."""
        loader = ConfigLoader()
        config = loader.config

        assert isinstance(config, AppConfig)
        assert config.network.timeout_seconds == 60.0
        assert config.ui.thumbnail_size == (40, 40)  # Tuple, not list

    def test_load_config_from_file(self, tmp_path, sample_config_file):
        """Test loading configuration from YAML file."""
        loader = ConfigLoader(config_path=str(sample_config_file))
        config = loader.config

        # Should have loaded custom values
        assert config.network.timeout_seconds == 120.0
        assert config.network.retry_count == 5
        assert config.ui.thumbnail_size == (60, 60)  # Converted from list to tuple
        assert config.ui.update_interval_ms == 15

    def test_partial_config_merges_with_defaults(self, tmp_path):
        """Test that partial config merges with defaults."""
        config_file = tmp_path / "partial.yaml"
        partial_data = {
            'network': {
                'timeout_seconds': 90.0
                # retry_count not specified
            }
        }

        with open(config_file, 'w') as f:
            yaml.dump(partial_data, f)

        loader = ConfigLoader(config_path=str(config_file))
        config = loader.config

        # Custom value
        assert config.network.timeout_seconds == 90.0
        # Default value (not in file)
        assert config.network.retry_count == 3  # Default
        assert config.ui.thumbnail_size == (40, 40)  # Default - tuple

    def test_invalid_yaml_falls_back_to_defaults(self, tmp_path):
        """Test that invalid YAML falls back to defaults."""
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("invalid: yaml: content: [[[")

        loader = ConfigLoader(config_path=str(config_file))
        config = loader.config

        # Should use defaults
        assert config.network.timeout_seconds == 60.0

    def test_nonexistent_file_uses_defaults(self, tmp_path):
        """Test that nonexistent file uses defaults."""
        nonexistent = tmp_path / "does_not_exist.yaml"

        loader = ConfigLoader(config_path=str(nonexistent))
        config = loader.config

        # Should use defaults
        assert config.network.timeout_seconds == 60.0

    def test_get_config_value(self, tmp_path, sample_config_file):
        """Test getting specific config values."""
        loader = ConfigLoader(config_path=str(sample_config_file))

        timeout = loader.get('network', 'timeout_seconds')
        assert timeout == 120.0

        thumb_size = loader.get('ui', 'thumbnail_size')
        assert thumb_size == (60, 60)

    def test_get_config_value_with_default(self, config_loader):
        """Test getting value with default fallback."""
        # Nonexistent key
        value = config_loader.get('nonexistent', 'key', default=999)
        assert value == 999

    def test_set_config_value(self, config_loader):
        """Test setting config values at runtime."""
        config_loader.set('network', 'timeout_seconds', 180.0)

        assert config_loader.config.network.timeout_seconds == 180.0

    def test_save_config_to_file(self, tmp_path):
        """Test saving configuration to file."""
        config_file = tmp_path / "saved_config.yaml"
        loader = ConfigLoader(config_path=str(config_file))

        # Modify config
        loader.set('network', 'timeout_seconds', 99.0)
        loader.save_config()

        # Load and verify
        with open(config_file, 'r') as f:
            data = yaml.safe_load(f)

        assert data['network']['timeout_seconds'] == 99.0

    def test_create_example_config(self, tmp_path):
        """Test creating example config file."""
        example_file = tmp_path / "config.example.yaml"
        loader = ConfigLoader()

        loader.create_example_config(str(example_file))

        assert example_file.exists()

        # Verify it's valid YAML with comments
        content = example_file.read_text()
        assert 'network:' in content
        assert 'ui:' in content
        assert '#' in content  # Has comments

    def test_nested_config_structure(self, tmp_path):
        """Test deeply nested configuration."""
        config_file = tmp_path / "nested.yaml"
        nested_data = {
            'threading': {
                'imx_threads': 10,
                'pixhost_threads': 8
            },
            'performance': {
                'ui_queue_batch_size': 30,
                'gc_threshold_files': 200
            }
        }

        with open(config_file, 'w') as f:
            yaml.dump(nested_data, f)

        loader = ConfigLoader(config_path=str(config_file))
        config = loader.config

        assert config.threading.imx_threads == 10
        assert config.performance.ui_queue_batch_size == 30

    def test_type_validation(self, tmp_path):
        """Test that type mismatches are handled."""
        config_file = tmp_path / "bad_types.yaml"
        bad_data = {
            'network': {
                'timeout_seconds': "not_a_number",  # Should be float
                'retry_count': 5.5  # Should be int
            }
        }

        with open(config_file, 'w') as f:
            yaml.dump(bad_data, f)

        loader = ConfigLoader(config_path=str(config_file))
        config = loader.config

        # Current implementation doesn't validate types, accepts values as-is
        assert config.network.timeout_seconds == "not_a_number"
        assert config.network.retry_count == 5.5

    def test_list_type_config(self, tmp_path):
        """Test configuration with list types."""
        config_file = tmp_path / "list_config.yaml"
        config_data = {
            'ui': {
                'thumbnail_size': [80, 80]
            }
        }

        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)

        loader = ConfigLoader(config_path=str(config_file))
        config = loader.config

        # List is converted to tuple in _merge_config
        assert config.ui.thumbnail_size == (80, 80)
        assert isinstance(config.ui.thumbnail_size, tuple)
        assert len(config.ui.thumbnail_size) == 2


class TestConfigDataclasses:
    """Test configuration dataclasses."""

    def test_network_config_defaults(self):
        """Test NetworkConfig default values."""
        config = NetworkConfig()

        assert config.timeout_seconds == 60.0
        assert config.retry_count == 3
        assert config.upload_timeout_seconds == 300.0
        assert config.chunk_size == 8192
        assert config.http2_enabled is True

    def test_ui_config_defaults(self):
        """Test UIConfig default values."""
        config = UIConfig()

        assert config.update_interval_ms == 20
        assert config.thumbnail_size == (40, 40)  # Tuple in dataclass
        assert config.show_previews_default is True
        assert config.recursion_limit == 3000

    def test_app_config_composition(self):
        """Test that AppConfig composes all sub-configs."""
        config = AppConfig()

        assert hasattr(config, 'network')
        assert hasattr(config, 'ui')
        assert hasattr(config, 'threading')
        assert hasattr(config, 'performance')

        assert isinstance(config.network, NetworkConfig)
        assert isinstance(config.ui, UIConfig)


class TestConfigLoaderSingleton:
    """Test singleton pattern for config loader."""

    def test_get_config_loader_singleton(self):
        """Test that get_config_loader returns singleton."""
        from modules.config_loader import get_config_loader

        loader1 = get_config_loader()
        loader2 = get_config_loader()

        assert loader1 is loader2

    def test_singleton_config_persists(self):
        """Test that singleton config modifications persist."""
        from modules.config_loader import get_config_loader

        loader1 = get_config_loader()
        loader1.set('network', 'timeout_seconds', 999.0)

        loader2 = get_config_loader()
        assert loader2.get('network', 'timeout_seconds') == 999.0


class TestConfigLoaderEdgeCases:
    """Edge case tests for ConfigLoader."""

    def test_empty_config_file(self, tmp_path):
        """Test handling of empty config file."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        loader = ConfigLoader(config_path=str(config_file))
        config = loader.config

        # Should use all defaults
        assert config.network.timeout_seconds == 60.0

    def test_config_with_extra_keys(self, tmp_path):
        """Test that extra unknown keys are ignored."""
        config_file = tmp_path / "extra_keys.yaml"
        config_data = {
            'network': {
                'timeout_seconds': 100.0,
                'unknown_key': 'value'
            },
            'completely_unknown_section': {
                'key': 'value'
            }
        }

        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)

        loader = ConfigLoader(config_path=str(config_file))
        config = loader.config

        # Known keys should work
        assert config.network.timeout_seconds == 100.0
        # Unknown keys silently ignored

    def test_unicode_in_config(self, tmp_path):
        """Test handling of Unicode characters in config."""
        config_file = tmp_path / "unicode.yaml"
        config_file.write_text("# Configuration avec des caractères spéciaux: éàü\nnetwork:\n  timeout_seconds: 60.0\n", encoding='utf-8')

        loader = ConfigLoader(config_path=str(config_file))
        config = loader.config

        assert config.network.timeout_seconds == 60.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
