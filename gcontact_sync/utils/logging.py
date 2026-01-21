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
DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Simplified format for console (less verbose)
CONSOLE_FORMAT = "%(levelname)s: %(message)s"

# Verbose format (includes more details)
VERBOSE_FORMAT = (
    "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
)

# Date format for log timestamps
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Environment variable names
ENV_LOG_LEVEL = "GCONTACT_SYNC_LOG_LEVEL"
ENV_DEBUG = "GCONTACT_SYNC_DEBUG"
ENV_LOG_FILE = "GCONTACT_SYNC_LOG_FILE"
ENV_CONFIG_DIR = "GCONTACT_SYNC_CONFIG_DIR"


# Project log directory (where pyproject.toml is located)
def _get_project_log_dir() -> Path:
    """Get the project logs directory."""
    current = Path(__file__).resolve()
    project_root = (
        current.parent.parent.parent
    )  # utils -> gcontact_sync -> project root
    return project_root / "logs"


PROJECT_LOG_DIR = _get_project_log_dir()

# Matching log format - detailed for debugging contact matching
MATCHING_LOG_FORMAT = "%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s"

# Matching log date format with milliseconds
MATCHING_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class ColoredFormatter(logging.Formatter):
    """
    A logging formatter that adds ANSI color codes to log messages.

    Colors are only applied when output is to a terminal that supports them.
    """

    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        use_colors: bool = True,
    ):
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
        if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
            return False

        # Check for NO_COLOR environment variable (https://no-color.org/)
        if os.environ.get("NO_COLOR"):
            return False

        # Check for TERM environment variable
        term = os.environ.get("TERM", "")
        return term != "dumb"

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
    if os.environ.get(ENV_DEBUG, "").lower() in ("1", "true", "yes"):
        return logging.DEBUG

    # Check for explicit log level
    level_str = os.environ.get(ENV_LOG_LEVEL, "INFO").upper()

    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
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
        if log_file.lower() in ("none", "disabled", ""):
            return None
        return Path(log_file)

    # Use project logs directory (consolidated logging location)
    return PROJECT_LOG_DIR / f"gcontact_sync_{datetime.now().strftime('%Y%m%d')}.log"


