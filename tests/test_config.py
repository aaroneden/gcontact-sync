"""
Tests for the config module.

Tests configuration loading, validation, and generation functionality
including YAML parsing, error handling, and file operations.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from gcontact_sync.config.generator import generate_default_config, save_config_file
from gcontact_sync.config.loader import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_FILE,
    ConfigError,
    ConfigLoader,
)
from gcontact_sync.config.sync_config import (
    CONFIG_VERSION,
    DEFAULT_SYNC_CONFIG_FILE,
    AccountSyncConfig,
    SyncConfig,
    SyncConfigError,
    load_config,
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
    def test_load_permission_error_raises_config_error(
        self, mock_open, loader, tmp_path
    ):
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

    def test_validate_full_wrong_type_raises_error(self, loader):
        """Test validating full with wrong type raises ConfigError."""
        config = {"full": "yes"}
        with pytest.raises(ConfigError, match="Invalid type for 'full'"):
            loader.validate(config)

    def test_validate_debug_wrong_type_raises_error(self, loader):
        """Test validating debug with wrong type raises ConfigError."""
        config = {"debug": 1}
        with pytest.raises(ConfigError, match="Invalid type for 'debug'"):
            loader.validate(config)

    def test_validate_verbose_wrong_type_raises_error(self, loader):
        """Test validating verbose with wrong type raises ConfigError."""
        config = {"verbose": "true"}
        with pytest.raises(ConfigError, match="Invalid type for 'verbose'"):
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
        with pytest.raises(
            ConfigError, match="Invalid type for 'similarity_threshold'"
        ):
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

    # Tests for new Tier 1/2 configuration options

    def test_validate_api_page_size_valid(self, loader):
        """Test validating api_page_size with valid values."""
        for size in [1, 100, 500, 1000]:
            config = {"api_page_size": size}
            loader.validate(config)  # Should not raise

    def test_validate_api_page_size_invalid(self, loader):
        """Test validating api_page_size with invalid values."""
        config = {"api_page_size": 0}
        with pytest.raises(ConfigError, match="api_page_size must be >= 1"):
            loader.validate(config)

    def test_validate_api_page_size_wrong_type(self, loader):
        """Test validating api_page_size with wrong type."""
        config = {"api_page_size": "100"}
        with pytest.raises(ConfigError, match="Invalid type for 'api_page_size'"):
            loader.validate(config)

    def test_validate_api_batch_size_valid(self, loader):
        """Test validating api_batch_size with valid values."""
        for size in [1, 50, 100, 200]:
            config = {"api_batch_size": size}
            loader.validate(config)  # Should not raise

    def test_validate_api_batch_size_invalid(self, loader):
        """Test validating api_batch_size with invalid values."""
        config = {"api_batch_size": 0}
        with pytest.raises(ConfigError, match="api_batch_size must be >= 1"):
            loader.validate(config)

    def test_validate_api_batch_size_wrong_type(self, loader):
        """Test validating api_batch_size with wrong type."""
        config = {"api_batch_size": "200"}
        with pytest.raises(ConfigError, match="Invalid type for 'api_batch_size'"):
            loader.validate(config)

    def test_validate_api_max_retries_valid(self, loader):
        """Test validating api_max_retries with valid values."""
        for retries in [1, 3, 5, 10]:
            config = {"api_max_retries": retries}
            loader.validate(config)  # Should not raise

    def test_validate_api_max_retries_invalid(self, loader):
        """Test validating api_max_retries with invalid values."""
        config = {"api_max_retries": 0}
        with pytest.raises(ConfigError, match="api_max_retries must be >= 1"):
            loader.validate(config)

    def test_validate_api_max_retries_wrong_type(self, loader):
        """Test validating api_max_retries with wrong type."""
        config = {"api_max_retries": "5"}
        with pytest.raises(ConfigError, match="Invalid type for 'api_max_retries'"):
            loader.validate(config)

    def test_validate_api_initial_retry_delay_valid(self, loader):
        """Test validating api_initial_retry_delay with valid values."""
        for delay in [0.1, 0.5, 1.0, 5.0]:
            config = {"api_initial_retry_delay": delay}
            loader.validate(config)  # Should not raise

    def test_validate_api_initial_retry_delay_invalid(self, loader):
        """Test validating api_initial_retry_delay with invalid values."""
        config = {"api_initial_retry_delay": 0}
        with pytest.raises(ConfigError, match="api_initial_retry_delay must be > 0"):
            loader.validate(config)

    def test_validate_api_initial_retry_delay_negative(self, loader):
        """Test validating api_initial_retry_delay with negative values."""
        config = {"api_initial_retry_delay": -1.0}
        with pytest.raises(ConfigError, match="api_initial_retry_delay must be > 0"):
            loader.validate(config)

    def test_validate_api_initial_retry_delay_wrong_type(self, loader):
        """Test validating api_initial_retry_delay with wrong type."""
        config = {"api_initial_retry_delay": "1.0"}
        with pytest.raises(
            ConfigError, match="Invalid type for 'api_initial_retry_delay'"
        ):
            loader.validate(config)

    def test_validate_api_max_retry_delay_valid(self, loader):
        """Test validating api_max_retry_delay with valid values."""
        for delay in [1.0, 30.0, 60.0, 120.0]:
            config = {"api_max_retry_delay": delay}
            loader.validate(config)  # Should not raise

    def test_validate_api_max_retry_delay_invalid(self, loader):
        """Test validating api_max_retry_delay with invalid values."""
        config = {"api_max_retry_delay": -1.0}
        with pytest.raises(ConfigError, match="api_max_retry_delay must be > 0"):
            loader.validate(config)

    def test_validate_api_max_retry_delay_zero(self, loader):
        """Test validating api_max_retry_delay with zero value."""
        config = {"api_max_retry_delay": 0}
        with pytest.raises(ConfigError, match="api_max_retry_delay must be > 0"):
            loader.validate(config)

    def test_validate_api_max_retry_delay_wrong_type(self, loader):
        """Test validating api_max_retry_delay with wrong type."""
        config = {"api_max_retry_delay": "60.0"}
        with pytest.raises(ConfigError, match="Invalid type for 'api_max_retry_delay'"):
            loader.validate(config)

    def test_validate_name_similarity_threshold_valid(self, loader):
        """Test validating name_similarity_threshold with valid values."""
        for threshold in [0.0, 0.5, 0.85, 1.0]:
            config = {"name_similarity_threshold": threshold}
            loader.validate(config)  # Should not raise

    def test_validate_name_similarity_threshold_invalid_low(self, loader):
        """Test validating name_similarity_threshold below 0."""
        config = {"name_similarity_threshold": -0.1}
        with pytest.raises(ConfigError, match="must be between 0.0 and 1.0"):
            loader.validate(config)

    def test_validate_name_similarity_threshold_invalid_high(self, loader):
        """Test validating name_similarity_threshold above 1."""
        config = {"name_similarity_threshold": 1.1}
        with pytest.raises(ConfigError, match="must be between 0.0 and 1.0"):
            loader.validate(config)

    def test_validate_name_similarity_threshold_wrong_type(self, loader):
        """Test validating name_similarity_threshold with wrong type."""
        config = {"name_similarity_threshold": "0.85"}
        with pytest.raises(
            ConfigError, match="Invalid type for 'name_similarity_threshold'"
        ):
            loader.validate(config)

    def test_validate_name_only_threshold_valid(self, loader):
        """Test validating name_only_threshold with valid values."""
        for threshold in [0.0, 0.5, 0.95, 1.0]:
            config = {"name_only_threshold": threshold}
            loader.validate(config)  # Should not raise

    def test_validate_name_only_threshold_invalid(self, loader):
        """Test validating name_only_threshold with invalid values."""
        config = {"name_only_threshold": 1.5}
        with pytest.raises(ConfigError, match="must be between 0.0 and 1.0"):
            loader.validate(config)

    def test_validate_name_only_threshold_wrong_type(self, loader):
        """Test validating name_only_threshold with wrong type."""
        config = {"name_only_threshold": "0.95"}
        with pytest.raises(ConfigError, match="Invalid type for 'name_only_threshold'"):
            loader.validate(config)

    def test_validate_uncertain_threshold_valid(self, loader):
        """Test validating uncertain_threshold with valid values."""
        for threshold in [0.0, 0.5, 0.7, 1.0]:
            config = {"uncertain_threshold": threshold}
            loader.validate(config)  # Should not raise

    def test_validate_uncertain_threshold_invalid(self, loader):
        """Test validating uncertain_threshold with invalid values."""
        config = {"uncertain_threshold": -0.5}
        with pytest.raises(ConfigError, match="must be between 0.0 and 1.0"):
            loader.validate(config)

    def test_validate_uncertain_threshold_wrong_type(self, loader):
        """Test validating uncertain_threshold with wrong type."""
        config = {"uncertain_threshold": "0.7"}
        with pytest.raises(ConfigError, match="Invalid type for 'uncertain_threshold'"):
            loader.validate(config)

    def test_validate_llm_batch_size_valid(self, loader):
        """Test validating llm_batch_size with valid values."""
        for size in [1, 10, 20, 50]:
            config = {"llm_batch_size": size}
            loader.validate(config)  # Should not raise

    def test_validate_llm_batch_size_invalid(self, loader):
        """Test validating llm_batch_size with invalid values."""
        config = {"llm_batch_size": 0}
        with pytest.raises(ConfigError, match="llm_batch_size must be >= 1"):
            loader.validate(config)

    def test_validate_llm_batch_size_wrong_type(self, loader):
        """Test validating llm_batch_size with wrong type."""
        config = {"llm_batch_size": "20"}
        with pytest.raises(ConfigError, match="Invalid type for 'llm_batch_size'"):
            loader.validate(config)

    def test_validate_llm_model_valid(self, loader):
        """Test validating llm_model with valid string values."""
        config = {"llm_model": "claude-haiku-4-5-20250514"}
        loader.validate(config)  # Should not raise

    def test_validate_llm_model_wrong_type(self, loader):
        """Test validating llm_model with wrong type."""
        config = {"llm_model": 123}
        with pytest.raises(ConfigError, match="Invalid type for 'llm_model'"):
            loader.validate(config)

    def test_validate_llm_max_tokens_valid(self, loader):
        """Test validating llm_max_tokens with valid values."""
        for tokens in [100, 500, 1000]:
            config = {"llm_max_tokens": tokens}
            loader.validate(config)  # Should not raise

    def test_validate_llm_max_tokens_invalid(self, loader):
        """Test validating llm_max_tokens with invalid values."""
        config = {"llm_max_tokens": 0}
        with pytest.raises(ConfigError, match="llm_max_tokens must be >= 1"):
            loader.validate(config)

    def test_validate_llm_max_tokens_wrong_type(self, loader):
        """Test validating llm_max_tokens with wrong type."""
        config = {"llm_max_tokens": "500"}
        with pytest.raises(ConfigError, match="Invalid type for 'llm_max_tokens'"):
            loader.validate(config)

    def test_validate_llm_batch_max_tokens_valid(self, loader):
        """Test validating llm_batch_max_tokens with valid values."""
        for tokens in [500, 2000, 4000]:
            config = {"llm_batch_max_tokens": tokens}
            loader.validate(config)  # Should not raise

    def test_validate_llm_batch_max_tokens_invalid(self, loader):
        """Test validating llm_batch_max_tokens with invalid values."""
        config = {"llm_batch_max_tokens": 0}
        with pytest.raises(ConfigError, match="llm_batch_max_tokens must be >= 1"):
            loader.validate(config)

    def test_validate_llm_batch_max_tokens_wrong_type(self, loader):
        """Test validating llm_batch_max_tokens with wrong type."""
        config = {"llm_batch_max_tokens": "2000"}
        with pytest.raises(
            ConfigError, match="Invalid type for 'llm_batch_max_tokens'"
        ):
            loader.validate(config)

    def test_validate_auth_timeout_valid(self, loader):
        """Test validating auth_timeout with valid values."""
        for timeout in [1, 10, 30, 60]:
            config = {"auth_timeout": timeout}
            loader.validate(config)  # Should not raise

    def test_validate_auth_timeout_invalid(self, loader):
        """Test validating auth_timeout with invalid values."""
        config = {"auth_timeout": 0}
        with pytest.raises(ConfigError, match="auth_timeout must be >= 1"):
            loader.validate(config)

    def test_validate_auth_timeout_negative(self, loader):
        """Test validating auth_timeout with negative values."""
        config = {"auth_timeout": -5}
        with pytest.raises(ConfigError, match="auth_timeout must be >= 1"):
            loader.validate(config)

    def test_validate_auth_timeout_wrong_type(self, loader):
        """Test validating auth_timeout with wrong type."""
        config = {"auth_timeout": "10"}
        with pytest.raises(ConfigError, match="Invalid type for 'auth_timeout'"):
            loader.validate(config)

    def test_validate_log_dir_valid(self, loader):
        """Test validating log_dir with valid string values."""
        config = {"log_dir": "/var/log/gcontact-sync"}
        loader.validate(config)  # Should not raise

    def test_validate_log_dir_wrong_type(self, loader):
        """Test validating log_dir with wrong type."""
        config = {"log_dir": 123}
        with pytest.raises(ConfigError, match="Invalid type for 'log_dir'"):
            loader.validate(config)

    def test_validate_complete_tier1_tier2_config(self, loader):
        """Test validating a config with all Tier 1 and Tier 2 options."""
        config = {
            # CLI options
            "dry_run": True,
            "verbose": True,
            "debug": False,
            "full": False,
            "strategy": "last_modified",
            # API options (Tier 1)
            "api_page_size": 100,
            "api_batch_size": 200,
            "api_max_retries": 5,
            "api_initial_retry_delay": 1.0,
            "api_max_retry_delay": 60.0,
            # Matching options (Tier 1)
            "name_similarity_threshold": 0.85,
            "name_only_threshold": 0.95,
            "uncertain_threshold": 0.7,
            "llm_batch_size": 20,
            # LLM options (Tier 1/2)
            "llm_model": "claude-haiku-4-5-20250514",
            "llm_max_tokens": 500,
            "llm_batch_max_tokens": 2000,
            # Auth options (Tier 2)
            "auth_timeout": 10,
            # Logging options (Tier 2)
            "log_dir": "/var/log/gcontact",
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
        assert config_path.read_text() == "existing content"

    def test_save_config_file_existing_file_with_overwrite(self, tmp_path):
        """Test that existing file is overwritten with overwrite=True."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("existing content", encoding="utf-8")

        success, error = save_config_file(config_path, overwrite=True)

        assert success is True
        assert error is None
        assert config_path.read_text() != "existing content"

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
        assert Path.home() / ".gcontact-sync" == DEFAULT_CONFIG_DIR

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


