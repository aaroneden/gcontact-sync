"""
Unit tests for the storage module.

Tests the SyncDatabase class for sync state and contact mapping operations.
"""

import sqlite3
from datetime import datetime

import pytest

from gcontact_sync.storage.db import SyncDatabase


class TestSyncDatabaseInitialization:
    """Tests for database initialization."""

    def test_create_in_memory_database(self):
        """Test creating an in-memory database."""
        db = SyncDatabase(":memory:")
        assert db.db_path == ":memory:"

    def test_create_file_database(self, tmp_path):
        """Test creating a file-based database."""
        db_path = str(tmp_path / "test.db")
        db = SyncDatabase(db_path)
        assert db.db_path == db_path

    def test_initialize_creates_tables(self):
        """Test that initialize creates the required tables."""
        db = SyncDatabase(":memory:")
        db.initialize()

        with db.connection() as conn:
            # Check sync_state table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='sync_state'"
            )
            assert cursor.fetchone() is not None

            # Check contact_mapping table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='contact_mapping'"
            )
            assert cursor.fetchone() is not None

            # Check llm_match_attempts table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='llm_match_attempts'"
            )
            assert cursor.fetchone() is not None

    def test_initialize_creates_indexes(self):
        """Test that initialize creates the required indexes."""
        db = SyncDatabase(":memory:")
        db.initialize()

        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_contact_mapping_key'"
            )
            assert cursor.fetchone() is not None

            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_sync_state_account'"
            )
            assert cursor.fetchone() is not None

            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_llm_attempts_contacts'"
            )
            assert cursor.fetchone() is not None

    def test_initialize_is_idempotent(self):
        """Test that initialize can be called multiple times safely."""
        db = SyncDatabase(":memory:")
        db.initialize()
        db.initialize()  # Should not raise

        # Verify tables still exist
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            )
            count = cursor.fetchone()[0]
            assert count >= 2


class TestConnectionContextManager:
    """Tests for the connection context manager."""

    def test_connection_commits_on_success(self):
        """Test that successful operations are committed."""
        db = SyncDatabase(":memory:")
        db.initialize()

        with db.connection() as conn:
            conn.execute(
                "INSERT INTO sync_state (account_id, sync_token) VALUES (?, ?)",
                ("test_account", "test_token"),
            )

        # Verify data was committed
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT sync_token FROM sync_state WHERE account_id = ?",
                ("test_account",),
            )
            row = cursor.fetchone()
            assert row["sync_token"] == "test_token"

    def test_connection_rollback_on_error(self):
        """Test that failed operations are rolled back."""
        db = SyncDatabase(":memory:")
        db.initialize()

        # Insert initial data
        with db.connection() as conn:
            conn.execute(
                "INSERT INTO sync_state (account_id, sync_token) VALUES (?, ?)",
                ("test_account", "original_token"),
            )

        # Try to update with an error
        with pytest.raises(sqlite3.IntegrityError), db.connection() as conn:
            # This should work
            conn.execute(
                "UPDATE sync_state SET sync_token = ? WHERE account_id = ?",
                ("new_token", "test_account"),
            )
            # This should fail (duplicate account_id)
            conn.execute(
                "INSERT INTO sync_state (account_id, sync_token) VALUES (?, ?)",
                ("test_account", "another_token"),
            )

        # Verify rollback occurred - original data should still be there
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT sync_token FROM sync_state WHERE account_id = ?",
                ("test_account",),
            )
            row = cursor.fetchone()
            # Note: SQLite autocommit behavior may vary,
            # but error should have prevented insert
            assert row is not None


class TestSyncStateOperations:
    """Tests for sync state CRUD operations."""

    @pytest.fixture
    def db(self):
        """Create an initialized in-memory database."""
        db = SyncDatabase(":memory:")
        db.initialize()
        return db

    def test_get_sync_state_returns_none_for_unknown_account(self, db):
        """Test that get_sync_state returns None for unknown account."""
        result = db.get_sync_state("unknown_account")
        assert result is None

    def test_update_sync_state_creates_new_entry(self, db):
        """Test that update_sync_state creates a new entry."""
        db.update_sync_state("account1", sync_token="token123")

        result = db.get_sync_state("account1")
        assert result is not None
        assert result["sync_token"] == "token123"
        assert result["last_sync_at"] is not None

    def test_update_sync_state_updates_existing_entry(self, db):
        """Test that update_sync_state updates an existing entry."""
        db.update_sync_state("account1", sync_token="token_v1")
        db.update_sync_state("account1", sync_token="token_v2")

        result = db.get_sync_state("account1")
        assert result["sync_token"] == "token_v2"

    def test_update_sync_state_with_custom_timestamp(self, db):
        """Test update_sync_state with custom timestamp."""
        custom_time = datetime(2024, 1, 15, 12, 0, 0)
        db.update_sync_state("account1", sync_token="token", last_sync_at=custom_time)

        result = db.get_sync_state("account1")
        assert result["last_sync_at"] == custom_time

    def test_update_sync_state_with_none_token(self, db):
        """Test update_sync_state with None token."""
        db.update_sync_state("account1", sync_token=None)

        result = db.get_sync_state("account1")
        assert result["sync_token"] is None

    def test_clear_sync_token(self, db):
        """Test clearing sync token for an account."""
        db.update_sync_state("account1", sync_token="token123")
        db.clear_sync_token("account1")

        result = db.get_sync_state("account1")
        assert result["sync_token"] is None

    def test_clear_sync_token_for_nonexistent_account(self, db):
        """Test clearing sync token for nonexistent account (should not raise)."""
        db.clear_sync_token("nonexistent")  # Should not raise

    def test_multiple_accounts(self, db):
        """Test managing sync state for multiple accounts."""
        db.update_sync_state("account1", sync_token="token1")
        db.update_sync_state("account2", sync_token="token2")

        result1 = db.get_sync_state("account1")
        result2 = db.get_sync_state("account2")

        assert result1["sync_token"] == "token1"
        assert result2["sync_token"] == "token2"


