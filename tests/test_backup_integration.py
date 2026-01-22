"""
Integration tests for backup/restore functionality.

These tests verify end-to-end backup workflows using real BackupManager
instances with Contact and ContactGroup objects (no mocks).

Tests are designed to validate:
- Data integrity through backup/restore cycle
- All Contact and ContactGroup fields are preserved
- Both accounts are properly separated
- Round-trip data matches original
"""

import base64
import json
import time
from datetime import datetime

import pytest

from gcontact_sync.backup.manager import BackupManager
from gcontact_sync.sync.contact import Contact
from gcontact_sync.sync.group import ContactGroup


def create_test_contact(
    resource_name: str = "people/123",
    display_name: str = "John Doe",
    email: str = "john@example.com",
    given_name: str | None = None,
    family_name: str | None = None,
    phones: list[str] | None = None,
    organizations: list[str] | None = None,
    notes: str | None = "Test contact",
    memberships: list[str] | None = None,
    photo_data: bytes | None = None,
    photo_url: str | None = None,
) -> Contact:
    """Create a test Contact object with configurable fields."""
    return Contact(
        resource_name=resource_name,
        etag=f"etag_{resource_name}",
        display_name=display_name,
        given_name=given_name,
        family_name=family_name,
        emails=[email] if email else [],
        phones=phones or [],
        organizations=organizations or [],
        notes=notes,
        last_modified=datetime.now(),
        photo_url=photo_url,
        photo_data=photo_data,
        photo_etag=f"photo_etag_{resource_name}" if photo_data else None,
        memberships=memberships or [],
        deleted=False,
    )


def create_test_group(
    resource_name: str = "contactGroups/456",
    name: str = "Test Group",
    member_count: int = 0,
    member_resource_names: list[str] | None = None,
) -> ContactGroup:
    """Create a test ContactGroup object with configurable fields."""
    return ContactGroup(
        resource_name=resource_name,
        name=name,
        etag=f"etag_{resource_name}",
        group_type="USER_CONTACT_GROUP",
        member_count=member_count,
        member_resource_names=member_resource_names or [],
    )


def create_backup_v2(
    manager: BackupManager,
    account1_contacts: list[Contact] | None = None,
    account1_groups: list[ContactGroup] | None = None,
    account2_contacts: list[Contact] | None = None,
    account2_groups: list[ContactGroup] | None = None,
    account1_email: str = "account1@example.com",
    account2_email: str = "account2@example.com",
):
    """Helper to create a v2.0 backup with proper account structure."""
    return manager.create_backup(
        account1_contacts=account1_contacts or [],
        account1_groups=account1_groups or [],
        account2_contacts=account2_contacts or [],
        account2_groups=account2_groups or [],
        account1_email=account1_email,
        account2_email=account2_email,
    )


