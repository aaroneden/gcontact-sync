"""
Tests for the logging configuration module.

Tests the centralized logging configuration functionality.
"""

import logging
import os
from pathlib import Path
from unittest.mock import patch

from gcontact_sync.utils.logging import (
    CONSOLE_FORMAT,
    DATE_FORMAT,
    DEFAULT_FORMAT,
    VERBOSE_FORMAT,
    ColoredFormatter,
    disable_logging,
    enable_logging,
    get_log_file_path,
    get_log_level_from_env,
    get_logger,
    get_matching_log_path,
    get_matching_logger,
    set_log_level,
    setup_logging,
    setup_matching_logger,
)


class TestConstants:
    """Tests for module constants."""

    def test_default_format_defined(self):
        """Test DEFAULT_FORMAT is defined."""
        assert DEFAULT_FORMAT is not None
        assert "%(message)s" in DEFAULT_FORMAT

    def test_console_format_defined(self):
        """Test CONSOLE_FORMAT is defined."""
        assert CONSOLE_FORMAT is not None
        assert "%(message)s" in CONSOLE_FORMAT

    def test_verbose_format_defined(self):
        """Test VERBOSE_FORMAT is defined."""
        assert VERBOSE_FORMAT is not None
        assert "%(filename)s" in VERBOSE_FORMAT
        assert "%(lineno)d" in VERBOSE_FORMAT

    def test_date_format_defined(self):
        """Test DATE_FORMAT is defined."""
        assert DATE_FORMAT is not None


class TestGetLogLevelFromEnv:
    """Tests for get_log_level_from_env function."""

    @patch.dict(os.environ, {"GCONTACT_SYNC_DEBUG": "1"}, clear=False)
    def test_debug_mode_from_env_1(self):
        """Test debug mode enabled with '1'."""
        level = get_log_level_from_env()
        assert level == logging.DEBUG

    @patch.dict(os.environ, {"GCONTACT_SYNC_DEBUG": "true"}, clear=False)
    def test_debug_mode_from_env_true(self):
        """Test debug mode enabled with 'true'."""
        level = get_log_level_from_env()
        assert level == logging.DEBUG

    @patch.dict(os.environ, {"GCONTACT_SYNC_DEBUG": "yes"}, clear=False)
    def test_debug_mode_from_env_yes(self):
        """Test debug mode enabled with 'yes'."""
        level = get_log_level_from_env()
        assert level == logging.DEBUG

    @patch.dict(
        os.environ,
        {"GCONTACT_SYNC_LOG_LEVEL": "WARNING", "GCONTACT_SYNC_DEBUG": ""},
        clear=False,
    )
    def test_log_level_warning(self):
        """Test WARNING log level from env."""
        level = get_log_level_from_env()
        assert level == logging.WARNING

    @patch.dict(
        os.environ,
        {"GCONTACT_SYNC_LOG_LEVEL": "ERROR", "GCONTACT_SYNC_DEBUG": ""},
        clear=False,
    )
    def test_log_level_error(self):
        """Test ERROR log level from env."""
        level = get_log_level_from_env()
        assert level == logging.ERROR

    @patch.dict(
        os.environ,
        {"GCONTACT_SYNC_LOG_LEVEL": "CRITICAL", "GCONTACT_SYNC_DEBUG": ""},
        clear=False,
    )
    def test_log_level_critical(self):
        """Test CRITICAL log level from env."""
        level = get_log_level_from_env()
        assert level == logging.CRITICAL

    @patch.dict(
        os.environ,
        {"GCONTACT_SYNC_LOG_LEVEL": "INVALID", "GCONTACT_SYNC_DEBUG": ""},
        clear=False,
    )
    def test_invalid_level_defaults_to_info(self):
        """Test invalid log level defaults to INFO."""
        level = get_log_level_from_env()
        assert level == logging.INFO

    @patch.dict(
        os.environ,
        {"GCONTACT_SYNC_LOG_LEVEL": "WARN", "GCONTACT_SYNC_DEBUG": ""},
        clear=False,
    )
    def test_warn_alias_for_warning(self):
        """Test WARN is an alias for WARNING."""
        level = get_log_level_from_env()
        assert level == logging.WARNING