# ==============================================================================
# SyncConfig Module Tests (Tag-Based Filtering)
# ==============================================================================


class TestAccountSyncConfigBasics:
    """Tests for basic AccountSyncConfig instantiation and attributes."""

    def test_create_account_config_with_groups(self):
        """Test creating account config with specific groups."""
        config = AccountSyncConfig(sync_groups=["Work", "Family"])
        assert config.sync_groups == ["Work", "Family"]

    def test_create_account_config_empty_groups(self):
        """Test creating account config with empty groups list."""
        config = AccountSyncConfig(sync_groups=[])
        assert config.sync_groups == []

    def test_create_account_config_default_groups(self):
        """Test default sync_groups is empty list."""
        config = AccountSyncConfig()
        assert config.sync_groups == []

    def test_account_config_with_resource_names(self):
        """Test account config with group resource names."""
        config = AccountSyncConfig(
            sync_groups=["contactGroups/abc123", "contactGroups/def456"]
        )
        assert "contactGroups/abc123" in config.sync_groups
        assert "contactGroups/def456" in config.sync_groups

    def test_account_config_with_mixed_identifiers(self):
        """Test account config with both display names and resource names."""
        config = AccountSyncConfig(
            sync_groups=["Work", "contactGroups/abc123", "Family"]
        )
        assert len(config.sync_groups) == 3