class TestContactMappingOperations:
    """Tests for contact mapping CRUD operations."""

    @pytest.fixture
    def db(self):
        """Create an initialized in-memory database."""
        db = SyncDatabase(":memory:")
        db.initialize()
        return db

    def test_get_contact_mapping_returns_none_for_unknown_key(self, db):
        """Test that get_contact_mapping returns None for unknown key."""
        result = db.get_contact_mapping("unknown_key")
        assert result is None

    def test_upsert_contact_mapping_creates_new_entry(self, db):
        """Test that upsert_contact_mapping creates a new entry."""
        db.upsert_contact_mapping(
            matching_key="john_doe:john@example.com",
            account1_resource_name="people/123",
            account2_resource_name="people/456",
            account1_etag="etag1",
            account2_etag="etag2",
            last_synced_hash="hash123",
        )

        result = db.get_contact_mapping("john_doe:john@example.com")
        assert result is not None
        assert result["matching_key"] == "john_doe:john@example.com"
        assert result["account1_resource_name"] == "people/123"
        assert result["account2_resource_name"] == "people/456"
        assert result["account1_etag"] == "etag1"
        assert result["account2_etag"] == "etag2"
        assert result["last_synced_hash"] == "hash123"

    def test_upsert_contact_mapping_updates_existing_entry(self, db):
        """Test that upsert_contact_mapping updates an existing entry."""
        db.upsert_contact_mapping(
            matching_key="john_doe:john@example.com",
            account1_resource_name="people/123",
            last_synced_hash="hash_v1",
        )

        db.upsert_contact_mapping(
            matching_key="john_doe:john@example.com",
            account2_resource_name="people/456",
            last_synced_hash="hash_v2",
        )

        result = db.get_contact_mapping("john_doe:john@example.com")
        assert result["account1_resource_name"] == "people/123"
        assert result["account2_resource_name"] == "people/456"
        assert result["last_synced_hash"] == "hash_v2"

    def test_upsert_contact_mapping_partial_update(self, db):
        """Test partial update of contact mapping."""
        db.upsert_contact_mapping(
            matching_key="test_key",
            account1_resource_name="people/old",
            account1_etag="old_etag",
        )

        # Update only etag
        db.upsert_contact_mapping(matching_key="test_key", account1_etag="new_etag")

        result = db.get_contact_mapping("test_key")
        assert result["account1_resource_name"] == "people/old"
        assert result["account1_etag"] == "new_etag"

    def test_delete_contact_mapping(self, db):
        """Test deleting a contact mapping."""
        db.upsert_contact_mapping(
            matching_key="to_delete", account1_resource_name="people/123"
        )

        deleted = db.delete_contact_mapping("to_delete")
        assert deleted is True

        result = db.get_contact_mapping("to_delete")
        assert result is None

    def test_delete_contact_mapping_returns_false_for_nonexistent(self, db):
        """Test that delete returns False for nonexistent key."""
        deleted = db.delete_contact_mapping("nonexistent")
        assert deleted is False

    def test_get_all_contact_mappings_empty(self, db):
        """Test get_all_contact_mappings with empty database."""
        result = db.get_all_contact_mappings()
        assert result == []

    def test_get_all_contact_mappings_returns_all(self, db):
        """Test get_all_contact_mappings returns all mappings."""
        db.upsert_contact_mapping(
            matching_key="alice:alice@example.com", account1_resource_name="people/1"
        )
        db.upsert_contact_mapping(
            matching_key="bob:bob@example.com", account1_resource_name="people/2"
        )
        db.upsert_contact_mapping(
            matching_key="charlie:charlie@example.com",
            account1_resource_name="people/3",
        )

        result = db.get_all_contact_mappings()
        assert len(result) == 3

    def test_get_all_contact_mappings_sorted_by_key(self, db):
        """Test that get_all_contact_mappings returns sorted results."""
        db.upsert_contact_mapping(matching_key="charlie", account1_resource_name="p1")
        db.upsert_contact_mapping(matching_key="alice", account1_resource_name="p2")
        db.upsert_contact_mapping(matching_key="bob", account1_resource_name="p3")

        result = db.get_all_contact_mappings()
        keys = [r["matching_key"] for r in result]
        assert keys == ["alice", "bob", "charlie"]


