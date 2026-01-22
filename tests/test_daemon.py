"""
Tests for the daemon module.

Tests interval parsing, scheduler initialization, signal handling,
PID file management, and service file generation.
"""

import os
import signal
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gcontact_sync.daemon import (
    DEFAULT_PID_DIR,
    DEFAULT_PID_FILE,
    DaemonAlreadyRunningError,
    DaemonError,
    DaemonScheduler,
    DaemonStats,
    PIDFileError,
    PIDFileManager,
    parse_interval,
)
from gcontact_sync.daemon.service import (
    PLATFORM_LINUX,
    PLATFORM_MACOS,
    PLATFORM_WINDOWS,
    ServiceManager,
    generate_launchd_plist,
    generate_systemd_service,
    get_platform,
)


class TestParseInterval:
    """Tests for interval parsing functionality."""

    def test_parse_interval_seconds(self):
        """Test parsing interval with seconds suffix."""
        assert parse_interval("30s") == 30
        assert parse_interval("1s") == 1
        assert parse_interval("120s") == 120

    def test_parse_interval_minutes(self):
        """Test parsing interval with minutes suffix."""
        assert parse_interval("5m") == 300
        assert parse_interval("1m") == 60
        assert parse_interval("30m") == 1800

    def test_parse_interval_hours(self):
        """Test parsing interval with hours suffix."""
        assert parse_interval("1h") == 3600
        assert parse_interval("2h") == 7200
        assert parse_interval("24h") == 86400

    def test_parse_interval_days(self):
        """Test parsing interval with days suffix."""
        assert parse_interval("1d") == 86400
        assert parse_interval("7d") == 604800

    def test_parse_interval_integer_passthrough(self):
        """Test that integer values are passed through unchanged."""
        assert parse_interval(3600) == 3600
        assert parse_interval(60) == 60
        assert parse_interval(0) == 0

    def test_parse_interval_numeric_string(self):
        """Test parsing numeric string without unit."""
        assert parse_interval("3600") == 3600
        assert parse_interval("60") == 60

    def test_parse_interval_case_insensitive(self):
        """Test that interval parsing is case insensitive."""
        assert parse_interval("1H") == 3600
        assert parse_interval("5M") == 300
        assert parse_interval("30S") == 30
        assert parse_interval("1D") == 86400

    def test_parse_interval_with_whitespace(self):
        """Test that whitespace is stripped from interval string."""
        assert parse_interval("  1h  ") == 3600
        assert parse_interval(" 30 s") == 30

    def test_parse_interval_invalid_format_raises_error(self):
        """Test that invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid interval format"):
            parse_interval("invalid")

        with pytest.raises(ValueError, match="Invalid interval format"):
            parse_interval("1x")

        with pytest.raises(ValueError, match="Invalid interval format"):
            parse_interval("1hour")

    def test_parse_interval_invalid_type_raises_error(self):
        """Test that invalid type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid interval type"):
            parse_interval(3.14)  # type: ignore

        with pytest.raises(ValueError, match="Invalid interval type"):
            parse_interval(None)  # type: ignore

        with pytest.raises(ValueError, match="Invalid interval type"):
            parse_interval([1, 2, 3])  # type: ignore


class TestDaemonStats:
    """Tests for DaemonStats dataclass."""

    def test_daemon_stats_default_values(self):
        """Test DaemonStats initializes with correct defaults."""
        stats = DaemonStats()
        assert isinstance(stats.started_at, datetime)
        assert stats.sync_count == 0
        assert stats.sync_success_count == 0
        assert stats.sync_error_count == 0
        assert stats.last_sync_at is None
        assert stats.last_sync_success is False
        assert stats.last_error is None

    def test_daemon_stats_custom_values(self):
        """Test DaemonStats can be initialized with custom values."""
        started = datetime(2024, 1, 20, 10, 30, 0)
        stats = DaemonStats(
            started_at=started,
            sync_count=5,
            sync_success_count=4,
            sync_error_count=1,
            last_sync_at=started,
            last_sync_success=True,
            last_error=None,
        )
        assert stats.started_at == started
        assert stats.sync_count == 5
        assert stats.sync_success_count == 4
        assert stats.sync_error_count == 1