@pytest.mark.integration
class TestBackupCreationIntegration:
    """Integration tests for backup creation with real Contact objects."""

    def test_backup_creates_file_with_contact_objects(self, tmp_path):
        """Test that backup correctly serializes real Contact objects."""
        backup_dir = tmp_path / "backups"
        manager = BackupManager(backup_dir, retention_count=10)

        acc1_contacts = [
            create_test_contact("people/1", "John Doe", "john@example.com"),
            create_test_contact("people/2", "Jane Smith", "jane@example.com"),
        ]
        acc1_groups = [
            create_test_group("contactGroups/1", "Friends"),
            create_test_group("contactGroups/2", "Family"),
        ]

        backup_file = create_backup_v2(
            manager,
            account1_contacts=acc1_contacts,
            account1_groups=acc1_groups,
        )

        assert backup_file is not None
        assert backup_file.exists()
        assert backup_file.parent == backup_dir

    def test_backup_preserves_contact_data_for_account1(self, tmp_path):
        """Test that all Contact fields are preserved in backup for account1."""
        backup_dir = tmp_path / "backups"
        manager = BackupManager(backup_dir, retention_count=10)

        contact = Contact(
            resource_name="people/123",
            etag="etag1",
            display_name="Jane Smith",
            given_name="Jane",
            family_name="Smith",
            emails=["jane@example.com", "jane.smith@work.com"],
            phones=["+1234567890"],
            organizations=["Example Corp"],
            notes="Important contact with notes",
            last_modified=datetime.now(),
            photo_url="https://example.com/photo.jpg",
            photo_data=b"fake_photo_data",
            photo_etag="photo_etag",
            memberships=["contactGroups/789"],
            deleted=False,
        )
        group = create_test_group("contactGroups/789", "VIP Group")

        backup_file = create_backup_v2(
            manager,
            account1_contacts=[contact],
            account1_groups=[group],
            account1_email="jane@gmail.com",
        )

        with open(backup_file, encoding="utf-8") as f:
            data = json.load(f)

        assert data["version"] == "2.0"
        assert "timestamp" in data
        assert "accounts" in data
        assert "account1" in data["accounts"]

        acc1 = data["accounts"]["account1"]
        assert acc1["email"] == "jane@gmail.com"
        assert len(acc1["contacts"]) == 1

        saved_contact = acc1["contacts"][0]
        assert saved_contact["display_name"] == "Jane Smith"
        assert saved_contact["given_name"] == "Jane"
        assert saved_contact["family_name"] == "Smith"
        assert saved_contact["emails"] == ["jane@example.com", "jane.smith@work.com"]
        assert saved_contact["phones"] == ["+1234567890"]
        assert saved_contact["organizations"] == ["Example Corp"]
        assert saved_contact["notes"] == "Important contact with notes"
        assert saved_contact["photo_url"] == "https://example.com/photo.jpg"
        assert saved_contact["photo_data"] is not None  # Base64 encoded
        assert saved_contact["memberships"] == ["contactGroups/789"]

        assert len(acc1["groups"]) == 1
        saved_group = acc1["groups"][0]
        assert saved_group["name"] == "VIP Group"
        assert saved_group["resource_name"] == "contactGroups/789"

    def test_backup_preserves_both_accounts_separately(self, tmp_path):
        """Test that data from both accounts is preserved and separated."""
        backup_dir = tmp_path / "backups"
        manager = BackupManager(backup_dir, retention_count=10)

        # Account 1 data
        acc1_contacts = [
            create_test_contact("people/acc1_1", "Account1 Contact", "acc1@example.com")
        ]
        acc1_groups = [create_test_group("contactGroups/acc1_g1", "Account1 Group")]

        # Account 2 data
        acc2_contacts = [
            create_test_contact("people/acc2_1", "Account2 Contact", "acc2@example.com")
        ]
        acc2_groups = [create_test_group("contactGroups/acc2_g1", "Account2 Group")]

        backup_file = create_backup_v2(
            manager,
            account1_contacts=acc1_contacts,
            account1_groups=acc1_groups,
            account2_contacts=acc2_contacts,
            account2_groups=acc2_groups,
            account1_email="user1@gmail.com",
            account2_email="user2@gmail.com",
        )

        with open(backup_file, encoding="utf-8") as f:
            data = json.load(f)

        # Verify account1
        acc1 = data["accounts"]["account1"]
        assert acc1["email"] == "user1@gmail.com"
        assert len(acc1["contacts"]) == 1
        assert acc1["contacts"][0]["display_name"] == "Account1 Contact"
        assert len(acc1["groups"]) == 1
        assert acc1["groups"][0]["name"] == "Account1 Group"

        # Verify account2
        acc2 = data["accounts"]["account2"]
        assert acc2["email"] == "user2@gmail.com"
        assert len(acc2["contacts"]) == 1
        assert acc2["contacts"][0]["display_name"] == "Account2 Contact"
        assert len(acc2["groups"]) == 1
        assert acc2["groups"][0]["name"] == "Account2 Group"


