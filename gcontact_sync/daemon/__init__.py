"""
gcontact_sync.daemon - Daemon and scheduler module

Background service management with configurable sync intervals and signal handling.
"""

import re


def parse_interval(interval: str | int) -> int:
    """Parse an interval string into seconds.

    Accepts interval strings with units (s, m, h, d) or plain integers.

    Args:
        interval: Interval specification. Examples:
            - "30s" -> 30 seconds
            - "5m" -> 5 minutes (300 seconds)
            - "1h" -> 1 hour (3600 seconds)
            - "1d" -> 1 day (86400 seconds)
            - 3600 -> 3600 seconds (pass-through)
            - "3600" -> 3600 seconds (numeric string)

    Returns:
        Interval in seconds as an integer.

    Raises:
        ValueError: If the interval format is invalid or uses an unknown unit.
    """
    if isinstance(interval, int):
        return interval

    if isinstance(interval, str):
        # Try numeric string first
        try:
            return int(interval)
        except ValueError:
            pass

        # Parse interval with unit suffix
        match = re.match(r"^(\d+)\s*([smhd])$", interval.lower().strip())
        if not match:
            raise ValueError(
                f"Invalid interval format: '{interval}'. "
                "Use format like '30s', '5m', '1h', or '1d'."
            )

        value = int(match.group(1))
        unit = match.group(2)

        multipliers = {
            "s": 1,
            "m": 60,
            "h": 3600,
            "d": 86400,
        }

        return value * multipliers[unit]

    raise ValueError(
        f"Invalid interval type: {type(interval).__name__}. Expected str or int."
    )


# Imports after parse_interval to avoid circular dependencies
from gcontact_sync.daemon.scheduler import (  # noqa: E402
    DEFAULT_PID_DIR,
    DEFAULT_PID_FILE,
    DaemonAlreadyRunningError,
    DaemonError,
    DaemonScheduler,
    DaemonStats,
    PIDFileError,
    PIDFileManager,
)
from gcontact_sync.daemon.service import (  # noqa: E402
    PLATFORM_LINUX,
    PLATFORM_MACOS,
    PLATFORM_WINDOWS,
    WINDOWS_TASK_NAME,
    ServiceError,
    ServiceInstallError,
    ServiceManager,
    ServiceUninstallError,
    UnsupportedPlatformError,
    generate_launchd_plist,
    generate_systemd_service,
    generate_windows_task_xml,
    get_platform,
)

__all__ = [
    "parse_interval",
    "DaemonScheduler",
    "DaemonStats",
    "DaemonError",
    "PIDFileError",
    "DaemonAlreadyRunningError",
    "PIDFileManager",
    "DEFAULT_PID_DIR",
    "DEFAULT_PID_FILE",
    # Service management
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
    "WINDOWS_TASK_NAME",
]