class TestPIDFileManager:
    """Tests for PID file management."""

    def test_pid_manager_default_path(self):
        """Test PIDFileManager uses default path when not specified."""
        manager = PIDFileManager()
        assert manager.pid_file == DEFAULT_PID_FILE

    def test_pid_manager_custom_path(self, tmp_path):
        """Test PIDFileManager accepts custom path."""
        custom_path = tmp_path / "custom.pid"
        manager = PIDFileManager(pid_file=custom_path)
        assert manager.pid_file == custom_path

    def test_pid_manager_create(self, tmp_path):
        """Test PIDFileManager creates PID file."""
        pid_file = tmp_path / "daemon.pid"
        manager = PIDFileManager(pid_file=pid_file)

        manager.create()

        assert pid_file.exists()
        assert int(pid_file.read_text()) == os.getpid()

    def test_pid_manager_create_creates_parent_directories(self, tmp_path):
        """Test that create() creates parent directories if needed."""
        pid_file = tmp_path / "nested" / "dirs" / "daemon.pid"
        manager = PIDFileManager(pid_file=pid_file)

        manager.create()

        assert pid_file.exists()
        assert pid_file.parent.exists()

    def test_pid_manager_read_returns_pid(self, tmp_path):
        """Test PIDFileManager reads PID from file."""
        pid_file = tmp_path / "daemon.pid"
        pid_file.write_text("12345")
        manager = PIDFileManager(pid_file=pid_file)

        result = manager.read()

        assert result == 12345

    def test_pid_manager_read_nonexistent_returns_none(self, tmp_path):
        """Test read() returns None for non-existent file."""
        pid_file = tmp_path / "nonexistent.pid"
        manager = PIDFileManager(pid_file=pid_file)

        result = manager.read()

        assert result is None

    def test_pid_manager_read_invalid_pid_raises_error(self, tmp_path):
        """Test read() raises PIDFileError for invalid PID content."""
        pid_file = tmp_path / "daemon.pid"
        pid_file.write_text("not_a_number")
        manager = PIDFileManager(pid_file=pid_file)

        with pytest.raises(PIDFileError, match="Invalid PID"):
            manager.read()

    def test_pid_manager_remove(self, tmp_path):
        """Test PIDFileManager removes PID file."""
        pid_file = tmp_path / "daemon.pid"
        pid_file.write_text("12345")
        manager = PIDFileManager(pid_file=pid_file)

        manager.remove()

        assert not pid_file.exists()

    def test_pid_manager_remove_nonexistent_does_nothing(self, tmp_path):
        """Test remove() does nothing if file doesn't exist."""
        pid_file = tmp_path / "nonexistent.pid"
        manager = PIDFileManager(pid_file=pid_file)

        manager.remove()  # Should not raise

    def test_pid_manager_create_detects_already_running(self, tmp_path):
        """Test create() raises error if daemon already running."""
        pid_file = tmp_path / "daemon.pid"
        # Write current process PID (which is definitely running)
        pid_file.write_text(str(os.getpid()))
        manager = PIDFileManager(pid_file=pid_file)

        with pytest.raises(DaemonAlreadyRunningError, match="already running"):
            manager.create()

    def test_pid_manager_create_removes_stale_pid_file(self, tmp_path):
        """Test create() removes stale PID file (non-existent process)."""
        pid_file = tmp_path / "daemon.pid"
        # Write a PID that almost certainly doesn't exist
        pid_file.write_text("99999999")
        manager = PIDFileManager(pid_file=pid_file)

        # Mock _is_process_running to return False
        with patch.object(manager, "_is_process_running", return_value=False):
            manager.create()

        # File should be recreated with current PID
        assert pid_file.exists()
        assert int(pid_file.read_text()) == os.getpid()

    def test_pid_manager_is_process_running_current_process(self):
        """Test _is_process_running returns True for current process."""
        manager = PIDFileManager()
        assert manager._is_process_running(os.getpid()) is True

    def test_pid_manager_is_process_running_nonexistent(self):
        """Test _is_process_running returns False for non-existent process."""
        manager = PIDFileManager()
        # Use a very high PID unlikely to exist
        assert manager._is_process_running(99999999) is False