@pytest.mark.integration
class TestBackupListingIntegration:
    """Integration tests for listing multiple backups."""

    def test_list_multiple_backups_sorted_by_time(self, tmp_path):
        """Test that multiple backups are listed newest first."""
        backup_dir = tmp_path / "backups"
        manager = BackupManager(backup_dir, retention_count=10)

        backup_files = []
        for i in range(3):
            contact = create_test_contact(f"people/{i}", f"Contact {i}")
            backup_file = create_backup_v2(manager, account1_contacts=[contact])
            backup_files.append(backup_file)
            time.sleep(1.1)  # Ensure unique timestamps

        backups = manager.list_backups()

        assert len(backups) == 3
        # Newest should be first
        assert backups[0] == backup_files[2]
        assert backups[1] == backup_files[1]
        assert backups[2] == backup_files[0]


@pytest.mark.integration
class TestBackupRestoreIntegration:
    """Integration tests for the complete backup/restore workflow."""

    def test_backup_and_restore_preserves_all_contact_fields(self, tmp_path):
        """Test that ALL Contact fields survive a backup and restore cycle."""
        backup_dir = tmp_path / "backups"
        manager = BackupManager(backup_dir, retention_count=10)

        # Create a contact with ALL fields populated
        original_contact = Contact(
            resource_name="people/full_test",
            etag="etag_full",
            display_name="Full Test Contact",
            given_name="Full",
            family_name="Contact",
            emails=["full@example.com", "full.contact@work.com"],
            phones=["+1-555-1234", "+1-555-5678"],
            organizations=["Acme Inc", "Side Project LLC"],
            notes=(
                "This is a detailed note\nwith multiple lines\n"
                "and special chars: é ñ 中文"
            ),
            last_modified=datetime(2024, 6, 15, 10, 30, 0),
            photo_url="https://example.com/photo.jpg",
            photo_data=b"binary_photo_data_here",
            photo_etag="photo_etag_full",
            memberships=["contactGroups/friends", "contactGroups/work"],
            deleted=False,
        )

        # Create backup
        backup_file = create_backup_v2(
            manager,
            account1_contacts=[original_contact],
            account1_email="test@gmail.com",
        )
        assert backup_file.exists()

        # Load backup
        restored_data = manager.load_backup(backup_file)

        assert restored_data is not None
        assert restored_data["version"] == "2.0"

        # Get the restored contact
        acc1 = restored_data["accounts"]["account1"]
        assert len(acc1["contacts"]) == 1
        restored = acc1["contacts"][0]

        # Verify ALL fields
        assert restored["resource_name"] == "people/full_test"
        assert restored["etag"] == "etag_full"
        assert restored["display_name"] == "Full Test Contact"
        assert restored["given_name"] == "Full"
        assert restored["family_name"] == "Contact"
        assert restored["emails"] == ["full@example.com", "full.contact@work.com"]
        assert restored["phones"] == ["+1-555-1234", "+1-555-5678"]
        assert restored["organizations"] == ["Acme Inc", "Side Project LLC"]
        expected_notes = (
            "This is a detailed note\nwith multiple lines\nand special chars: é ñ 中文"
        )
        assert restored["notes"] == expected_notes
        assert restored["last_modified"] == "2024-06-15T10:30:00"
        assert restored["photo_url"] == "https://example.com/photo.jpg"
        # Photo data should be base64 encoded
        assert restored["photo_data"] == base64.b64encode(
            b"binary_photo_data_here"
        ).decode("ascii")
        assert restored["photo_etag"] == "photo_etag_full"
        assert restored["memberships"] == [
            "contactGroups/friends",
            "contactGroups/work",
        ]
        assert restored["deleted"] is False

    def test_backup_and_restore_preserves_all_group_fields(self, tmp_path):
        """Test that ALL ContactGroup fields survive a backup and restore cycle."""
        backup_dir = tmp_path / "backups"
        manager = BackupManager(backup_dir, retention_count=10)

        # Create a group with ALL fields populated
        original_group = ContactGroup(
            resource_name="contactGroups/full_test",
            etag="group_etag_full",
            name="Full Test Group",
            group_type="USER_CONTACT_GROUP",
            member_count=5,
            member_resource_names=["people/1", "people/2", "people/3"],
            formatted_name="Full Test Group (Formatted)",
            deleted=False,
        )

        # Create backup
        backup_file = create_backup_v2(
            manager,
            account1_groups=[original_group],
            account1_email="test@gmail.com",
        )
        assert backup_file.exists()

        # Load backup
        restored_data = manager.load_backup(backup_file)

        assert restored_data is not None
        acc1 = restored_data["accounts"]["account1"]
        assert len(acc1["groups"]) == 1
        restored = acc1["groups"][0]

        # Verify ALL fields
        assert restored["resource_name"] == "contactGroups/full_test"
        assert restored["etag"] == "group_etag_full"
        assert restored["name"] == "Full Test Group"
        assert restored["group_type"] == "USER_CONTACT_GROUP"
        assert restored["member_count"] == 5
        assert restored["member_resource_names"] == ["people/1", "people/2", "people/3"]
        assert restored["formatted_name"] == "Full Test Group (Formatted)"
        assert restored["deleted"] is False

    def test_backup_and_restore_both_accounts_complete(self, tmp_path):
        """Test complete backup/restore cycle with both accounts populated."""
        backup_dir = tmp_path / "backups"
        manager = BackupManager(backup_dir, retention_count=10)

        # Account 1: Multiple contacts and groups
        acc1_contacts = [
            Contact(
                resource_name="people/acc1_john",
                etag="etag1",
                display_name="John Doe",
                emails=["john@example.com"],
                phones=["+1-555-1234"],
                organizations=["Acme Inc"],
                notes="Primary contact",
                last_modified=datetime(2024, 6, 15, 10, 30, 0),
                photo_data=b"john_photo",
                memberships=["contactGroups/friends"],
            ),
            Contact(
                resource_name="people/acc1_jane",
                etag="etag2",
                display_name="Jane Smith",
                emails=["jane@example.com", "jsmith@work.com"],
                phones=[],
                organizations=[],
                notes="",
                last_modified=datetime(2024, 6, 16, 14, 0, 0),
                photo_url="https://example.com/jane.jpg",
                memberships=["contactGroups/family", "contactGroups/friends"],
            ),
        ]
        acc1_groups = [
            ContactGroup(
                resource_name="contactGroups/friends",
                name="Friends",
                etag="g_etag1",
                group_type="USER_CONTACT_GROUP",
                member_count=2,
            ),
            ContactGroup(
                resource_name="contactGroups/family",
                name="Family",
                etag="g_etag2",
                group_type="USER_CONTACT_GROUP",
            ),
        ]

        # Account 2: Different contacts and groups
        acc2_contacts = [
            Contact(
                resource_name="people/acc2_bob",
                etag="etag3",
                display_name="Bob Wilson",
                emails=["bob@other.com"],
                phones=["+1-555-9999"],
                notes="Account 2 contact",
                last_modified=datetime(2024, 7, 1, 8, 0, 0),
            ),
        ]
        acc2_groups = [
            ContactGroup(
                resource_name="contactGroups/work",
                name="Work",
                etag="g_etag3",
                group_type="USER_CONTACT_GROUP",
            ),
        ]

        # Create backup
        backup_file = create_backup_v2(
            manager,
            account1_contacts=acc1_contacts,
            account1_groups=acc1_groups,
            account2_contacts=acc2_contacts,
            account2_groups=acc2_groups,
            account1_email="user1@gmail.com",
            account2_email="user2@gmail.com",
        )
        assert backup_file.exists()

        # Load backup
        restored_data = manager.load_backup(backup_file)

        assert restored_data is not None
        assert restored_data["version"] == "2.0"
        assert "timestamp" in restored_data

        # Verify account 1
        acc1 = restored_data["accounts"]["account1"]
        assert acc1["email"] == "user1@gmail.com"
        assert len(acc1["contacts"]) == 2
        assert len(acc1["groups"]) == 2

        john = next(c for c in acc1["contacts"] if c["display_name"] == "John Doe")
        assert john["emails"] == ["john@example.com"]
        assert john["phones"] == ["+1-555-1234"]
        assert john["organizations"] == ["Acme Inc"]
        assert john["notes"] == "Primary contact"
        assert john["photo_data"] is not None  # Base64 encoded

        jane = next(c for c in acc1["contacts"] if c["display_name"] == "Jane Smith")
        assert jane["emails"] == ["jane@example.com", "jsmith@work.com"]
        assert jane["memberships"] == ["contactGroups/family", "contactGroups/friends"]

        group_names = {g["name"] for g in acc1["groups"]}
        assert group_names == {"Friends", "Family"}

        # Verify account 2
        acc2 = restored_data["accounts"]["account2"]
        assert acc2["email"] == "user2@gmail.com"
        assert len(acc2["contacts"]) == 1
        assert len(acc2["groups"]) == 1

        bob = acc2["contacts"][0]
        assert bob["display_name"] == "Bob Wilson"
        assert bob["emails"] == ["bob@other.com"]
        assert bob["phones"] == ["+1-555-9999"]

        assert acc2["groups"][0]["name"] == "Work"

    def test_backup_handles_empty_and_none_fields(self, tmp_path):
        """Test that empty lists, empty strings, and None values are preserved."""
        backup_dir = tmp_path / "backups"
        manager = BackupManager(backup_dir, retention_count=10)

        # Contact with minimal data (many fields empty/None)
        minimal_contact = Contact(
            resource_name="people/minimal",
            etag="etag_min",
            display_name="Minimal Contact",
            given_name=None,
            family_name=None,
            emails=[],
            phones=[],
            organizations=[],
            notes=None,
            last_modified=None,
            photo_url=None,
            photo_data=None,
            photo_etag=None,
            memberships=[],
            deleted=False,
        )

        backup_file = create_backup_v2(
            manager,
            account1_contacts=[minimal_contact],
        )

        restored_data = manager.load_backup(backup_file)
        acc1 = restored_data["accounts"]["account1"]
        restored = acc1["contacts"][0]

        assert restored["display_name"] == "Minimal Contact"
        assert restored["given_name"] is None
        assert restored["family_name"] is None
        assert restored["emails"] == []
        assert restored["phones"] == []
        assert restored["organizations"] == []
        assert restored["notes"] is None
        assert restored["last_modified"] is None
        assert restored["photo_url"] is None
        assert restored["photo_data"] is None
        assert restored["photo_etag"] is None
        assert restored["memberships"] == []
        assert restored["deleted"] is False

    def test_backup_handles_unicode_and_special_characters(self, tmp_path):
        """Test that unicode and special characters are preserved correctly."""
        backup_dir = tmp_path / "backups"
        manager = BackupManager(backup_dir, retention_count=10)

        unicode_contact = Contact(
            resource_name="people/unicode",
            etag="etag_unicode",
            display_name="José García 田中太郎",
            given_name="José",
            family_name="García 田中",
            emails=["josé@example.com"],
            phones=["+1-555-1234"],
            organizations=["Société Générale", "日本株式会社"],
            notes="Notes with emojis 🎉 and special chars: é ñ ü ß 中文 日本語 한국어",
            last_modified=datetime.now(),
        )

        backup_file = create_backup_v2(
            manager,
            account1_contacts=[unicode_contact],
        )

        restored_data = manager.load_backup(backup_file)
        acc1 = restored_data["accounts"]["account1"]
        restored = acc1["contacts"][0]

        assert restored["display_name"] == "José García 田中太郎"
        assert restored["given_name"] == "José"
        assert restored["family_name"] == "García 田中"
        assert restored["emails"] == ["josé@example.com"]
        assert restored["organizations"] == ["Société Générale", "日本株式会社"]
        assert "emojis 🎉" in restored["notes"]
        assert "中文 日本語 한국어" in restored["notes"]


