"""CLI package for gcontact_sync."""

from gcontact_sync.cli.formatters import (
    print_contact_debug,
    show_debug_info,
    show_detailed_changes,
)
from gcontact_sync.cli.main import (
    DEFAULT_CONFIG_FILE,
    VALID_ACCOUNTS,
    cli,
    get_config_dir,
    validate_account,
)
from gcontact_sync.utils import DEFAULT_CONFIG_DIR

__all__ = [
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_CONFIG_FILE",
    "VALID_ACCOUNTS",
    "cli",
    "get_config_dir",
    "print_contact_debug",
    "show_debug_info",
    "show_detailed_changes",
    "validate_account",
]