class TestDaemonScheduler:
    """Tests for DaemonScheduler class."""

    def test_scheduler_default_initialization(self):
        """Test DaemonScheduler initializes with defaults."""
        scheduler = DaemonScheduler()

        assert scheduler.interval == 3600
        assert scheduler.run_immediately is True
        assert scheduler.pid_file == DEFAULT_PID_FILE
        assert scheduler._sync_callback is None
        assert scheduler._running is False
        assert scheduler._shutdown_requested is False

    def test_scheduler_custom_interval(self):
        """Test DaemonScheduler accepts custom interval."""
        scheduler = DaemonScheduler(interval=1800)
        assert scheduler.interval == 1800

    def test_scheduler_custom_pid_file(self, tmp_path):
        """Test DaemonScheduler accepts custom PID file path."""
        pid_file = tmp_path / "custom.pid"
        scheduler = DaemonScheduler(pid_file=pid_file)
        assert scheduler.pid_file == pid_file

    def test_scheduler_run_immediately_flag(self):
        """Test DaemonScheduler respects run_immediately flag."""
        scheduler = DaemonScheduler(run_immediately=False)
        assert scheduler.run_immediately is False

    def test_scheduler_set_sync_callback(self):
        """Test set_sync_callback stores the callback."""
        scheduler = DaemonScheduler()
        callback = MagicMock(return_value=True)

        scheduler.set_sync_callback(callback)

        assert scheduler._sync_callback is callback

    def test_scheduler_is_running_initially_false(self):
        """Test is_running returns False initially."""
        scheduler = DaemonScheduler()
        assert scheduler.is_running() is False

    def test_scheduler_stop_sets_shutdown_flag(self):
        """Test stop() sets the shutdown flag."""
        scheduler = DaemonScheduler()

        scheduler.stop()

        assert scheduler._shutdown_requested is True


class TestDaemonSchedulerSignalHandling:
    """Tests for signal handling in DaemonScheduler."""

    def test_signal_handler_sets_shutdown_flag(self):
        """Test that signal handler sets shutdown flag."""
        scheduler = DaemonScheduler()

        scheduler._signal_handler(signal.SIGTERM, None)

        assert scheduler._shutdown_requested is True

    def test_signal_handler_handles_sigint(self):
        """Test that signal handler handles SIGINT."""
        scheduler = DaemonScheduler()

        scheduler._signal_handler(signal.SIGINT, None)

        assert scheduler._shutdown_requested is True

    def test_setup_signal_handlers(self):
        """Test _setup_signal_handlers installs handlers."""
        scheduler = DaemonScheduler()

        with patch("signal.signal") as mock_signal:
            scheduler._setup_signal_handlers()

            # Should install handlers for SIGTERM and SIGINT
            assert mock_signal.call_count == 2
            calls = mock_signal.call_args_list
            signals_handled = [call[0][0] for call in calls]
            assert signal.SIGTERM in signals_handled
            assert signal.SIGINT in signals_handled

    def test_restore_signal_handlers(self):
        """Test _restore_signal_handlers restores original handlers."""
        scheduler = DaemonScheduler()

        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sigint = signal.getsignal(signal.SIGINT)

        scheduler._setup_signal_handlers()
        scheduler._restore_signal_handlers()

        # Handlers should be restored
        assert signal.getsignal(signal.SIGTERM) == original_sigterm
        assert signal.getsignal(signal.SIGINT) == original_sigint


