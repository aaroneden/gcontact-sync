"""
Configuration file generator for Google Contacts synchronization.

Provides functionality to generate default configuration files with
comprehensive documentation and examples for all available options.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_default_config() -> str:
    """
    Generate default YAML configuration with all options documented.

    Returns a string containing a complete YAML configuration file
    with helpful comments explaining each option.

    Returns:
        String containing YAML configuration with comments

    Example:
        config_yaml = generate_default_config()
        with open("config.yaml", "w") as f:
            f.write(config_yaml)
    """
    return """# Google Contacts Sync Configuration
# ===================================
#
# This file allows you to set default options for gcontact-sync.
# CLI arguments will always override these values.
#
# To use this configuration:
#   1. Save as ~/.gcontact-sync/config.yaml (or custom location)
#   2. Uncomment and modify options as needed
#   3. Run gcontact-sync commands normally

# Logging Options
# ---------------

# Enable verbose output with detailed logging
# Default: false
# verbose: true

# Show debug information including sample matches and unmatched contacts
# Default: false
# debug: false


# Sync Behavior
# -------------

# Preview changes without applying them (dry-run mode)
# Useful for testing sync behavior before making actual changes
# Default: false
# dry_run: false

# Force full sync by ignoring sync tokens
# This will compare all contacts in both accounts instead of just changes
# Default: false
# full: false

# Conflict resolution strategy when the same contact is modified in both accounts
# Options:
#   - last_modified: Use the most recently modified version (recommended)
#   - newest: Alias for last_modified
#   - account1: Always prefer changes from account1
#   - account2: Always prefer changes from account2
#   - manual: Prompt for each conflict (not yet implemented)
# Default: last_modified
# strategy: last_modified


# Advanced Options
# ----------------

# Custom configuration directory path
# Default: ~/.gcontact-sync
# config_dir: /path/to/config

# Similarity threshold for matching contacts (0.0 to 1.0)
# Higher values require closer matches. Lower values may create false matches.
# Default: 0.8 (not yet used in current implementation)
# similarity_threshold: 0.8

# Batch size for API operations
# Number of contacts to process in a single batch
# Default: 100 (not yet used in current implementation)
# batch_size: 100


# Example Configurations
# ----------------------
#
# Conservative (preview before sync):
#   dry_run: true
#   verbose: true
#   strategy: last_modified
#
# Production (automatic sync):
#   dry_run: false
#   verbose: false
#   strategy: last_modified
#
# Debugging (detailed output):
#   verbose: true
#   debug: true
#   dry_run: true
"""


def save_config_file(
    config_path: Path, overwrite: bool = False
) -> tuple[bool, str | None]:
    """
    Save default configuration file to specified path.

    Creates parent directories if they don't exist and saves
    the configuration with secure permissions.

    Args:
        config_path: Path where the config file should be saved
        overwrite: If True, overwrite existing file. If False, fail if file exists.

    Returns:
        Tuple of (success: bool, error_message: Optional[str])
        Returns (True, None) on success, (False, error_message) on failure

    Example:
        success, error = save_config_file(Path("~/.gcontact-sync/config.yaml"))
        if success:
            print("Config file created!")
        else:
            print(f"Error: {error}")
    """
    try:
        # Expand user path and resolve
        config_path = config_path.expanduser().resolve()

        # Check if file already exists
        if config_path.exists() and not overwrite:
            return (
                False,
                f"Configuration file already exists: {config_path}\n"
                "Use --force to overwrite.",
            )

        # Create parent directories with secure permissions
        config_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)

        # Generate and write config
        config_content = generate_default_config()
        config_path.write_text(config_content, encoding="utf-8")

        # Set secure file permissions (readable/writable by owner only)
        config_path.chmod(0o600)

        logger.info(f"Created configuration file: {config_path}")
        return (True, None)

    except OSError as e:
        error_msg = f"Failed to create configuration file: {e}"
        logger.error(error_msg)
        return (False, error_msg)
    except Exception as e:
        error_msg = f"Unexpected error creating configuration file: {e}"
        logger.exception(error_msg)
        return (False, error_msg)