class TestAccountSyncConfigHasFilter:
    """Tests for AccountSyncConfig.has_filter() method."""

    def test_has_filter_returns_true_with_groups(self):
        """Test has_filter returns True when groups are configured."""
        config = AccountSyncConfig(sync_groups=["Work"])
        assert config.has_filter() is True

    def test_has_filter_returns_false_with_empty_groups(self):
        """Test has_filter returns False when groups list is empty."""
        config = AccountSyncConfig(sync_groups=[])
        assert config.has_filter() is False

    def test_has_filter_returns_false_with_default(self):
        """Test has_filter returns False with default config."""
        config = AccountSyncConfig()
        assert config.has_filter() is False


class TestAccountSyncConfigShouldSyncGroup:
    """Tests for AccountSyncConfig.should_sync_group() method."""

    def test_should_sync_group_matches_exact_display_name(self):
        """Test exact match of display name."""
        config = AccountSyncConfig(sync_groups=["Work"])
        assert config.should_sync_group("Work") is True

    def test_should_sync_group_matches_case_insensitive(self):
        """Test case-insensitive matching of display names."""
        config = AccountSyncConfig(sync_groups=["Work"])
        assert config.should_sync_group("work") is True
        assert config.should_sync_group("WORK") is True
        assert config.should_sync_group("WoRk") is True

    def test_should_sync_group_matches_resource_name(self):
        """Test exact match of resource name."""
        config = AccountSyncConfig(sync_groups=["contactGroups/abc123"])
        assert config.should_sync_group("contactGroups/abc123") is True

    def test_should_sync_group_resource_name_case_sensitive(self):
        """Test resource names match case-sensitively."""
        config = AccountSyncConfig(sync_groups=["contactGroups/Abc123"])
        # Resource name exact match works
        assert config.should_sync_group("contactGroups/Abc123") is True
        # But lowercase check also happens
        assert config.should_sync_group("contactGroups/abc123") is True

    def test_should_sync_group_returns_false_for_non_matching(self):
        """Test returns False for non-matching groups."""
        config = AccountSyncConfig(sync_groups=["Work"])
        assert config.should_sync_group("Personal") is False

    def test_should_sync_group_returns_true_when_no_filter(self):
        """Test returns True for any group when no filter is set."""
        config = AccountSyncConfig(sync_groups=[])
        assert config.should_sync_group("Work") is True
        assert config.should_sync_group("Personal") is True
        assert config.should_sync_group("contactGroups/anything") is True

    def test_should_sync_group_multiple_groups(self):
        """Test matching against multiple configured groups."""
        config = AccountSyncConfig(sync_groups=["Work", "Family", "Important"])
        assert config.should_sync_group("Work") is True
        assert config.should_sync_group("Family") is True
        assert config.should_sync_group("Important") is True
        assert config.should_sync_group("Personal") is False


class TestAccountSyncConfigFromDict:
    """Tests for AccountSyncConfig.from_dict() method."""

    def test_from_dict_valid_config(self):
        """Test creating from valid dictionary."""
        data = {"sync_groups": ["Work", "Family"]}
        config = AccountSyncConfig.from_dict(data)
        assert config.sync_groups == ["Work", "Family"]

    def test_from_dict_empty_groups(self):
        """Test creating from dictionary with empty groups."""
        data = {"sync_groups": []}
        config = AccountSyncConfig.from_dict(data)
        assert config.sync_groups == []

    def test_from_dict_missing_sync_groups(self):
        """Test creating from dictionary without sync_groups key."""
        data = {}
        config = AccountSyncConfig.from_dict(data)
        assert config.sync_groups == []

    def test_from_dict_none_returns_default(self):
        """Test that None input returns default config."""
        config = AccountSyncConfig.from_dict(None)
        assert config.sync_groups == []

    def test_from_dict_invalid_not_dict_raises_error(self):
        """Test that non-dict input raises SyncConfigError."""
        with pytest.raises(SyncConfigError) as exc_info:
            AccountSyncConfig.from_dict("not a dict")
        assert "must be a dictionary" in str(exc_info.value)

    def test_from_dict_invalid_sync_groups_not_list(self):
        """Test that non-list sync_groups raises SyncConfigError."""
        data = {"sync_groups": "not a list"}
        with pytest.raises(SyncConfigError) as exc_info:
            AccountSyncConfig.from_dict(data)
        assert "must be a list" in str(exc_info.value)

    def test_from_dict_invalid_sync_groups_item_not_string(self):
        """Test that non-string items in sync_groups raise SyncConfigError."""
        data = {"sync_groups": ["Work", 123, "Family"]}
        with pytest.raises(SyncConfigError) as exc_info:
            AccountSyncConfig.from_dict(data)
        assert "sync_groups[1] must be a string" in str(exc_info.value)


class TestAccountSyncConfigToDict:
    """Tests for AccountSyncConfig.to_dict() method."""

    def test_to_dict_with_groups(self):
        """Test conversion to dictionary with groups."""
        config = AccountSyncConfig(sync_groups=["Work", "Family"])
        result = config.to_dict()
        assert result == {"sync_groups": ["Work", "Family"]}

    def test_to_dict_empty_groups(self):
        """Test conversion to dictionary with empty groups."""
        config = AccountSyncConfig(sync_groups=[])
        result = config.to_dict()
        assert result == {"sync_groups": []}


class TestSyncConfigBasics:
    """Tests for basic SyncConfig instantiation and attributes."""

    def test_create_sync_config_default(self):
        """Test creating SyncConfig with defaults."""
        config = SyncConfig()
        assert config.version == CONFIG_VERSION
        assert config.account1.sync_groups == []
        assert config.account2.sync_groups == []

    def test_create_sync_config_with_accounts(self):
        """Test creating SyncConfig with account configurations."""
        config = SyncConfig(
            account1=AccountSyncConfig(sync_groups=["Work"]),
            account2=AccountSyncConfig(sync_groups=["Personal"]),
        )
        assert config.account1.sync_groups == ["Work"]
        assert config.account2.sync_groups == ["Personal"]

    def test_create_sync_config_with_version(self):
        """Test creating SyncConfig with specific version."""
        config = SyncConfig(version="2.0")
        assert config.version == "2.0"


class TestSyncConfigHasAnyFilter:
    """Tests for SyncConfig.has_any_filter() method."""

    def test_has_any_filter_both_empty(self):
        """Test returns False when both accounts have no filter."""
        config = SyncConfig()
        assert config.has_any_filter() is False

    def test_has_any_filter_account1_has_filter(self):
        """Test returns True when account1 has filter."""
        config = SyncConfig(
            account1=AccountSyncConfig(sync_groups=["Work"]),
        )
        assert config.has_any_filter() is True

    def test_has_any_filter_account2_has_filter(self):
        """Test returns True when account2 has filter."""
        config = SyncConfig(
            account2=AccountSyncConfig(sync_groups=["Work"]),
        )
        assert config.has_any_filter() is True

    def test_has_any_filter_both_have_filter(self):
        """Test returns True when both accounts have filter."""
        config = SyncConfig(
            account1=AccountSyncConfig(sync_groups=["Work"]),
            account2=AccountSyncConfig(sync_groups=["Personal"]),
        )
        assert config.has_any_filter() is True


