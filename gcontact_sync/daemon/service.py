"""
Platform service file management for daemon installation.

Provides functionality to detect the current platform and install/uninstall
the gcontact-sync daemon as a system service on Linux (systemd), macOS (launchd),
and Windows (Task Scheduler).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# Platform identifiers
PLATFORM_LINUX = "linux"
PLATFORM_MACOS = "macos"
PLATFORM_WINDOWS = "windows"
PLATFORM_UNKNOWN = "unknown"

# Default service name
SERVICE_NAME = "gcontact-sync"

# Systemd paths (Linux)
SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"
SYSTEMD_SERVICE_FILE = SYSTEMD_USER_DIR / f"{SERVICE_NAME}.service"

# Launchd paths (macOS)
LAUNCHD_USER_DIR = Path.home() / "Library" / "LaunchAgents"
LAUNCHD_PLIST_FILE = LAUNCHD_USER_DIR / f"com.{SERVICE_NAME}.plist"

# Windows Task Scheduler
WINDOWS_TASK_NAME = "GContactSync"


class ServiceError(Exception):
    """Base exception for service-related errors."""

    pass


class ServiceInstallError(ServiceError):
    """Raised when service installation fails."""

    pass


class ServiceUninstallError(ServiceError):
    """Raised when service uninstallation fails."""

    pass


class UnsupportedPlatformError(ServiceError):
    """Raised when operating on an unsupported platform."""

    pass


def get_platform() -> str:
    """
    Detect the current operating system platform.

    Returns:
        Platform identifier string:
        - "linux" for Linux systems
        - "macos" for macOS systems
        - "windows" for Windows systems
        - "unknown" for unrecognized platforms

    Example:
        platform = get_platform()
        if platform == "linux":
            print("Running on Linux")
    """
    platform = sys.platform.lower()

    if platform.startswith("linux"):
        return PLATFORM_LINUX
    elif platform == "darwin":
        return PLATFORM_MACOS
    elif platform in ("win32", "cygwin"):
        return PLATFORM_WINDOWS
    else:
        return PLATFORM_UNKNOWN


def _get_executable_path() -> str:
    """
    Get the path to the gcontact-sync executable.

    Returns:
        Path to the Python executable running gcontact-sync.
    """
    # Find the gcontact-sync entry point
    # Prefer sys.executable with -m module invocation for reliability
    return sys.executable


def _get_module_invocation() -> list[str]:
    """
    Get the command to invoke gcontact-sync as a module.

    Returns:
        List of command arguments for subprocess invocation.
    """
    return [sys.executable, "-m", "gcontact_sync"]


def generate_systemd_service(
    interval: str = "1h",
    config_dir: Path | None = None,
) -> str:
    """
    Generate systemd service unit file content.

    Creates a systemd user service unit that runs gcontact-sync daemon
    with the specified configuration.

    Args:
        interval: Sync interval (e.g., "1h", "30m", "6h")
        config_dir: Optional custom config directory path

    Returns:
        String containing systemd service unit file content

    Example:
        service_content = generate_systemd_service(interval="30m")
        with open("gcontact-sync.service", "w") as f:
            f.write(service_content)
    """
    python_path = _get_executable_path()
    exec_start = (
        f"{python_path} -m gcontact_sync daemon start "
        f"--foreground --interval {interval}"
    )

    if config_dir:
        exec_start += f" --config-dir {config_dir}"

    return f"""[Unit]
Description=Google Contacts Sync Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=30

# Environment
Environment=PYTHONUNBUFFERED=1

# Graceful shutdown
TimeoutStopSec=30
KillMode=mixed
KillSignal=SIGTERM