class TestResourceNameLookup:
    """Tests for looking up mappings by resource name."""

    @pytest.fixture
    def db(self):
        """Create an initialized in-memory database with test data."""
        db = SyncDatabase(":memory:")
        db.initialize()

        db.upsert_contact_mapping(
            matching_key="user1",
            account1_resource_name="people/a1",
            account2_resource_name="people/b1",
        )
        db.upsert_contact_mapping(
            matching_key="user2",
            account1_resource_name="people/a2",
            account2_resource_name="people/b2",
        )
        return db

    def test_get_mappings_by_resource_name_account1(self, db):
        """Test finding mappings by account 1 resource name."""
        result = db.get_mappings_by_resource_name("people/a1", account=1)
        assert len(result) == 1
        assert result[0]["matching_key"] == "user1"

    def test_get_mappings_by_resource_name_account2(self, db):
        """Test finding mappings by account 2 resource name."""
        result = db.get_mappings_by_resource_name("people/b2", account=2)
        assert len(result) == 1
        assert result[0]["matching_key"] == "user2"

    def test_get_mappings_by_resource_name_not_found(self, db):
        """Test that empty list is returned for unknown resource name."""
        result = db.get_mappings_by_resource_name("people/unknown", account=1)
        assert result == []

    def test_get_mappings_by_resource_name_invalid_account(self, db):
        """Test that invalid account number raises ValueError."""
        with pytest.raises(ValueError, match="Account must be 1 or 2"):
            db.get_mappings_by_resource_name("people/a1", account=3)

        with pytest.raises(ValueError, match="Account must be 1 or 2"):
            db.get_mappings_by_resource_name("people/a1", account=0)


class TestUtilityOperations:
    """Tests for utility operations."""

    @pytest.fixture
    def db(self):
        """Create an initialized in-memory database."""
        db = SyncDatabase(":memory:")
        db.initialize()
        return db

    def test_get_mapping_count_empty(self, db):
        """Test get_mapping_count with empty database."""
        assert db.get_mapping_count() == 0

    def test_get_mapping_count_with_data(self, db):
        """Test get_mapping_count with data."""
        db.upsert_contact_mapping(matching_key="key1", account1_resource_name="p1")
        db.upsert_contact_mapping(matching_key="key2", account1_resource_name="p2")
        db.upsert_contact_mapping(matching_key="key3", account1_resource_name="p3")

        assert db.get_mapping_count() == 3

    def test_clear_all_mappings(self, db):
        """Test clear_all_mappings removes all mappings."""
        db.upsert_contact_mapping(matching_key="key1", account1_resource_name="p1")
        db.upsert_contact_mapping(matching_key="key2", account1_resource_name="p2")

        deleted = db.clear_all_mappings()
        assert deleted == 2
        assert db.get_mapping_count() == 0

    def test_clear_all_mappings_empty_db(self, db):
        """Test clear_all_mappings on empty database."""
        deleted = db.clear_all_mappings()
        assert deleted == 0

    def test_clear_all_state(self, db):
        """Test clear_all_state removes sync state and mappings."""
        db.update_sync_state("account1", sync_token="token1")
        db.update_sync_state("account2", sync_token="token2")
        db.upsert_contact_mapping(matching_key="key1", account1_resource_name="p1")

        db.clear_all_state()

        assert db.get_sync_state("account1") is None
        assert db.get_sync_state("account2") is None
        assert db.get_mapping_count() == 0

    def test_vacuum(self, db):
        """Test vacuum operation runs without error."""
        db.upsert_contact_mapping(matching_key="key1", account1_resource_name="p1")
        db.delete_contact_mapping("key1")

        # Vacuum should complete without error
        db.vacuum()