class TestSyncConfigFromDict:
    """Tests for SyncConfig.from_dict() method."""

    def test_from_dict_full_config(self):
        """Test creating from full configuration dictionary."""
        data = {
            "version": "1.0",
            "account1": {"sync_groups": ["Work", "Family"]},
            "account2": {"sync_groups": ["Important"]},
        }
        config = SyncConfig.from_dict(data)
        assert config.version == "1.0"
        assert config.account1.sync_groups == ["Work", "Family"]
        assert config.account2.sync_groups == ["Important"]

    def test_from_dict_minimal_config(self):
        """Test creating from minimal configuration dictionary."""
        data = {}
        config = SyncConfig.from_dict(data)
        assert config.version == CONFIG_VERSION
        assert config.account1.sync_groups == []
        assert config.account2.sync_groups == []

    def test_from_dict_missing_accounts(self):
        """Test creating from dictionary with missing account keys."""
        data = {"version": "1.0"}
        config = SyncConfig.from_dict(data)
        assert config.account1.sync_groups == []
        assert config.account2.sync_groups == []

    def test_from_dict_only_account1(self):
        """Test creating from dictionary with only account1."""
        data = {"account1": {"sync_groups": ["Work"]}}
        config = SyncConfig.from_dict(data)
        assert config.account1.sync_groups == ["Work"]
        assert config.account2.sync_groups == []

    def test_from_dict_invalid_not_dict_raises_error(self):
        """Test that non-dict input raises SyncConfigError."""
        with pytest.raises(SyncConfigError) as exc_info:
            SyncConfig.from_dict("not a dict")
        assert "must be a dictionary" in str(exc_info.value)

    def test_from_dict_invalid_version_not_string(self):
        """Test that non-string version raises SyncConfigError."""
        data = {"version": 123}
        with pytest.raises(SyncConfigError) as exc_info:
            SyncConfig.from_dict(data)
        assert "version must be a string" in str(exc_info.value)


class TestSyncConfigToDict:
    """Tests for SyncConfig.to_dict() method."""

    def test_to_dict_full_config(self):
        """Test conversion to dictionary with all fields."""
        from gcontact_sync.config.sync_config import DEFAULT_SYNC_LABEL_GROUP_NAME

        config = SyncConfig(
            version="1.0",
            account1=AccountSyncConfig(sync_groups=["Work"]),
            account2=AccountSyncConfig(sync_groups=["Family"]),
        )
        result = config.to_dict()
        assert result == {
            "version": "1.0",
            "sync_label": {
                "enabled": True,
                "group_name": DEFAULT_SYNC_LABEL_GROUP_NAME,
            },
            "account1": {"sync_groups": ["Work"]},
            "account2": {"sync_groups": ["Family"]},
        }

    def test_to_dict_empty_config(self):
        """Test conversion of empty config to dictionary."""
        from gcontact_sync.config.sync_config import DEFAULT_SYNC_LABEL_GROUP_NAME

        config = SyncConfig()
        result = config.to_dict()
        assert result == {
            "version": CONFIG_VERSION,
            "sync_label": {
                "enabled": True,
                "group_name": DEFAULT_SYNC_LABEL_GROUP_NAME,
            },
            "account1": {"sync_groups": []},
            "account2": {"sync_groups": []},
        }


class TestSyncConfigRepr:
    """Tests for SyncConfig.__repr__() method."""

    def test_repr_contains_key_info(self):
        """Test that repr contains key information."""
        config = SyncConfig(
            version="1.0",
            account1=AccountSyncConfig(sync_groups=["Work"]),
            account2=AccountSyncConfig(sync_groups=["Family"]),
        )
        repr_str = repr(config)
        assert "SyncConfig" in repr_str
        assert "version='1.0'" in repr_str
        assert "Work" in repr_str
        assert "Family" in repr_str


class TestSyncConfigLoadFromFile:
    """Tests for SyncConfig.load_from_file() method."""

    def test_load_from_file_valid_json(self, tmp_path):
        """Test loading valid JSON config file."""
        import json

        config_file = tmp_path / "sync_config.json"
        config_data = {
            "version": "1.0",
            "account1": {"sync_groups": ["Work", "Family"]},
            "account2": {"sync_groups": ["Important"]},
        }
        config_file.write_text(json.dumps(config_data))

        config = SyncConfig.load_from_file(config_file)

        assert config.version == "1.0"
        assert config.account1.sync_groups == ["Work", "Family"]
        assert config.account2.sync_groups == ["Important"]

    def test_load_from_file_missing_file_returns_default(self, tmp_path):
        """Test that missing file returns default config (backwards compatibility)."""
        config_file = tmp_path / "nonexistent.json"

        config = SyncConfig.load_from_file(config_file)

        assert config.version == CONFIG_VERSION
        assert config.account1.sync_groups == []
        assert config.account2.sync_groups == []

    def test_load_from_file_invalid_json_raises_error(self, tmp_path):
        """Test that invalid JSON raises SyncConfigError."""
        config_file = tmp_path / "sync_config.json"
        config_file.write_text("{invalid json")

        with pytest.raises(SyncConfigError) as exc_info:
            SyncConfig.load_from_file(config_file)
        assert "Failed to parse sync config JSON" in str(exc_info.value)

    def test_load_from_file_empty_file_raises_error(self, tmp_path):
        """Test that empty file raises SyncConfigError."""
        config_file = tmp_path / "sync_config.json"
        config_file.write_text("")

        with pytest.raises(SyncConfigError) as exc_info:
            SyncConfig.load_from_file(config_file)
        assert "Failed to parse sync config JSON" in str(exc_info.value)

    def test_load_from_file_malformed_structure(self, tmp_path):
        """Test that malformed structure raises SyncConfigError."""
        import json

        config_file = tmp_path / "sync_config.json"
        # JSON array instead of object
        config_file.write_text(json.dumps(["not", "a", "dict"]))

        with pytest.raises(SyncConfigError) as exc_info:
            SyncConfig.load_from_file(config_file)
        assert "must be a dictionary" in str(exc_info.value)

    def test_load_from_file_handles_path_object(self, tmp_path):
        """Test loading with Path object."""
        import json

        config_file = tmp_path / "sync_config.json"
        config_file.write_text(json.dumps({"version": "1.0"}))

        config = SyncConfig.load_from_file(Path(config_file))

        assert config.version == "1.0"


class TestSyncConfigSaveToFile:
    """Tests for SyncConfig.save_to_file() method."""

    def test_save_to_file_creates_file(self, tmp_path):
        """Test saving creates new file."""
        import json

        config_file = tmp_path / "sync_config.json"
        config = SyncConfig(
            account1=AccountSyncConfig(sync_groups=["Work"]),
        )

        config.save_to_file(config_file)

        assert config_file.exists()
        saved_data = json.loads(config_file.read_text())
        assert saved_data["account1"]["sync_groups"] == ["Work"]

    def test_save_to_file_creates_parent_directories(self, tmp_path):
        """Test saving creates parent directories."""
        config_file = tmp_path / "nested" / "dir" / "sync_config.json"
        config = SyncConfig()

        config.save_to_file(config_file)

        assert config_file.exists()
        assert (tmp_path / "nested" / "dir").is_dir()

    def test_save_to_file_overwrites_existing(self, tmp_path):
        """Test saving overwrites existing file."""
        import json

        config_file = tmp_path / "sync_config.json"
        config_file.write_text('{"old": "data"}')

        config = SyncConfig(
            account1=AccountSyncConfig(sync_groups=["New"]),
        )
        config.save_to_file(config_file)

        saved_data = json.loads(config_file.read_text())
        assert "old" not in saved_data
        assert saved_data["account1"]["sync_groups"] == ["New"]

    def test_save_to_file_preserves_formatting(self, tmp_path):
        """Test that saved file has nice formatting."""
        config_file = tmp_path / "sync_config.json"
        config = SyncConfig()

        config.save_to_file(config_file)

        content = config_file.read_text()
        # Should have indentation
        assert "  " in content
        # Should end with newline
        assert content.endswith("\n")

    def test_save_to_file_roundtrip(self, tmp_path):
        """Test save then load preserves data."""
        config_file = tmp_path / "sync_config.json"
        original = SyncConfig(
            version="1.0",
            account1=AccountSyncConfig(sync_groups=["Work", "Family"]),
            account2=AccountSyncConfig(sync_groups=["Important"]),
        )

        original.save_to_file(config_file)
        loaded = SyncConfig.load_from_file(config_file)

        assert loaded.version == original.version
        assert loaded.account1.sync_groups == original.account1.sync_groups
        assert loaded.account2.sync_groups == original.account2.sync_groups


