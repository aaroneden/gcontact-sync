"""
Tests for the config module.

Tests configuration loading, validation, and generation functionality
including YAML parsing, error handling, and file operations.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from gcontact_sync.config.generator import generate_default_config, save_config_file
from gcontact_sync.config.loader import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_FILE,
    ConfigError,
    ConfigLoader,
)


class TestConfigLoaderInitialization:
    """Tests for ConfigLoader initialization."""

    def test_default_config_dir(self):
        """Test that default config dir is used when no argument provided."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove GCONTACT_SYNC_CONFIG_DIR if it exists
            os.environ.pop("GCONTACT_SYNC_CONFIG_DIR", None)
            loader = ConfigLoader()
            assert loader.config_dir == DEFAULT_CONFIG_DIR

    def test_custom_config_dir_via_argument(self, tmp_path):
        """Test that custom config dir can be passed as argument."""
        custom_dir = tmp_path / "custom_config"
        loader = ConfigLoader(config_dir=custom_dir)
        assert loader.config_dir == custom_dir

    def test_config_dir_from_environment_variable(self, tmp_path):
        """Test that config dir can be set via environment variable."""
        env_dir = str(tmp_path / "env_config")
        with patch.dict(os.environ, {"GCONTACT_SYNC_CONFIG_DIR": env_dir}):
            loader = ConfigLoader()
            assert loader.config_dir == Path(env_dir)

    def test_argument_takes_precedence_over_environment(self, tmp_path):
        """Test that explicit argument takes precedence over env variable."""
        arg_dir = tmp_path / "arg_config"
        env_dir = str(tmp_path / "env_config")
        with patch.dict(os.environ, {"GCONTACT_SYNC_CONFIG_DIR": env_dir}):
            loader = ConfigLoader(config_dir=arg_dir)
            assert loader.config_dir == arg_dir

    def test_default_config_file_name(self):
        """Test that default config file name is set correctly."""
        loader = ConfigLoader()
        assert loader.config_file == DEFAULT_CONFIG_FILE

    def test_custom_config_file_name(self, tmp_path):
        """Test that custom config file name can be specified."""
        loader = ConfigLoader(config_dir=tmp_path, config_file="custom.yaml")
        assert loader.config_file == "custom.yaml"


class TestConfigPathGeneration:
    """Tests for config path generation."""

    @pytest.fixture
    def loader(self, tmp_path):
        """Create a ConfigLoader instance with temp config dir."""
        return ConfigLoader(config_dir=tmp_path)

    def test_get_config_path_returns_full_path(self, loader, tmp_path):
        """Test that _get_config_path returns full path."""
        path = loader._get_config_path()
        assert path == tmp_path / DEFAULT_CONFIG_FILE

    def test_get_config_path_with_custom_file(self, tmp_path):
        """Test _get_config_path with custom file name."""
        loader = ConfigLoader(config_dir=tmp_path, config_file="custom.yaml")
        path = loader._get_config_path()
        assert path == tmp_path / "custom.yaml"