def setup_logging(
    level: Optional[int] = None,
    verbose: bool = False,
    log_dir: Optional[Path] = None,
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
        log_dir: Directory for log files. If provided, overrides default.
        log_file: Path to log file. If None, uses log_dir or default.
        enable_file_logging: If False, disable file logging entirely.
        use_colors: If True, use colored output for console (when supported).

    Returns:
        The root logger for gcontact_sync

    Example:
        # Basic setup
        setup_logging()

        # Verbose mode for CLI
        setup_logging(verbose=True)

        # Custom log directory from config
        setup_logging(log_dir=Path('/path/to/logs'))

        # Disable file logging
        setup_logging(enable_file_logging=False)
    """
    # Determine log level
    if level is None:
        level = get_log_level_from_env()
    if verbose:
        level = logging.DEBUG

    # Get the gcontact_sync logger
    logger = logging.getLogger("gcontact_sync")
    logger.setLevel(level)

    # Clear any existing handlers
    logger.handlers.clear()

    # Prevent propagation to root logger to avoid duplicate messages
    logger.propagate = False

    # Select format based on verbosity
    console_format = VERBOSE_FORMAT if verbose else CONSOLE_FORMAT

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)

    console_formatter: logging.Formatter
    if use_colors:
        console_formatter = ColoredFormatter(console_format, DATE_FORMAT)
    else:
        console_formatter = logging.Formatter(console_format, DATE_FORMAT)

    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler (optional)
    if enable_file_logging:
        file_path: Optional[Path] = None
        if log_file:
            file_path = log_file
        elif log_dir:
            # Use provided log_dir from config
            file_path = (
                log_dir / f"gcontact_sync_{datetime.now().strftime('%Y%m%d')}.log"
            )
        else:
            file_path = get_log_file_path()

        if file_path:
            try:
                # Ensure log directory exists
                file_path.parent.mkdir(parents=True, exist_ok=True)

                file_handler = logging.FileHandler(file_path, encoding="utf-8")
                file_handler.setLevel(logging.DEBUG)  # Always capture debug in file
                file_formatter = logging.Formatter(VERBOSE_FORMAT, DATE_FORMAT)
                file_handler.setFormatter(file_formatter)
                logger.addHandler(file_handler)

                logger.debug(f"Log file: {file_path}")
            except (OSError, PermissionError) as e:
                # Log warning but don't fail
                logger.warning(f"Could not create log file {file_path}: {e}")

    # Store log_dir for matching logger to use
    if log_dir:
        _current_log_dir = log_dir
    elif log_file:
        _current_log_dir = log_file.parent
    else:
        _current_log_dir = None
    # Store in module-level variable for matching logger
    global _configured_log_dir
    _configured_log_dir = _current_log_dir

    return logger


# Module-level variable to store configured log directory
_configured_log_dir: Optional[Path] = None


def cleanup_old_logs(log_dir: Optional[Path] = None, keep_count: int = 10) -> int:
    """
    Clean up old log files, keeping only the most recent ones.

    Removes old gcontact_sync_*.log and matching_*.log files from the log
    directory, keeping only the specified number of most recent files.

    Args:
        log_dir: Directory containing log files. If None, uses configured
                 directory or project default.
        keep_count: Number of log files to keep for each type. Default 10.
                    Set to 0 to disable cleanup.

    Returns:
        Number of files deleted.
    """
    if keep_count <= 0:
        return 0

    # Determine log directory
    if log_dir:
        logs_dir = log_dir
    elif _configured_log_dir:
        logs_dir = _configured_log_dir
    else:
        logs_dir = PROJECT_LOG_DIR

    if not logs_dir.exists():
        return 0

    deleted_count = 0

    # Clean up gcontact_sync_*.log files
    sync_logs = sorted(
        logs_dir.glob("gcontact_sync_*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_log in sync_logs[keep_count:]:
        try:
            old_log.unlink()
            deleted_count += 1
        except OSError:
            pass  # Ignore errors deleting old logs

    # Clean up matching_*.log files
    matching_logs = sorted(
        logs_dir.glob("matching_*.log"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for old_log in matching_logs[keep_count:]:
        try:
            old_log.unlink()
            deleted_count += 1
        except OSError:
            pass  # Ignore errors deleting old logs

    return deleted_count


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
    if not name.startswith("gcontact_sync"):
        name = f"gcontact_sync.{name}"

    return logging.getLogger(name)


def set_log_level(level: int) -> None:
    """
    Change the logging level at runtime.

    Args:
        level: New logging level (e.g., logging.DEBUG)
    """
    logger = logging.getLogger("gcontact_sync")
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
    logger = logging.getLogger("gcontact_sync")
    logger.disabled = True


def enable_logging() -> None:
    """
    Re-enable logging output after it was disabled.
    """
    logger = logging.getLogger("gcontact_sync")
    logger.disabled = False


def get_matching_log_path(log_dir: Optional[Path] = None) -> Path:
    """
    Get the path for the matching log file.

    Creates a timestamped log file for each session. Uses the configured
    log directory if available, otherwise falls back to project logs directory.

    Args:
        log_dir: Optional directory for log files. If None, uses configured
                 directory from setup_logging() or project default.

    Returns:
        Path to the matching log file
    """
    # Use provided log_dir, or configured log_dir, or project default
    if log_dir:
        logs_dir = log_dir
    elif _configured_log_dir:
        logs_dir = _configured_log_dir
    else:
        logs_dir = PROJECT_LOG_DIR

    # Create timestamped filename for this session
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return logs_dir / f"matching_{timestamp}.log"


def setup_matching_logger(
    log_file: Optional[Path] = None,
    level: int = logging.DEBUG,
) -> logging.Logger:
    """
    Set up a dedicated logger for contact matching operations.

    This logger captures every matching attempt with detailed information
    about why contacts were matched or not matched. The log file is written
    to a project-local logs/ directory which is excluded from source control.

    Args:
        log_file: Optional custom path for the log file. If None, uses
                  default location in project logs/ directory.
        level: Logging level (default: DEBUG for comprehensive logging)

    Returns:
        Logger instance for matching operations

    The matching logger records:
    - Every contact processed with its matching key components
    - Match attempts between contacts from both accounts
    - Match results (matched/unmatched) with detailed reasons
    - Timestamps for all operations
    """
    # Get or create the matching logger
    logger = logging.getLogger("gcontact_sync.matching")
    logger.setLevel(level)

    # Clear any existing handlers to avoid duplicates
    logger.handlers.clear()

    # Prevent propagation to parent loggers to avoid duplicate messages
    logger.propagate = False

    # Determine log file path
    file_path = log_file if log_file else get_matching_log_path()

    try:
        # Ensure log directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Create file handler
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setLevel(level)

        # Use detailed format with millisecond timestamps
        file_formatter = logging.Formatter(MATCHING_LOG_FORMAT, MATCHING_DATE_FORMAT)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # Log the session start
        logger.info("=" * 80)
        logger.info(f"Matching log session started at {datetime.now().isoformat()}")
        logger.info(f"Log file: {file_path}")
        logger.info("=" * 80)

    except (OSError, PermissionError) as e:
        # If we can't create the file, log to console as fallback
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_handler.setFormatter(
            logging.Formatter(MATCHING_LOG_FORMAT, MATCHING_DATE_FORMAT)
        )
        logger.addHandler(console_handler)
        logger.warning(f"Could not create matching log file {file_path}: {e}")
        logger.warning("Falling back to console output for matching logs")

    return logger


def get_matching_logger() -> logging.Logger:
    """
    Get the matching logger instance.

    If the matching logger hasn't been set up yet, this will return
    a logger that only logs to the root logger.

    Returns:
        The matching logger instance
    """
    return logging.getLogger("gcontact_sync.matching")


# Module-level exports
__all__ = [
    "setup_logging",
    "get_logger",
    "set_log_level",
    "disable_logging",
    "enable_logging",
    "cleanup_old_logs",
    "ColoredFormatter",
    "get_log_level_from_env",
    "get_log_file_path",
    "setup_matching_logger",
    "get_matching_logger",
    "get_matching_log_path",
    "PROJECT_LOG_DIR",
    "DEFAULT_FORMAT",
    "CONSOLE_FORMAT",
    "VERBOSE_FORMAT",
    "DATE_FORMAT",
    "MATCHING_LOG_FORMAT",
    "MATCHING_DATE_FORMAT",
]