@pytest.mark.integration
class TestRetentionPolicyIntegration:
    """Integration tests for backup retention policy."""

    def test_retention_deletes_oldest_backups(self, tmp_path):
        """Test that retention policy keeps only the newest backups."""
        backup_dir = tmp_path / "backups"
        retention_count = 5
        manager = BackupManager(backup_dir, retention_count=retention_count)

        # Create more backups than retention allows
        created_backups = []
        for i in range(8):
            contact = create_test_contact(f"people/{i}", f"Contact {i}")
            backup_file = create_backup_v2(manager, account1_contacts=[contact])
            created_backups.append(backup_file)
            time.sleep(1.1)  # Ensure unique timestamps

        # Verify only retention_count backups remain
        remaining_backups = manager.list_backups()
        assert len(remaining_backups) == retention_count

        # Verify the newest backups are kept
        for i in range(retention_count):
            assert created_backups[-(i + 1)] in remaining_backups

        # Verify the oldest backups are deleted
        for i in range(3):  # 8 - 5 = 3 deleted
            assert not created_backups[i].exists()

    def test_retention_zero_keeps_all_backups(self, tmp_path):
        """Test that retention_count=0 keeps all backups (unlimited)."""
        backup_dir = tmp_path / "backups"
        manager = BackupManager(backup_dir, retention_count=0)

        # Create several backups
        for i in range(5):
            contact = create_test_contact(f"people/{i}", f"Contact {i}")
            create_backup_v2(manager, account1_contacts=[contact])
            time.sleep(1.1)

        # All backups should remain
        backups = manager.list_backups()
        assert len(backups) == 5


