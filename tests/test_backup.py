"""
Unit tests for the backup module.

Tests the BackupManager class for creating, listing, loading, and managing
contact data backups with retention policies.
"""

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from gcontact_sync.backup.manager import BackupManager


def create_backup_helper(
    bm: BackupManager,
    account1_contacts: list | None = None,
    account1_groups: list | None = None,
    account2_contacts: list | None = None,
    account2_groups: list | None = None,
    account1_email: str = "test1@example.com",
    account2_email: str = "test2@example.com",
) -> Path | None:
    """Helper to create backup with sensible defaults."""
    return bm.create_backup(
        account1_contacts=account1_contacts or [],
        account1_groups=account1_groups or [],
        account2_contacts=account2_contacts or [],
        account2_groups=account2_groups or [],
        account1_email=account1_email,
        account2_email=account2_email,
    )


class TestBackupManagerInitialization:
    """Tests for BackupManager initialization."""

    def test_create_with_simple_path(self, tmp_path):
        """Test creating BackupManager with a simple path."""
        backup_dir = tmp_path / "backups"
        bm = BackupManager(backup_dir)
        assert bm.backup_dir == backup_dir
        assert bm.retention_count == 10

    def test_create_with_custom_retention(self, tmp_path):
        """Test creating BackupManager with custom retention count."""
        backup_dir = tmp_path / "backups"
        bm = BackupManager(backup_dir, retention_count=5)
        assert bm.retention_count == 5

    def test_create_with_zero_retention(self, tmp_path):
        """Test creating BackupManager with unlimited retention."""
        backup_dir = tmp_path / "backups"
        bm = BackupManager(backup_dir, retention_count=0)
        assert bm.retention_count == 0

    def test_initialization_creates_directory(self, tmp_path):
        """Test that initialization creates backup directory if it doesn't exist."""
        backup_dir = tmp_path / "backups" / "nested"
        assert not backup_dir.exists()

        BackupManager(backup_dir)
        assert backup_dir.exists()
        assert backup_dir.is_dir()

    def test_initialization_with_existing_directory(self, tmp_path):
        """Test initialization with existing directory."""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        BackupManager(backup_dir)
        assert backup_dir.exists()

    def test_path_expansion_with_tilde(self, tmp_path):
        """Test that paths with ~ are expanded."""
        # We can't easily test actual home directory expansion,
        # but we can verify the expanduser() is called by checking the result
        bm = BackupManager("~/test_backups")
        assert "~" not in str(bm.backup_dir)