[Install]
WantedBy=default.target
"""


def generate_launchd_plist(
    interval: str = "1h",
    config_dir: Path | None = None,
) -> str:
    """
    Generate launchd plist file content for macOS.

    Creates a launchd property list that runs gcontact-sync daemon
    with the specified configuration.

    Args:
        interval: Sync interval (e.g., "1h", "30m", "6h")
        config_dir: Optional custom config directory path

    Returns:
        String containing launchd plist XML content

    Example:
        plist_content = generate_launchd_plist(interval="30m")
        with open("com.gcontact-sync.plist", "w") as f:
            f.write(plist_content)
    """
    python_path = _get_executable_path()
    log_dir = Path.home() / ".gcontact-sync" / "logs"

    program_args = [
        python_path,
        "-m",
        "gcontact_sync",
        "daemon",
        "start",
        "--foreground",
        "--interval",
        interval,
    ]

    if config_dir:
        program_args.extend(["--config-dir", str(config_dir)])

    # Build ProgramArguments XML
    args_xml = "\n".join(f"        <string>{arg}</string>" for arg in program_args)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.{SERVICE_NAME}</string>

    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>30</integer>

    <key>StandardOutPath</key>
    <string>{log_dir}/daemon.log</string>

    <key>StandardErrorPath</key>
    <string>{log_dir}/daemon.err</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
"""


def generate_windows_task_xml(
    interval: str = "1h",
    config_dir: Path | None = None,
) -> str:
    """
    Generate Windows Task Scheduler XML for gcontact-sync daemon.

    Creates a Task Scheduler XML definition that runs gcontact-sync sync
    at the specified interval.

    Args:
        interval: Sync interval (e.g., "1h", "30m", "6h", "1d")
        config_dir: Optional custom config directory path

    Returns:
        String containing Windows Task Scheduler XML content

    Example:
        xml_content = generate_windows_task_xml(interval="1h")
    """
    from gcontact_sync.daemon import parse_interval

    python_path = _get_executable_path()

    # Build command arguments
    args = "-m gcontact_sync sync"
    if config_dir:
        args += f" --config-dir {config_dir}"

    # Parse interval to get repetition settings
    interval_seconds = parse_interval(interval)

    # Convert to ISO 8601 duration format for Task Scheduler
    # PT = Period Time, H = hours, M = minutes, S = seconds
    if interval_seconds >= 86400:  # Days
        days = interval_seconds // 86400
        duration = f"P{days}D"
    elif interval_seconds >= 3600:  # Hours
        hours = interval_seconds // 3600
        duration = f"PT{hours}H"
    elif interval_seconds >= 60:  # Minutes
        minutes = interval_seconds // 60
        duration = f"PT{minutes}M"
    else:  # Seconds
        duration = f"PT{interval_seconds}S"

    # Task runs indefinitely with repetition
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Google Contacts Sync - Automatic synchronization daemon</Description>
    <Author>gcontact-sync</Author>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>{duration}</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{python_path}</Command>
      <Arguments>{args}</Arguments>
      <WorkingDirectory>{Path.home()}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


