"""
Backup and restore functionality for contact data.

This module provides backup capabilities to create local snapshots of contact
data before sync operations, with restore capabilities for recovery.
"""

from gcontact_sync.backup.manager import BackupManager

__all__ = ["BackupManager"]
