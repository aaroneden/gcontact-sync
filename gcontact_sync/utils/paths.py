"""
Path utilities for configuration directory resolution.

Provides consistent path resolution for the gcontact-sync configuration
directory across all modules.
"""

from __future__ import annotations

import os
from pathlib import Path

# Default configuration directory
DEFAULT_CONFIG_DIR = Path.home() / ".gcontact-sync"

# Environment variable for overriding config directory
CONFIG_DIR_ENV_VAR = "GCONTACT_SYNC_CONFIG_DIR"


def resolve_config_dir(config_dir: Path | str | None = None) -> Path:
    """
    Resolve the configuration directory path.

    Priority:
        1. Explicit config_dir parameter (if provided)
        2. GCONTACT_SYNC_CONFIG_DIR environment variable
        3. Default directory (~/.gcontact-sync)

    Args:
        config_dir: Optional explicit configuration directory path.
                   Can be a Path object or string.

    Returns:
        Resolved Path to the configuration directory (expanduser and resolve applied)
    """
    if config_dir is not None:
        return Path(config_dir).expanduser().resolve()

    env_dir = os.environ.get(CONFIG_DIR_ENV_VAR)
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    return DEFAULT_CONFIG_DIR.expanduser().resolve()