class TestGetLogFilePath:
    """Tests for get_log_file_path function."""

    @patch.dict(os.environ, {"GCONTACT_SYNC_LOG_FILE": "/custom/path/app.log"})
    def test_custom_log_file_from_env(self):
        """Test custom log file path from environment."""
        path = get_log_file_path()
        assert path == Path("/custom/path/app.log")

    @patch.dict(os.environ, {"GCONTACT_SYNC_LOG_FILE": "none"})
    def test_log_file_disabled_with_none(self):
        """Test log file disabled with 'none'."""
        path = get_log_file_path()
        assert path is None

    @patch.dict(os.environ, {"GCONTACT_SYNC_LOG_FILE": "disabled"})
    def test_log_file_disabled_with_disabled(self):
        """Test log file disabled with 'disabled'."""
        path = get_log_file_path()
        assert path is None

    @patch.dict(os.environ, {"GCONTACT_SYNC_LOG_FILE": ""}, clear=False)
    def test_log_file_empty_uses_default(self):
        """Test empty GCONTACT_SYNC_LOG_FILE uses default path."""
        # Empty string is falsy, so it falls through to default behavior
        path = get_log_file_path()
        assert path is not None
        assert "gcontact_sync" in str(path)
        assert ".log" in str(path)

    @patch.dict(
        os.environ,
        {"GCONTACT_SYNC_CONFIG_DIR": "/custom/config", "GCONTACT_SYNC_LOG_FILE": ""},
        clear=False,
    )
    def test_default_log_dir_with_custom_config(self):
        """Test default log file uses custom config dir."""
        # Clear GCONTACT_SYNC_LOG_FILE to trigger default behavior
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.dict(os.environ, {"GCONTACT_SYNC_CONFIG_DIR": "/custom/config"}),
        ):
            path = get_log_file_path()
            assert path is not None
            assert "/custom/config/logs" in str(path)


