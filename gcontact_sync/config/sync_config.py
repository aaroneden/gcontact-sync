"""
Sync configuration for tag-based contact filtering.

Provides configuration dataclasses for controlling which contacts
are synchronized based on contact group/tag membership. Supports
per-account tag specifications for fine-grained sync control.

Configuration file format (sync_config.json):

    {
        "version": "1.0",
        "account1": {
            "sync_groups": ["Work", "Family", "contactGroups/456def"]
        },
        "account2": {
            "sync_groups": ["Important", "contactGroups/789ghi"]
        }
    }

Notes:
    - Empty sync_groups or missing account config means "sync all contacts"
    - Groups can be specified by display name ("Work") or resource name
      ("contactGroups/123abc")
    - Both accounts can have independent filter configurations
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Current configuration schema version
CONFIG_VERSION = "1.0"

# Default sync config file name
DEFAULT_SYNC_CONFIG_FILE = "sync_config.json"

# Default configuration directory
DEFAULT_CONFIG_DIR = Path.home() / ".gcontact-sync"


class SyncConfigError(Exception):
    """Raised when sync configuration loading or validation fails."""

    pass


@dataclass
class AccountSyncConfig:
    """
    Per-account synchronization configuration.

    Attributes:
        sync_groups: List of group names or resource names to filter contacts.
                    Empty list means sync all contacts (no filtering).

    Usage:
        # Create with specific groups to sync
        config = AccountSyncConfig(sync_groups=["Work", "Family"])

        # Check if filtering is enabled
        if config.has_filter():
            # Apply filtering logic
            pass

        # Check if a group should be synced
        if config.should_sync_group("Work"):
            # Include contacts from this group
            pass
    """

    sync_groups: list[str] = field(default_factory=list)

    def has_filter(self) -> bool:
        """
        Check if group filtering is enabled for this account.

        Returns:
            True if sync_groups is non-empty (filtering enabled),
            False if empty (sync all contacts)
        """
        return len(self.sync_groups) > 0

    def should_sync_group(self, group_identifier: str) -> bool:
        """
        Check if a group matches the configured filter.

        Matches against both display names and resource names.
        Case-insensitive matching is used for display names.

        Args:
            group_identifier: Group display name or resource name to check

        Returns:
            True if the group matches the filter (or no filter is set),
            False if filtering is enabled and group doesn't match
        """
        # If no filter is set, sync all groups
        if not self.has_filter():
            return True

        # Check for exact match (resource name) or case-insensitive match (display name)
        group_lower = group_identifier.lower()
        for configured_group in self.sync_groups:
            # Exact match for resource names (e.g., "contactGroups/123abc")
            if configured_group == group_identifier:
                return True
            # Case-insensitive match for display names
            if configured_group.lower() == group_lower:
                return True

        return False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AccountSyncConfig:
        """
        Create AccountSyncConfig from a dictionary.

        Args:
            data: Dictionary containing account configuration, or None

        Returns:
            AccountSyncConfig instance

        Raises:
            SyncConfigError: If configuration structure is invalid
        """
        if data is None:
            return cls()

        if not isinstance(data, dict):
            raise SyncConfigError(
                f"Account configuration must be a dictionary, got {type(data).__name__}"
            )

        sync_groups = data.get("sync_groups", [])

        if not isinstance(sync_groups, list):
            raise SyncConfigError(
                f"sync_groups must be a list, got {type(sync_groups).__name__}"
            )

        # Validate all items are strings
        for i, group in enumerate(sync_groups):
            if not isinstance(group, str):
                raise SyncConfigError(
                    f"sync_groups[{i}] must be a string, got {type(group).__name__}"
                )

        return cls(sync_groups=sync_groups)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary format.

        Returns:
            Dictionary representation of the account config
        """
        return {"sync_groups": self.sync_groups}


