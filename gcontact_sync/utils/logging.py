"""
Logging configuration module for gcontact_sync.

Provides centralized logging configuration with support for:
- Console and file logging
- Configurable log levels via environment variables
- Verbose mode for detailed output
- Colored output for better readability (when supported)
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# Default log format
DEFAULT_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# Simplified format for console (less verbose)
CONSOLE_FORMAT = '%(levelname)s: %(message)s'

# Verbose format (includes more details)
VERBOSE_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'

# Date format for log timestamps
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Environment variable names
ENV_LOG_LEVEL = 'GCONTACT_SYNC_LOG_LEVEL'
ENV_DEBUG = 'GCONTACT_SYNC_DEBUG'
ENV_LOG_FILE = 'GCONTACT_SYNC_LOG_FILE'
ENV_CONFIG_DIR = 'GCONTACT_SYNC_CONFIG_DIR'

# Default log directory
DEFAULT_LOG_DIR = Path.home() / '.gcontact-sync' / 'logs'


class ColoredFormatter(logging.Formatter):
    """
    A logging formatter that adds ANSI color codes to log messages.

    Colors are only applied when output is to a terminal that supports them.
    """

    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'

    def __init__(self, fmt: Optional[str] = None, datefmt: Optional[str] = None, use_colors: bool = True):
        """
        Initialize the colored formatter.

        Args:
            fmt: Log message format string
            datefmt: Date format string
            use_colors: Whether to use colors (auto-detected if not specified)
        """
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors and self._supports_color()

    def _supports_color(self) -> bool:
        """Check if the terminal supports colors."""
        # Check if stdout is a terminal
        if not hasattr(sys.stdout, 'isatty') or not sys.stdout.isatty():
            return False

        # Check for NO_COLOR environment variable (https://no-color.org/)
        if os.environ.get('NO_COLOR'):
            return False

        # Check for TERM environment variable
        term = os.environ.get('TERM', '')
        if term == 'dumb':
            return False

        return True

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with optional colors."""
        # Make a copy to avoid modifying the original
        record = logging.makeLogRecord(record.__dict__)

        if self.use_colors and record.levelname in self.COLORS:
            color = self.COLORS[record.levelname]
            record.levelname = f"{color}{record.levelname}{self.RESET}"
            record.msg = f"{color}{record.msg}{self.RESET}"

        return super().format(record)


def get_log_level_from_env() -> int:
    """
    Get the logging level from environment variables.

    Checks GCONTACT_SYNC_DEBUG and GCONTACT_SYNC_LOG_LEVEL environment
    variables to determine the appropriate log level.

    Returns:
        Logging level constant (e.g., logging.DEBUG, logging.INFO)
    """
    # Check for debug mode first
    if os.environ.get(ENV_DEBUG, '').lower() in ('1', 'true', 'yes'):
        return logging.DEBUG

    # Check for explicit log level
    level_str = os.environ.get(ENV_LOG_LEVEL, 'INFO').upper()

    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'WARN': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL,
    }

    return level_map.get(level_str, logging.INFO)


def get_log_file_path() -> Optional[Path]:
    """
    Get the log file path from environment or default location.

    Returns:
        Path to log file, or None if file logging is disabled
    """
    # Check for explicit log file path
    log_file = os.environ.get(ENV_LOG_FILE)
    if log_file:
        if log_file.lower() in ('none', 'disabled', ''):
            return None
        return Path(log_file)

    # Use default location in config directory
    config_dir = os.environ.get(ENV_CONFIG_DIR)
    if config_dir:
        log_dir = Path(config_dir) / 'logs'
    else:
        log_dir = DEFAULT_LOG_DIR

    return log_dir / f"gcontact_sync_{datetime.now().strftime('%Y%m%d')}.log"