class TestLoadConfigFunction:
    """Tests for the load_config() convenience function."""

    def test_load_config_from_explicit_directory(self, tmp_path):
        """Test loading from explicit directory path."""
        import json

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / DEFAULT_SYNC_CONFIG_FILE
        config_file.write_text(json.dumps({"account1": {"sync_groups": ["Work"]}}))

        config = load_config(config_dir)

        assert config.account1.sync_groups == ["Work"]

    def test_load_config_from_string_path(self, tmp_path):
        """Test loading from string path."""
        import json

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / DEFAULT_SYNC_CONFIG_FILE
        config_file.write_text(json.dumps({"account1": {"sync_groups": ["Work"]}}))

        config = load_config(str(config_dir))

        assert config.account1.sync_groups == ["Work"]

    def test_load_config_from_env_variable(self, tmp_path, monkeypatch):
        """Test loading from GCONTACT_SYNC_CONFIG_DIR environment variable."""
        import json

        config_dir = tmp_path / "env_config"
        config_dir.mkdir()
        config_file = config_dir / DEFAULT_SYNC_CONFIG_FILE
        config_file.write_text(json.dumps({"account1": {"sync_groups": ["EnvWork"]}}))

        monkeypatch.setenv("GCONTACT_SYNC_CONFIG_DIR", str(config_dir))

        config = load_config()

        assert config.account1.sync_groups == ["EnvWork"]

    def test_load_config_explicit_overrides_env(self, tmp_path, monkeypatch):
        """Test that explicit path overrides environment variable."""
        import json

        # Env config
        env_config_dir = tmp_path / "env_config"
        env_config_dir.mkdir()
        env_config_file = env_config_dir / DEFAULT_SYNC_CONFIG_FILE
        env_config_file.write_text(
            json.dumps({"account1": {"sync_groups": ["FromEnv"]}})
        )

        # Explicit config
        explicit_config_dir = tmp_path / "explicit_config"
        explicit_config_dir.mkdir()
        explicit_config_file = explicit_config_dir / DEFAULT_SYNC_CONFIG_FILE
        explicit_config_file.write_text(
            json.dumps({"account1": {"sync_groups": ["FromExplicit"]}})
        )

        monkeypatch.setenv("GCONTACT_SYNC_CONFIG_DIR", str(env_config_dir))

        config = load_config(explicit_config_dir)

        assert config.account1.sync_groups == ["FromExplicit"]

    def test_load_config_missing_directory_returns_default(self, tmp_path):
        """Test that missing directory returns default config."""
        nonexistent = tmp_path / "nonexistent"

        config = load_config(nonexistent)

        assert config.account1.sync_groups == []
        assert config.account2.sync_groups == []

    def test_load_config_missing_file_returns_default(self, tmp_path):
        """Test that existing directory without config file returns default."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        # No config file created

        config = load_config(config_dir)

        assert config.account1.sync_groups == []
        assert config.account2.sync_groups == []

    def test_load_config_invalid_json_raises_error(self, tmp_path):
        """Test that invalid JSON in config file raises error."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / DEFAULT_SYNC_CONFIG_FILE
        config_file.write_text("{invalid")

        with pytest.raises(SyncConfigError):
            load_config(config_dir)


class TestSyncConfigBackwardsCompatibility:
    """Tests ensuring backwards compatibility with existing setups."""

    def test_no_config_file_syncs_all(self, tmp_path):
        """Test that missing config file means sync all (no filtering)."""
        config = load_config(tmp_path)

        assert not config.has_any_filter()
        assert config.account1.should_sync_group("AnyGroup") is True
        assert config.account2.should_sync_group("AnyGroup") is True

    def test_empty_sync_groups_syncs_all(self, tmp_path):
        """Test that empty sync_groups means sync all."""
        import json

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / DEFAULT_SYNC_CONFIG_FILE
        config_file.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "account1": {"sync_groups": []},
                    "account2": {"sync_groups": []},
                }
            )
        )

        config = load_config(config_dir)

        assert not config.has_any_filter()
        assert config.account1.should_sync_group("AnyGroup") is True

    def test_partial_config_syncs_all_for_unconfigured(self, tmp_path):
        """Test that unconfigured account syncs all contacts."""
        import json

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / DEFAULT_SYNC_CONFIG_FILE
        # Only account1 configured
        config_file.write_text(
            json.dumps(
                {
                    "account1": {"sync_groups": ["Work"]},
                }
            )
        )

        config = load_config(config_dir)

        # Account1 has filter
        assert config.account1.has_filter()
        assert config.account1.should_sync_group("Work") is True
        assert config.account1.should_sync_group("Personal") is False

        # Account2 syncs all
        assert not config.account2.has_filter()
        assert config.account2.should_sync_group("AnyGroup") is True


class TestSyncConfigEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_unicode_group_names(self):
        """Test handling of unicode characters in group names."""
        config = AccountSyncConfig(sync_groups=["工作", "家庭", "Família"])
        assert config.should_sync_group("工作") is True
        assert config.should_sync_group("家庭") is True
        assert config.should_sync_group("Família") is True

    def test_unicode_group_names_case_insensitive(self):
        """Test case-insensitive matching with unicode."""
        config = AccountSyncConfig(sync_groups=["FAMÍLIA"])
        assert config.should_sync_group("família") is True

    def test_whitespace_in_group_names(self):
        """Test handling of whitespace in group names."""
        config = AccountSyncConfig(sync_groups=["  Work Team  ", "Family Friends"])
        # Exact match with whitespace
        assert config.should_sync_group("  Work Team  ") is True
        # Without whitespace doesn't match
        assert config.should_sync_group("Work Team") is False

    def test_empty_string_group_name(self):
        """Test handling of empty string group name."""
        config = AccountSyncConfig(sync_groups=[""])
        assert config.has_filter() is True
        assert config.should_sync_group("") is True
        assert config.should_sync_group("Work") is False

    def test_very_long_group_name(self):
        """Test handling of very long group names."""
        long_name = "A" * 1000
        config = AccountSyncConfig(sync_groups=[long_name])
        assert config.should_sync_group(long_name) is True

    def test_special_characters_in_group_name(self):
        """Test handling of special characters in group names."""
        config = AccountSyncConfig(sync_groups=["Work & Home", "Friends (close)"])
        assert config.should_sync_group("Work & Home") is True
        assert config.should_sync_group("Friends (close)") is True

    def test_many_groups(self):
        """Test handling of many configured groups."""
        groups = [f"Group{i}" for i in range(100)]
        config = AccountSyncConfig(sync_groups=groups)

        assert config.should_sync_group("Group0") is True
        assert config.should_sync_group("Group50") is True
        assert config.should_sync_group("Group99") is True
        assert config.should_sync_group("Group100") is False

    def test_json_file_with_extra_fields(self, tmp_path):
        """Test that extra fields in JSON are ignored."""
        import json

        config_file = tmp_path / "sync_config.json"
        config_file.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "account1": {"sync_groups": ["Work"], "unknown_field": "ignored"},
                    "account2": {"sync_groups": []},
                    "extra_top_level": "also ignored",
                }
            )
        )

        config = SyncConfig.load_from_file(config_file)

        assert config.account1.sync_groups == ["Work"]

    def test_json_with_null_values(self, tmp_path):
        """Test handling of null values in JSON."""
        import json

        config_file = tmp_path / "sync_config.json"
        config_file.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "account1": None,
                    "account2": {"sync_groups": ["Work"]},
                }
            )
        )

        config = SyncConfig.load_from_file(config_file)

        assert config.account1.sync_groups == []
        assert config.account2.sync_groups == ["Work"]


class TestSyncConfigConstants:
    """Tests for sync configuration constants and defaults."""

    def test_config_version_is_defined(self):
        """Test that CONFIG_VERSION is defined."""
        assert CONFIG_VERSION is not None
        assert isinstance(CONFIG_VERSION, str)
        assert CONFIG_VERSION == "1.0"

    def test_default_sync_config_file_name(self):
        """Test default sync config file name."""
        assert DEFAULT_SYNC_CONFIG_FILE == "sync_config.json"