class TestBackupCreation:
    """Tests for creating backups."""

    @pytest.fixture
    def bm(self, tmp_path):
        """Create a BackupManager instance."""
        return BackupManager(tmp_path / "backups")

    def test_create_backup_with_empty_data(self, bm):
        """Test creating backup with empty contacts and groups."""
        backup_path = create_backup_helper(bm)

        assert backup_path is not None
        assert backup_path.exists()
        assert backup_path.name.startswith("backup_")
        assert backup_path.name.endswith(".json")

    def test_create_backup_with_dict_contacts(self, bm):
        """Test creating backup with dictionary contacts."""
        contacts = [
            {"name": "John Doe", "email": "john@example.com"},
            {"name": "Jane Smith", "email": "jane@example.com"},
        ]
        groups = [{"name": "Friends", "id": "group1"}]

        backup_path = create_backup_helper(
            bm, account1_contacts=contacts, account1_groups=groups
        )

        assert backup_path is not None
        assert backup_path.exists()

    def test_create_backup_filename_format(self, bm):
        """Test that backup filename follows expected format."""
        backup_path = create_backup_helper(bm)

        # Format: backup_YYYYMMDD_HHMMSS.json
        name = backup_path.name
        assert name.startswith("backup_")
        assert name.endswith(".json")

        # Extract timestamp part
        timestamp_part = name[7:-5]  # Remove "backup_" and ".json"
        assert len(timestamp_part) == 15  # YYYYMMDD_HHMMSS
        assert timestamp_part[8] == "_"

    def test_create_backup_file_content_structure(self, bm):
        """Test that backup file has correct structure."""
        contacts = [{"name": "Test Contact"}]
        groups = [{"name": "Test Group"}]

        backup_path = create_backup_helper(
            bm, account1_contacts=contacts, account1_groups=groups
        )

        with open(backup_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "version" in data
        assert "timestamp" in data
        assert "accounts" in data
        assert "account1" in data["accounts"]
        assert "account2" in data["accounts"]
        assert data["version"] == "2.0"
        assert "email" in data["accounts"]["account1"]
        assert "contacts" in data["accounts"]["account1"]
        assert "groups" in data["accounts"]["account1"]
        assert len(data["accounts"]["account1"]["contacts"]) == 1
        assert len(data["accounts"]["account1"]["groups"]) == 1

    def test_create_backup_preserves_contact_data(self, bm):
        """Test that contact data is preserved in backup."""
        contacts = [
            {"name": "John Doe", "email": "john@example.com", "phone": "555-1234"}
        ]

        backup_path = create_backup_helper(bm, account1_contacts=contacts)

        with open(backup_path, encoding="utf-8") as f:
            data = json.load(f)

        acc1_contacts = data["accounts"]["account1"]["contacts"]
        assert acc1_contacts[0]["name"] == "John Doe"
        assert acc1_contacts[0]["email"] == "john@example.com"
        assert acc1_contacts[0]["phone"] == "555-1234"

    def test_create_backup_timestamp_is_iso_format(self, bm):
        """Test that timestamp is in ISO format."""
        backup_path = create_backup_helper(bm)

        with open(backup_path, encoding="utf-8") as f:
            data = json.load(f)

        # Should be able to parse as ISO format datetime
        timestamp = datetime.fromisoformat(data["timestamp"])
        assert isinstance(timestamp, datetime)

    def test_create_backup_applies_retention(self, tmp_path):
        """Test that creating backup applies retention policy."""
        bm = BackupManager(tmp_path / "backups", retention_count=2)

        # Create 3 backups
        create_backup_helper(bm)
        time.sleep(1.1)  # Ensure different timestamps (filename has second precision)
        create_backup_helper(bm)
        time.sleep(1.1)
        create_backup_helper(bm)

        # Should only have 2 backups due to retention
        backups = bm.list_backups()
        assert len(backups) == 2

    def test_create_backup_with_object_contacts(self, bm):
        """Test creating backup with contact objects."""

        class MockContact:
            def __init__(self, name, email):
                self.name = name
                self.email = email

        contacts = [MockContact("John", "john@example.com")]

        backup_path = create_backup_helper(bm, account1_contacts=contacts)

        with open(backup_path, encoding="utf-8") as f:
            data = json.load(f)

        acc1_contacts = data["accounts"]["account1"]["contacts"]
        assert len(acc1_contacts) == 1
        assert acc1_contacts[0]["name"] == "John"
        assert acc1_contacts[0]["email"] == "john@example.com"

    def test_create_backup_with_mixed_types(self, bm):
        """Test creating backup with mixed contact types."""

        class MockContact:
            def __init__(self, name):
                self.name = name

        contacts = [
            MockContact("Object Contact"),
            {"name": "Dict Contact"},
        ]

        backup_path = create_backup_helper(bm, account1_contacts=contacts)

        with open(backup_path, encoding="utf-8") as f:
            data = json.load(f)

        acc1_contacts = data["accounts"]["account1"]["contacts"]
        assert len(acc1_contacts) == 2

    def test_create_backup_stores_account_emails(self, bm):
        """Test that account emails are stored in backup."""
        backup_path = create_backup_helper(
            bm,
            account1_email="user1@gmail.com",
            account2_email="user2@gmail.com",
        )

        with open(backup_path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["accounts"]["account1"]["email"] == "user1@gmail.com"
        assert data["accounts"]["account2"]["email"] == "user2@gmail.com"

    def test_create_backup_separates_account_data(self, bm):
        """Test that data from each account is kept separate."""
        acc1_contacts = [{"name": "Account1 Contact"}]
        acc1_groups = [{"name": "Account1 Group"}]
        acc2_contacts = [{"name": "Account2 Contact"}]
        acc2_groups = [{"name": "Account2 Group"}]

        backup_path = create_backup_helper(
            bm,
            account1_contacts=acc1_contacts,
            account1_groups=acc1_groups,
            account2_contacts=acc2_contacts,
            account2_groups=acc2_groups,
        )

        with open(backup_path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["accounts"]["account1"]["contacts"][0]["name"] == "Account1 Contact"
        assert data["accounts"]["account1"]["groups"][0]["name"] == "Account1 Group"
        assert data["accounts"]["account2"]["contacts"][0]["name"] == "Account2 Contact"
        assert data["accounts"]["account2"]["groups"][0]["name"] == "Account2 Group"


class TestBackupListing:
    """Tests for listing backups."""

    @pytest.fixture
    def bm(self, tmp_path):
        """Create a BackupManager instance."""
        return BackupManager(tmp_path / "backups")

    def test_list_backups_empty_directory(self, bm):
        """Test listing backups in empty directory."""
        backups = bm.list_backups()
        assert backups == []

    def test_list_backups_returns_created_backup(self, bm):
        """Test that list_backups returns created backup."""
        backup_path = create_backup_helper(bm)

        backups = bm.list_backups()
        assert len(backups) == 1
        assert backups[0] == backup_path

    def test_list_backups_multiple_backups(self, bm):
        """Test listing multiple backups."""
        create_backup_helper(bm)
        time.sleep(1.1)
        create_backup_helper(bm)
        time.sleep(1.1)
        create_backup_helper(bm)

        backups = bm.list_backups()
        assert len(backups) == 3

    def test_list_backups_sorted_newest_first(self, bm):
        """Test that backups are sorted newest first."""
        backup1 = create_backup_helper(bm)
        time.sleep(1.1)
        backup2 = create_backup_helper(bm)
        time.sleep(1.1)
        backup3 = create_backup_helper(bm)

        backups = bm.list_backups()

        # Newest should be first
        assert backups[0] == backup3
        assert backups[1] == backup2
        assert backups[2] == backup1

    def test_list_backups_ignores_non_backup_files(self, bm, tmp_path):
        """Test that list_backups ignores non-backup files."""
        # Create a backup
        create_backup_helper(bm)

        # Create some non-backup files
        backup_dir = tmp_path / "backups"
        (backup_dir / "other_file.txt").write_text("test")
        (backup_dir / "backup_invalid.txt").write_text("test")
        (backup_dir / "not_a_backup.json").write_text("test")

        backups = bm.list_backups()

        # Should only find the one valid backup
        assert len(backups) == 1
        assert backups[0].name.startswith("backup_")
        assert backups[0].name.endswith(".json")


class TestBackupLoading:
    """Tests for loading backups."""

    @pytest.fixture
    def bm(self, tmp_path):
        """Create a BackupManager instance."""
        return BackupManager(tmp_path / "backups")

    def test_load_backup_returns_backup_data(self, bm):
        """Test loading a valid backup file."""
        contacts = [{"name": "John Doe"}]
        groups = [{"name": "Friends"}]
        backup_path = create_backup_helper(
            bm, account1_contacts=contacts, account1_groups=groups
        )

        data = bm.load_backup(backup_path)

        assert data is not None
        assert "version" in data
        assert "timestamp" in data
        assert "accounts" in data

    def test_load_backup_preserves_data(self, bm):
        """Test that loaded data matches original data."""
        contacts = [{"name": "John Doe", "email": "john@example.com"}]
        groups = [{"name": "Friends", "id": "group1"}]
        backup_path = create_backup_helper(
            bm, account1_contacts=contacts, account1_groups=groups
        )

        data = bm.load_backup(backup_path)

        acc1 = data["accounts"]["account1"]
        assert len(acc1["contacts"]) == 1
        assert acc1["contacts"][0]["name"] == "John Doe"
        assert acc1["contacts"][0]["email"] == "john@example.com"
        assert len(acc1["groups"]) == 1
        assert acc1["groups"][0]["name"] == "Friends"

    def test_load_backup_nonexistent_file(self, bm, tmp_path):
        """Test loading non-existent backup file."""
        nonexistent = tmp_path / "backups" / "nonexistent.json"
        data = bm.load_backup(nonexistent)

        assert data is None

    def test_load_backup_invalid_json(self, bm, tmp_path):
        """Test loading file with invalid JSON."""
        invalid_file = tmp_path / "backups" / "invalid.json"
        invalid_file.write_text("not valid json {{{", encoding="utf-8")

        data = bm.load_backup(invalid_file)

        assert data is None

    def test_load_backup_non_dict_json(self, bm, tmp_path):
        """Test loading file with non-dict JSON."""
        invalid_file = tmp_path / "backups" / "list.json"
        invalid_file.write_text('["list", "not", "dict"]', encoding="utf-8")

        data = bm.load_backup(invalid_file)

        assert data is None

    def test_load_backup_missing_required_fields(self, bm, tmp_path):
        """Test loading backup missing required fields."""
        incomplete_file = tmp_path / "backups" / "incomplete.json"
        incomplete_data = {"timestamp": "2024-01-20T10:00:00"}
        incomplete_file.write_text(json.dumps(incomplete_data), encoding="utf-8")

        data = bm.load_backup(incomplete_file)

        assert data is None

    def test_load_backup_missing_version(self, bm, tmp_path):
        """Test loading backup missing version field."""
        incomplete_file = tmp_path / "backups" / "no_version.json"
        incomplete_data = {"contacts": [], "groups": []}
        incomplete_file.write_text(json.dumps(incomplete_data), encoding="utf-8")

        data = bm.load_backup(incomplete_file)

        assert data is None

    def test_load_backup_with_path_object(self, bm):
        """Test load_backup accepts Path objects."""
        backup_path = create_backup_helper(bm)
        data = bm.load_backup(backup_path)

        assert data is not None
        assert isinstance(backup_path, Path)


class TestRetentionPolicy:
    """Tests for backup retention policy."""

    def test_apply_retention_with_zero_keeps_all(self, tmp_path):
        """Test that retention_count=0 keeps all backups."""
        bm = BackupManager(tmp_path / "backups", retention_count=0)

        # Create 5 backups
        for _ in range(5):
            create_backup_helper(bm)
            time.sleep(1.1)

        backups = bm.list_backups()
        assert len(backups) == 5

    def test_apply_retention_keeps_recent_backups(self, tmp_path):
        """Test that retention keeps most recent backups."""
        bm = BackupManager(tmp_path / "backups", retention_count=3)

        # Create backups
        old1 = create_backup_helper(bm, account1_contacts=[{"name": "old1"}])
        time.sleep(1.1)
        old2 = create_backup_helper(bm, account1_contacts=[{"name": "old2"}])
        time.sleep(1.1)
        new1 = create_backup_helper(bm, account1_contacts=[{"name": "new1"}])
        time.sleep(1.1)
        new2 = create_backup_helper(bm, account1_contacts=[{"name": "new2"}])
        time.sleep(1.1)
        new3 = create_backup_helper(bm, account1_contacts=[{"name": "new3"}])

        # Manually apply retention
        bm.apply_retention()

        backups = bm.list_backups()

        # Should keep 3 most recent
        assert len(backups) == 3
        assert new3 in backups
        assert new2 in backups
        assert new1 in backups
        assert old1 not in backups or not old1.exists()
        assert old2 not in backups or not old2.exists()

    def test_apply_retention_deletes_oldest_first(self, tmp_path):
        """Test that oldest backups are deleted first."""
        bm = BackupManager(tmp_path / "backups", retention_count=2)

        oldest = create_backup_helper(bm)
        time.sleep(1.1)
        middle = create_backup_helper(bm)
        time.sleep(1.1)
        newest = create_backup_helper(bm)

        bm.apply_retention()

        # Oldest should be deleted
        assert not oldest.exists()
        assert middle.exists()
        assert newest.exists()

    def test_apply_retention_with_no_backups(self, tmp_path):
        """Test applying retention with no backups."""
        bm = BackupManager(tmp_path / "backups", retention_count=5)

        # Should not raise
        bm.apply_retention()

        backups = bm.list_backups()
        assert len(backups) == 0

    def test_apply_retention_with_fewer_than_limit(self, tmp_path):
        """Test retention when fewer backups than limit exist."""
        bm = BackupManager(tmp_path / "backups", retention_count=10)

        # Create only 3 backups
        create_backup_helper(bm)
        time.sleep(1.1)
        create_backup_helper(bm)
        time.sleep(1.1)
        create_backup_helper(bm)

        bm.apply_retention()

        # All should remain
        backups = bm.list_backups()
        assert len(backups) == 3


class TestSerialization:
    """Tests for contact and group serialization."""

    @pytest.fixture
    def bm(self, tmp_path):
        """Create a BackupManager instance."""
        return BackupManager(tmp_path / "backups")

    def test_serialize_contacts_with_dicts(self, bm):
        """Test serializing dictionary contacts."""
        contacts = [
            {"name": "John", "email": "john@example.com"},
            {"name": "Jane", "email": "jane@example.com"},
        ]

        result = bm._serialize_contacts(contacts)

        assert len(result) == 2
        assert result[0]["name"] == "John"
        assert result[1]["name"] == "Jane"

    def test_serialize_contacts_with_objects(self, bm):
        """Test serializing contact objects."""

        class MockContact:
            def __init__(self, name, email):
                self.name = name
                self.email = email

        contacts = [MockContact("John", "john@example.com")]

        result = bm._serialize_contacts(contacts)

        assert len(result) == 1
        assert result[0]["name"] == "John"
        assert result[0]["email"] == "john@example.com"

    def test_serialize_contacts_skips_invalid_types(self, bm):
        """Test that invalid contact types are skipped."""
        contacts = [
            {"name": "Valid"},
            "invalid_string",
            123,
            None,
        ]

        result = bm._serialize_contacts(contacts)

        # Only the dict should be included
        assert len(result) == 1
        assert result[0]["name"] == "Valid"

    def test_serialize_groups_with_dicts(self, bm):
        """Test serializing dictionary groups."""
        groups = [
            {"name": "Friends", "id": "group1"},
            {"name": "Family", "id": "group2"},
        ]

        result = bm._serialize_groups(groups)

        assert len(result) == 2
        assert result[0]["name"] == "Friends"
        assert result[1]["name"] == "Family"

    def test_serialize_object_with_datetime(self, bm):
        """Test serializing object with datetime field."""

        class MockObject:
            def __init__(self):
                self.created_at = datetime(2024, 1, 20, 10, 30, 0)
                self.name = "Test"

        obj = MockObject()
        result = bm._serialize_object(obj)

        assert result["name"] == "Test"
        assert result["created_at"] == "2024-01-20T10:30:00"

    def test_serialize_object_with_bytes(self, bm):
        """Test serializing object with bytes field."""
        import base64

        class MockObject:
            def __init__(self):
                self.photo = b"fake_photo_data"
                self.name = "Test"

        obj = MockObject()
        result = bm._serialize_object(obj)

        assert result["name"] == "Test"
        # Should be base64 encoded
        assert result["photo"] == base64.b64encode(b"fake_photo_data").decode("ascii")

    def test_serialize_object_with_none_values(self, bm):
        """Test serializing object with None values."""

        class MockObject:
            def __init__(self):
                self.name = "Test"
                self.email = None
                self.phone = None

        obj = MockObject()
        result = bm._serialize_object(obj)

        assert result["name"] == "Test"
        assert result["email"] is None
        assert result["phone"] is None

    def test_serialize_object_with_primitive_types(self, bm):
        """Test serializing object with various primitive types."""

        class MockObject:
            def __init__(self):
                self.name = "Test"
                self.age = 30
                self.score = 95.5
                self.active = True

        obj = MockObject()
        result = bm._serialize_object(obj)

        assert result["name"] == "Test"
        assert result["age"] == 30
        assert result["score"] == 95.5
        assert result["active"] is True

    def test_serialize_object_with_list_and_dict(self, bm):
        """Test serializing object with list and dict fields."""

        class MockObject:
            def __init__(self):
                self.tags = ["tag1", "tag2"]
                self.metadata = {"key": "value"}

        obj = MockObject()
        result = bm._serialize_object(obj)

        assert result["tags"] == ["tag1", "tag2"]
        assert result["metadata"] == {"key": "value"}

    def test_serialize_object_with_unknown_type(self, bm):
        """Test serializing object with unknown type converts to string."""

        class CustomType:
            def __str__(self):
                return "custom_value"

        class MockObject:
            def __init__(self):
                self.custom = CustomType()

        obj = MockObject()
        result = bm._serialize_object(obj)

        assert result["custom"] == "custom_value"


class TestBackupIntegration:
    """Integration tests for complete backup workflows."""

    def test_full_backup_and_restore_workflow(self, tmp_path):
        """Test complete workflow: create, list, load backup."""
        bm = BackupManager(tmp_path / "backups", retention_count=5)

        # Create backup
        original_contacts = [
            {"name": "John Doe", "email": "john@example.com"},
            {"name": "Jane Smith", "email": "jane@example.com"},
        ]
        original_groups = [
            {"name": "Friends", "id": "group1"},
        ]

        backup_path = create_backup_helper(
            bm,
            account1_contacts=original_contacts,
            account1_groups=original_groups,
            account1_email="user1@gmail.com",
            account2_email="user2@gmail.com",
        )

        # List backups
        backups = bm.list_backups()
        assert len(backups) == 1
        assert backups[0] == backup_path

        # Load backup
        loaded_data = bm.load_backup(backup_path)
        assert loaded_data is not None

        acc1 = loaded_data["accounts"]["account1"]
        assert len(acc1["contacts"]) == 2
        assert len(acc1["groups"]) == 1
        assert acc1["contacts"][0]["name"] == "John Doe"
        assert acc1["groups"][0]["name"] == "Friends"
        assert acc1["email"] == "user1@gmail.com"

    def test_multiple_backups_with_retention(self, tmp_path):
        """Test creating multiple backups with retention policy."""
        bm = BackupManager(tmp_path / "backups", retention_count=3)

        backup_paths = []
        for i in range(5):
            contacts = [{"name": f"Contact {i}"}]
            backup_path = create_backup_helper(bm, account1_contacts=contacts)
            backup_paths.append(backup_path)
            time.sleep(1.1)

        # Should only have 3 most recent backups
        backups = bm.list_backups()
        assert len(backups) == 3

        # Verify the kept backups are the most recent ones
        assert backups[0] == backup_paths[4]
        assert backups[1] == backup_paths[3]
        assert backups[2] == backup_paths[2]