@dataclass
class SyncConfig:
    """
    Main synchronization configuration for tag-based filtering.

    Controls which contacts are synchronized between accounts based on
    their group/tag membership. Each account can have independent filter
    settings.

    Attributes:
        version: Configuration schema version (currently "1.0")
        account1: Sync configuration for account 1
        account2: Sync configuration for account 2

    Usage:
        # Load from file
        config = SyncConfig.load_from_file("~/.gcontact-sync/sync_config.json")

        # Check if filtering is enabled for an account
        if config.account1.has_filter():
            print("Account 1 has group filtering enabled")

        # Get groups to sync for account 1
        groups = config.account1.sync_groups

        # Create programmatically
        config = SyncConfig(
            account1=AccountSyncConfig(sync_groups=["Work", "Family"]),
            account2=AccountSyncConfig(sync_groups=["Important"]),
        )
    """

    version: str = CONFIG_VERSION
    account1: AccountSyncConfig = field(default_factory=AccountSyncConfig)
    account2: AccountSyncConfig = field(default_factory=AccountSyncConfig)

    def has_any_filter(self) -> bool:
        """
        Check if any account has filtering enabled.

        Returns:
            True if either account has a non-empty sync_groups list
        """
        return self.account1.has_filter() or self.account2.has_filter()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncConfig:
        """
        Create SyncConfig from a dictionary.

        Args:
            data: Dictionary containing sync configuration

        Returns:
            SyncConfig instance

        Raises:
            SyncConfigError: If configuration structure is invalid

        Example:
            data = {
                "version": "1.0",
                "account1": {"sync_groups": ["Work"]},
                "account2": {"sync_groups": []}
            }
            config = SyncConfig.from_dict(data)
        """
        if not isinstance(data, dict):
            raise SyncConfigError(
                f"Configuration must be a dictionary, got {type(data).__name__}"
            )

        # Extract version (default to current if not specified)
        version = data.get("version", CONFIG_VERSION)
        if not isinstance(version, str):
            raise SyncConfigError(
                f"version must be a string, got {type(version).__name__}"
            )

        # Parse account configurations
        account1 = AccountSyncConfig.from_dict(data.get("account1"))
        account2 = AccountSyncConfig.from_dict(data.get("account2"))

        return cls(version=version, account1=account1, account2=account2)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary format.

        Returns:
            Dictionary representation of the sync config
        """
        return {
            "version": self.version,
            "account1": self.account1.to_dict(),
            "account2": self.account2.to_dict(),
        }

    @classmethod
    def load_from_file(cls, path: Path | str) -> SyncConfig:
        """
        Load sync configuration from a JSON file.

        Returns a default (empty) configuration if the file doesn't exist,
        maintaining backwards compatibility with setups that don't use
        tag filtering.

        Args:
            path: Path to the sync_config.json file

        Returns:
            SyncConfig instance (default config if file doesn't exist)

        Raises:
            SyncConfigError: If file exists but cannot be parsed or is invalid
        """
        path = Path(path).expanduser().resolve()

        if not path.exists():
            logger.debug(f"Sync config file not found: {path}, using defaults")
            return cls()

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            logger.debug(f"Loaded sync config from {path}")
            return cls.from_dict(data)

        except json.JSONDecodeError as e:
            raise SyncConfigError(
                f"Failed to parse sync config JSON at {path}: {e}"
            ) from e
        except OSError as e:
            raise SyncConfigError(f"Failed to read sync config file: {e}") from e

    def save_to_file(self, path: Path | str) -> None:
        """
        Save sync configuration to a JSON file.

        Creates parent directories if they don't exist and sets
        secure file permissions.

        Args:
            path: Path to save the configuration to

        Raises:
            SyncConfigError: If file cannot be written
        """
        path = Path(path).expanduser().resolve()

        try:
            # Create parent directories with secure permissions
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)

            # Write config with nice formatting
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
                f.write("\n")  # Add trailing newline

            # Set secure file permissions (readable/writable by owner only)
            path.chmod(0o600)

            logger.info(f"Saved sync config to {path}")

        except OSError as e:
            raise SyncConfigError(f"Failed to write sync config file: {e}") from e

    def __repr__(self) -> str:
        """Return a readable string representation."""
        return (
            f"SyncConfig(version={self.version!r}, "
            f"account1_groups={self.account1.sync_groups!r}, "
            f"account2_groups={self.account2.sync_groups!r})"
        )


def load_config(config_dir: Path | str | None = None) -> SyncConfig:
    """
    Load sync configuration from a config directory.

    This is a convenience function that handles config directory resolution
    and loads the sync_config.json file from within that directory. Supports
    environment variable override and provides sensible defaults.

    Resolution order for config directory:
    1. Explicit config_dir parameter (if provided)
    2. GCONTACT_SYNC_CONFIG_DIR environment variable (if set)
    3. Default: ~/.gcontact-sync

    Args:
        config_dir: Configuration directory path. Can be a string path
                   (supports ~ expansion) or Path object. If None, uses
                   environment variable or default.

    Returns:
        SyncConfig instance. Returns default (empty) config if:
        - Config directory doesn't exist
        - sync_config.json file doesn't exist
        This ensures backwards compatibility with existing setups.

    Raises:
        SyncConfigError: If config file exists but is invalid JSON
                        or has invalid structure

    Usage:
        # Load from default location (~/.gcontact-sync/sync_config.json)
        config = load_config()

        # Load from explicit directory
        config = load_config("~/.my-config-dir")

        # Environment variable override
        # $ export GCONTACT_SYNC_CONFIG_DIR=/path/to/config
        config = load_config()  # Uses env var path
    """
    # Resolve config directory path
    if config_dir is not None:
        resolved_dir = Path(config_dir).expanduser().resolve()
    else:
        # Check environment variable
        env_dir = os.environ.get("GCONTACT_SYNC_CONFIG_DIR")
        if env_dir:
            resolved_dir = Path(env_dir).expanduser().resolve()
        else:
            resolved_dir = DEFAULT_CONFIG_DIR

    # Construct path to sync config file
    config_file_path = resolved_dir / DEFAULT_SYNC_CONFIG_FILE

    logger.debug(f"Loading sync config from directory: {resolved_dir}")

    # Load config (returns default if file doesn't exist)
    return SyncConfig.load_from_file(config_file_path)