class TestSyncConfigErrorException:
    """Tests for SyncConfigError exception."""

    def test_sync_config_error_is_exception(self):
        """Test that SyncConfigError is an Exception."""
        assert issubclass(SyncConfigError, Exception)

    def test_sync_config_error_can_be_raised(self):
        """Test that SyncConfigError can be raised with a message."""
        with pytest.raises(SyncConfigError, match="Test sync error"):
            raise SyncConfigError("Test sync error")

    def test_sync_config_error_can_be_caught(self):
        """Test that SyncConfigError can be caught as Exception."""
        try:
            raise SyncConfigError("Test error")
        except Exception as e:
            assert isinstance(e, SyncConfigError)
            assert str(e) == "Test error"


# ==============================================================================
# SyncLabelConfig Tests (Sync Label Group Feature)
# ==============================================================================


class TestSyncLabelConfigBasics:
    """Tests for basic SyncLabelConfig instantiation and attributes."""

    def test_create_sync_label_config_default(self):
        """Test creating SyncLabelConfig with defaults."""
        from gcontact_sync.config.sync_config import (
            DEFAULT_SYNC_LABEL_GROUP_NAME,
            SyncLabelConfig,
        )

        config = SyncLabelConfig()
        assert config.enabled is True
        assert config.group_name == DEFAULT_SYNC_LABEL_GROUP_NAME

    def test_create_sync_label_config_disabled(self):
        """Test creating SyncLabelConfig with enabled=False."""
        from gcontact_sync.config.sync_config import SyncLabelConfig

        config = SyncLabelConfig(enabled=False)
        assert config.enabled is False

    def test_create_sync_label_config_custom_name(self):
        """Test creating SyncLabelConfig with custom group name."""
        from gcontact_sync.config.sync_config import SyncLabelConfig

        config = SyncLabelConfig(group_name="My Custom Sync Label")
        assert config.group_name == "My Custom Sync Label"

    def test_create_sync_label_config_all_custom(self):
        """Test creating SyncLabelConfig with all custom values."""
        from gcontact_sync.config.sync_config import SyncLabelConfig

        config = SyncLabelConfig(enabled=False, group_name="Custom Label")
        assert config.enabled is False
        assert config.group_name == "Custom Label"


class TestSyncLabelConfigFromDict:
    """Tests for SyncLabelConfig.from_dict() method."""

    def test_from_dict_valid_config(self):
        """Test creating from valid dictionary."""
        from gcontact_sync.config.sync_config import SyncLabelConfig

        data = {"enabled": True, "group_name": "Test Label"}
        config = SyncLabelConfig.from_dict(data)
        assert config.enabled is True
        assert config.group_name == "Test Label"

    def test_from_dict_disabled(self):
        """Test creating from dictionary with enabled=False."""
        from gcontact_sync.config.sync_config import SyncLabelConfig

        data = {"enabled": False, "group_name": "Test Label"}
        config = SyncLabelConfig.from_dict(data)
        assert config.enabled is False

    def test_from_dict_missing_enabled_defaults_true(self):
        """Test that missing enabled defaults to True."""
        from gcontact_sync.config.sync_config import SyncLabelConfig

        data = {"group_name": "Test Label"}
        config = SyncLabelConfig.from_dict(data)
        assert config.enabled is True

    def test_from_dict_missing_group_name_uses_default(self):
        """Test that missing group_name uses default."""
        from gcontact_sync.config.sync_config import (
            DEFAULT_SYNC_LABEL_GROUP_NAME,
            SyncLabelConfig,
        )

        data = {"enabled": True}
        config = SyncLabelConfig.from_dict(data)
        assert config.group_name == DEFAULT_SYNC_LABEL_GROUP_NAME

    def test_from_dict_empty_dict_uses_defaults(self):
        """Test that empty dictionary uses all defaults."""
        from gcontact_sync.config.sync_config import (
            DEFAULT_SYNC_LABEL_GROUP_NAME,
            SyncLabelConfig,
        )

        data = {}
        config = SyncLabelConfig.from_dict(data)
        assert config.enabled is True
        assert config.group_name == DEFAULT_SYNC_LABEL_GROUP_NAME

    def test_from_dict_none_returns_default(self):
        """Test that None input returns default config."""
        from gcontact_sync.config.sync_config import (
            DEFAULT_SYNC_LABEL_GROUP_NAME,
            SyncLabelConfig,
        )

        config = SyncLabelConfig.from_dict(None)
        assert config.enabled is True
        assert config.group_name == DEFAULT_SYNC_LABEL_GROUP_NAME

    def test_from_dict_invalid_not_dict_raises_error(self):
        """Test that non-dict input raises SyncConfigError."""
        from gcontact_sync.config.sync_config import SyncConfigError, SyncLabelConfig

        with pytest.raises(SyncConfigError) as exc_info:
            SyncLabelConfig.from_dict("not a dict")
        assert "must be a dictionary" in str(exc_info.value)

    def test_from_dict_invalid_enabled_not_bool(self):
        """Test that non-bool enabled raises SyncConfigError."""
        from gcontact_sync.config.sync_config import SyncConfigError, SyncLabelConfig

        data = {"enabled": "yes"}
        with pytest.raises(SyncConfigError) as exc_info:
            SyncLabelConfig.from_dict(data)
        assert "must be a boolean" in str(exc_info.value)

    def test_from_dict_invalid_group_name_not_string(self):
        """Test that non-string group_name raises SyncConfigError."""
        from gcontact_sync.config.sync_config import SyncConfigError, SyncLabelConfig

        data = {"group_name": 123}
        with pytest.raises(SyncConfigError) as exc_info:
            SyncLabelConfig.from_dict(data)
        assert "must be a string" in str(exc_info.value)

    def test_from_dict_invalid_empty_group_name(self):
        """Test that empty group_name raises SyncConfigError."""
        from gcontact_sync.config.sync_config import SyncConfigError, SyncLabelConfig

        data = {"group_name": ""}
        with pytest.raises(SyncConfigError) as exc_info:
            SyncLabelConfig.from_dict(data)
        assert "cannot be empty" in str(exc_info.value)

    def test_from_dict_invalid_whitespace_only_group_name(self):
        """Test that whitespace-only group_name raises SyncConfigError."""
        from gcontact_sync.config.sync_config import SyncConfigError, SyncLabelConfig

        data = {"group_name": "   "}
        with pytest.raises(SyncConfigError) as exc_info:
            SyncLabelConfig.from_dict(data)
        assert "cannot be empty" in str(exc_info.value)


class TestSyncLabelConfigToDict:
    """Tests for SyncLabelConfig.to_dict() method."""

    def test_to_dict_default(self):
        """Test conversion of default config to dictionary."""
        from gcontact_sync.config.sync_config import (
            DEFAULT_SYNC_LABEL_GROUP_NAME,
            SyncLabelConfig,
        )

        config = SyncLabelConfig()
        result = config.to_dict()
        assert result == {"enabled": True, "group_name": DEFAULT_SYNC_LABEL_GROUP_NAME}

    def test_to_dict_custom(self):
        """Test conversion of custom config to dictionary."""
        from gcontact_sync.config.sync_config import SyncLabelConfig

        config = SyncLabelConfig(enabled=False, group_name="Custom")
        result = config.to_dict()
        assert result == {"enabled": False, "group_name": "Custom"}

    def test_to_dict_roundtrip(self):
        """Test that to_dict and from_dict are inverse operations."""
        from gcontact_sync.config.sync_config import SyncLabelConfig

        original = SyncLabelConfig(enabled=False, group_name="Roundtrip Test")
        result = SyncLabelConfig.from_dict(original.to_dict())
        assert result.enabled == original.enabled
        assert result.group_name == original.group_name


