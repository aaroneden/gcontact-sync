"""
Backup manager for contact data persistence and recovery.

Provides functionality to:
- Create JSON backups of contact and group data with timestamp naming
- List available backups sorted by timestamp
- Load backup data for restore operations
- Apply retention policy to limit backup count
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class BackupManager:
    """
    Manager for creating and managing contact data backups.

    Creates timestamped JSON backups of contacts and groups before sync
    operations. Supports retention policies to limit backup count and
    provides restore capabilities.

    Attributes:
        backup_dir: Directory path where backups are stored
        retention_count: Maximum number of backups to retain (0 = unlimited)

    Usage:
        from pathlib import Path

        # Create backup manager
        bm = BackupManager(Path("~/.gcontact-sync/backups"), retention_count=10)

        # Create backup
        backup_file = bm.create_backup(contacts, groups)

        # List available backups
        backups = bm.list_backups()

        # Load specific backup
        data = bm.load_backup(backup_file)

        # Apply retention policy
        bm.apply_retention()
    """

    BACKUP_VERSION = "2.0"
    BACKUP_PREFIX = "backup_"
    BACKUP_SUFFIX = ".json"

    def __init__(self, backup_dir: Path, retention_count: int = 10):
        """
        Initialize the backup manager.

        Args:
            backup_dir: Directory path where backups will be stored
            retention_count: Maximum number of backups to keep (0 = keep all)
        """
        self.backup_dir = Path(backup_dir).expanduser()
        self.retention_count = retention_count

        # Ensure backup directory exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(
        self,
        account1_contacts: list[Any],
        account1_groups: list[Any],
        account2_contacts: list[Any],
        account2_groups: list[Any],
        account1_email: str = "account1",
        account2_email: str = "account2",
    ) -> Path | None:
        """
        Create a timestamped backup of contacts and groups from both accounts.

        Creates a JSON file with format: backup_YYYYMMDD_HHMMSS.json
        containing contact and group data organized by account.

        Args:
            account1_contacts: List of Contact objects from account 1
            account1_groups: List of ContactGroup objects from account 1
            account2_contacts: List of Contact objects from account 2
            account2_groups: List of ContactGroup objects from account 2
            account1_email: Email address of account 1 (for identification)
            account2_email: Email address of account 2 (for identification)

        Returns:
            Path to created backup file, or None if backup failed

        Backup format:
            {
                "version": "2.0",
                "timestamp": "2024-01-20T10:30:00.000000",
                "accounts": {
                    "account1": {
                        "email": "user1@gmail.com",
                        "contacts": [...],
                        "groups": [...]
                    },
                    "account2": {
                        "email": "user2@gmail.com",
                        "contacts": [...],
                        "groups": [...]
                    }
                }
            }
        """
        # Generate timestamp-based filename
        timestamp = datetime.now()
        ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"{self.BACKUP_PREFIX}{ts_str}{self.BACKUP_SUFFIX}"
        backup_path = self.backup_dir / filename

        # Prepare backup data structure organized by account
        backup_data = {
            "version": self.BACKUP_VERSION,
            "timestamp": timestamp.isoformat(),
            "accounts": {
                "account1": {
                    "email": account1_email,
                    "contacts": self._serialize_contacts(account1_contacts),
                    "groups": self._serialize_groups(account1_groups),
                },
                "account2": {
                    "email": account2_email,
                    "contacts": self._serialize_contacts(account2_contacts),
                    "groups": self._serialize_groups(account2_groups),
                },
            },
        }

        try:
            # Write backup to file with pretty formatting
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(backup_data, f, indent=2, ensure_ascii=False)

            # Apply retention policy after creating backup
            self.apply_retention()

            return backup_path

        except OSError:
            # Log error but don't raise - backup failure shouldn't block sync
            # TODO: Add proper logging when logger is available
            return None

    def list_backups(self) -> list[Path]:
        """
        List all available backup files sorted by timestamp (newest first).

        Returns:
            List of Path objects for backup files, sorted newest to oldest

        Example:
            backups = bm.list_backups()
            for backup in backups:
                print(f"Backup: {backup.name}")
        """
        # Find all backup files matching the pattern
        backup_files = list(
            self.backup_dir.glob(f"{self.BACKUP_PREFIX}*{self.BACKUP_SUFFIX}")
        )

        # Sort by modification time, newest first
        backup_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        return backup_files

    def load_backup(self, backup_file: Path) -> dict[str, Any] | None:
        """
        Load and parse a backup file.

        Args:
            backup_file: Path to the backup file to load

        Returns:
            Dictionary containing backup data with keys:
                - version: Backup format version
                - timestamp: ISO format timestamp string
                - contacts: List of contact data
                - groups: List of group data
            Returns None if file cannot be read or parsed

        Example:
            data = bm.load_backup(Path("backup_20240120_103000.json"))
            if data:
                acc1 = data["accounts"]["account1"]
                contacts = acc1["contacts"]
                groups = acc1["groups"]
        """
        try:
            with open(backup_file, encoding="utf-8") as f:
                backup_data = json.load(f)

            # Basic validation
            if not isinstance(backup_data, dict):
                return None

            if "version" not in backup_data:
                return None

            # Support both v1.0 (contacts at top level) and v2.0 (accounts structure)
            version = backup_data.get("version", "1.0")
            if version == "1.0":
                if "contacts" not in backup_data:
                    return None
            else:
                if "accounts" not in backup_data:
                    return None

            return backup_data

        except (OSError, json.JSONDecodeError):
            return None

    def apply_retention(self) -> None:
        """
        Apply retention policy by deleting old backups.

        Keeps only the most recent N backups where N = retention_count.
        If retention_count is 0, all backups are kept.

        Example:
            # Keep only last 10 backups
            bm = BackupManager(backup_dir, retention_count=10)
            bm.apply_retention()  # Deletes backups beyond the 10 most recent
        """
        # If retention_count is 0, keep all backups
        if self.retention_count == 0:
            return

        backups = self.list_backups()

        # Delete backups beyond retention limit
        backups_to_delete = backups[self.retention_count :]

        import contextlib

        for backup in backups_to_delete:
            with contextlib.suppress(OSError):
                backup.unlink()

    def _serialize_contacts(self, contacts: list[Any]) -> list[dict[str, Any]]:
        """
        Serialize contact objects to JSON-compatible dictionaries.

        Args:
            contacts: List of Contact objects or dictionaries

        Returns:
            List of dictionaries ready for JSON serialization
        """
        serialized = []

        for contact in contacts:
            if hasattr(contact, "__dict__"):
                # Convert Contact dataclass to dictionary
                contact_dict = self._serialize_object(contact)
            elif isinstance(contact, dict):
                # Already a dictionary
                contact_dict = contact
            else:
                continue

            serialized.append(contact_dict)

        return serialized

    def _serialize_groups(self, groups: list[Any]) -> list[dict[str, Any]]:
        """
        Serialize group objects to JSON-compatible dictionaries.

        Args:
            groups: List of ContactGroup objects or dictionaries

        Returns:
            List of dictionaries ready for JSON serialization
        """
        serialized = []

        for group in groups:
            if hasattr(group, "__dict__"):
                # Convert ContactGroup dataclass to dictionary
                group_dict = self._serialize_object(group)
            elif isinstance(group, dict):
                # Already a dictionary
                group_dict = group
            else:
                continue

            serialized.append(group_dict)

        return serialized

    def _serialize_object(self, obj: Any) -> dict[str, Any]:
        """
        Serialize an object to a JSON-compatible dictionary.

        Handles:
        - Dataclass objects (__dict__)
        - datetime objects (converted to ISO format)
        - bytes objects (converted to base64 for photo data)

        Args:
            obj: Object to serialize

        Returns:
            Dictionary representation of the object
        """
        import base64

        result: dict[str, Any] = {}

        for key, value in obj.__dict__.items():
            if value is None:
                result[key] = None
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, bytes):
                # Encode binary data (like photos) as base64
                result[key] = base64.b64encode(value).decode("ascii")
            elif isinstance(value, (str, int, float, bool, list, dict)):
                result[key] = value
            else:
                # For other types, convert to string
                result[key] = str(value)

        return result

    def deserialize_contact(self, contact_data: dict[str, Any]) -> Any:
        """
        Deserialize a contact dictionary back to a Contact object.

        Args:
            contact_data: Dictionary from backup containing contact fields

        Returns:
            Contact object reconstructed from backup data
        """
        import base64
        import contextlib

        from gcontact_sync.sync.contact import Contact

        # Parse datetime fields
        last_modified = None
        if contact_data.get("last_modified"):
            with contextlib.suppress(ValueError, TypeError):
                last_modified = datetime.fromisoformat(contact_data["last_modified"])

        # Decode base64 photo data
        photo_data = None
        if contact_data.get("photo_data"):
            with contextlib.suppress(ValueError, TypeError):
                photo_data = base64.b64decode(contact_data["photo_data"])

        return Contact(
            resource_name=contact_data.get("resource_name", ""),
            etag=contact_data.get("etag", ""),
            display_name=contact_data.get("display_name", ""),
            given_name=contact_data.get("given_name"),
            family_name=contact_data.get("family_name"),
            emails=contact_data.get("emails", []),
            phones=contact_data.get("phones", []),
            organizations=contact_data.get("organizations", []),
            notes=contact_data.get("notes"),
            last_modified=last_modified,
            memberships=contact_data.get("memberships", []),
            photo_url=contact_data.get("photo_url"),
            photo_data=photo_data,
            photo_etag=contact_data.get("photo_etag"),
            deleted=contact_data.get("deleted", False),
        )

    def deserialize_group(self, group_data: dict[str, Any]) -> Any:
        """
        Deserialize a group dictionary back to a ContactGroup object.

        Args:
            group_data: Dictionary from backup containing group fields

        Returns:
            ContactGroup object reconstructed from backup data
        """
        from gcontact_sync.sync.group import ContactGroup

        return ContactGroup(
            resource_name=group_data.get("resource_name", ""),
            etag=group_data.get("etag", ""),
            name=group_data.get("name", ""),
            group_type=group_data.get("group_type", "USER_CONTACT_GROUP"),
            member_count=group_data.get("member_count", 0),
            member_resource_names=group_data.get("member_resource_names", []),
            formatted_name=group_data.get("formatted_name"),
            deleted=group_data.get("deleted", False),
        )

    def get_contacts_for_restore(
        self, backup_data: dict[str, Any], account_key: str
    ) -> list[Any]:
        """
        Extract and deserialize contacts from backup for a specific account.

        Args:
            backup_data: Loaded backup data dictionary
            account_key: "account1" or "account2"

        Returns:
            List of Contact objects ready for restore
        """
        version = backup_data.get("version", "1.0")

        if version == "1.0":
            # Legacy format - contacts at top level
            contact_dicts = backup_data.get("contacts", [])
        else:
            # v2.0 format - contacts under accounts
            account_data = backup_data.get("accounts", {}).get(account_key, {})
            contact_dicts = account_data.get("contacts", [])

        return [self.deserialize_contact(c) for c in contact_dicts]

    def get_groups_for_restore(
        self, backup_data: dict[str, Any], account_key: str
    ) -> list[Any]:
        """
        Extract and deserialize groups from backup for a specific account.

        Args:
            backup_data: Loaded backup data dictionary
            account_key: "account1" or "account2"

        Returns:
            List of ContactGroup objects ready for restore
        """
        version = backup_data.get("version", "1.0")

        if version == "1.0":
            # Legacy format - groups at top level
            group_dicts = backup_data.get("groups", [])
        else:
            # v2.0 format - groups under accounts
            account_data = backup_data.get("accounts", {}).get(account_key, {})
            group_dicts = account_data.get("groups", [])

        return [self.deserialize_group(g) for g in group_dicts]