class TestDaemonSchedulerSyncExecution:
    """Tests for sync execution in DaemonScheduler."""

    def test_run_sync_without_callback(self):
        """Test _run_sync returns False without callback."""
        scheduler = DaemonScheduler()

        result = scheduler._run_sync()

        assert result is False

    def test_run_sync_with_successful_callback(self):
        """Test _run_sync tracks successful sync."""
        scheduler = DaemonScheduler()
        callback = MagicMock(return_value=True)
        scheduler.set_sync_callback(callback)

        result = scheduler._run_sync()

        assert result is True
        assert scheduler.stats.sync_count == 1
        assert scheduler.stats.sync_success_count == 1
        assert scheduler.stats.sync_error_count == 0
        assert scheduler.stats.last_sync_success is True
        assert scheduler.stats.last_sync_at is not None

    def test_run_sync_with_failed_callback(self):
        """Test _run_sync tracks failed sync."""
        scheduler = DaemonScheduler()
        callback = MagicMock(return_value=False)
        scheduler.set_sync_callback(callback)

        result = scheduler._run_sync()

        assert result is False
        assert scheduler.stats.sync_count == 1
        assert scheduler.stats.sync_success_count == 0
        assert scheduler.stats.sync_error_count == 1
        assert scheduler.stats.last_sync_success is False

    def test_run_sync_with_exception(self):
        """Test _run_sync handles callback exceptions."""
        scheduler = DaemonScheduler()
        callback = MagicMock(side_effect=RuntimeError("Sync error"))
        scheduler.set_sync_callback(callback)

        result = scheduler._run_sync()

        assert result is False
        assert scheduler.stats.sync_count == 1
        assert scheduler.stats.sync_error_count == 1
        assert scheduler.stats.last_error == "Sync error"


class TestDaemonSchedulerSleep:
    """Tests for interruptible sleep in DaemonScheduler."""

    def test_sleep_interruptible_completes(self):
        """Test _sleep_interruptible completes normal sleep."""
        scheduler = DaemonScheduler()

        start = time.time()
        result = scheduler._sleep_interruptible(1)
        elapsed = time.time() - start

        assert result is True
        assert elapsed >= 0.9  # Allow some tolerance

    def test_sleep_interruptible_stops_on_shutdown(self):
        """Test _sleep_interruptible stops when shutdown requested."""
        scheduler = DaemonScheduler()
        scheduler._shutdown_requested = True

        start = time.time()
        result = scheduler._sleep_interruptible(10)
        elapsed = time.time() - start

        assert result is False
        assert elapsed < 2  # Should return quickly


class TestDaemonSchedulerClassMethods:
    """Tests for class methods of DaemonScheduler."""

    def test_get_running_pid_no_file(self, tmp_path):
        """Test get_running_pid returns None when no PID file."""
        pid_file = tmp_path / "nonexistent.pid"

        result = DaemonScheduler.get_running_pid(pid_file)

        assert result is None

    def test_get_running_pid_stale_file(self, tmp_path):
        """Test get_running_pid returns None for stale PID file."""
        pid_file = tmp_path / "daemon.pid"
        pid_file.write_text("99999999")  # Non-existent process

        with patch.object(
            PIDFileManager, "_is_process_running", return_value=False
        ):
            result = DaemonScheduler.get_running_pid(pid_file)

        assert result is None

    def test_get_running_pid_with_running_process(self, tmp_path):
        """Test get_running_pid returns PID for running process."""
        pid_file = tmp_path / "daemon.pid"
        current_pid = os.getpid()
        pid_file.write_text(str(current_pid))

        result = DaemonScheduler.get_running_pid(pid_file)

        assert result == current_pid

    def test_stop_running_daemon_no_daemon(self, tmp_path):
        """Test stop_running_daemon returns False when no daemon."""
        pid_file = tmp_path / "nonexistent.pid"

        result = DaemonScheduler.stop_running_daemon(pid_file)

        assert result is False

    def test_stop_running_daemon_sends_signal(self, tmp_path):
        """Test stop_running_daemon sends SIGTERM to daemon."""
        pid_file = tmp_path / "daemon.pid"
        pid_file.write_text("12345")

        with patch("os.kill") as mock_kill, patch.object(
            PIDFileManager, "_is_process_running", return_value=True
        ):
            result = DaemonScheduler.stop_running_daemon(pid_file)

        assert result is True
        mock_kill.assert_called_once_with(12345, signal.SIGTERM)


class TestDaemonErrors:
    """Tests for daemon exception classes."""

    def test_daemon_error_is_exception(self):
        """Test DaemonError is an Exception."""
        assert issubclass(DaemonError, Exception)

    def test_pid_file_error_is_daemon_error(self):
        """Test PIDFileError is a DaemonError."""
        assert issubclass(PIDFileError, DaemonError)

    def test_daemon_already_running_error_is_daemon_error(self):
        """Test DaemonAlreadyRunningError is a DaemonError."""
        assert issubclass(DaemonAlreadyRunningError, DaemonError)

    def test_daemon_error_can_be_raised(self):
        """Test DaemonError can be raised with message."""
        with pytest.raises(DaemonError, match="Test error"):
            raise DaemonError("Test error")


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_default_pid_dir_is_in_home(self):
        """Test DEFAULT_PID_DIR is in user's home directory."""
        assert Path.home() / ".gcontact-sync" == DEFAULT_PID_DIR

    def test_default_pid_file_path(self):
        """Test DEFAULT_PID_FILE is correctly defined."""
        assert DEFAULT_PID_FILE == DEFAULT_PID_DIR / "daemon.pid"