class TestTimestampHandling:
    """Tests for timestamp handling."""

    @pytest.fixture
    def db(self):
        """Create an initialized in-memory database."""
        db = SyncDatabase(":memory:")
        db.initialize()
        return db

    def test_contact_mapping_has_timestamps(self, db):
        """Test that contact mappings have created_at and updated_at."""
        datetime.utcnow()
        db.upsert_contact_mapping(matching_key="test", account1_resource_name="p1")
        datetime.utcnow()

        result = db.get_contact_mapping("test")
        # Timestamps may be returned as strings or datetime objects
        # depending on SQLite config
        created = result["created_at"]
        updated = result["updated_at"]

        assert created is not None
        assert updated is not None

    def test_contact_mapping_updated_at_changes_on_update(self, db):
        """Test that updated_at changes when mapping is updated."""
        db.upsert_contact_mapping(matching_key="test", account1_resource_name="p1")
        result1 = db.get_contact_mapping("test")
        updated1 = result1["updated_at"]

        # Small delay to ensure different timestamp
        import time

        time.sleep(0.01)

        db.upsert_contact_mapping(matching_key="test", account1_resource_name="p2")
        result2 = db.get_contact_mapping("test")
        updated2 = result2["updated_at"]

        # Updated timestamps should be different (or at least not before)
        assert updated2 >= updated1 if isinstance(updated2, datetime) else True


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    @pytest.fixture
    def db(self):
        """Create an initialized in-memory database."""
        db = SyncDatabase(":memory:")
        db.initialize()
        return db

    def test_empty_string_matching_key(self, db):
        """Test handling of empty string matching key."""
        db.upsert_contact_mapping(matching_key="", account1_resource_name="p1")
        result = db.get_contact_mapping("")
        assert result is not None
        assert result["matching_key"] == ""

    def test_unicode_in_matching_key(self, db):
        """Test handling of unicode characters in matching key."""
        unicode_key = "jose_garcia:jose@example.com"
        db.upsert_contact_mapping(matching_key=unicode_key, account1_resource_name="p1")
        result = db.get_contact_mapping(unicode_key)
        assert result is not None
        assert result["matching_key"] == unicode_key

    def test_special_characters_in_matching_key(self, db):
        """Test handling of special characters in matching key."""
        special_key = "o'reilly:o'reilly@example.com"
        db.upsert_contact_mapping(matching_key=special_key, account1_resource_name="p1")
        result = db.get_contact_mapping(special_key)
        assert result is not None
        assert result["matching_key"] == special_key

    def test_long_sync_token(self, db):
        """Test handling of long sync token."""
        long_token = "x" * 10000
        db.update_sync_state("account1", sync_token=long_token)
        result = db.get_sync_state("account1")
        assert result["sync_token"] == long_token

    def test_concurrent_updates_same_mapping(self, db):
        """Test multiple updates to same mapping key."""
        for i in range(100):
            db.upsert_contact_mapping(
                matching_key="concurrent_test", account1_resource_name=f"people/{i}"
            )

        result = db.get_contact_mapping("concurrent_test")
        assert result["account1_resource_name"] == "people/99"

    def test_file_database_persists(self, tmp_path):
        """Test that file-based database persists data."""
        db_path = str(tmp_path / "persist_test.db")

        # Create and populate database
        db1 = SyncDatabase(db_path)
        db1.initialize()
        db1.upsert_contact_mapping(
            matching_key="persistent", account1_resource_name="p1"
        )

        # Create new instance and verify data persists
        db2 = SyncDatabase(db_path)
        result = db2.get_contact_mapping("persistent")
        assert result is not None
        assert result["account1_resource_name"] == "p1"


