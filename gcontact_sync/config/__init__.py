"""
gcontact_sync.config - Configuration management module

Contains configuration loading, validation, and default settings.
"""

from gcontact_sync.config.sync_config import (
    AccountSyncConfig,
    SyncConfig,
    SyncConfigError,
    SyncLabelConfig,
    load_config,
)

__all__ = [
    "SyncConfig",
    "SyncLabelConfig",
    "AccountSyncConfig",
    "SyncConfigError",
    "load_config",
]