class TestGetPlatform:
    """Tests for platform detection."""

    def test_get_platform_returns_string(self):
        """Test get_platform returns a string."""
        result = get_platform()
        assert isinstance(result, str)

    def test_get_platform_returns_known_value(self):
        """Test get_platform returns a known platform identifier."""
        result = get_platform()
        assert result in [PLATFORM_LINUX, PLATFORM_MACOS, PLATFORM_WINDOWS, "unknown"]

    @patch("sys.platform", "linux")
    def test_get_platform_linux(self):
        """Test get_platform returns 'linux' for Linux systems."""
        assert get_platform() == PLATFORM_LINUX

    @patch("sys.platform", "darwin")
    def test_get_platform_macos(self):
        """Test get_platform returns 'macos' for macOS systems."""
        assert get_platform() == PLATFORM_MACOS

    @patch("sys.platform", "win32")
    def test_get_platform_windows(self):
        """Test get_platform returns 'windows' for Windows systems."""
        assert get_platform() == PLATFORM_WINDOWS

    @patch("sys.platform", "freebsd")
    def test_get_platform_unknown(self):
        """Test get_platform returns 'unknown' for unrecognized platforms."""
        assert get_platform() == "unknown"


class TestGenerateSystemdService:
    """Tests for systemd service file generation."""

    def test_generate_systemd_service_returns_string(self):
        """Test generate_systemd_service returns a string."""
        result = generate_systemd_service()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_systemd_service_contains_required_sections(self):
        """Test generated service file contains required sections."""
        result = generate_systemd_service()
        assert "[Unit]" in result
        assert "[Service]" in result
        assert "[Install]" in result

    def test_generate_systemd_service_contains_description(self):
        """Test generated service file contains description."""
        result = generate_systemd_service()
        assert "Description=" in result
        assert "Google Contacts Sync" in result

    def test_generate_systemd_service_contains_exec_start(self):
        """Test generated service file contains ExecStart."""
        result = generate_systemd_service()
        assert "ExecStart=" in result
        assert "daemon start" in result
        assert "--foreground" in result

    def test_generate_systemd_service_custom_interval(self):
        """Test generate_systemd_service uses custom interval."""
        result = generate_systemd_service(interval="30m")
        assert "--interval 30m" in result

    def test_generate_systemd_service_custom_config_dir(self, tmp_path):
        """Test generate_systemd_service uses custom config dir."""
        result = generate_systemd_service(config_dir=tmp_path)
        assert f"--config-dir {tmp_path}" in result

    def test_generate_systemd_service_restart_policy(self):
        """Test generated service file has restart policy."""
        result = generate_systemd_service()
        assert "Restart=" in result
        assert "RestartSec=" in result


class TestGenerateLaunchdPlist:
    """Tests for launchd plist file generation."""

    def test_generate_launchd_plist_returns_string(self):
        """Test generate_launchd_plist returns a string."""
        result = generate_launchd_plist()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_launchd_plist_is_valid_xml(self):
        """Test generated plist is valid XML."""
        result = generate_launchd_plist()
        assert "<?xml version" in result
        assert "<plist" in result
        assert "</plist>" in result

    def test_generate_launchd_plist_contains_label(self):
        """Test generated plist contains Label."""
        result = generate_launchd_plist()
        assert "<key>Label</key>" in result
        assert "com.gcontact-sync" in result

    def test_generate_launchd_plist_contains_program_arguments(self):
        """Test generated plist contains ProgramArguments."""
        result = generate_launchd_plist()
        assert "<key>ProgramArguments</key>" in result
        assert "daemon" in result
        assert "start" in result
        assert "--foreground" in result

    def test_generate_launchd_plist_custom_interval(self):
        """Test generate_launchd_plist uses custom interval."""
        result = generate_launchd_plist(interval="2h")
        assert "2h" in result

    def test_generate_launchd_plist_custom_config_dir(self, tmp_path):
        """Test generate_launchd_plist uses custom config dir."""
        result = generate_launchd_plist(config_dir=tmp_path)
        assert str(tmp_path) in result
        assert "--config-dir" in result

    def test_generate_launchd_plist_keep_alive(self):
        """Test generated plist has KeepAlive configuration."""
        result = generate_launchd_plist()
        assert "<key>KeepAlive</key>" in result

    def test_generate_launchd_plist_run_at_load(self):
        """Test generated plist has RunAtLoad configuration."""
        result = generate_launchd_plist()
        assert "<key>RunAtLoad</key>" in result
        assert "<true/>" in result