class ServiceManager:
    """
    Cross-platform service manager for gcontact-sync daemon.

    Provides methods to install, uninstall, start, stop, and check status
    of the daemon service on Linux (systemd) and macOS (launchd).

    Usage:
        manager = ServiceManager()

        # Install the service
        success, error = manager.install(interval="1h")
        if success:
            print("Service installed!")

        # Check if installed
        if manager.is_installed():
            print("Service is installed")

        # Uninstall the service
        manager.uninstall()
    """

    def __init__(self, config_dir: Path | None = None):
        """
        Initialize the service manager.

        Args:
            config_dir: Optional custom configuration directory path
        """
        self.config_dir = config_dir
        self.platform = get_platform()

    def is_platform_supported(self) -> bool:
        """
        Check if the current platform is supported for service installation.

        Returns:
            True if the platform supports service installation, False otherwise.
        """
        return self.platform in (PLATFORM_LINUX, PLATFORM_MACOS, PLATFORM_WINDOWS)

    def get_service_file_path(self) -> Path | None:
        """
        Get the path where the service file will be installed.

        Returns:
            Path to the service file, or None if platform not supported.
            For Windows, returns None as Task Scheduler doesn't use files directly.
        """
        if self.platform == PLATFORM_LINUX:
            return SYSTEMD_SERVICE_FILE
        elif self.platform == PLATFORM_MACOS:
            return LAUNCHD_PLIST_FILE
        elif self.platform == PLATFORM_WINDOWS:
            # Windows Task Scheduler doesn't use a file path in the same way
            # Return a placeholder path for consistency
            return Path.home() / ".gcontact-sync" / "task.xml"
        return None

    def is_installed(self) -> bool:
        """
        Check if the service is currently installed.

        Returns:
            True if the service file exists, False otherwise.
        """
        if self.platform == PLATFORM_WINDOWS:
            return self._is_windows_task_installed()

        service_path = self.get_service_file_path()
        return service_path is not None and service_path.exists()

    def _is_windows_task_installed(self) -> bool:
        """Check if the Windows Task Scheduler task is installed."""
        result = self._run_command(
            ["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME],
            check=False,
        )
        return result.returncode == 0

    def install(
        self,
        interval: str = "1h",
        overwrite: bool = False,
    ) -> tuple[bool, str | None]:
        """
        Install the daemon as a system service.

        Creates the appropriate service file for the current platform
        and optionally enables the service to start on boot.

        Args:
            interval: Sync interval (e.g., "1h", "30m")
            overwrite: If True, overwrite existing service file

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
            Returns (True, None) on success, (False, error_message) on failure

        Example:
            manager = ServiceManager()
            success, error = manager.install(interval="30m")
            if success:
                print("Service installed successfully!")
            else:
                print(f"Installation failed: {error}")
        """
        if not self.is_platform_supported():
            return (
                False,
                f"Platform '{self.platform}' is not supported for service "
                "installation. Supported platforms: Linux (systemd), macOS (launchd), "
                "Windows (Task Scheduler).",
            )

        # Handle Windows separately since it uses Task Scheduler
        if self.platform == PLATFORM_WINDOWS:
            return self._install_windows_task(interval, overwrite)

        service_path = self.get_service_file_path()
        if service_path is None:
            return (False, "Could not determine service file path")

        # Check for existing installation
        if service_path.exists() and not overwrite:
            return (
                False,
                f"Service already installed at {service_path}\n"
                "Use --force to overwrite.",
            )

        try:
            # Generate service content
            if self.platform == PLATFORM_LINUX:
                content = generate_systemd_service(
                    interval=interval,
                    config_dir=self.config_dir,
                )
            else:  # macOS
                content = generate_launchd_plist(
                    interval=interval,
                    config_dir=self.config_dir,
                )

            # Create directory if needed
            service_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)

            # Write service file
            service_path.write_text(content, encoding="utf-8")
            service_path.chmod(0o644)

            logger.info(f"Created service file: {service_path}")

            # Platform-specific post-installation
            if self.platform == PLATFORM_LINUX:
                # Reload systemd to pick up new service
                self._run_command(["systemctl", "--user", "daemon-reload"])
                logger.info("Reloaded systemd user daemon")
            elif self.platform == PLATFORM_MACOS:
                # Ensure log directory exists
                log_dir = Path.home() / ".gcontact-sync" / "logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created log directory: {log_dir}")

            return (True, None)

        except OSError as e:
            error_msg = f"Failed to create service file: {e}"
            logger.error(error_msg)
            return (False, error_msg)
        except Exception as e:
            error_msg = f"Unexpected error during installation: {e}"
            logger.exception(error_msg)
            return (False, error_msg)

    def uninstall(self) -> tuple[bool, str | None]:
        """
        Uninstall the daemon service.

        Stops the service if running and removes the service file.

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
            Returns (True, None) on success, (False, error_message) on failure

        Example:
            manager = ServiceManager()
            success, error = manager.uninstall()
            if success:
                print("Service uninstalled!")
        """
        if not self.is_platform_supported():
            return (
                False,
                f"Platform '{self.platform}' is not supported for service management.",
            )

        # Handle Windows separately
        if self.platform == PLATFORM_WINDOWS:
            return self._uninstall_windows_task()

        service_path = self.get_service_file_path()
        if service_path is None:
            return (False, "Could not determine service file path")

        if not service_path.exists():
            return (False, f"Service not installed (no file at {service_path})")

        try:
            # Stop the service first
            self.stop()

            # Platform-specific pre-removal
            if self.platform == PLATFORM_LINUX:
                # Disable the service
                self._run_command(
                    ["systemctl", "--user", "disable", SERVICE_NAME],
                    check=False,
                )
            elif self.platform == PLATFORM_MACOS:
                # Unload the service
                self._run_command(
                    ["launchctl", "unload", str(service_path)],
                    check=False,
                )

            # Remove service file
            service_path.unlink()
            logger.info(f"Removed service file: {service_path}")

            # Reload systemd
            if self.platform == PLATFORM_LINUX:
                self._run_command(["systemctl", "--user", "daemon-reload"])

            return (True, None)

        except OSError as e:
            error_msg = f"Failed to remove service file: {e}"
            logger.error(error_msg)
            return (False, error_msg)
        except Exception as e:
            error_msg = f"Unexpected error during uninstallation: {e}"
            logger.exception(error_msg)
            return (False, error_msg)

    def start(self) -> tuple[bool, str | None]:
        """
        Start the daemon service.

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        if not self.is_installed():
            return (False, "Service is not installed. Run 'daemon install' first.")

        try:
            if self.platform == PLATFORM_LINUX:
                result = self._run_command(
                    ["systemctl", "--user", "start", SERVICE_NAME]
                )
            elif self.platform == PLATFORM_MACOS:
                service_path = self.get_service_file_path()
                result = self._run_command(["launchctl", "load", str(service_path)])
            elif self.platform == PLATFORM_WINDOWS:
                result = self._run_command(
                    ["schtasks", "/Run", "/TN", WINDOWS_TASK_NAME]
                )
            else:
                return (False, f"Unsupported platform: {self.platform}")

            if result.returncode == 0:
                logger.info("Service started")
                return (True, None)
            else:
                return (False, f"Failed to start service: {result.stderr}")

        except Exception as e:
            error_msg = f"Error starting service: {e}"
            logger.error(error_msg)
            return (False, error_msg)

    def stop(self) -> tuple[bool, str | None]:
        """
        Stop the daemon service.

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        if not self.is_installed():
            return (True, None)  # Not installed, nothing to stop

        try:
            if self.platform == PLATFORM_LINUX:
                self._run_command(
                    ["systemctl", "--user", "stop", SERVICE_NAME],
                    check=False,
                )
            elif self.platform == PLATFORM_MACOS:
                service_path = self.get_service_file_path()
                self._run_command(
                    ["launchctl", "unload", str(service_path)],
                    check=False,
                )
            elif self.platform == PLATFORM_WINDOWS:
                self._run_command(
                    ["schtasks", "/End", "/TN", WINDOWS_TASK_NAME],
                    check=False,
                )
            else:
                return (False, f"Unsupported platform: {self.platform}")

            logger.info("Service stopped")
            return (True, None)

        except Exception as e:
            error_msg = f"Error stopping service: {e}"
            logger.error(error_msg)
            return (False, error_msg)

    def enable(self) -> tuple[bool, str | None]:
        """
        Enable the service to start on boot.

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        if not self.is_installed():
            return (False, "Service is not installed. Run 'daemon install' first.")

        try:
            if self.platform == PLATFORM_LINUX:
                result = self._run_command(
                    ["systemctl", "--user", "enable", SERVICE_NAME]
                )
                if result.returncode == 0:
                    logger.info("Service enabled for autostart")
                    return (True, None)
                return (False, f"Failed to enable service: {result.stderr}")
            elif self.platform == PLATFORM_MACOS:
                # launchd services with RunAtLoad are automatically enabled
                logger.info("Service is already configured to run at load (macOS)")
                return (True, None)
            elif self.platform == PLATFORM_WINDOWS:
                # Windows tasks with LogonTrigger are already enabled
                logger.info("Service is already configured to run at logon (Windows)")
                return (True, None)
            else:
                return (False, f"Unsupported platform: {self.platform}")

        except Exception as e:
            error_msg = f"Error enabling service: {e}"
            logger.error(error_msg)
            return (False, error_msg)

    def disable(self) -> tuple[bool, str | None]:
        """
        Disable the service from starting on boot.

        Returns:
            Tuple of (success: bool, error_message: str | None)
        """
        if not self.is_installed():
            return (True, None)  # Not installed, nothing to disable

        try:
            if self.platform == PLATFORM_LINUX:
                self._run_command(
                    ["systemctl", "--user", "disable", SERVICE_NAME],
                    check=False,
                )
                logger.info("Service disabled from autostart")
                return (True, None)
            elif self.platform == PLATFORM_MACOS:
                # Would need to modify plist to disable RunAtLoad
                logger.info("To disable autostart on macOS, uninstall the service")
                return (True, None)
            elif self.platform == PLATFORM_WINDOWS:
                result = self._run_command(
                    ["schtasks", "/Change", "/TN", WINDOWS_TASK_NAME, "/DISABLE"],
                    check=False,
                )
                if result.returncode == 0:
                    logger.info("Service disabled from autostart")
                    return (True, None)
                return (False, f"Failed to disable service: {result.stderr}")
            else:
                return (False, f"Unsupported platform: {self.platform}")

        except Exception as e:
            error_msg = f"Error disabling service: {e}"
            logger.error(error_msg)
            return (False, error_msg)

    def status(self) -> dict[str, str | bool]:
        """
        Get the current status of the daemon service.

        Returns:
            Dictionary with status information:
            - installed: bool - Whether service file exists
            - running: bool - Whether service is running
            - enabled: bool - Whether service is enabled for autostart
            - platform: str - Current platform
            - service_path: str - Path to service file
        """
        status_info: dict[str, str | bool] = {
            "platform": self.platform,
            "installed": False,
            "running": False,
            "enabled": False,
            "service_path": "",
        }

        # Handle Windows separately
        if self.platform == PLATFORM_WINDOWS:
            status_info["installed"] = self._is_windows_task_installed()
            status_info["service_path"] = f"Task: {WINDOWS_TASK_NAME}"
            if status_info["installed"]:
                status_info["running"] = self._is_windows_task_running()
                status_info["enabled"] = self._is_windows_task_enabled()
            return status_info

        service_path = self.get_service_file_path()
        if service_path:
            status_info["service_path"] = str(service_path)
            status_info["installed"] = service_path.exists()

        if not status_info["installed"]:
            return status_info

        try:
            if self.platform == PLATFORM_LINUX:
                # Check if running
                result = self._run_command(
                    ["systemctl", "--user", "is-active", SERVICE_NAME],
                    check=False,
                )
                status_info["running"] = result.stdout.strip() == "active"

                # Check if enabled
                result = self._run_command(
                    ["systemctl", "--user", "is-enabled", SERVICE_NAME],
                    check=False,
                )
                status_info["enabled"] = result.stdout.strip() == "enabled"

            elif self.platform == PLATFORM_MACOS:
                # Check if loaded (running)
                result = self._run_command(
                    ["launchctl", "list"],
                    check=False,
                )
                service_label = f"com.{SERVICE_NAME}"
                status_info["running"] = service_label in result.stdout
                # launchd services with RunAtLoad are considered enabled
                status_info["enabled"] = status_info["installed"]

        except Exception as e:
            logger.warning(f"Error checking service status: {e}")

        return status_info

    def _run_command(
        self,
        cmd: list[str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """
        Run a command and return the result.

        Args:
            cmd: Command and arguments to run
            check: If True, don't raise on non-zero exit

        Returns:
            CompletedProcess with stdout and stderr
        """
        logger.debug(f"Running command: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            if check and result.returncode != 0:
                logger.warning(
                    f"Command failed with code {result.returncode}: {result.stderr}"
                )
            return result
        except FileNotFoundError as e:
            logger.warning(f"Command not found: {cmd[0]}")
            # Return a fake result for missing commands
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=127,
                stdout="",
                stderr=str(e),
            )

    # Windows-specific helper methods

    def _install_windows_task(
        self, interval: str, overwrite: bool
    ) -> tuple[bool, str | None]:
        """Install the daemon as a Windows Task Scheduler task."""
        if self._is_windows_task_installed() and not overwrite:
            return (
                False,
                f"Task '{WINDOWS_TASK_NAME}' already installed.\n"
                "Use --force to overwrite.",
            )

        try:
            # Generate XML content
            xml_content = generate_windows_task_xml(
                interval=interval,
                config_dir=self.config_dir,
            )

            # Write XML to temp file
            task_xml_path = Path.home() / ".gcontact-sync" / "task.xml"
            task_xml_path.parent.mkdir(parents=True, exist_ok=True)
            task_xml_path.write_text(xml_content, encoding="utf-16")

            # Delete existing task if overwriting
            if overwrite and self._is_windows_task_installed():
                self._run_command(
                    ["schtasks", "/Delete", "/TN", WINDOWS_TASK_NAME, "/F"],
                    check=False,
                )

            # Create the task from XML
            result = self._run_command(
                [
                    "schtasks",
                    "/Create",
                    "/TN",
                    WINDOWS_TASK_NAME,
                    "/XML",
                    str(task_xml_path),
                ],
            )

            if result.returncode == 0:
                logger.info(f"Created Windows scheduled task: {WINDOWS_TASK_NAME}")

                # Create log directory
                log_dir = Path.home() / ".gcontact-sync" / "logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created log directory: {log_dir}")

                return (True, None)
            else:
                return (False, f"Failed to create task: {result.stderr}")

        except OSError as e:
            error_msg = f"Failed to create Windows task: {e}"
            logger.error(error_msg)
            return (False, error_msg)
        except Exception as e:
            error_msg = f"Unexpected error during Windows task installation: {e}"
            logger.exception(error_msg)
            return (False, error_msg)

    def _uninstall_windows_task(self) -> tuple[bool, str | None]:
        """Uninstall the Windows Task Scheduler task."""
        if not self._is_windows_task_installed():
            return (False, f"Task '{WINDOWS_TASK_NAME}' is not installed.")

        try:
            # Stop the task if running
            self._run_command(
                ["schtasks", "/End", "/TN", WINDOWS_TASK_NAME],
                check=False,
            )

            # Delete the task
            result = self._run_command(
                ["schtasks", "/Delete", "/TN", WINDOWS_TASK_NAME, "/F"],
            )

            if result.returncode == 0:
                logger.info(f"Deleted Windows scheduled task: {WINDOWS_TASK_NAME}")

                # Clean up XML file if it exists
                task_xml_path = Path.home() / ".gcontact-sync" / "task.xml"
                if task_xml_path.exists():
                    task_xml_path.unlink()
                    logger.debug(f"Removed task XML file: {task_xml_path}")

                return (True, None)
            else:
                return (False, f"Failed to delete task: {result.stderr}")

        except Exception as e:
            error_msg = f"Unexpected error during Windows task uninstallation: {e}"
            logger.exception(error_msg)
            return (False, error_msg)

    def _is_windows_task_running(self) -> bool:
        """Check if the Windows Task is currently running."""
        result = self._run_command(
            ["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME, "/FO", "LIST", "/V"],
            check=False,
        )
        if result.returncode != 0:
            return False
        # Look for "Status: Running" in the output
        return "Running" in result.stdout

    def _is_windows_task_enabled(self) -> bool:
        """Check if the Windows Task is enabled."""
        result = self._run_command(
            ["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME, "/FO", "LIST", "/V"],
            check=False,
        )
        if result.returncode != 0:
            return False
        # Look for "Scheduled Task State: Enabled" in the output
        return "Enabled" in result.stdout and "Disabled" not in result.stdout


# Module-level exports
__all__ = [
    "get_platform",
    "ServiceManager",
    "ServiceError",
    "ServiceInstallError",
    "ServiceUninstallError",
    "UnsupportedPlatformError",
    "generate_systemd_service",
    "generate_launchd_plist",
    "generate_windows_task_xml",
    "PLATFORM_LINUX",
    "PLATFORM_MACOS",
    "PLATFORM_WINDOWS",
    "PLATFORM_UNKNOWN",
    "SERVICE_NAME",
    "SYSTEMD_SERVICE_FILE",
    "LAUNCHD_PLIST_FILE",
    "WINDOWS_TASK_NAME",
]