def setup_logging(
    level: Optional[int] = None,
    verbose: bool = False,
    log_file: Optional[Path] = None,
    enable_file_logging: bool = True,
    use_colors: bool = True,
) -> logging.Logger:
    """
    Configure logging for the gcontact_sync application.

    Sets up both console and file logging handlers with appropriate
    formatters and levels.

    Args:
        level: Logging level (e.g., logging.DEBUG). If None, determined from
               environment variables.
        verbose: If True, use verbose format with more details.
        log_file: Path to log file. If None, uses default or env variable.
        enable_file_logging: If False, disable file logging entirely.
        use_colors: If True, use colored output for console (when supported).

    Returns:
        The root logger for gcontact_sync

    Example:
        # Basic setup
        setup_logging()

        # Verbose mode for CLI
        setup_logging(verbose=True)

        # Debug level with specific file
        setup_logging(level=logging.DEBUG, log_file=Path('/tmp/sync.log'))

        # Disable file logging
        setup_logging(enable_file_logging=False)
    """
    # Determine log level
    if level is None:
        level = get_log_level_from_env()
    if verbose:
        level = logging.DEBUG

    # Get the gcontact_sync logger
    logger = logging.getLogger('gcontact_sync')
    logger.setLevel(level)

    # Clear any existing handlers
    logger.handlers.clear()

    # Prevent propagation to root logger to avoid duplicate messages
    logger.propagate = False

    # Select format based on verbosity
    if verbose:
        console_format = VERBOSE_FORMAT
    else:
        console_format = CONSOLE_FORMAT

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)

    if use_colors:
        console_formatter = ColoredFormatter(console_format, DATE_FORMAT)
    else:
        console_formatter = logging.Formatter(console_format, DATE_FORMAT)

    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler (optional)
    if enable_file_logging:
        file_path = log_file if log_file else get_log_file_path()

        if file_path:
            try:
                # Ensure log directory exists
                file_path.parent.mkdir(parents=True, exist_ok=True)

                file_handler = logging.FileHandler(file_path, encoding='utf-8')
                file_handler.setLevel(logging.DEBUG)  # Always capture debug in file
                file_formatter = logging.Formatter(VERBOSE_FORMAT, DATE_FORMAT)
                file_handler.setFormatter(file_formatter)
                logger.addHandler(file_handler)

                logger.debug(f"Log file: {file_path}")
            except (OSError, PermissionError) as e:
                # Log warning but don't fail
                logger.warning(f"Could not create log file {file_path}: {e}")

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.

    This is a convenience function that returns a child logger of the
    gcontact_sync logger hierarchy.

    Args:
        name: Name of the module (typically __name__)

    Returns:
        Logger instance for the module

    Example:
        # In any module
        logger = get_logger(__name__)
        logger.info("Operation completed")
    """
    # If name starts with 'gcontact_sync', use it directly
    # Otherwise, prepend 'gcontact_sync' for proper hierarchy
    if not name.startswith('gcontact_sync'):
        name = f'gcontact_sync.{name}'

    return logging.getLogger(name)


def set_log_level(level: int) -> None:
    """
    Change the logging level at runtime.

    Args:
        level: New logging level (e.g., logging.DEBUG)
    """
    logger = logging.getLogger('gcontact_sync')
    logger.setLevel(level)

    # Update all handlers
    for handler in logger.handlers:
        # Keep file handler at DEBUG for complete logs
        if not isinstance(handler, logging.FileHandler):
            handler.setLevel(level)


def disable_logging() -> None:
    """
    Disable all logging output.

    Useful for testing or when running in completely silent mode.
    """
    logger = logging.getLogger('gcontact_sync')
    logger.disabled = True


def enable_logging() -> None:
    """
    Re-enable logging output after it was disabled.
    """
    logger = logging.getLogger('gcontact_sync')
    logger.disabled = False


# Module-level exports
__all__ = [
    'setup_logging',
    'get_logger',
    'set_log_level',
    'disable_logging',
    'enable_logging',
    'ColoredFormatter',
    'get_log_level_from_env',
    'get_log_file_path',
    'DEFAULT_FORMAT',
    'CONSOLE_FORMAT',
    'VERBOSE_FORMAT',
    'DATE_FORMAT',
]
