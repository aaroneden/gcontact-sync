"""
Configuration loader module for Google Contacts synchronization.

Provides YAML-based configuration file loading with support for:
- Loading configuration from default or custom paths
- Graceful handling of missing configuration files
- Basic validation of configuration structure
- Merging with CLI argument overrides
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# Default configuration directory
DEFAULT_CONFIG_DIR = Path.home() / ".gcontact-sync"

# Default configuration file name
DEFAULT_CONFIG_FILE = "config.yaml"

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""

    pass


class ConfigLoader:
    """
    YAML configuration file loader.

    Handles loading and basic validation of YAML configuration files
    for the gcontact-sync application.

    Attributes:
        config_dir: Directory containing the configuration file
        config_file: Name of the configuration file

    Usage:
        loader = ConfigLoader()
        config = loader.load()

        # With custom path
        loader = ConfigLoader(config_dir=Path("/custom/path"))
        config = loader.load()

        # Load from specific file
        config = loader.load_from_file("/path/to/config.yaml")
    """

    def __init__(
        self, config_dir: Optional[Path] = None, config_file: str = DEFAULT_CONFIG_FILE
    ):
        """
        Initialize the configuration loader.

        Args:
            config_dir: Directory containing the configuration file.
                       Defaults to ~/.gcontact-sync/ or $GCONTACT_SYNC_CONFIG_DIR
            config_file: Name of the configuration file (default: config.yaml)
        """
        # Use environment variable if set, otherwise default
        if config_dir is not None:
            self.config_dir = Path(config_dir)
        else:
            env_dir = os.environ.get("GCONTACT_SYNC_CONFIG_DIR")
            if env_dir:
                self.config_dir = Path(env_dir)
            else:
                self.config_dir = DEFAULT_CONFIG_DIR

        self.config_file = config_file

    def _get_config_path(self) -> Path:
        """
        Get the full path to the configuration file.

        Returns:
            Path to the configuration file
        """
        return self.config_dir / self.config_file

    def load(self) -> Dict[str, Any]:
        """
        Load configuration from the default configuration file.

        Returns an empty dict if the file doesn't exist, allowing
        graceful operation with CLI defaults.

        Returns:
            Dictionary containing configuration values, or empty dict if file
            doesn't exist

        Raises:
            ConfigError: If the configuration file exists but cannot be parsed
        """
        config_path = self._get_config_path()
        return self.load_from_file(config_path)

    def load_from_file(self, path: Path | str) -> Dict[str, Any]:
        """
        Load configuration from a specific file.

        Returns an empty dict if the file doesn't exist, allowing
        graceful operation with CLI defaults.

        Args:
            path: Path to the configuration file

        Returns:
            Dictionary containing configuration values, or empty dict if file
            doesn't exist

        Raises:
            ConfigError: If the configuration file exists but cannot be parsed
        """
        path = Path(path)

        if not path.exists():
            logger.debug(f"Configuration file not found: {path}")
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            # Handle empty files
            if config is None:
                logger.debug(f"Configuration file is empty: {path}")
                return {}

            # Validate that config is a dictionary
            if not isinstance(config, dict):
                raise ConfigError(
                    f"Configuration file must contain a YAML dictionary, "
                    f"got {type(config).__name__}"
                )

            logger.debug(f"Loaded configuration from {path}")
            return config

        except yaml.YAMLError as e:
            raise ConfigError(f"Failed to parse YAML configuration file: {e}") from e
        except (OSError, IOError) as e:
            raise ConfigError(f"Failed to read configuration file: {e}") from e

    def validate(self, config: Dict[str, Any]) -> None:
        """
        Validate configuration structure and values.

        Performs basic validation to ensure configuration contains
        expected types and values.

        Args:
            config: Configuration dictionary to validate

        Raises:
            ConfigError: If configuration is invalid
        """
        if not isinstance(config, dict):
            raise ConfigError(
                f"Configuration must be a dictionary, got {type(config).__name__}"
            )

        # Define valid configuration keys and their expected types
        # This can be expanded as more configuration options are added
        valid_keys = {
            # CLI options
            "dry_run": bool,
            "full": bool,
            "debug": bool,
            "verbose": bool,
            "strategy": str,
            "config_dir": str,
            # Sync options (for future use)
            "similarity_threshold": (int, float),
            "batch_size": int,
        }

        # Validate known keys
        for key, value in config.items():
            if key in valid_keys:
                expected_type = valid_keys[key]
                if not isinstance(value, expected_type):
                    type_name = (
                        f"{expected_type[0].__name__} or {expected_type[1].__name__}"
                        if isinstance(expected_type, tuple)
                        else expected_type.__name__
                    )
                    raise ConfigError(
                        f"Invalid type for '{key}': expected {type_name}, "
                        f"got {type(value).__name__}"
                    )

        # Validate strategy value if present
        if "strategy" in config:
            valid_strategies = ["account1", "account2", "newest", "manual"]
            if config["strategy"] not in valid_strategies:
                raise ConfigError(
                    f"Invalid strategy '{config['strategy']}'. "
                    f"Must be one of: {', '.join(valid_strategies)}"
                )

        # Validate numeric ranges if present
        if "similarity_threshold" in config:
            threshold = config["similarity_threshold"]
            if not (0.0 <= threshold <= 1.0):
                raise ConfigError(
                    f"similarity_threshold must be between 0.0 and 1.0, "
                    f"got {threshold}"
                )

        if "batch_size" in config:
            batch_size = config["batch_size"]
            if batch_size < 1:
                raise ConfigError(f"batch_size must be >= 1, got {batch_size}")

    def load_and_validate(self) -> Dict[str, Any]:
        """
        Load configuration and validate it.

        Convenience method that combines load() and validate().

        Returns:
            Validated configuration dictionary

        Raises:
            ConfigError: If configuration cannot be loaded or is invalid
        """
        config = self.load()
        if config:  # Only validate if config is not empty
            self.validate(config)
        return config