@pytest.mark.integration
class TestRoundTripValidation:
    """
    Comprehensive round-trip validation tests.

    These tests ensure that backup data can be used to reconstruct
    Contact and ContactGroup objects with all data intact.
    """

    def test_contact_round_trip_field_by_field(self, tmp_path):
        """Verify every Contact field survives round-trip exactly."""
        backup_dir = tmp_path / "backups"
        manager = BackupManager(backup_dir)

        # Define expected values for each field
        expected = {
            "resource_name": "people/roundtrip_test",
            "etag": "etag_rt",
            "display_name": "Round Trip Test",
            "given_name": "Round",
            "family_name": "Trip",
            "emails": ["rt@example.com", "roundtrip@work.com"],
            "phones": ["+1-555-0001", "+1-555-0002"],
            "organizations": ["Org One", "Org Two"],
            "notes": "Test notes with\nmultiline\ncontent",
            "last_modified": datetime(2024, 3, 15, 12, 30, 45),
            "photo_url": "https://example.com/photo.png",
            "photo_data": b"\x89PNG\r\n\x1a\n\x00\x00\x00",  # Fake PNG header
            "photo_etag": "photo_etag_rt",
            "memberships": ["contactGroups/g1", "contactGroups/g2"],
            "deleted": False,
        }

        original = Contact(**expected)

        # Backup and restore
        backup_file = create_backup_v2(manager, account1_contacts=[original])
        restored_data = manager.load_backup(backup_file)
        restored = restored_data["accounts"]["account1"]["contacts"][0]

        # Verify each field
        assert restored["resource_name"] == expected["resource_name"]
        assert restored["etag"] == expected["etag"]
        assert restored["display_name"] == expected["display_name"]
        assert restored["given_name"] == expected["given_name"]
        assert restored["family_name"] == expected["family_name"]
        assert restored["emails"] == expected["emails"]
        assert restored["phones"] == expected["phones"]
        assert restored["organizations"] == expected["organizations"]
        assert restored["notes"] == expected["notes"]
        assert restored["last_modified"] == expected["last_modified"].isoformat()
        assert restored["photo_url"] == expected["photo_url"]
        assert restored["photo_data"] == base64.b64encode(
            expected["photo_data"]
        ).decode("ascii")
        assert restored["photo_etag"] == expected["photo_etag"]
        assert restored["memberships"] == expected["memberships"]
        assert restored["deleted"] == expected["deleted"]

    def test_group_round_trip_field_by_field(self, tmp_path):
        """Verify every ContactGroup field survives round-trip exactly."""
        backup_dir = tmp_path / "backups"
        manager = BackupManager(backup_dir)

        # Define expected values for each field
        expected = {
            "resource_name": "contactGroups/roundtrip_group",
            "etag": "group_etag_rt",
            "name": "Round Trip Group",
            "group_type": "USER_CONTACT_GROUP",
            "member_count": 42,
            "member_resource_names": ["people/m1", "people/m2", "people/m3"],
            "formatted_name": "Round Trip Group (Formatted)",
            "deleted": False,
        }

        original = ContactGroup(**expected)

        # Backup and restore
        backup_file = create_backup_v2(manager, account1_groups=[original])
        restored_data = manager.load_backup(backup_file)
        restored = restored_data["accounts"]["account1"]["groups"][0]

        # Verify each field
        assert restored["resource_name"] == expected["resource_name"]
        assert restored["etag"] == expected["etag"]
        assert restored["name"] == expected["name"]
        assert restored["group_type"] == expected["group_type"]
        assert restored["member_count"] == expected["member_count"]
        assert restored["member_resource_names"] == expected["member_resource_names"]
        assert restored["formatted_name"] == expected["formatted_name"]
        assert restored["deleted"] == expected["deleted"]

    def test_large_backup_with_many_contacts(self, tmp_path):
        """Test backup with many contacts to ensure scalability."""
        backup_dir = tmp_path / "backups"
        manager = BackupManager(backup_dir)

        # Create 100 contacts for each account
        acc1_contacts = [
            create_test_contact(
                resource_name=f"people/acc1_{i}",
                display_name=f"Account1 Contact {i}",
                email=f"acc1_contact{i}@example.com",
                phones=[f"+1-555-{i:04d}"],
                notes=f"Notes for contact {i}",
            )
            for i in range(100)
        ]
        acc2_contacts = [
            create_test_contact(
                resource_name=f"people/acc2_{i}",
                display_name=f"Account2 Contact {i}",
                email=f"acc2_contact{i}@example.com",
            )
            for i in range(100)
        ]

        # Create 10 groups for each account
        acc1_groups = [
            create_test_group(
                resource_name=f"contactGroups/acc1_g{i}",
                name=f"Account1 Group {i}",
            )
            for i in range(10)
        ]
        acc2_groups = [
            create_test_group(
                resource_name=f"contactGroups/acc2_g{i}",
                name=f"Account2 Group {i}",
            )
            for i in range(10)
        ]

        # Backup
        backup_file = create_backup_v2(
            manager,
            account1_contacts=acc1_contacts,
            account1_groups=acc1_groups,
            account2_contacts=acc2_contacts,
            account2_groups=acc2_groups,
            account1_email="user1@gmail.com",
            account2_email="user2@gmail.com",
        )

        # Verify file exists and is reasonable size
        assert backup_file.exists()
        file_size = backup_file.stat().st_size
        assert file_size > 0

        # Load and verify counts
        restored_data = manager.load_backup(backup_file)

        acc1 = restored_data["accounts"]["account1"]
        assert len(acc1["contacts"]) == 100
        assert len(acc1["groups"]) == 10

        acc2 = restored_data["accounts"]["account2"]
        assert len(acc2["contacts"]) == 100
        assert len(acc2["groups"]) == 10

        # Spot check a few contacts
        acc1_c50 = next(
            c for c in acc1["contacts"] if c["resource_name"] == "people/acc1_50"
        )
        assert acc1_c50["display_name"] == "Account1 Contact 50"
        assert acc1_c50["emails"] == ["acc1_contact50@example.com"]

        acc2_c75 = next(
            c for c in acc2["contacts"] if c["resource_name"] == "people/acc2_75"
        )
        assert acc2_c75["display_name"] == "Account2 Contact 75"