class TestConfigLoading:
    """Tests for configuration file loading."""

    @pytest.fixture
    def loader(self, tmp_path):
        """Create a ConfigLoader instance with temp config dir."""
        return ConfigLoader(config_dir=tmp_path)

    def test_load_nonexistent_file_returns_empty_dict(self, loader):
        """Test loading non-existent config file returns empty dict."""
        result = loader.load()
        assert result == {}

    def test_load_from_file_nonexistent_returns_empty_dict(self, loader, tmp_path):
        """Test load_from_file with non-existent file returns empty dict."""
        nonexistent = tmp_path / "nonexistent.yaml"
        result = loader.load_from_file(nonexistent)
        assert result == {}

    def test_load_valid_yaml_file(self, loader, tmp_path):
        """Test loading a valid YAML configuration file."""
        config_path = tmp_path / DEFAULT_CONFIG_FILE
        config_data = {
            "verbose": True,
            "dry_run": False,
            "strategy": "last_modified",
        }
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        result = loader.load()
        assert result == config_data

    def test_load_from_file_with_valid_yaml(self, loader, tmp_path):
        """Test load_from_file with valid YAML."""
        config_path = tmp_path / "custom.yaml"
        config_data = {"debug": True, "full": True}
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        result = loader.load_from_file(config_path)
        assert result == config_data

    def test_load_empty_yaml_file_returns_empty_dict(self, loader, tmp_path):
        """Test loading empty YAML file returns empty dict."""
        config_path = tmp_path / DEFAULT_CONFIG_FILE
        config_path.write_text("", encoding="utf-8")

        result = loader.load()
        assert result == {}

    def test_load_yaml_with_only_comments_returns_empty_dict(self, loader, tmp_path):
        """Test loading YAML file with only comments returns empty dict."""
        config_path = tmp_path / DEFAULT_CONFIG_FILE
        config_path.write_text("# Just comments\n# No actual config", encoding="utf-8")

        result = loader.load()
        assert result == {}

    def test_load_invalid_yaml_raises_config_error(self, loader, tmp_path):
        """Test loading invalid YAML raises ConfigError."""
        config_path = tmp_path / DEFAULT_CONFIG_FILE
        config_path.write_text("invalid: yaml: {{{", encoding="utf-8")

        with pytest.raises(ConfigError, match="Failed to parse YAML"):
            loader.load()

    def test_load_non_dict_yaml_raises_config_error(self, loader, tmp_path):
        """Test loading YAML that is not a dict raises ConfigError."""
        config_path = tmp_path / DEFAULT_CONFIG_FILE
        config_path.write_text("- list\n- items\n", encoding="utf-8")

        with pytest.raises(ConfigError, match="must contain a YAML dictionary"):
            loader.load()

    def test_load_string_yaml_raises_config_error(self, loader, tmp_path):
        """Test loading YAML that is a string raises ConfigError."""
        config_path = tmp_path / DEFAULT_CONFIG_FILE
        config_path.write_text("just a string", encoding="utf-8")

        with pytest.raises(ConfigError, match="must contain a YAML dictionary"):
            loader.load()

    def test_load_from_file_with_path_object(self, loader, tmp_path):
        """Test load_from_file accepts Path objects."""
        config_path = tmp_path / "test.yaml"
        config_data = {"test": True}
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        result = loader.load_from_file(config_path)
        assert result == config_data

    def test_load_from_file_with_string_path(self, loader, tmp_path):
        """Test load_from_file accepts string paths."""
        config_path = tmp_path / "test.yaml"
        config_data = {"test": True}
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        result = loader.load_from_file(str(config_path))
        assert result == config_data

    @patch("builtins.open", side_effect=OSError("Permission denied"))
    def test_load_permission_error_raises_config_error(self, mock_open, loader, tmp_path):
        """Test loading file with permission error raises ConfigError."""
        config_path = tmp_path / DEFAULT_CONFIG_FILE
        config_path.write_text("test: true", encoding="utf-8")

        with pytest.raises(ConfigError, match="Failed to read configuration file"):
            loader.load()