class TestServiceManager:
    """Tests for ServiceManager class."""

    def test_service_manager_initialization(self):
        """Test ServiceManager initializes correctly."""
        manager = ServiceManager()
        assert manager.platform == get_platform()
        assert manager.config_dir is None

    def test_service_manager_custom_config_dir(self, tmp_path):
        """Test ServiceManager accepts custom config dir."""
        manager = ServiceManager(config_dir=tmp_path)
        assert manager.config_dir == tmp_path

    @patch("gcontact_sync.daemon.service.get_platform", return_value=PLATFORM_LINUX)
    def test_service_manager_is_platform_supported_linux(self, mock_platform):
        """Test is_platform_supported returns True for Linux."""
        manager = ServiceManager()
        manager.platform = PLATFORM_LINUX
        assert manager.is_platform_supported() is True

    @patch("gcontact_sync.daemon.service.get_platform", return_value=PLATFORM_MACOS)
    def test_service_manager_is_platform_supported_macos(self, mock_platform):
        """Test is_platform_supported returns True for macOS."""
        manager = ServiceManager()
        manager.platform = PLATFORM_MACOS
        assert manager.is_platform_supported() is True

    @patch("gcontact_sync.daemon.service.get_platform", return_value=PLATFORM_WINDOWS)
    def test_service_manager_is_platform_supported_windows(self, mock_platform):
        """Test is_platform_supported returns False for Windows."""
        manager = ServiceManager()
        manager.platform = PLATFORM_WINDOWS
        assert manager.is_platform_supported() is False

    def test_service_manager_is_installed_no_file(self, tmp_path):
        """Test is_installed returns False when service file doesn't exist."""
        manager = ServiceManager()

        # Mock get_service_file_path to return a non-existent path
        with patch.object(
            manager, "get_service_file_path", return_value=tmp_path / "nonexistent"
        ):
            assert manager.is_installed() is False

    def test_service_manager_is_installed_with_file(self, tmp_path):
        """Test is_installed returns True when service file exists."""
        service_file = tmp_path / "service.file"
        service_file.write_text("content")

        manager = ServiceManager()
        with patch.object(
            manager, "get_service_file_path", return_value=service_file
        ):
            assert manager.is_installed() is True

    def test_service_manager_install_unsupported_platform(self):
        """Test install returns error for unsupported platform."""
        manager = ServiceManager()
        manager.platform = "unsupported"

        success, error = manager.install()

        assert success is False
        assert "not supported" in error

    def test_service_manager_install_already_installed(self, tmp_path):
        """Test install fails if service already installed without overwrite."""
        service_file = tmp_path / "service.file"
        service_file.write_text("existing content")

        manager = ServiceManager()
        manager.platform = PLATFORM_LINUX

        with patch.object(
            manager, "get_service_file_path", return_value=service_file
        ):
            success, error = manager.install(overwrite=False)

        assert success is False
        assert "already installed" in error

    def test_service_manager_status_not_installed(self, tmp_path):
        """Test status returns correct info when not installed."""
        manager = ServiceManager()
        manager.platform = PLATFORM_LINUX

        with patch.object(
            manager, "get_service_file_path", return_value=tmp_path / "nonexistent"
        ):
            status = manager.status()

        assert status["installed"] is False
        assert status["running"] is False
        assert status["enabled"] is False