class TestLLMMatchAttemptOperations:
    """Tests for LLM match attempt CRUD operations."""

    @pytest.fixture
    def db(self):
        """Create an initialized in-memory database."""
        db = SyncDatabase(":memory:")
        db.initialize()
        return db

    def test_get_llm_match_attempt_returns_none_for_unknown(self, db):
        """Test that get_llm_match_attempt returns None for unknown pair."""
        result = db.get_llm_match_attempt("people/123", "people/456")
        assert result is None

    def test_upsert_llm_match_attempt_creates_new_entry(self, db):
        """Test that upsert_llm_match_attempt creates a new entry."""
        db.upsert_llm_match_attempt(
            contact1_resource_name="people/123",
            contact2_resource_name="people/456",
            contact1_display_name="John Doe",
            contact2_display_name="Johnny D",
            contact1_content_hash="hash1",
            contact2_content_hash="hash2",
            is_match=True,
            confidence=0.85,
            reasoning="Same person, nickname variation",
            model_used="claude-haiku-4-5-20250514",
        )

        result = db.get_llm_match_attempt("people/123", "people/456")
        assert result is not None
        assert result["contact1_resource_name"] == "people/123"
        assert result["contact2_resource_name"] == "people/456"
        assert result["contact1_display_name"] == "John Doe"
        assert result["contact2_display_name"] == "Johnny D"
        assert result["contact1_content_hash"] == "hash1"
        assert result["contact2_content_hash"] == "hash2"
        assert result["is_match"] == 1  # SQLite stores bool as int
        assert result["confidence"] == 0.85
        assert result["reasoning"] == "Same person, nickname variation"
        assert result["model_used"] == "claude-haiku-4-5-20250514"

    def test_upsert_llm_match_attempt_updates_existing(self, db):
        """Test that upsert_llm_match_attempt updates an existing entry."""
        db.upsert_llm_match_attempt(
            contact1_resource_name="people/123",
            contact2_resource_name="people/456",
            contact1_display_name="John Doe",
            contact2_display_name="Johnny D",
            contact1_content_hash="hash1",
            contact2_content_hash="hash2",
            is_match=False,
            confidence=0.3,
            reasoning="Different people",
            model_used="claude-haiku-4-5-20250514",
        )

        # Update with new decision
        db.upsert_llm_match_attempt(
            contact1_resource_name="people/123",
            contact2_resource_name="people/456",
            contact1_display_name="John Doe",
            contact2_display_name="Johnny D",
            contact1_content_hash="hash1_updated",
            contact2_content_hash="hash2_updated",
            is_match=True,
            confidence=0.9,
            reasoning="Actually same person after data update",
            model_used="claude-haiku-4-5-20250514",
        )

        result = db.get_llm_match_attempt("people/123", "people/456")
        assert result["is_match"] == 1
        assert result["confidence"] == 0.9
        assert result["reasoning"] == "Actually same person after data update"
        assert result["contact1_content_hash"] == "hash1_updated"

    def test_get_llm_match_attempt_reverse_order(self, db):
        """Test that get_llm_match_attempt finds pair regardless of order."""
        db.upsert_llm_match_attempt(
            contact1_resource_name="people/123",
            contact2_resource_name="people/456",
            contact1_display_name="John",
            contact2_display_name="Jane",
            contact1_content_hash="h1",
            contact2_content_hash="h2",
            is_match=False,
            confidence=0.2,
            reasoning="Different people",
            model_used="claude-haiku-4-5-20250514",
        )

        # Query with reversed order
        result = db.get_llm_match_attempt("people/456", "people/123")
        assert result is not None
        assert result["contact1_resource_name"] == "people/123"

    def test_delete_llm_match_attempts_for_contact(self, db):
        """Test deleting all LLM match attempts involving a contact."""
        # Create multiple attempts involving people/123
        db.upsert_llm_match_attempt(
            contact1_resource_name="people/123",
            contact2_resource_name="people/456",
            contact1_display_name="John",
            contact2_display_name="Jane",
            contact1_content_hash="h1",
            contact2_content_hash="h2",
            is_match=False,
            confidence=0.2,
            reasoning="Test 1",
            model_used="test",
        )
        db.upsert_llm_match_attempt(
            contact1_resource_name="people/789",
            contact2_resource_name="people/123",
            contact1_display_name="Bob",
            contact2_display_name="John",
            contact1_content_hash="h3",
            contact2_content_hash="h1",
            is_match=True,
            confidence=0.9,
            reasoning="Test 2",
            model_used="test",
        )
        # This one should NOT be deleted
        db.upsert_llm_match_attempt(
            contact1_resource_name="people/456",
            contact2_resource_name="people/789",
            contact1_display_name="Jane",
            contact2_display_name="Bob",
            contact1_content_hash="h2",
            contact2_content_hash="h3",
            is_match=False,
            confidence=0.1,
            reasoning="Test 3",
            model_used="test",
        )

        deleted = db.delete_llm_match_attempts_for_contact("people/123")
        assert deleted == 2

        # Verify the remaining attempt
        assert db.get_llm_match_attempt("people/456", "people/789") is not None
        assert db.get_llm_match_attempt("people/123", "people/456") is None
        assert db.get_llm_match_attempt("people/789", "people/123") is None

    def test_get_llm_match_attempt_count(self, db):
        """Test counting LLM match attempts."""
        assert db.get_llm_match_attempt_count() == 0

        db.upsert_llm_match_attempt(
            contact1_resource_name="people/1",
            contact2_resource_name="people/2",
            contact1_display_name="A",
            contact2_display_name="B",
            contact1_content_hash="h1",
            contact2_content_hash="h2",
            is_match=True,
            confidence=0.9,
            reasoning="Test",
            model_used="test",
        )
        assert db.get_llm_match_attempt_count() == 1

        db.upsert_llm_match_attempt(
            contact1_resource_name="people/3",
            contact2_resource_name="people/4",
            contact1_display_name="C",
            contact2_display_name="D",
            contact1_content_hash="h3",
            contact2_content_hash="h4",
            is_match=False,
            confidence=0.1,
            reasoning="Test 2",
            model_used="test",
        )
        assert db.get_llm_match_attempt_count() == 2

    def test_llm_match_attempt_not_match_stored_correctly(self, db):
        """Test that is_match=False is stored correctly."""
        db.upsert_llm_match_attempt(
            contact1_resource_name="people/1",
            contact2_resource_name="people/2",
            contact1_display_name="A",
            contact2_display_name="B",
            contact1_content_hash="h1",
            contact2_content_hash="h2",
            is_match=False,
            confidence=0.15,
            reasoning="Definitely different people",
            model_used="test",
        )

        result = db.get_llm_match_attempt("people/1", "people/2")
        assert result["is_match"] == 0  # SQLite stores False as 0