class TestSyncConfigWithSyncLabel:
    """Tests for SyncConfig integration with SyncLabelConfig."""

    def test_sync_config_default_has_sync_label(self):
        """Test that default SyncConfig has sync_label enabled."""
        from gcontact_sync.config.sync_config import (
            DEFAULT_SYNC_LABEL_GROUP_NAME,
            SyncConfig,
        )

        config = SyncConfig()
        assert config.sync_label.enabled is True
        assert config.sync_label.group_name == DEFAULT_SYNC_LABEL_GROUP_NAME

    def test_sync_config_with_custom_sync_label(self):
        """Test creating SyncConfig with custom SyncLabelConfig."""
        from gcontact_sync.config.sync_config import SyncConfig, SyncLabelConfig

        config = SyncConfig(
            sync_label=SyncLabelConfig(enabled=False, group_name="Custom"),
        )
        assert config.sync_label.enabled is False
        assert config.sync_label.group_name == "Custom"

    def test_sync_config_from_dict_with_sync_label(self):
        """Test SyncConfig.from_dict with sync_label configuration."""
        from gcontact_sync.config.sync_config import SyncConfig

        data = {
            "version": "1.0",
            "sync_label": {"enabled": True, "group_name": "My Synced"},
            "account1": {"sync_groups": ["Work"]},
            "account2": {"sync_groups": []},
        }
        config = SyncConfig.from_dict(data)
        assert config.sync_label.enabled is True
        assert config.sync_label.group_name == "My Synced"

    def test_sync_config_from_dict_without_sync_label_uses_defaults(self):
        """Test SyncConfig.from_dict uses defaults when sync_label missing."""
        from gcontact_sync.config.sync_config import (
            DEFAULT_SYNC_LABEL_GROUP_NAME,
            SyncConfig,
        )

        data = {
            "version": "1.0",
            "account1": {"sync_groups": ["Work"]},
        }
        config = SyncConfig.from_dict(data)
        assert config.sync_label.enabled is True
        assert config.sync_label.group_name == DEFAULT_SYNC_LABEL_GROUP_NAME

    def test_sync_config_to_dict_includes_sync_label(self):
        """Test SyncConfig.to_dict includes sync_label."""
        from gcontact_sync.config.sync_config import SyncConfig, SyncLabelConfig

        config = SyncConfig(
            sync_label=SyncLabelConfig(enabled=False, group_name="Custom"),
        )
        result = config.to_dict()
        assert "sync_label" in result
        assert result["sync_label"] == {"enabled": False, "group_name": "Custom"}

    def test_sync_config_repr_includes_sync_label(self):
        """Test SyncConfig.__repr__ includes sync_label info."""
        from gcontact_sync.config.sync_config import SyncConfig, SyncLabelConfig

        config = SyncConfig(
            sync_label=SyncLabelConfig(group_name="Test Label"),
        )
        repr_str = repr(config)
        assert "Test Label" in repr_str
        assert "enabled=True" in repr_str

    def test_sync_config_load_from_file_with_sync_label(self, tmp_path):
        """Test loading config file with sync_label configuration."""
        import json

        from gcontact_sync.config.sync_config import SyncConfig

        config_file = tmp_path / "sync_config.json"
        config_data = {
            "version": "1.0",
            "sync_label": {"enabled": True, "group_name": "Loaded Label"},
            "account1": {"sync_groups": ["Work"]},
            "account2": {"sync_groups": []},
        }
        config_file.write_text(json.dumps(config_data))

        config = SyncConfig.load_from_file(config_file)

        assert config.sync_label.enabled is True
        assert config.sync_label.group_name == "Loaded Label"

    def test_sync_config_load_from_file_without_sync_label(self, tmp_path):
        """Test loading config file without sync_label uses defaults."""
        import json

        from gcontact_sync.config.sync_config import (
            DEFAULT_SYNC_LABEL_GROUP_NAME,
            SyncConfig,
        )

        config_file = tmp_path / "sync_config.json"
        config_data = {
            "version": "1.0",
            "account1": {"sync_groups": ["Work"]},
        }
        config_file.write_text(json.dumps(config_data))

        config = SyncConfig.load_from_file(config_file)

        assert config.sync_label.enabled is True
        assert config.sync_label.group_name == DEFAULT_SYNC_LABEL_GROUP_NAME

    def test_sync_config_save_and_load_roundtrip(self, tmp_path):
        """Test save then load preserves sync_label data."""
        from gcontact_sync.config.sync_config import SyncConfig, SyncLabelConfig

        config_file = tmp_path / "sync_config.json"
        original = SyncConfig(
            sync_label=SyncLabelConfig(enabled=False, group_name="Roundtrip"),
        )

        original.save_to_file(config_file)
        loaded = SyncConfig.load_from_file(config_file)

        assert loaded.sync_label.enabled == original.sync_label.enabled
        assert loaded.sync_label.group_name == original.sync_label.group_name


class TestSyncLabelConfigConstants:
    """Tests for sync label configuration constants."""

    def test_default_sync_label_group_name_is_defined(self):
        """Test that DEFAULT_SYNC_LABEL_GROUP_NAME is defined."""
        from gcontact_sync.config.sync_config import DEFAULT_SYNC_LABEL_GROUP_NAME

        assert DEFAULT_SYNC_LABEL_GROUP_NAME is not None
        assert isinstance(DEFAULT_SYNC_LABEL_GROUP_NAME, str)
        assert DEFAULT_SYNC_LABEL_GROUP_NAME == "Synced Contacts"


# ==============================================================================
# AccountSyncConfig Target Group Tests
# ==============================================================================


class TestAccountSyncConfigTargetGroup:
    """Tests for AccountSyncConfig target_group and preserve_source_groups."""

    def test_target_group_default_none(self):
        """Test that target_group defaults to None."""
        config = AccountSyncConfig()
        assert config.target_group is None

    def test_target_group_from_dict_valid_string(self):
        """Test creating from dict with valid target_group string."""
        data = {"sync_groups": [], "target_group": "Brain Bridge"}
        config = AccountSyncConfig.from_dict(data)
        assert config.target_group == "Brain Bridge"

    def test_target_group_from_dict_with_spaces(self):
        """Test that spaces in target_group are preserved."""
        data = {"target_group": "  My Group  "}
        config = AccountSyncConfig.from_dict(data)
        assert config.target_group == "  My Group  "

    def test_target_group_empty_string_raises_sync_config_error(self):
        """Test that empty target_group raises SyncConfigError."""
        data = {"target_group": ""}
        with pytest.raises(SyncConfigError) as exc_info:
            AccountSyncConfig.from_dict(data)
        assert "target_group cannot be empty if specified" in str(exc_info.value)

    def test_target_group_whitespace_only_raises_sync_config_error(self):
        """Test that whitespace-only target_group raises SyncConfigError."""
        data = {"target_group": "   "}
        with pytest.raises(SyncConfigError) as exc_info:
            AccountSyncConfig.from_dict(data)
        assert "target_group cannot be empty if specified" in str(exc_info.value)

    def test_target_group_invalid_type_int_raises_sync_config_error(self):
        """Test that int target_group raises SyncConfigError."""
        data = {"target_group": 123}
        with pytest.raises(SyncConfigError) as exc_info:
            AccountSyncConfig.from_dict(data)
        assert "target_group must be a string, got int" in str(exc_info.value)

    def test_target_group_invalid_type_list_raises_sync_config_error(self):
        """Test that list target_group raises SyncConfigError."""
        data = {"target_group": ["Work"]}
        with pytest.raises(SyncConfigError) as exc_info:
            AccountSyncConfig.from_dict(data)
        assert "target_group must be a string, got list" in str(exc_info.value)

    def test_target_group_null_in_json_is_valid(self):
        """Test that None/null target_group is valid."""
        data = {"target_group": None}
        config = AccountSyncConfig.from_dict(data)
        assert config.target_group is None

    def test_preserve_source_groups_default_true(self):
        """Test that preserve_source_groups defaults to True."""
        config = AccountSyncConfig()
        assert config.preserve_source_groups is True

    def test_preserve_source_groups_false_from_dict(self):
        """Test creating from dict with preserve_source_groups=False."""
        data = {"preserve_source_groups": False}
        config = AccountSyncConfig.from_dict(data)
        assert config.preserve_source_groups is False

    def test_preserve_source_groups_invalid_type_string_raises(self):
        """Test that string preserve_source_groups raises SyncConfigError."""
        data = {"preserve_source_groups": "yes"}
        with pytest.raises(SyncConfigError) as exc_info:
            AccountSyncConfig.from_dict(data)
        assert "preserve_source_groups must be a boolean, got str" in str(
            exc_info.value
        )

    def test_preserve_source_groups_invalid_type_int_raises(self):
        """Test that int preserve_source_groups raises SyncConfigError."""
        data = {"preserve_source_groups": 1}
        with pytest.raises(SyncConfigError) as exc_info:
            AccountSyncConfig.from_dict(data)
        assert "preserve_source_groups must be a boolean, got int" in str(
            exc_info.value
        )

    def test_to_dict_omits_none_target_group(self):
        """Test that to_dict omits target_group when None."""
        config = AccountSyncConfig(target_group=None)
        d = config.to_dict()
        assert "target_group" not in d

    def test_to_dict_includes_target_group_when_set(self):
        """Test that to_dict includes target_group when set."""
        config = AccountSyncConfig(target_group="Brain Bridge")
        d = config.to_dict()
        assert d["target_group"] == "Brain Bridge"

    def test_to_dict_omits_preserve_source_groups_when_true(self):
        """Test that to_dict omits preserve_source_groups when True (default)."""
        config = AccountSyncConfig(preserve_source_groups=True)
        d = config.to_dict()
        assert "preserve_source_groups" not in d

    def test_to_dict_includes_preserve_source_groups_when_false(self):
        """Test that to_dict includes preserve_source_groups when False."""
        config = AccountSyncConfig(preserve_source_groups=False)
        d = config.to_dict()
        assert d["preserve_source_groups"] is False

    def test_target_group_unicode_characters(self):
        """Test that unicode characters work in target_group."""
        data = {"target_group": "工作联系人"}
        config = AccountSyncConfig.from_dict(data)
        assert config.target_group == "工作联系人"

    def test_target_group_with_emoji(self):
        """Test that emojis work in target_group."""
        data = {"target_group": "Work 👔"}
        config = AccountSyncConfig.from_dict(data)
        assert config.target_group == "Work 👔"