class TestConfigValidation:
    """Tests for configuration validation."""

    @pytest.fixture
    def loader(self, tmp_path):
        """Create a ConfigLoader instance with temp config dir."""
        return ConfigLoader(config_dir=tmp_path)

    def test_validate_empty_config(self, loader):
        """Test validating empty config succeeds."""
        loader.validate({})  # Should not raise

    def test_validate_non_dict_raises_error(self, loader):
        """Test validating non-dict raises ConfigError."""
        with pytest.raises(ConfigError, match="must be a dictionary"):
            loader.validate([])

    def test_validate_string_raises_error(self, loader):
        """Test validating string raises ConfigError."""
        with pytest.raises(ConfigError, match="must be a dictionary"):
            loader.validate("not a dict")

    def test_validate_valid_bool_options(self, loader):
        """Test validating boolean options."""
        config = {
            "dry_run": True,
            "full": False,
            "debug": True,
            "verbose": False,
        }
        loader.validate(config)  # Should not raise

    def test_validate_invalid_bool_type_raises_error(self, loader):
        """Test validating invalid boolean type raises ConfigError."""
        config = {"dry_run": "true"}  # String instead of bool
        with pytest.raises(ConfigError, match="Invalid type for 'dry_run'"):
            loader.validate(config)

    def test_validate_valid_strategy(self, loader):
        """Test validating valid strategy values."""
        valid_strategies = ["account1", "account2", "newest", "manual"]
        for strategy in valid_strategies:
            config = {"strategy": strategy}
            loader.validate(config)  # Should not raise

    def test_validate_invalid_strategy_raises_error(self, loader):
        """Test validating invalid strategy raises ConfigError."""
        config = {"strategy": "invalid_strategy"}
        with pytest.raises(ConfigError, match="Invalid strategy"):
            loader.validate(config)

    def test_validate_strategy_wrong_type_raises_error(self, loader):
        """Test validating strategy with wrong type raises ConfigError."""
        config = {"strategy": 123}  # Number instead of string
        with pytest.raises(ConfigError, match="Invalid type for 'strategy'"):
            loader.validate(config)

    def test_validate_config_dir_string(self, loader):
        """Test validating config_dir as string."""
        config = {"config_dir": "/path/to/config"}
        loader.validate(config)  # Should not raise

    def test_validate_config_dir_wrong_type_raises_error(self, loader):
        """Test validating config_dir with wrong type raises ConfigError."""
        config = {"config_dir": 123}
        with pytest.raises(ConfigError, match="Invalid type for 'config_dir'"):
            loader.validate(config)

    def test_validate_similarity_threshold_valid_values(self, loader):
        """Test validating similarity_threshold with valid values."""
        valid_thresholds = [0.0, 0.5, 0.8, 1.0]
        for threshold in valid_thresholds:
            config = {"similarity_threshold": threshold}
            loader.validate(config)  # Should not raise

    def test_validate_similarity_threshold_as_int(self, loader):
        """Test validating similarity_threshold as integer."""
        config = {"similarity_threshold": 1}
        loader.validate(config)  # Should not raise

    def test_validate_similarity_threshold_too_low_raises_error(self, loader):
        """Test validating similarity_threshold below 0 raises ConfigError."""
        config = {"similarity_threshold": -0.1}
        with pytest.raises(ConfigError, match="must be between 0.0 and 1.0"):
            loader.validate(config)

    def test_validate_similarity_threshold_too_high_raises_error(self, loader):
        """Test validating similarity_threshold above 1 raises ConfigError."""
        config = {"similarity_threshold": 1.1}
        with pytest.raises(ConfigError, match="must be between 0.0 and 1.0"):
            loader.validate(config)

    def test_validate_similarity_threshold_wrong_type_raises_error(self, loader):
        """Test validating similarity_threshold with wrong type raises ConfigError."""
        config = {"similarity_threshold": "0.8"}
        with pytest.raises(ConfigError, match="Invalid type for 'similarity_threshold'"):
            loader.validate(config)

    def test_validate_batch_size_valid_values(self, loader):
        """Test validating batch_size with valid values."""
        valid_sizes = [1, 10, 100, 1000]
        for size in valid_sizes:
            config = {"batch_size": size}
            loader.validate(config)  # Should not raise

    def test_validate_batch_size_too_low_raises_error(self, loader):
        """Test validating batch_size below 1 raises ConfigError."""
        config = {"batch_size": 0}
        with pytest.raises(ConfigError, match="must be >= 1"):
            loader.validate(config)

    def test_validate_batch_size_negative_raises_error(self, loader):
        """Test validating negative batch_size raises ConfigError."""
        config = {"batch_size": -10}
        with pytest.raises(ConfigError, match="must be >= 1"):
            loader.validate(config)

    def test_validate_batch_size_wrong_type_raises_error(self, loader):
        """Test validating batch_size with wrong type raises ConfigError."""
        config = {"batch_size": "100"}
        with pytest.raises(ConfigError, match="Invalid type for 'batch_size'"):
            loader.validate(config)

    def test_validate_unknown_keys_are_allowed(self, loader):
        """Test that unknown keys don't cause validation errors."""
        config = {
            "unknown_option": "value",
            "another_unknown": 123,
        }
        loader.validate(config)  # Should not raise

    def test_validate_mixed_valid_and_unknown_keys(self, loader):
        """Test validating config with both valid and unknown keys."""
        config = {
            "verbose": True,
            "strategy": "last_modified",
            "unknown_key": "some_value",
        }
        loader.validate(config)  # Should not raise

    def test_validate_complex_valid_config(self, loader):
        """Test validating a complex but valid configuration."""
        config = {
            "dry_run": True,
            "full": False,
            "debug": False,
            "verbose": True,
            "strategy": "last_modified",
            "config_dir": "/custom/path",
            "similarity_threshold": 0.85,
            "batch_size": 50,
        }
        loader.validate(config)  # Should not raise