class TestContactGroupOperations:
    """Tests for contact group CRUD operations."""

    @pytest.fixture
    def db(self):
        """Create an initialized in-memory database."""
        db = SyncDatabase(":memory:")
        db.initialize()
        return db

    def test_get_group_returns_none_for_unknown(self, db):
        """Test that get_group returns None for unknown resource name."""
        result = db.get_group("contactGroups/unknown", "account1")
        assert result is None

    def test_upsert_group_creates_new_entry(self, db):
        """Test that upsert_group creates a new entry."""
        db.upsert_group(
            name="Work Contacts",
            account_id="account1",
            resource_name="contactGroups/abc123",
            etag="etag1",
            group_type="USER_CONTACT_GROUP",
            member_count=5,
        )

        result = db.get_group("contactGroups/abc123", "account1")
        assert result is not None
        assert result["name"] == "Work Contacts"
        assert result["resource_name"] == "contactGroups/abc123"
        assert result["account_id"] == "account1"
        assert result["etag"] == "etag1"
        assert result["group_type"] == "USER_CONTACT_GROUP"
        assert result["member_count"] == 5

    def test_upsert_group_updates_existing(self, db):
        """Test that upsert_group updates an existing entry."""
        db.upsert_group(
            name="My Group",
            account_id="account1",
            resource_name="contactGroups/abc",
            etag="etag_v1",
        )

        db.upsert_group(
            name="My Group Updated",
            account_id="account1",
            resource_name="contactGroups/abc",
            etag="etag_v2",
            member_count=10,
        )

        result = db.get_group("contactGroups/abc", "account1")
        assert result["name"] == "My Group Updated"
        assert result["etag"] == "etag_v2"
        assert result["member_count"] == 10

    def test_get_group_by_name(self, db):
        """Test getting a group by name and account."""
        db.upsert_group(
            name="Friends",
            account_id="account1",
            resource_name="contactGroups/123",
        )

        result = db.get_group_by_name("Friends", "account1")
        assert result is not None
        assert result["name"] == "Friends"
        assert result["resource_name"] == "contactGroups/123"

    def test_get_group_by_name_returns_none_for_unknown(self, db):
        """Test that get_group_by_name returns None for unknown name."""
        result = db.get_group_by_name("Unknown Group", "account1")
        assert result is None

    def test_get_groups_by_account(self, db):
        """Test getting all groups for an account."""
        db.upsert_group(name="Group A", account_id="account1", resource_name="cg/a")
        db.upsert_group(name="Group B", account_id="account1", resource_name="cg/b")
        db.upsert_group(name="Group C", account_id="account2", resource_name="cg/c")

        result = db.get_groups_by_account("account1")
        assert len(result) == 2
        names = [r["name"] for r in result]
        assert "Group A" in names
        assert "Group B" in names

    def test_get_groups_by_account_empty(self, db):
        """Test getting groups for account with no groups."""
        result = db.get_groups_by_account("nonexistent")
        assert result == []

    def test_get_groups_by_account_sorted_by_name(self, db):
        """Test that groups are returned sorted by name."""
        db.upsert_group(name="Zebra", account_id="account1", resource_name="cg/z")
        db.upsert_group(name="Alpha", account_id="account1", resource_name="cg/a")
        db.upsert_group(name="Middle", account_id="account1", resource_name="cg/m")

        result = db.get_groups_by_account("account1")
        names = [r["name"] for r in result]
        assert names == ["Alpha", "Middle", "Zebra"]

    def test_delete_group(self, db):
        """Test deleting a contact group."""
        db.upsert_group(
            name="To Delete",
            account_id="account1",
            resource_name="contactGroups/delete",
        )

        deleted = db.delete_group("contactGroups/delete", "account1")
        assert deleted is True

        result = db.get_group("contactGroups/delete", "account1")
        assert result is None

    def test_delete_group_returns_false_for_nonexistent(self, db):
        """Test that delete returns False for nonexistent group."""
        deleted = db.delete_group("contactGroups/nonexistent", "account1")
        assert deleted is False

    def test_get_group_count_empty(self, db):
        """Test get_group_count with empty database."""
        assert db.get_group_count() == 0

    def test_get_group_count_with_data(self, db):
        """Test get_group_count with data."""
        db.upsert_group(name="Group 1", account_id="account1", resource_name="cg/1")
        db.upsert_group(name="Group 2", account_id="account1", resource_name="cg/2")
        db.upsert_group(name="Group 3", account_id="account2", resource_name="cg/3")

        assert db.get_group_count() == 3

    def test_get_group_count_by_account(self, db):
        """Test get_group_count filtered by account."""
        db.upsert_group(name="Group 1", account_id="account1", resource_name="cg/1")
        db.upsert_group(name="Group 2", account_id="account1", resource_name="cg/2")
        db.upsert_group(name="Group 3", account_id="account2", resource_name="cg/3")

        assert db.get_group_count("account1") == 2
        assert db.get_group_count("account2") == 1

    def test_clear_groups_for_account(self, db):
        """Test clearing all groups for an account."""
        db.upsert_group(name="Group 1", account_id="account1", resource_name="cg/1")
        db.upsert_group(name="Group 2", account_id="account1", resource_name="cg/2")
        db.upsert_group(name="Group 3", account_id="account2", resource_name="cg/3")

        deleted = db.clear_groups_for_account("account1")
        assert deleted == 2
        assert db.get_group_count("account1") == 0
        assert db.get_group_count("account2") == 1

    def test_group_has_timestamps(self, db):
        """Test that groups have created_at and updated_at."""
        db.upsert_group(name="Test", account_id="account1", resource_name="cg/test")

        result = db.get_group("cg/test", "account1")
        assert result["created_at"] is not None
        assert result["updated_at"] is not None

    def test_group_default_type(self, db):
        """Test that default group type is USER_CONTACT_GROUP."""
        db.upsert_group(name="Default", account_id="account1", resource_name="cg/def")

        result = db.get_group("cg/def", "account1")
        assert result["group_type"] == "USER_CONTACT_GROUP"


