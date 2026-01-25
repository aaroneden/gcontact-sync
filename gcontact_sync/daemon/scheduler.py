"""
Daemon scheduler for background Google Contacts synchronization.

Provides a DaemonScheduler class that manages:
- Scheduled sync operations at configurable intervals
- Signal handling for graceful shutdown (SIGTERM/SIGINT)
- PID file management for daemon control
- Logging of sync results and daemon status
"""

from __future__ import annotations

import logging
import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# Default PID file location
DEFAULT_PID_DIR = Path.home() / ".gcontact-sync"
DEFAULT_PID_FILE = DEFAULT_PID_DIR / "daemon.pid"


class DaemonError(Exception):
    """Base exception for daemon-related errors."""

    pass


class PIDFileError(DaemonError):
    """Raised when PID file operations fail."""

    pass


class DaemonAlreadyRunningError(DaemonError):
    """Raised when attempting to start a daemon that is already running."""

    pass


@dataclass
class DaemonStats:
    """
    Statistics from daemon operation.

    Tracks daemon uptime and sync cycle information.
    """

    started_at: datetime = field(default_factory=datetime.now)
    sync_count: int = 0
    sync_success_count: int = 0
    sync_error_count: int = 0
    last_sync_at: datetime | None = None
    last_sync_success: bool = False
    last_error: str | None = None


class PIDFileManager:
    """
    Manages PID file for daemon process.

    Provides methods to create, read, and remove PID files for
    daemon process management and duplicate prevention.
    """

    def __init__(self, pid_file: Path | None = None):
        """
        Initialize the PID file manager.

        Args:
            pid_file: Path to the PID file. Defaults to ~/.gcontact-sync/daemon.pid
        """
        self.pid_file = pid_file or DEFAULT_PID_FILE

    def create(self) -> None:
        """
        Create the PID file with the current process ID.

        Creates parent directories if they don't exist.

        Raises:
            PIDFileError: If the PID file cannot be created.
            DaemonAlreadyRunningError: If a daemon is already running.
        """
        # Check for existing daemon
        existing_pid = self.read()
        if existing_pid is not None:
            if self._is_process_running(existing_pid):
                raise DaemonAlreadyRunningError(
                    f"Daemon already running with PID {existing_pid}"
                )
            else:
                # Stale PID file - remove it
                logger.warning(
                    f"Removing stale PID file (process {existing_pid} not running)"
                )
                self.remove()

        try:
            # Ensure directory exists
            self.pid_file.parent.mkdir(parents=True, exist_ok=True)

            # Write PID file
            pid = os.getpid()
            self.pid_file.write_text(str(pid))
            logger.debug(f"Created PID file: {self.pid_file} (PID: {pid})")

        except OSError as e:
            raise PIDFileError(f"Failed to create PID file {self.pid_file}: {e}") from e

    def read(self) -> int | None:
        """
        Read the PID from the PID file.

        Returns:
            The PID stored in the file, or None if the file doesn't exist.

        Raises:
            PIDFileError: If the PID file exists but cannot be read or parsed.
        """
        if not self.pid_file.exists():
            return None

        try:
            content = self.pid_file.read_text().strip()
            return int(content)
        except ValueError as e:
            raise PIDFileError(f"Invalid PID in file {self.pid_file}: {content}") from e
        except OSError as e:
            raise PIDFileError(f"Failed to read PID file {self.pid_file}: {e}") from e

    def remove(self) -> None:
        """
        Remove the PID file.

        Does nothing if the file doesn't exist.

        Raises:
            PIDFileError: If the PID file exists but cannot be removed.
        """
        if not self.pid_file.exists():
            return

        try:
            self.pid_file.unlink()
            logger.debug(f"Removed PID file: {self.pid_file}")
        except OSError as e:
            raise PIDFileError(f"Failed to remove PID file {self.pid_file}: {e}") from e

    def _is_process_running(self, pid: int) -> bool:
        """
        Check if a process with the given PID is running.

        Args:
            pid: Process ID to check.

        Returns:
            True if the process is running, False otherwise.
        """
        try:
            # Send signal 0 to check if process exists
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but we don't have permission to signal it
            return True