class TestLoadAndValidate:
    """Tests for combined load and validate functionality."""

    @pytest.fixture
    def loader(self, tmp_path):
        """Create a ConfigLoader instance with temp config dir."""
        return ConfigLoader(config_dir=tmp_path)

    def test_load_and_validate_nonexistent_file(self, loader):
        """Test load_and_validate with non-existent file returns empty dict."""
        result = loader.load_and_validate()
        assert result == {}

    def test_load_and_validate_valid_config(self, loader, tmp_path):
        """Test load_and_validate with valid configuration."""
        config_path = tmp_path / DEFAULT_CONFIG_FILE
        config_data = {
            "verbose": True,
            "strategy": "last_modified",
            "batch_size": 100,
        }
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        result = loader.load_and_validate()
        assert result == config_data

    def test_load_and_validate_empty_file(self, loader, tmp_path):
        """Test load_and_validate with empty file returns empty dict."""
        config_path = tmp_path / DEFAULT_CONFIG_FILE
        config_path.write_text("", encoding="utf-8")

        result = loader.load_and_validate()
        assert result == {}

    def test_load_and_validate_invalid_yaml(self, loader, tmp_path):
        """Test load_and_validate with invalid YAML raises ConfigError."""
        config_path = tmp_path / DEFAULT_CONFIG_FILE
        config_path.write_text("invalid: yaml: {{{", encoding="utf-8")

        with pytest.raises(ConfigError, match="Failed to parse YAML"):
            loader.load_and_validate()

    def test_load_and_validate_invalid_config_values(self, loader, tmp_path):
        """Test load_and_validate with invalid config values raises ConfigError."""
        config_path = tmp_path / DEFAULT_CONFIG_FILE
        config_data = {"strategy": "invalid_strategy"}
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        with pytest.raises(ConfigError, match="Invalid strategy"):
            loader.load_and_validate()

    def test_load_and_validate_invalid_types(self, loader, tmp_path):
        """Test load_and_validate with invalid types raises ConfigError."""
        config_path = tmp_path / DEFAULT_CONFIG_FILE
        config_data = {"dry_run": "yes"}  # String instead of bool
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        with pytest.raises(ConfigError, match="Invalid type"):
            loader.load_and_validate()


class TestConfigGenerator:
    """Tests for configuration file generation."""

    def test_generate_default_config_returns_string(self):
        """Test that generate_default_config returns a string."""
        result = generate_default_config()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_default_config_is_valid_yaml(self):
        """Test that generated config is valid YAML."""
        config_yaml = generate_default_config()
        # Should not raise when parsing (comments are fine)
        yaml.safe_load(config_yaml)

    def test_generate_default_config_contains_key_sections(self):
        """Test that generated config contains expected sections."""
        config_yaml = generate_default_config()
        expected_sections = [
            "Logging Options",
            "Sync Behavior",
            "Advanced Options",
            "Example Configurations",
        ]
        for section in expected_sections:
            assert section in config_yaml

    def test_generate_default_config_contains_common_options(self):
        """Test that generated config documents common options."""
        config_yaml = generate_default_config()
        common_options = [
            "verbose",
            "debug",
            "dry_run",
            "full",
            "strategy",
            "config_dir",
            "similarity_threshold",
            "batch_size",
        ]
        for option in common_options:
            assert option in config_yaml

    def test_generate_default_config_has_comments(self):
        """Test that generated config includes helpful comments."""
        config_yaml = generate_default_config()
        assert "#" in config_yaml
        assert "Default:" in config_yaml