# ==============================================================================
# GroupSyncMode Config Tests
# ==============================================================================


class TestGroupSyncModeConfig:
    """Tests for SyncConfig group_sync_mode field."""

    def test_group_sync_mode_default_all(self):
        """Test that group_sync_mode defaults to 'all'."""
        config = SyncConfig()
        assert config.group_sync_mode == "all"

    def test_group_sync_mode_from_dict_all_explicit(self):
        """Test creating from dict with explicit group_sync_mode='all'."""
        data = {"group_sync_mode": "all"}
        config = SyncConfig.from_dict(data)
        assert config.group_sync_mode == "all"

    def test_group_sync_mode_from_dict_used(self):
        """Test creating from dict with group_sync_mode='used'."""
        data = {"group_sync_mode": "used"}
        config = SyncConfig.from_dict(data)
        assert config.group_sync_mode == "used"

    def test_group_sync_mode_from_dict_none(self):
        """Test creating from dict with group_sync_mode='none'."""
        data = {"group_sync_mode": "none"}
        config = SyncConfig.from_dict(data)
        assert config.group_sync_mode == "none"

    def test_group_sync_mode_invalid_value_raises(self):
        """Test that invalid group_sync_mode value raises SyncConfigError."""
        data = {"group_sync_mode": "invalid"}
        with pytest.raises(SyncConfigError) as exc_info:
            SyncConfig.from_dict(data)
        assert "group_sync_mode must be one of" in str(exc_info.value)

    def test_group_sync_mode_case_sensitive_ALL_raises(self):
        """Test that uppercase 'ALL' is rejected (case sensitive)."""
        data = {"group_sync_mode": "ALL"}
        with pytest.raises(SyncConfigError) as exc_info:
            SyncConfig.from_dict(data)
        assert "must be one of" in str(exc_info.value)

    def test_group_sync_mode_invalid_type_int_raises(self):
        """Test that int group_sync_mode raises SyncConfigError."""
        data = {"group_sync_mode": 123}
        with pytest.raises(SyncConfigError) as exc_info:
            SyncConfig.from_dict(data)
        assert "group_sync_mode must be a string, got int" in str(exc_info.value)

    def test_group_sync_mode_invalid_type_bool_raises(self):
        """Test that bool group_sync_mode raises SyncConfigError."""
        data = {"group_sync_mode": True}
        with pytest.raises(SyncConfigError) as exc_info:
            SyncConfig.from_dict(data)
        assert "group_sync_mode must be a string, got bool" in str(exc_info.value)

    def test_to_dict_omits_group_sync_mode_when_default(self):
        """Test that to_dict omits group_sync_mode when 'all' (default)."""
        config = SyncConfig(group_sync_mode="all")
        d = config.to_dict()
        assert "group_sync_mode" not in d

    def test_to_dict_includes_group_sync_mode_used(self):
        """Test that to_dict includes group_sync_mode when 'used'."""
        config = SyncConfig(group_sync_mode="used")
        d = config.to_dict()
        assert d["group_sync_mode"] == "used"

    def test_to_dict_includes_group_sync_mode_none(self):
        """Test that to_dict includes group_sync_mode when 'none'."""
        config = SyncConfig(group_sync_mode="none")
        d = config.to_dict()
        assert d["group_sync_mode"] == "none"

    def test_group_sync_mode_missing_uses_default(self):
        """Test that missing group_sync_mode uses default 'all'."""
        data = {"version": "1.0"}
        config = SyncConfig.from_dict(data)
        assert config.group_sync_mode == "all"


# ==============================================================================
# Full Config Integration Tests
# ==============================================================================


class TestFullConfigIntegration:
    """Tests for complete config with all new fields."""

    def test_full_config_from_dict(self):
        """Test creating full config with all new fields from dict."""
        data = {
            "version": "1.0",
            "group_sync_mode": "used",
            "sync_label": {"enabled": True, "group_name": "Synced Contacts"},
            "account1": {
                "sync_groups": ["Work"],
                "target_group": "From Account 2",
                "preserve_source_groups": True,
            },
            "account2": {
                "sync_groups": [],
                "target_group": "Brain Bridge",
                "preserve_source_groups": False,
            },
        }
        config = SyncConfig.from_dict(data)

        assert config.group_sync_mode == "used"
        assert config.account1.target_group == "From Account 2"
        assert config.account1.preserve_source_groups is True
        assert config.account2.target_group == "Brain Bridge"
        assert config.account2.preserve_source_groups is False

    def test_full_config_save_and_load_roundtrip(self, tmp_path):
        """Test save then load preserves all new fields."""

        config_file = tmp_path / "sync_config.json"
        original = SyncConfig(
            group_sync_mode="none",
            account1=AccountSyncConfig(
                target_group="From Account 2",
                preserve_source_groups=False,
            ),
            account2=AccountSyncConfig(
                target_group="Brain Bridge",
                preserve_source_groups=True,
            ),
        )

        original.save_to_file(config_file)
        loaded = SyncConfig.load_from_file(config_file)

        assert loaded.group_sync_mode == original.group_sync_mode
        assert loaded.account1.target_group == original.account1.target_group
        assert (
            loaded.account1.preserve_source_groups
            == original.account1.preserve_source_groups
        )
        assert loaded.account2.target_group == original.account2.target_group
        assert (
            loaded.account2.preserve_source_groups
            == original.account2.preserve_source_groups
        )

    def test_repr_includes_group_sync_mode(self):
        """Test that repr includes group_sync_mode."""
        config = SyncConfig(group_sync_mode="used")
        repr_str = repr(config)
        assert "group_sync_mode='used'" in repr_str


class TestGroupSyncModeEnum:
    """Tests for GroupSyncMode enum."""

    def test_enum_values(self):
        """Test that GroupSyncMode enum has expected values."""
        from gcontact_sync.config.sync_config import GroupSyncMode

        assert GroupSyncMode.ALL.value == "all"
        assert GroupSyncMode.USED.value == "used"
        assert GroupSyncMode.NONE.value == "none"

    def test_valid_group_sync_modes_set(self):
        """Test that VALID_GROUP_SYNC_MODES contains all enum values."""
        from gcontact_sync.config.sync_config import (
            VALID_GROUP_SYNC_MODES,
            GroupSyncMode,
        )

        assert {"all", "used", "none"} == VALID_GROUP_SYNC_MODES
        assert all(mode.value in VALID_GROUP_SYNC_MODES for mode in GroupSyncMode)
