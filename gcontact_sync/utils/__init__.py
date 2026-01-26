"""
gcontact_sync.utils - Utility module

Common utilities including logging configuration.
"""

from gcontact_sync.utils.normalization import normalize_string
from gcontact_sync.utils.paths import DEFAULT_CONFIG_DIR, resolve_config_dir

__all__ = ["normalize_string", "resolve_config_dir", "DEFAULT_CONFIG_DIR"]