class TestSaveConfigFile:
    """Tests for saving configuration files."""

    def test_save_config_file_creates_file(self, tmp_path):
        """Test that save_config_file creates the config file."""
        config_path = tmp_path / "config.yaml"
        success, error = save_config_file(config_path)

        assert success is True
        assert error is None
        assert config_path.exists()

    def test_save_config_file_creates_parent_directories(self, tmp_path):
        """Test that save_config_file creates parent directories."""
        config_path = tmp_path / "nested" / "dirs" / "config.yaml"
        success, error = save_config_file(config_path)

        assert success is True
        assert error is None
        assert config_path.exists()
        assert config_path.parent.exists()

    def test_save_config_file_content_is_valid_yaml(self, tmp_path):
        """Test that saved config file contains valid YAML."""
        config_path = tmp_path / "config.yaml"
        save_config_file(config_path)

        # Should not raise when parsing
        yaml.safe_load(config_path.read_text())

    def test_save_config_file_sets_secure_permissions(self, tmp_path):
        """Test that config file has secure permissions (0o600)."""
        config_path = tmp_path / "config.yaml"
        save_config_file(config_path)

        mode = config_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_save_config_file_parent_dir_has_secure_permissions(self, tmp_path):
        """Test that parent directory has secure permissions (0o700)."""
        config_path = tmp_path / "secure_dir" / "config.yaml"
        save_config_file(config_path)

        mode = config_path.parent.stat().st_mode & 0o777
        assert mode == 0o700

    def test_save_config_file_existing_file_without_overwrite(self, tmp_path):
        """Test that existing file is not overwritten without --force."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("existing content", encoding="utf-8")

        success, error = save_config_file(config_path, overwrite=False)

        assert success is False
        assert error is not None
        assert "already exists" in error
        assert "existing content" == config_path.read_text()

    def test_save_config_file_existing_file_with_overwrite(self, tmp_path):
        """Test that existing file is overwritten with overwrite=True."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("existing content", encoding="utf-8")

        success, error = save_config_file(config_path, overwrite=True)

        assert success is True
        assert error is None
        assert "existing content" != config_path.read_text()

    def test_save_config_file_with_tilde_path(self, tmp_path, monkeypatch):
        """Test that save_config_file handles tilde paths."""
        # Patch HOME environment variable to use tmp_path
        monkeypatch.setenv("HOME", str(tmp_path))

        config_path = Path("~/test_config.yaml")
        success, error = save_config_file(config_path)

        assert success is True
        assert error is None
        # File should be created in the mocked home directory
        assert (tmp_path / "test_config.yaml").exists()

        # Verify the content is valid
        content = (tmp_path / "test_config.yaml").read_text()
        assert "Google Contacts Sync Configuration" in content

    @patch("pathlib.Path.write_text", side_effect=OSError("Permission denied"))
    def test_save_config_file_permission_error(self, mock_write, tmp_path):
        """Test that save_config_file handles permission errors."""
        config_path = tmp_path / "config.yaml"
        success, error = save_config_file(config_path)

        assert success is False
        assert error is not None
        assert "Failed to create configuration file" in error

    @patch("pathlib.Path.write_text", side_effect=Exception("Unexpected error"))
    def test_save_config_file_unexpected_error(self, mock_write, tmp_path):
        """Test that save_config_file handles unexpected errors."""
        config_path = tmp_path / "config.yaml"
        success, error = save_config_file(config_path)

        assert success is False
        assert error is not None
        assert "Unexpected error" in error


class TestConfigConstants:
    """Tests for module constants."""

    def test_default_config_dir_is_in_home(self):
        """Test that DEFAULT_CONFIG_DIR is in user's home directory."""
        assert DEFAULT_CONFIG_DIR == Path.home() / ".gcontact-sync"

    def test_default_config_file_name(self):
        """Test that DEFAULT_CONFIG_FILE is config.yaml."""
        assert DEFAULT_CONFIG_FILE == "config.yaml"


class TestConfigError:
    """Tests for ConfigError exception."""

    def test_config_error_is_exception(self):
        """Test that ConfigError is an Exception."""
        assert issubclass(ConfigError, Exception)

    def test_config_error_can_be_raised(self):
        """Test that ConfigError can be raised with a message."""
        with pytest.raises(ConfigError, match="Test error message"):
            raise ConfigError("Test error message")

    def test_config_error_can_be_caught(self):
        """Test that ConfigError can be caught as Exception."""
        try:
            raise ConfigError("Test error")
        except Exception as e:
            assert isinstance(e, ConfigError)
            assert str(e) == "Test error"