class DaemonScheduler:
    """
    Daemon scheduler for background synchronization.

    Manages scheduled sync operations with configurable intervals,
    signal handling for graceful shutdown, and PID file management.

    Usage:
        # Create scheduler with 1-hour interval
        scheduler = DaemonScheduler(interval=3600)

        # Set up sync callback
        scheduler.set_sync_callback(my_sync_function)

        # Run (blocks until shutdown signal)
        scheduler.run()

    Attributes:
        interval: Sync interval in seconds
        pid_file: Path to PID file
        stats: Daemon statistics
    """

    def __init__(
        self,
        interval: int = 3600,
        pid_file: Path | None = None,
        run_immediately: bool = True,
    ):
        """
        Initialize the daemon scheduler.

        Args:
            interval: Sync interval in seconds (default: 3600 = 1 hour)
            pid_file: Path to PID file. Defaults to ~/.gcontact-sync/daemon.pid
            run_immediately: If True, run sync immediately on start before
                           waiting for interval. Default True.
        """
        self.interval = interval
        self.run_immediately = run_immediately
        self._pid_manager = PIDFileManager(pid_file)
        self._sync_callback: Callable[[], bool] | None = None
        self._running = False
        self._shutdown_requested = False
        # Signal handler types are complex in Python's type system
        self._original_sigterm_handler: signal.Handlers | None = None  # type: ignore[assignment]
        self._original_sigint_handler: signal.Handlers | None = None  # type: ignore[assignment]
        self.stats = DaemonStats()

    @property
    def pid_file(self) -> Path:
        """Get the PID file path."""
        return self._pid_manager.pid_file

    def set_sync_callback(self, callback: Callable[[], bool]) -> None:
        """
        Set the callback function to execute for sync operations.

        The callback should return True on success, False on failure.

        Args:
            callback: Function to call for sync operations.
                     Should return True on success, False on failure.
        """
        self._sync_callback = callback

    def _setup_signal_handlers(self) -> None:
        """
        Set up signal handlers for graceful shutdown.

        Handles SIGTERM and SIGINT for clean daemon shutdown.
        """
        # Store original handlers for restoration
        self._original_sigterm_handler = signal.signal(  # type: ignore[assignment]
            signal.SIGTERM, self._signal_handler
        )
        self._original_sigint_handler = signal.signal(  # type: ignore[assignment]
            signal.SIGINT, self._signal_handler
        )
        logger.debug("Signal handlers installed for SIGTERM and SIGINT")

    def _restore_signal_handlers(self) -> None:
        """Restore original signal handlers."""
        if self._original_sigterm_handler is not None:
            signal.signal(signal.SIGTERM, self._original_sigterm_handler)
        if self._original_sigint_handler is not None:
            signal.signal(signal.SIGINT, self._original_sigint_handler)
        logger.debug("Signal handlers restored")

    def _signal_handler(self, signum: int, frame: object) -> None:
        """
        Handle shutdown signals.

        Args:
            signum: Signal number received.
            frame: Current stack frame (unused).
        """
        signal_name = signal.Signals(signum).name
        logger.info(f"Received {signal_name}, initiating graceful shutdown...")
        self._shutdown_requested = True

    def _run_sync(self) -> bool:
        """
        Execute the sync callback and update statistics.

        Returns:
            True if sync succeeded, False otherwise.
        """
        if self._sync_callback is None:
            logger.warning("No sync callback configured, skipping sync")
            return False

        self.stats.sync_count += 1
        self.stats.last_sync_at = datetime.now()

        try:
            logger.info(f"Starting sync (cycle #{self.stats.sync_count})")
            success = self._sync_callback()

            if success:
                self.stats.sync_success_count += 1
                self.stats.last_sync_success = True
                self.stats.last_error = None
                logger.info("Sync completed successfully")
            else:
                self.stats.sync_error_count += 1
                self.stats.last_sync_success = False
                logger.warning("Sync completed with errors")

            return success

        except Exception as e:
            self.stats.sync_error_count += 1
            self.stats.last_sync_success = False
            self.stats.last_error = str(e)
            logger.error(f"Sync failed with exception: {e}")
            return False

    def _sleep_interruptible(self, seconds: int) -> bool:
        """
        Sleep for the specified duration, checking for shutdown.

        Sleeps in small increments to allow quick response to shutdown signals.
        Uses wall-clock time to handle system sleep correctly - when the OS
        suspends (e.g., laptop lid closed), wall-clock time continues to advance
        so the sync will run on schedule after wake.

        Args:
            seconds: Total seconds to sleep.

        Returns:
            True if sleep completed normally, False if interrupted by shutdown.
        """
        # Use wall-clock time to handle system sleep correctly.
        # When the system sleeps, time.time() continues to advance,
        # ensuring syncs happen on schedule after wake.
        end_time = time.time() + seconds
        while time.time() < end_time and not self._shutdown_requested:
            # Sleep in 1-second increments for responsiveness to shutdown
            remaining = end_time - time.time()
            sleep_time = min(1.0, max(0, remaining))
            if sleep_time > 0:
                time.sleep(sleep_time)

        return not self._shutdown_requested

    def run(self) -> None:
        """
        Run the daemon scheduler.

        Blocks until a shutdown signal is received. Manages PID file
        creation and cleanup, signal handler setup, and the main sync loop.

        Raises:
            DaemonError: If daemon initialization fails.
            DaemonAlreadyRunningError: If another daemon is already running.
        """
        logger.info(f"Starting daemon scheduler (interval: {self.interval}s)")

        # Create PID file
        self._pid_manager.create()
        logger.info(f"Daemon started (PID: {os.getpid()}, PID file: {self.pid_file})")

        # Set up signal handlers
        self._setup_signal_handlers()

        self._running = True
        self._shutdown_requested = False
        self.stats = DaemonStats()

        try:
            # Run immediately if configured
            if self.run_immediately:
                self._run_sync()

            # Main loop
            while not self._shutdown_requested:
                # Wait for next interval
                logger.debug(f"Sleeping for {self.interval} seconds until next sync")
                if not self._sleep_interruptible(self.interval):
                    # Shutdown requested during sleep
                    break

                # Run sync if not shutting down
                if not self._shutdown_requested:
                    self._run_sync()

        finally:
            # Cleanup
            self._running = False
            self._restore_signal_handlers()
            self._pid_manager.remove()
            logger.info("Daemon scheduler stopped")

    def stop(self) -> None:
        """
        Request daemon shutdown.

        Sets the shutdown flag to trigger graceful shutdown.
        This can be called from within the sync callback or another thread.
        """
        logger.info("Stop requested")
        self._shutdown_requested = True

    def is_running(self) -> bool:
        """
        Check if the daemon is currently running.

        Returns:
            True if the daemon is running, False otherwise.
        """
        return self._running

    @classmethod
    def get_running_pid(cls, pid_file: Path | None = None) -> int | None:
        """
        Get the PID of the currently running daemon.

        Args:
            pid_file: Path to PID file. Defaults to standard location.

        Returns:
            PID if a daemon is running, None otherwise.
        """
        manager = PIDFileManager(pid_file)
        pid = manager.read()

        if pid is None:
            return None

        # Verify process is actually running
        if manager._is_process_running(pid):
            return pid

        return None

    @classmethod
    def stop_running_daemon(cls, pid_file: Path | None = None) -> bool:
        """
        Send a stop signal to the running daemon.

        Args:
            pid_file: Path to PID file. Defaults to standard location.

        Returns:
            True if signal was sent successfully, False if no daemon running.
        """
        pid = cls.get_running_pid(pid_file)

        if pid is None:
            logger.info("No running daemon found")
            return False

        try:
            os.kill(pid, signal.SIGTERM)
            logger.info(f"Sent SIGTERM to daemon (PID: {pid})")
            return True
        except ProcessLookupError:
            logger.warning(f"Daemon process {pid} not found")
            return False
        except PermissionError:
            logger.error(f"Permission denied sending signal to PID {pid}")
            return False


# Module-level exports
__all__ = [
    "DaemonScheduler",
    "DaemonStats",
    "DaemonError",
    "PIDFileError",
    "DaemonAlreadyRunningError",
    "PIDFileManager",
    "DEFAULT_PID_DIR",
    "DEFAULT_PID_FILE",
]