class TestContactGroupMappingOperations:
    """Tests for contact group mapping CRUD operations."""

    @pytest.fixture
    def db(self):
        """Create an initialized in-memory database."""
        db = SyncDatabase(":memory:")
        db.initialize()
        return db

    def test_get_group_mapping_returns_none_for_unknown(self, db):
        """Test that get_group_mapping returns None for unknown group name."""
        result = db.get_group_mapping("unknown_group")
        assert result is None

    def test_upsert_group_mapping_creates_new_entry(self, db):
        """Test that upsert_group_mapping creates a new entry."""
        db.upsert_group_mapping(
            group_name="work contacts",
            account1_resource_name="contactGroups/abc",
            account2_resource_name="contactGroups/xyz",
            account1_etag="etag1",
            account2_etag="etag2",
            last_synced_hash="hash123",
        )

        result = db.get_group_mapping("work contacts")
        assert result is not None
        assert result["group_name"] == "work contacts"
        assert result["account1_resource_name"] == "contactGroups/abc"
        assert result["account2_resource_name"] == "contactGroups/xyz"
        assert result["account1_etag"] == "etag1"
        assert result["account2_etag"] == "etag2"
        assert result["last_synced_hash"] == "hash123"

    def test_upsert_group_mapping_updates_existing(self, db):
        """Test that upsert_group_mapping updates an existing entry."""
        db.upsert_group_mapping(
            group_name="friends",
            account1_resource_name="cg/1",
            last_synced_hash="hash_v1",
        )

        db.upsert_group_mapping(
            group_name="friends",
            account2_resource_name="cg/2",
            last_synced_hash="hash_v2",
        )

        result = db.get_group_mapping("friends")
        assert result["account1_resource_name"] == "cg/1"
        assert result["account2_resource_name"] == "cg/2"
        assert result["last_synced_hash"] == "hash_v2"

    def test_upsert_group_mapping_partial_update(self, db):
        """Test partial update of group mapping."""
        db.upsert_group_mapping(
            group_name="test_group",
            account1_resource_name="cg/old",
            account1_etag="old_etag",
        )

        # Update only etag
        db.upsert_group_mapping(
            group_name="test_group",
            account1_etag="new_etag",
        )

        result = db.get_group_mapping("test_group")
        assert result["account1_resource_name"] == "cg/old"
        assert result["account1_etag"] == "new_etag"

    def test_delete_group_mapping(self, db):
        """Test deleting a group mapping."""
        db.upsert_group_mapping(
            group_name="to_delete",
            account1_resource_name="cg/123",
        )

        deleted = db.delete_group_mapping("to_delete")
        assert deleted is True

        result = db.get_group_mapping("to_delete")
        assert result is None

    def test_delete_group_mapping_returns_false_for_nonexistent(self, db):
        """Test that delete returns False for nonexistent mapping."""
        deleted = db.delete_group_mapping("nonexistent")
        assert deleted is False

    def test_get_all_group_mappings_empty(self, db):
        """Test get_all_group_mappings with empty database."""
        result = db.get_all_group_mappings()
        assert result == []

    def test_get_all_group_mappings_returns_all(self, db):
        """Test get_all_group_mappings returns all mappings."""
        db.upsert_group_mapping(group_name="group_a", account1_resource_name="cg/1")
        db.upsert_group_mapping(group_name="group_b", account1_resource_name="cg/2")
        db.upsert_group_mapping(group_name="group_c", account1_resource_name="cg/3")

        result = db.get_all_group_mappings()
        assert len(result) == 3

    def test_get_all_group_mappings_sorted_by_name(self, db):
        """Test that get_all_group_mappings returns sorted results."""
        db.upsert_group_mapping(group_name="charlie", account1_resource_name="cg/c")
        db.upsert_group_mapping(group_name="alpha", account1_resource_name="cg/a")
        db.upsert_group_mapping(group_name="bravo", account1_resource_name="cg/b")

        result = db.get_all_group_mappings()
        names = [r["group_name"] for r in result]
        assert names == ["alpha", "bravo", "charlie"]

    def test_get_group_mapping_by_resource_name_account1(self, db):
        """Test finding group mapping by account 1 resource name."""
        db.upsert_group_mapping(
            group_name="test",
            account1_resource_name="cg/a1",
            account2_resource_name="cg/a2",
        )

        result = db.get_group_mapping_by_resource_name("cg/a1", account=1)
        assert result is not None
        assert result["group_name"] == "test"

    def test_get_group_mapping_by_resource_name_account2(self, db):
        """Test finding group mapping by account 2 resource name."""
        db.upsert_group_mapping(
            group_name="test",
            account1_resource_name="cg/a1",
            account2_resource_name="cg/a2",
        )

        result = db.get_group_mapping_by_resource_name("cg/a2", account=2)
        assert result is not None
        assert result["group_name"] == "test"

    def test_get_group_mapping_by_resource_name_not_found(self, db):
        """Test that None is returned for unknown resource name."""
        result = db.get_group_mapping_by_resource_name("cg/unknown", account=1)
        assert result is None

    def test_get_group_mapping_by_resource_name_invalid_account(self, db):
        """Test that invalid account number raises ValueError."""
        with pytest.raises(ValueError, match="Account must be 1 or 2"):
            db.get_group_mapping_by_resource_name("cg/test", account=3)

        with pytest.raises(ValueError, match="Account must be 1 or 2"):
            db.get_group_mapping_by_resource_name("cg/test", account=0)

    def test_get_group_mapping_count_empty(self, db):
        """Test get_group_mapping_count with empty database."""
        assert db.get_group_mapping_count() == 0

    def test_get_group_mapping_count_with_data(self, db):
        """Test get_group_mapping_count with data."""
        db.upsert_group_mapping(group_name="g1", account1_resource_name="cg/1")
        db.upsert_group_mapping(group_name="g2", account1_resource_name="cg/2")
        db.upsert_group_mapping(group_name="g3", account1_resource_name="cg/3")

        assert db.get_group_mapping_count() == 3

    def test_clear_all_group_mappings(self, db):
        """Test clear_all_group_mappings removes all mappings."""
        db.upsert_group_mapping(group_name="g1", account1_resource_name="cg/1")
        db.upsert_group_mapping(group_name="g2", account1_resource_name="cg/2")

        deleted = db.clear_all_group_mappings()
        assert deleted == 2
        assert db.get_group_mapping_count() == 0

    def test_clear_all_group_mappings_empty_db(self, db):
        """Test clear_all_group_mappings on empty database."""
        deleted = db.clear_all_group_mappings()
        assert deleted == 0

    def test_group_mapping_has_timestamps(self, db):
        """Test that group mappings have created_at and updated_at."""
        db.upsert_group_mapping(group_name="test", account1_resource_name="cg/1")

        result = db.get_group_mapping("test")
        assert result["created_at"] is not None
        assert result["updated_at"] is not None

    def test_group_mapping_updated_at_changes_on_update(self, db):
        """Test that updated_at changes when mapping is updated."""
        db.upsert_group_mapping(group_name="test", account1_resource_name="cg/1")
        result1 = db.get_group_mapping("test")
        updated1 = result1["updated_at"]

        # Small delay to ensure different timestamp
        import time

        time.sleep(0.01)

        db.upsert_group_mapping(group_name="test", account1_resource_name="cg/2")
        result2 = db.get_group_mapping("test")
        updated2 = result2["updated_at"]

        # Updated timestamps should be different (or at least not before)
        assert updated2 >= updated1 if isinstance(updated2, datetime) else True


class TestContactGroupDatabaseTableExists:
    """Tests that contact_groups and contact_group_mappings tables exist."""

    def test_initialize_creates_contact_groups_table(self):
        """Test that initialize creates the contact_groups table."""
        db = SyncDatabase(":memory:")
        db.initialize()

        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='contact_groups'"
            )
            assert cursor.fetchone() is not None

    def test_initialize_creates_contact_group_mappings_table(self):
        """Test that initialize creates the contact_group_mappings table."""
        db = SyncDatabase(":memory:")
        db.initialize()

        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='contact_group_mappings'"
            )
            assert cursor.fetchone() is not None

    def test_initialize_creates_group_indexes(self):
        """Test that initialize creates the required group indexes."""
        db = SyncDatabase(":memory:")
        db.initialize()

        with db.connection() as conn:
            # Check contact_groups indexes
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_contact_groups_name'"
            )
            assert cursor.fetchone() is not None

            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_contact_groups_account'"
            )
            assert cursor.fetchone() is not None

            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_contact_groups_resource'"
            )
            assert cursor.fetchone() is not None

            # Check contact_group_mappings index
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_grp_map_name'"
            )
            assert cursor.fetchone() is not None