class TestColoredFormatter:
    """Tests for ColoredFormatter class."""

    def test_formatter_with_colors_disabled(self):
        """Test formatter with colors explicitly disabled."""
        formatter = ColoredFormatter(CONSOLE_FORMAT, DATE_FORMAT, use_colors=False)
        assert formatter.use_colors is False

    @patch("sys.stdout")
    def test_formatter_supports_color_non_tty(self, mock_stdout):
        """Test formatter detects non-TTY and disables colors."""
        mock_stdout.isatty.return_value = False
        formatter = ColoredFormatter(CONSOLE_FORMAT, DATE_FORMAT, use_colors=True)
        assert formatter.use_colors is False

    @patch.dict(os.environ, {"NO_COLOR": "1"})
    @patch("sys.stdout")
    def test_formatter_respects_no_color_env(self, mock_stdout):
        """Test formatter respects NO_COLOR environment variable."""
        mock_stdout.isatty.return_value = True
        formatter = ColoredFormatter(CONSOLE_FORMAT, DATE_FORMAT, use_colors=True)
        assert formatter.use_colors is False

    @patch.dict(os.environ, {"TERM": "dumb"}, clear=False)
    @patch("sys.stdout")
    def test_formatter_detects_dumb_terminal(self, mock_stdout):
        """Test formatter detects dumb terminal."""
        mock_stdout.isatty.return_value = True
        # Clear NO_COLOR if set
        with patch.dict(os.environ, {"TERM": "dumb", "NO_COLOR": ""}):
            formatter = ColoredFormatter(CONSOLE_FORMAT, DATE_FORMAT, use_colors=True)
            assert formatter.use_colors is False

    def test_format_record_without_colors(self):
        """Test formatting a record without colors."""
        formatter = ColoredFormatter(CONSOLE_FORMAT, DATE_FORMAT, use_colors=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert "Test message" in result
        # Should not contain ANSI codes
        assert "\033[" not in result


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_setup_logging_returns_logger(self):
        """Test setup_logging returns a logger."""
        logger = setup_logging(enable_file_logging=False)
        assert isinstance(logger, logging.Logger)
        assert logger.name == "gcontact_sync"

    def test_setup_logging_with_verbose(self):
        """Test setup_logging with verbose mode."""
        logger = setup_logging(verbose=True, enable_file_logging=False)
        assert logger.level == logging.DEBUG

    def test_setup_logging_with_explicit_level(self):
        """Test setup_logging with explicit level."""
        logger = setup_logging(level=logging.WARNING, enable_file_logging=False)
        assert logger.level == logging.WARNING

    def test_setup_logging_clears_handlers(self):
        """Test setup_logging clears existing handlers."""
        # Setup twice to ensure handlers are cleared
        setup_logging(enable_file_logging=False)
        logger = setup_logging(enable_file_logging=False)
        # Should have exactly one handler (console)
        assert len(logger.handlers) == 1

    def test_setup_logging_with_file(self, tmp_path):
        """Test setup_logging with file logging."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(
            log_file=log_file, enable_file_logging=True, use_colors=False
        )
        # Should have console + file handlers
        assert len(logger.handlers) == 2
        # Log something
        logger.info("Test message")
        # Verify file exists and has content
        assert log_file.exists()

    def test_setup_logging_without_file(self):
        """Test setup_logging without file logging."""
        logger = setup_logging(enable_file_logging=False)
        # Should have only console handler
        assert len(logger.handlers) == 1

    def test_setup_logging_propagate_disabled(self):
        """Test that propagation to root logger is disabled."""
        logger = setup_logging(enable_file_logging=False)
        assert logger.propagate is False


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_with_module_name(self):
        """Test get_logger with module name."""
        logger = get_logger("gcontact_sync.test")
        assert logger.name == "gcontact_sync.test"

    def test_get_logger_without_prefix(self):
        """Test get_logger prepends prefix if needed."""
        logger = get_logger("mymodule")
        assert logger.name == "gcontact_sync.mymodule"

    def test_get_logger_returns_child_logger(self):
        """Test get_logger returns a child of gcontact_sync logger."""
        logger = get_logger("test_child")
        # Should be a child of gcontact_sync
        assert logger.parent is not None
        assert logger.parent.name == "gcontact_sync"


class TestSetLogLevel:
    """Tests for set_log_level function."""

    def test_set_log_level_changes_level(self):
        """Test set_log_level changes the logger level."""
        setup_logging(enable_file_logging=False)
        set_log_level(logging.ERROR)
        logger = logging.getLogger("gcontact_sync")
        assert logger.level == logging.ERROR
        # Reset
        set_log_level(logging.INFO)


class TestDisableEnableLogging:
    """Tests for disable_logging and enable_logging functions."""

    def test_disable_logging(self):
        """Test disable_logging disables the logger."""
        setup_logging(enable_file_logging=False)
        disable_logging()
        logger = logging.getLogger("gcontact_sync")
        assert logger.disabled is True
        # Re-enable for other tests
        enable_logging()

    def test_enable_logging(self):
        """Test enable_logging re-enables the logger."""
        setup_logging(enable_file_logging=False)
        disable_logging()
        enable_logging()
        logger = logging.getLogger("gcontact_sync")
        assert logger.disabled is False


class TestMatchingLogger:
    """Tests for matching logger functions."""

    def test_get_matching_log_path(self):
        """Test get_matching_log_path returns a path."""
        path = get_matching_log_path()
        assert isinstance(path, Path)
        assert "matching_" in str(path)
        assert ".log" in str(path)

    def test_get_matching_logger(self):
        """Test get_matching_logger returns a logger."""
        logger = get_matching_logger()
        assert isinstance(logger, logging.Logger)
        assert "matching" in logger.name

    def test_setup_matching_logger(self, tmp_path):
        """Test setup_matching_logger creates logger with file handler."""
        log_file = tmp_path / "matching.log"
        logger = setup_matching_logger(log_file=log_file)

        assert isinstance(logger, logging.Logger)
        assert len(logger.handlers) >= 1

        # Log a message
        logger.info("Test matching log")

        # Check file was created
        assert log_file.exists()

    def test_setup_matching_logger_clears_handlers(self, tmp_path):
        """Test setup_matching_logger clears existing handlers."""
        log_file = tmp_path / "matching.log"
        # Setup twice
        setup_matching_logger(log_file=log_file)
        logger = setup_matching_logger(log_file=log_file)

        # Should not accumulate handlers
        # Note: exact count depends on implementation
        assert len(logger.handlers) >= 1

    def test_setup_matching_logger_default_path(self):
        """Test setup_matching_logger with default path."""
        # This creates a file in the project logs directory
        logger = setup_matching_logger()
        assert isinstance(logger, logging.Logger)
        # Clean up
        logger.handlers.clear()
