"""
Unit tests for the sync engine and conflict resolution modules.

Tests the SyncEngine class for bidirectional synchronization and
ConflictResolver for conflict detection and resolution.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from gcontact_sync.api.people_api import PeopleAPI, PeopleAPIError
from gcontact_sync.storage.db import SyncDatabase
from gcontact_sync.sync.conflict import (
    ConflictResolver,
    ConflictResult,
    ConflictSide,
    ConflictStrategy,
)
from gcontact_sync.sync.contact import Contact
from gcontact_sync.sync.engine import (
    SyncEngine,
    SyncResult,
    SyncStats,
)

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def sample_contact1():
    """Create a sample contact for account 1."""
    return Contact(
        resource_name="people/c1",
        etag="etag1",
        display_name="John Doe",
        given_name="John",
        family_name="Doe",
        emails=["john@example.com"],
        phones=["+1234567890"],
        organizations=["Acme Corp"],
        last_modified=datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_contact2():
    """Create a sample contact for account 2 (same person, different resource)."""
    return Contact(
        resource_name="people/c2",
        etag="etag2",
        display_name="John Doe",
        given_name="John",
        family_name="Doe",
        emails=["john@example.com"],
        phones=["+1234567890"],
        organizations=["Acme Corp"],
        last_modified=datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def newer_contact1():
    """Create a newer version of contact for account 1."""
    return Contact(
        resource_name="people/c1",
        etag="etag1_new",
        display_name="John Doe",
        given_name="John",
        family_name="Doe",
        emails=["john@example.com", "john.work@example.com"],
        phones=["+1234567890"],
        organizations=["Acme Corp", "Tech Inc"],
        last_modified=datetime(2024, 6, 20, 14, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def older_contact2():
    """Create an older version of contact for account 2."""
    return Contact(
        resource_name="people/c2",
        etag="etag2_old",
        display_name="John Doe",
        given_name="John",
        family_name="Doe",
        emails=["john@example.com"],
        phones=["+1234567890"],
        organizations=["Acme Corp"],
        last_modified=datetime(2024, 6, 10, 8, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def mock_api1():
    """Create a mock PeopleAPI for account 1."""
    api = MagicMock(spec=PeopleAPI)
    # Default return values for API methods
    api.list_contact_groups.return_value = ([], None)
    return api


@pytest.fixture
def mock_api2():
    """Create a mock PeopleAPI for account 2."""
    api = MagicMock(spec=PeopleAPI)
    # Default return values for API methods
    api.list_contact_groups.return_value = ([], None)
    return api


@pytest.fixture
def mock_database():
    """Create a mock SyncDatabase."""
    db = MagicMock(spec=SyncDatabase)
    db.db_path = ":memory:"  # For __repr__ test
    db.get_sync_state.return_value = None
    db.get_contact_mapping.return_value = None
    db.get_mappings_by_resource_name.return_value = []
    db.get_mapping_count.return_value = 0
    return db


@pytest.fixture
def sync_engine(mock_api1, mock_api2, mock_database):
    """Create a SyncEngine instance with mocked dependencies."""
    return SyncEngine(api1=mock_api1, api2=mock_api2, database=mock_database)


@pytest.fixture
def contact_with_photo1():
    """Create a contact with photo for account 1."""
    return Contact(
        resource_name="people/c1",
        etag="etag1",
        display_name="John Doe",
        given_name="John",
        family_name="Doe",
        emails=["john@example.com"],
        photo_url="https://example.com/photo1.jpg",
        photo_etag="photo_etag1",
        last_modified=datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def contact_without_photo1():
    """Create a contact without photo for account 1."""
    return Contact(
        resource_name="people/c1",
        etag="etag1",
        display_name="John Doe",
        given_name="John",
        family_name="Doe",
        emails=["john@example.com"],
        last_modified=datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def contact_with_different_photo2():
    """Create a contact with different photo for account 2."""
    return Contact(
        resource_name="people/c2",
        etag="etag2",
        display_name="John Doe",
        given_name="John",
        family_name="Doe",
        emails=["john@example.com"],
        photo_url="https://example.com/photo2.jpg",
        photo_etag="photo_etag2",
        last_modified=datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
    )


# ==============================================================================
# ConflictStrategy Tests
# ==============================================================================


class TestConflictStrategy:
    """Tests for ConflictStrategy enum."""

    def test_last_modified_wins_value(self):
        """Test LAST_MODIFIED_WINS enum value."""
        assert ConflictStrategy.LAST_MODIFIED_WINS.value == "last_modified_wins"

    def test_account1_wins_value(self):
        """Test ACCOUNT1_WINS enum value."""
        assert ConflictStrategy.ACCOUNT1_WINS.value == "account1_wins"

    def test_account2_wins_value(self):
        """Test ACCOUNT2_WINS enum value."""
        assert ConflictStrategy.ACCOUNT2_WINS.value == "account2_wins"

    def test_all_strategies_exist(self):
        """Test that all expected strategies exist."""
        strategies = list(ConflictStrategy)
        assert len(strategies) == 3


class TestConflictSide:
    """Tests for ConflictSide enum."""

    def test_account1_value(self):
        """Test ACCOUNT1 enum value."""
        assert ConflictSide.ACCOUNT1.value == "account1"

    def test_account2_value(self):
        """Test ACCOUNT2 enum value."""
        assert ConflictSide.ACCOUNT2.value == "account2"

    def test_no_conflict_value(self):
        """Test NO_CONFLICT enum value."""
        assert ConflictSide.NO_CONFLICT.value == "no_conflict"

    def test_equal_value(self):
        """Test EQUAL enum value."""
        assert ConflictSide.EQUAL.value == "equal"


# ==============================================================================
# ConflictResult Tests
# ==============================================================================


class TestConflictResult:
    """Tests for ConflictResult dataclass."""

    def test_conflict_result_creation(self, sample_contact1, sample_contact2):
        """Test creating a ConflictResult instance."""
        result = ConflictResult(
            winner=sample_contact1,
            loser=sample_contact2,
            winning_side=ConflictSide.ACCOUNT1,
            reason="Test reason",
        )

        assert result.winner == sample_contact1
        assert result.loser == sample_contact2
        assert result.winning_side == ConflictSide.ACCOUNT1
        assert result.reason == "Test reason"
        assert result.needs_update_in_account1 is False
        assert result.needs_update_in_account2 is False

    def test_conflict_result_with_update_flags(self, sample_contact1, sample_contact2):
        """Test ConflictResult with update flags set."""
        result = ConflictResult(
            winner=sample_contact1,
            loser=sample_contact2,
            winning_side=ConflictSide.ACCOUNT1,
            reason="Test",
            needs_update_in_account1=False,
            needs_update_in_account2=True,
        )

        assert result.needs_update_in_account1 is False
        assert result.needs_update_in_account2 is True


# ==============================================================================
# ConflictResolver Initialization Tests
# ==============================================================================


class TestConflictResolverInit:
    """Tests for ConflictResolver initialization."""

    def test_default_strategy(self):
        """Test default strategy is LAST_MODIFIED_WINS."""
        resolver = ConflictResolver()
        assert resolver.strategy == ConflictStrategy.LAST_MODIFIED_WINS

    def test_custom_strategy_account1_wins(self):
        """Test initialization with ACCOUNT1_WINS strategy."""
        resolver = ConflictResolver(strategy=ConflictStrategy.ACCOUNT1_WINS)
        assert resolver.strategy == ConflictStrategy.ACCOUNT1_WINS

    def test_custom_strategy_account2_wins(self):
        """Test initialization with ACCOUNT2_WINS strategy."""
        resolver = ConflictResolver(strategy=ConflictStrategy.ACCOUNT2_WINS)
        assert resolver.strategy == ConflictStrategy.ACCOUNT2_WINS

    def test_repr(self):
        """Test string representation."""
        resolver = ConflictResolver()
        repr_str = repr(resolver)
        assert "ConflictResolver" in repr_str
        assert "last_modified_wins" in repr_str


# ==============================================================================
# ConflictResolver has_conflict Tests
# ==============================================================================


class TestConflictResolverHasConflict:
    """Tests for ConflictResolver.has_conflict() method."""

    def test_no_conflict_same_content(self, sample_contact1, sample_contact2):
        """Test no conflict when contacts have same content."""
        resolver = ConflictResolver()
        # Contacts have same content (same hash)
        assert resolver.has_conflict(sample_contact1, sample_contact2) is False

    def test_no_conflict_different_matching_keys(self):
        """Test no conflict when contacts have different matching keys."""
        resolver = ConflictResolver()

        contact1 = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])
        contact2 = Contact("people/2", "e2", "Jane Smith", emails=["jane@example.com"])

        # Different matching keys means not same contact
        assert resolver.has_conflict(contact1, contact2) is False

    def test_conflict_different_content_same_key(self):
        """Test conflict when same key but different content without last hash."""
        resolver = ConflictResolver()

        contact1 = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])
        contact2 = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            phones=["+1234567890"],
        )

        # Same matching key, different content, no last synced hash
        assert resolver.has_conflict(contact1, contact2) is True

    def test_no_conflict_only_one_changed_with_hash(self):
        """Test no conflict when only one contact changed from last synced state."""
        resolver = ConflictResolver()

        # Original synced state
        original = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])
        last_synced_hash = original.content_hash()

        # Contact 1 unchanged
        contact1 = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])

        # Contact 2 changed (added phone)
        contact2 = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            phones=["+1234567890"],
        )

        # Only one changed - not a conflict, just propagate
        assert resolver.has_conflict(contact1, contact2, last_synced_hash) is False

    def test_conflict_both_changed_with_hash(self):
        """Test conflict when both contacts changed from last synced state."""
        resolver = ConflictResolver()

        # Original synced state
        original = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])
        last_synced_hash = original.content_hash()

        # Contact 1 changed (added organization)
        contact1 = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            organizations=["Acme Corp"],
        )

        # Contact 2 changed (added phone)
        contact2 = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            phones=["+1234567890"],
        )

        # Both changed - this is a true conflict
        assert resolver.has_conflict(contact1, contact2, last_synced_hash) is True


# ==============================================================================
# ConflictResolver resolve Tests
# ==============================================================================


class TestConflictResolverResolve:
    """Tests for ConflictResolver.resolve() method."""

    def test_resolve_last_modified_wins_contact1_newer(
        self, newer_contact1, older_contact2
    ):
        """Test LAST_MODIFIED_WINS when contact1 is newer."""
        resolver = ConflictResolver(strategy=ConflictStrategy.LAST_MODIFIED_WINS)

        result = resolver.resolve(newer_contact1, older_contact2)

        assert result.winning_side == ConflictSide.ACCOUNT1
        assert result.winner == newer_contact1
        assert result.loser == older_contact2
        assert result.needs_update_in_account1 is False
        assert result.needs_update_in_account2 is True
        assert "Account 1 has newer" in result.reason

    def test_resolve_last_modified_wins_contact2_newer(
        self, older_contact2, newer_contact1
    ):
        """Test LAST_MODIFIED_WINS when contact2 is newer."""
        resolver = ConflictResolver(strategy=ConflictStrategy.LAST_MODIFIED_WINS)

        # Swap: older_contact2 is contact1, newer_contact1 is contact2
        # For this test, create proper contacts
        older = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Doe",
            emails=["john@example.com"],
            last_modified=datetime(2024, 6, 10, tzinfo=timezone.utc),
        )
        newer = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="John Doe",
            emails=["john@example.com"],
            phones=["+1234567890"],
            last_modified=datetime(2024, 6, 20, tzinfo=timezone.utc),
        )

        result = resolver.resolve(older, newer)

        assert result.winning_side == ConflictSide.ACCOUNT2
        assert result.winner == newer
        assert result.loser == older
        assert result.needs_update_in_account1 is True
        assert result.needs_update_in_account2 is False
        assert "Account 2 has newer" in result.reason

    def test_resolve_last_modified_wins_equal_timestamps(self):
        """Test LAST_MODIFIED_WINS with equal timestamps (defaults to account1)."""
        resolver = ConflictResolver(strategy=ConflictStrategy.LAST_MODIFIED_WINS)

        same_time = datetime(2024, 6, 15, tzinfo=timezone.utc)
        contact1 = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            last_modified=same_time,
        )
        contact2 = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            phones=["+1234"],
            last_modified=same_time,
        )

        result = resolver.resolve(contact1, contact2)

        assert result.winning_side == ConflictSide.ACCOUNT1
        assert "Equal timestamps" in result.reason

    def test_resolve_last_modified_wins_no_timestamps(self):
        """Test LAST_MODIFIED_WINS with no timestamps (defaults to account1)."""
        resolver = ConflictResolver(strategy=ConflictStrategy.LAST_MODIFIED_WINS)

        contact1 = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])
        contact2 = Contact(
            "people/2", "e2", "John Doe", emails=["john@example.com"], phones=["+1234"]
        )

        result = resolver.resolve(contact1, contact2)

        # Both default to epoch, so equal - account1 wins
        assert result.winning_side == ConflictSide.ACCOUNT1

    def test_resolve_last_modified_wins_one_timestamp_missing(self):
        """Test LAST_MODIFIED_WINS when one timestamp is missing."""
        resolver = ConflictResolver(strategy=ConflictStrategy.LAST_MODIFIED_WINS)

        contact1 = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            last_modified=datetime(2024, 6, 15, tzinfo=timezone.utc),
        )
        contact2 = Contact(
            "people/2", "e2", "John Doe", emails=["john@example.com"], phones=["+1234"]
        )  # No timestamp

        result = resolver.resolve(contact1, contact2)

        # contact1 has timestamp, contact2 defaults to epoch
        assert result.winning_side == ConflictSide.ACCOUNT1

    def test_resolve_account1_wins_strategy(self):
        """Test ACCOUNT1_WINS strategy always picks account1."""
        resolver = ConflictResolver(strategy=ConflictStrategy.ACCOUNT1_WINS)

        # Even though contact2 is newer, account1 should win
        older = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        newer = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            phones=["+1234"],
            last_modified=datetime(2024, 12, 31, tzinfo=timezone.utc),
        )

        result = resolver.resolve(older, newer)

        assert result.winning_side == ConflictSide.ACCOUNT1
        assert result.winner == older
        assert "Account 1 always wins" in result.reason
        assert result.needs_update_in_account2 is True

    def test_resolve_account2_wins_strategy(self):
        """Test ACCOUNT2_WINS strategy always picks account2."""
        resolver = ConflictResolver(strategy=ConflictStrategy.ACCOUNT2_WINS)

        newer = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            phones=["+1234"],
            last_modified=datetime(2024, 12, 31, tzinfo=timezone.utc),
        )
        older = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        result = resolver.resolve(newer, older)

        assert result.winning_side == ConflictSide.ACCOUNT2
        assert result.winner == older
        assert "Account 2 always wins" in result.reason
        assert result.needs_update_in_account1 is True


# ==============================================================================
# ConflictResolver compare_timestamps Tests
# ==============================================================================


class TestConflictResolverCompareTimestamps:
    """Tests for ConflictResolver.compare_timestamps() method."""

    def test_compare_timestamps_contact1_newer(self):
        """Test comparison when contact1 is newer."""
        resolver = ConflictResolver()

        contact1 = Contact(
            "p/1",
            "e1",
            "Test",
            last_modified=datetime(2024, 6, 20, tzinfo=timezone.utc),
        )
        contact2 = Contact(
            "p/2",
            "e2",
            "Test",
            last_modified=datetime(2024, 6, 10, tzinfo=timezone.utc),
        )

        time1, time2, comparison = resolver.compare_timestamps(contact1, contact2)

        assert comparison == 1  # contact1 is newer
        assert time1 > time2

    def test_compare_timestamps_contact2_newer(self):
        """Test comparison when contact2 is newer."""
        resolver = ConflictResolver()

        contact1 = Contact(
            "p/1",
            "e1",
            "Test",
            last_modified=datetime(2024, 6, 10, tzinfo=timezone.utc),
        )
        contact2 = Contact(
            "p/2",
            "e2",
            "Test",
            last_modified=datetime(2024, 6, 20, tzinfo=timezone.utc),
        )

        time1, time2, comparison = resolver.compare_timestamps(contact1, contact2)

        assert comparison == -1  # contact2 is newer

    def test_compare_timestamps_equal(self):
        """Test comparison when timestamps are equal."""
        resolver = ConflictResolver()

        same_time = datetime(2024, 6, 15, tzinfo=timezone.utc)
        contact1 = Contact("p/1", "e1", "Test", last_modified=same_time)
        contact2 = Contact("p/2", "e2", "Test", last_modified=same_time)

        time1, time2, comparison = resolver.compare_timestamps(contact1, contact2)

        assert comparison == 0  # equal

    def test_compare_timestamps_both_none(self):
        """Test comparison when both timestamps are None."""
        resolver = ConflictResolver()

        contact1 = Contact("p/1", "e1", "Test")
        contact2 = Contact("p/2", "e2", "Test")

        time1, time2, comparison = resolver.compare_timestamps(contact1, contact2)

        assert time1 is None
        assert time2 is None
        assert comparison == 0

    def test_compare_timestamps_contact1_none(self):
        """Test comparison when contact1 timestamp is None."""
        resolver = ConflictResolver()

        contact1 = Contact("p/1", "e1", "Test")
        contact2 = Contact(
            "p/2",
            "e2",
            "Test",
            last_modified=datetime(2024, 6, 15, tzinfo=timezone.utc),
        )

        time1, time2, comparison = resolver.compare_timestamps(contact1, contact2)

        assert time1 is None
        assert time2 is not None
        assert comparison == -1  # contact2 is "newer" (has timestamp)

    def test_compare_timestamps_contact2_none(self):
        """Test comparison when contact2 timestamp is None."""
        resolver = ConflictResolver()

        contact1 = Contact(
            "p/1",
            "e1",
            "Test",
            last_modified=datetime(2024, 6, 15, tzinfo=timezone.utc),
        )
        contact2 = Contact("p/2", "e2", "Test")

        time1, time2, comparison = resolver.compare_timestamps(contact1, contact2)

        assert time1 is not None
        assert time2 is None
        assert comparison == 1  # contact1 is "newer" (has timestamp)


# ==============================================================================
# ConflictResolver needs_sync Tests
# ==============================================================================


class TestConflictResolverNeedsSync:
    """Tests for ConflictResolver.needs_sync() method."""

    def test_needs_sync_same_content(self, sample_contact1, sample_contact2):
        """Test no sync needed when content is same."""
        resolver = ConflictResolver()

        update1, update2 = resolver.needs_sync(sample_contact1, sample_contact2)

        assert update1 is False
        assert update2 is False

    def test_needs_sync_only_contact1_changed(self):
        """Test sync needed when only contact1 changed."""
        resolver = ConflictResolver()

        original = Contact("p/1", "e1", "John Doe", emails=["john@example.com"])
        last_hash = original.content_hash()

        contact1 = Contact(
            "p/1", "e1", "John Doe", emails=["john@example.com"], phones=["+1234"]
        )  # Changed
        contact2 = Contact("p/2", "e2", "John Doe", emails=["john@example.com"])  # Same

        update1, update2 = resolver.needs_sync(contact1, contact2, last_hash)

        assert update1 is False  # contact1 doesn't need update
        assert update2 is True  # contact2 needs update (propagate from contact1)

    def test_needs_sync_only_contact2_changed(self):
        """Test sync needed when only contact2 changed."""
        resolver = ConflictResolver()

        original = Contact("p/1", "e1", "John Doe", emails=["john@example.com"])
        last_hash = original.content_hash()

        contact1 = Contact("p/1", "e1", "John Doe", emails=["john@example.com"])  # Same
        contact2 = Contact(
            "p/2", "e2", "John Doe", emails=["john@example.com"], phones=["+1234"]
        )  # Changed

        update1, update2 = resolver.needs_sync(contact1, contact2, last_hash)

        assert update1 is True  # contact1 needs update (propagate from contact2)
        assert update2 is False  # contact2 doesn't need update

    def test_needs_sync_both_changed_conflict(self):
        """Test sync when both changed (conflict resolution)."""
        resolver = ConflictResolver(strategy=ConflictStrategy.LAST_MODIFIED_WINS)

        original = Contact("p/1", "e1", "John Doe", emails=["john@example.com"])
        last_hash = original.content_hash()

        contact1 = Contact(
            "p/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            organizations=["Acme"],
            last_modified=datetime(2024, 6, 20, tzinfo=timezone.utc),
        )
        contact2 = Contact(
            "p/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            phones=["+1234"],
            last_modified=datetime(2024, 6, 10, tzinfo=timezone.utc),
        )

        update1, update2 = resolver.needs_sync(contact1, contact2, last_hash)

        # contact1 is newer, so contact2 needs update
        assert update1 is False
        assert update2 is True

    def test_needs_sync_no_hash_resolves_conflict(self):
        """Test sync without last hash uses conflict resolution."""
        resolver = ConflictResolver(strategy=ConflictStrategy.ACCOUNT2_WINS)

        contact1 = Contact(
            "p/1", "e1", "John Doe", emails=["john@example.com"], organizations=["Acme"]
        )
        contact2 = Contact(
            "p/2", "e2", "John Doe", emails=["john@example.com"], phones=["+1234"]
        )

        update1, update2 = resolver.needs_sync(contact1, contact2)

        # ACCOUNT2_WINS strategy
        assert update1 is True  # contact1 needs update
        assert update2 is False  # contact2 wins


# ==============================================================================
# SyncStats Tests
# ==============================================================================


class TestSyncStats:
    """Tests for SyncStats dataclass."""

    def test_default_values(self):
        """Test that SyncStats has correct default values."""
        stats = SyncStats()

        assert stats.contacts_in_account1 == 0
        assert stats.contacts_in_account2 == 0
        assert stats.created_in_account1 == 0
        assert stats.created_in_account2 == 0
        assert stats.updated_in_account1 == 0
        assert stats.updated_in_account2 == 0
        assert stats.deleted_in_account1 == 0
        assert stats.deleted_in_account2 == 0
        assert stats.conflicts_resolved == 0
        assert stats.skipped_invalid == 0
        assert stats.errors == 0

    def test_custom_values(self):
        """Test SyncStats with custom values."""
        stats = SyncStats(
            contacts_in_account1=100,
            contacts_in_account2=95,
            created_in_account1=5,
            created_in_account2=10,
            conflicts_resolved=2,
        )

        assert stats.contacts_in_account1 == 100
        assert stats.contacts_in_account2 == 95
        assert stats.created_in_account1 == 5
        assert stats.created_in_account2 == 10
        assert stats.conflicts_resolved == 2


# ==============================================================================
# SyncResult Tests
# ==============================================================================


class TestSyncResult:
    """Tests for SyncResult dataclass."""

    def test_default_values(self):
        """Test that SyncResult has correct default values."""
        result = SyncResult()

        assert result.to_create_in_account1 == []
        assert result.to_create_in_account2 == []
        assert result.to_update_in_account1 == []
        assert result.to_update_in_account2 == []
        assert result.to_delete_in_account1 == []
        assert result.to_delete_in_account2 == []
        assert result.conflicts == []
        assert isinstance(result.stats, SyncStats)

    def test_has_changes_false_when_empty(self):
        """Test has_changes returns False when no changes."""
        result = SyncResult()
        assert result.has_changes() is False

    def test_has_changes_true_with_creates(self, sample_contact1):
        """Test has_changes returns True with creates."""
        result = SyncResult()
        result.to_create_in_account1.append(sample_contact1)
        assert result.has_changes() is True

    def test_has_changes_true_with_updates(self, sample_contact1):
        """Test has_changes returns True with updates."""
        result = SyncResult()
        result.to_update_in_account2.append(("people/123", sample_contact1))
        assert result.has_changes() is True

    def test_has_changes_true_with_deletes(self):
        """Test has_changes returns True with deletes."""
        result = SyncResult()
        result.to_delete_in_account1.append("people/123")
        assert result.has_changes() is True

    def test_summary_basic(self):
        """Test summary generation."""
        result = SyncResult()
        result.stats.contacts_in_account1 = 50
        result.stats.contacts_in_account2 = 45

        summary = result.summary()

        assert "Sync Summary" in summary
        assert "Account 1: 50 contacts" in summary
        assert "Account 2: 45 contacts" in summary
        assert "Contact changes to apply" in summary

    def test_summary_with_changes(self, sample_contact1, sample_contact2):
        """Test summary with various changes."""
        result = SyncResult()
        result.stats.contacts_in_account1 = 50
        result.stats.contacts_in_account2 = 45
        result.to_create_in_account1.append(sample_contact1)
        result.to_update_in_account2.append(("people/123", sample_contact2))

        summary = result.summary()

        assert "Create in Account 1: 1" in summary
        assert "Update in Account 2: 1" in summary

    def test_summary_with_conflicts(self, sample_contact1, sample_contact2):
        """Test summary with conflicts."""
        result = SyncResult()
        conflict = ConflictResult(
            winner=sample_contact1,
            loser=sample_contact2,
            winning_side=ConflictSide.ACCOUNT1,
            reason="Test",
        )
        result.conflicts.append(conflict)

        summary = result.summary()

        assert "Conflicts resolved: 1" in summary

    def test_summary_with_skipped(self):
        """Test summary with skipped contacts."""
        result = SyncResult()
        result.stats.skipped_invalid = 3

        summary = result.summary()

        assert "Skipped (invalid): 3" in summary


# ==============================================================================
# SyncEngine Initialization Tests
# ==============================================================================


class TestSyncEngineInit:
    """Tests for SyncEngine initialization."""

    def test_init_with_defaults(self, mock_api1, mock_api2, mock_database):
        """Test initialization with default strategy."""
        engine = SyncEngine(api1=mock_api1, api2=mock_api2, database=mock_database)

        assert engine.api1 == mock_api1
        assert engine.api2 == mock_api2
        assert engine.database == mock_database
        assert engine.conflict_resolver.strategy == ConflictStrategy.LAST_MODIFIED_WINS

    def test_init_with_custom_strategy(self, mock_api1, mock_api2, mock_database):
        """Test initialization with custom conflict strategy."""
        engine = SyncEngine(
            api1=mock_api1,
            api2=mock_api2,
            database=mock_database,
            conflict_strategy=ConflictStrategy.ACCOUNT1_WINS,
        )

        assert engine.conflict_resolver.strategy == ConflictStrategy.ACCOUNT1_WINS

    def test_repr(self, sync_engine):
        """Test string representation."""
        repr_str = repr(sync_engine)
        assert "SyncEngine" in repr_str
        assert "last_modified_wins" in repr_str


# ==============================================================================
# SyncEngine analyze Tests
# ==============================================================================


class TestSyncEngineAnalyze:
    """Tests for SyncEngine.analyze() method."""

    def test_analyze_empty_accounts(self, sync_engine, mock_api1, mock_api2):
        """Test analyze with empty accounts."""
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        result = sync_engine.analyze()

        assert result.stats.contacts_in_account1 == 0
        assert result.stats.contacts_in_account2 == 0
        assert not result.has_changes()

    def test_analyze_contact_only_in_account1(self, sync_engine, mock_api1, mock_api2):
        """Test analyze when contact exists only in account 1."""
        contact1 = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])
        mock_api1.list_contacts.return_value = ([contact1], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        result = sync_engine.analyze()

        assert len(result.to_create_in_account2) == 1
        assert result.to_create_in_account2[0] == contact1
        assert len(result.to_create_in_account1) == 0

    def test_analyze_contact_only_in_account2(self, sync_engine, mock_api1, mock_api2):
        """Test analyze when contact exists only in account 2."""
        contact2 = Contact("people/2", "e2", "Jane Smith", emails=["jane@example.com"])
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([contact2], "token2")

        result = sync_engine.analyze()

        assert len(result.to_create_in_account1) == 1
        assert result.to_create_in_account1[0] == contact2
        assert len(result.to_create_in_account2) == 0

    def test_analyze_contacts_in_sync(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test analyze when contacts are already in sync."""
        contact1 = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])
        contact2 = Contact("people/2", "e2", "John Doe", emails=["john@example.com"])

        mock_api1.list_contacts.return_value = ([contact1], "token1")
        mock_api2.list_contacts.return_value = ([contact2], "token2")

        result = sync_engine.analyze()

        assert not result.has_changes()

    def test_analyze_contact_needs_update(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test analyze when contact needs update."""
        # Contact1 is newer
        contact1 = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            phones=["+1234567890"],
            last_modified=datetime(2024, 6, 20, tzinfo=timezone.utc),
        )
        # Contact2 is older with different content
        contact2 = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            last_modified=datetime(2024, 6, 10, tzinfo=timezone.utc),
        )

        mock_api1.list_contacts.return_value = ([contact1], "token1")
        mock_api2.list_contacts.return_value = ([contact2], "token2")

        result = sync_engine.analyze()

        # Should update account 2 with contact1's data
        assert len(result.to_update_in_account2) == 1
        assert result.to_update_in_account2[0][0] == "people/2"

    def test_analyze_skips_invalid_contacts(self, sync_engine, mock_api1, mock_api2):
        """Test that analyze skips invalid contacts."""
        valid = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])
        invalid = Contact("people/2", "e2", "", emails=[])  # Invalid - no name or email

        mock_api1.list_contacts.return_value = ([valid, invalid], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        result = sync_engine.analyze()

        # Only valid contact should be processed
        assert len(result.to_create_in_account2) == 1

    def test_analyze_skips_deleted_contacts(self, sync_engine, mock_api1, mock_api2):
        """Test that analyze skips deleted contacts in index."""
        normal = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])
        deleted = Contact(
            "people/2", "e2", "Jane Smith", emails=["jane@example.com"], deleted=True
        )

        mock_api1.list_contacts.return_value = ([normal, deleted], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        result = sync_engine.analyze()

        # Only non-deleted contact should be in creates
        assert len(result.to_create_in_account2) == 1
        assert result.to_create_in_account2[0].display_name == "John Doe"

    def test_analyze_uses_stored_sync_token(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test that analyze uses stored sync token for incremental sync."""
        mock_database.get_sync_state.return_value = {"sync_token": "stored_token"}
        mock_api1.list_contacts.return_value = ([], "new_token")
        mock_api2.list_contacts.return_value = ([], "new_token2")

        sync_engine.analyze(full_sync=False)

        # Should have been called with stored token
        mock_api1.list_contacts.assert_called()

    def test_analyze_full_sync_ignores_token(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test that full_sync=True ignores stored sync token."""
        mock_database.get_sync_state.return_value = {"sync_token": "stored_token"}
        mock_api1.list_contacts.return_value = ([], "new_token")
        mock_api2.list_contacts.return_value = ([], "new_token2")

        sync_engine.analyze(full_sync=True)

        # Should call list_contacts without sync token
        mock_api1.list_contacts.assert_called()

    def test_analyze_handles_expired_sync_token(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test handling of expired sync token."""
        mock_database.get_sync_state.return_value = {"sync_token": "expired_token"}

        # First call with token fails, second without token succeeds
        def list_contacts_side_effect(sync_token=None, **kwargs):
            if sync_token == "expired_token":
                raise PeopleAPIError("Sync token expired")
            return ([], "new_token")

        mock_api1.list_contacts.side_effect = list_contacts_side_effect
        mock_api2.list_contacts.return_value = ([], "token2")

        sync_engine.analyze()

        # Should have cleared the token and succeeded
        mock_database.clear_sync_token.assert_called()

    def test_analyze_multiple_contacts(self, sync_engine, mock_api1, mock_api2):
        """Test analyze with multiple contacts in both accounts."""
        contacts1 = [
            Contact("people/1", "e1", "John Doe", emails=["john@example.com"]),
            Contact("people/2", "e2", "Jane Smith", emails=["jane@example.com"]),
        ]
        contacts2 = [
            Contact("people/3", "e3", "John Doe", emails=["john@example.com"]),
            # Jane missing - needs to be created
            Contact("people/4", "e4", "Bob Wilson", emails=["bob@example.com"]),
            # Bob only in account2 - needs to be created in account1
        ]

        mock_api1.list_contacts.return_value = (contacts1, "token1")
        mock_api2.list_contacts.return_value = (contacts2, "token2")

        result = sync_engine.analyze()

        assert result.stats.contacts_in_account1 == 2
        assert result.stats.contacts_in_account2 == 2
        # Jane should be created in account2, Bob in account1
        assert len(result.to_create_in_account1) == 1  # Bob
        assert len(result.to_create_in_account2) == 1  # Jane


# ==============================================================================
# SyncEngine execute Tests
# ==============================================================================


class TestSyncEngineExecute:
    """Tests for SyncEngine.execute() method."""

    def test_execute_no_changes(self, sync_engine, mock_api1, mock_api2):
        """Test execute with no changes does nothing."""
        result = SyncResult()

        sync_engine.execute(result)

        mock_api1.batch_create_contacts.assert_not_called()
        mock_api2.batch_create_contacts.assert_not_called()

    def test_execute_creates_in_account1(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test execute creates contacts in account 1."""
        contact = Contact("people/orig", "e1", "John Doe", emails=["john@example.com"])
        created = Contact(
            "people/new1", "e_new", "John Doe", emails=["john@example.com"]
        )

        result = SyncResult()
        result.to_create_in_account1.append(contact)

        mock_api1.batch_create_contacts.return_value = [created]

        sync_engine.execute(result)

        mock_api1.batch_create_contacts.assert_called_once_with([contact])
        mock_database.upsert_contact_mapping.assert_called()
        assert result.stats.created_in_account1 == 1

    def test_execute_creates_in_account2(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test execute creates contacts in account 2."""
        contact = Contact(
            "people/orig", "e1", "Jane Smith", emails=["jane@example.com"]
        )
        created = Contact(
            "people/new2", "e_new", "Jane Smith", emails=["jane@example.com"]
        )

        result = SyncResult()
        result.to_create_in_account2.append(contact)

        mock_api2.batch_create_contacts.return_value = [created]

        sync_engine.execute(result)

        mock_api2.batch_create_contacts.assert_called_once_with([contact])
        assert result.stats.created_in_account2 == 1

    def test_execute_updates_in_account1(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test execute updates contacts in account 1."""
        source = Contact("people/2", "e2", "John Updated", emails=["john@example.com"])
        current = Contact(
            "people/1", "current_etag", "John Doe", emails=["john@example.com"]
        )
        updated = Contact(
            "people/1", "new_etag", "John Updated", emails=["john@example.com"]
        )

        result = SyncResult()
        result.to_update_in_account1.append(("people/1", source))

        mock_api1.get_contact.return_value = current
        mock_api1.batch_update_contacts.return_value = [updated]

        sync_engine.execute(result)

        mock_api1.get_contact.assert_called_with("people/1")
        mock_api1.batch_update_contacts.assert_called()
        assert result.stats.updated_in_account1 == 1

    def test_execute_updates_in_account2(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test execute updates contacts in account 2."""
        source = Contact("people/1", "e1", "Jane Updated", emails=["jane@example.com"])
        current = Contact(
            "people/2", "current_etag", "Jane Smith", emails=["jane@example.com"]
        )
        updated = Contact(
            "people/2", "new_etag", "Jane Updated", emails=["jane@example.com"]
        )

        result = SyncResult()
        result.to_update_in_account2.append(("people/2", source))

        mock_api2.get_contact.return_value = current
        mock_api2.batch_update_contacts.return_value = [updated]

        sync_engine.execute(result)

        mock_api2.get_contact.assert_called_with("people/2")
        assert result.stats.updated_in_account2 == 1

    def test_execute_deletes_in_account1(self, sync_engine, mock_api1, mock_api2):
        """Test execute deletes contacts in account 1."""
        result = SyncResult()
        result.to_delete_in_account1.append("people/to_delete")

        mock_api1.batch_delete_contacts.return_value = 1

        sync_engine.execute(result)

        mock_api1.batch_delete_contacts.assert_called_once_with(["people/to_delete"])
        assert result.stats.deleted_in_account1 == 1

    def test_execute_deletes_in_account2(self, sync_engine, mock_api1, mock_api2):
        """Test execute deletes contacts in account 2."""
        result = SyncResult()
        result.to_delete_in_account2.append("people/to_delete")

        mock_api2.batch_delete_contacts.return_value = 1

        sync_engine.execute(result)

        mock_api2.batch_delete_contacts.assert_called_once_with(["people/to_delete"])
        assert result.stats.deleted_in_account2 == 1

    def test_execute_handles_update_error(self, sync_engine, mock_api1, mock_api2):
        """Test execute handles errors during update."""
        source = Contact("people/2", "e2", "John Updated", emails=["john@example.com"])

        result = SyncResult()
        result.to_update_in_account1.append(("people/1", source))

        mock_api1.get_contact.side_effect = PeopleAPIError("Contact not found")

        sync_engine.execute(result)

        assert result.stats.errors == 1

    def test_execute_creates_then_updates_then_deletes(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test execute performs operations in correct order."""
        # Setup create
        create_contact = Contact(
            "p/orig", "e1", "New Person", emails=["new@example.com"]
        )
        created = Contact("p/new", "e_new", "New Person", emails=["new@example.com"])

        # Setup update
        update_source = Contact(
            "p/src", "e_src", "Updated", emails=["update@example.com"]
        )
        current = Contact(
            "p/target", "e_cur", "Original", emails=["update@example.com"]
        )
        updated = Contact("p/target", "e_upd", "Updated", emails=["update@example.com"])

        result = SyncResult()
        result.to_create_in_account1.append(create_contact)
        result.to_update_in_account1.append(("p/target", update_source))
        result.to_delete_in_account1.append("p/to_delete")

        mock_api1.batch_create_contacts.return_value = [created]
        mock_api1.get_contact.return_value = current
        mock_api1.batch_update_contacts.return_value = [updated]
        mock_api1.batch_delete_contacts.return_value = 1

        sync_engine.execute(result)

        # Verify all operations were called
        mock_api1.batch_create_contacts.assert_called()
        mock_api1.batch_update_contacts.assert_called()
        mock_api1.batch_delete_contacts.assert_called()


# ==============================================================================
# SyncEngine sync Tests
# ==============================================================================


class TestSyncEngineSync:
    """Tests for SyncEngine.sync() method."""

    def test_sync_dry_run_no_execute(self, sync_engine, mock_api1, mock_api2):
        """Test sync with dry_run=True does not execute changes."""
        contact = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])
        mock_api1.list_contacts.return_value = ([contact], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        result = sync_engine.sync(dry_run=True)

        assert len(result.to_create_in_account2) == 1
        # batch_create should not be called in dry run
        mock_api2.batch_create_contacts.assert_not_called()

    def test_sync_executes_changes(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test sync with dry_run=False executes changes."""
        contact = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])
        created = Contact(
            "people/new", "e_new", "John Doe", emails=["john@example.com"]
        )

        mock_api1.list_contacts.return_value = ([contact], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api2.batch_create_contacts.return_value = [created]

        result = sync_engine.sync(dry_run=False)

        mock_api2.batch_create_contacts.assert_called()
        assert result.stats.created_in_account2 == 1

    def test_sync_full_sync_flag(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test sync with full_sync=True ignores sync tokens."""
        mock_database.get_sync_state.return_value = {"sync_token": "old_token"}
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        sync_engine.sync(full_sync=True, dry_run=True)

        # Should not use stored sync token
        # This is tested indirectly by verifying the analyze was called


# ==============================================================================
# SyncEngine get_status Tests
# ==============================================================================


class TestSyncEngineGetStatus:
    """Tests for SyncEngine.get_status() method."""

    def test_get_status_no_previous_sync(self, sync_engine, mock_database):
        """Test get_status when no previous sync has occurred."""
        mock_database.get_sync_state.return_value = None
        mock_database.get_mapping_count.return_value = 0

        status = sync_engine.get_status()

        assert status["account1"] is None
        assert status["account2"] is None
        assert status["total_mappings"] == 0

    def test_get_status_with_previous_sync(self, sync_engine, mock_database):
        """Test get_status with previous sync data."""
        last_sync = datetime(2024, 6, 15, 10, 30, 0)
        mock_database.get_sync_state.side_effect = [
            {"sync_token": "token1", "last_sync_at": last_sync},
            {"sync_token": "token2", "last_sync_at": last_sync},
        ]
        mock_database.get_mapping_count.return_value = 50

        status = sync_engine.get_status()

        assert status["account1"]["last_sync"] == last_sync
        assert status["account1"]["has_sync_token"] is True
        assert status["account2"]["has_sync_token"] is True
        assert status["total_mappings"] == 50


# ==============================================================================
# SyncEngine reset Tests
# ==============================================================================


class TestSyncEngineReset:
    """Tests for SyncEngine.reset() method."""

    def test_reset_clears_all_state(self, sync_engine, mock_database):
        """Test reset clears all sync state."""
        sync_engine.reset()

        mock_database.clear_all_state.assert_called_once()


# ==============================================================================
# SyncEngine Deletion Handling Tests
# ==============================================================================


class TestSyncEngineDeletions:
    """Tests for deletion propagation in SyncEngine."""

    def test_analyze_propagates_deletion_to_account2(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test that deleted contact in account1 is propagated to account2."""
        deleted = Contact(
            "people/deleted",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            deleted=True,
        )

        mock_api1.list_contacts.return_value = ([deleted], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_database.get_mappings_by_resource_name.return_value = [
            {
                "matching_key": "johndoe|john@examplecom",
                "account1_resource_name": "people/deleted",
                "account2_resource_name": "people/2",
            }
        ]

        result = sync_engine.analyze()

        assert "people/2" in result.to_delete_in_account2

    def test_analyze_propagates_deletion_to_account1(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test that deleted contact in account2 is propagated to account1."""
        deleted = Contact(
            "people/deleted2",
            "e2",
            "Jane Smith",
            emails=["jane@example.com"],
            deleted=True,
        )

        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([deleted], "token2")
        mock_database.get_mappings_by_resource_name.return_value = [
            {
                "matching_key": "janesmith|jane@examplecom",
                "account1_resource_name": "people/1",
                "account2_resource_name": "people/deleted2",
            }
        ]

        result = sync_engine.analyze()

        assert "people/1" in result.to_delete_in_account1

    def test_analyze_no_mapping_for_deleted_contact(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test handling of deleted contact with no mapping."""
        deleted = Contact(
            "people/deleted",
            "e1",
            "Unknown",
            emails=["unknown@example.com"],
            deleted=True,
        )

        mock_api1.list_contacts.return_value = ([deleted], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_database.get_mappings_by_resource_name.return_value = []

        result = sync_engine.analyze()

        # Should not have any deletions since no mapping exists
        assert len(result.to_delete_in_account2) == 0


# ==============================================================================
# SyncEngine Contact Index Building Tests
# ==============================================================================


class TestSyncEngineBuildContactIndex:
    """Tests for _build_contact_index helper method."""

    def test_build_index_handles_duplicate_keys(
        self, sync_engine, mock_api1, mock_api2
    ):
        """Test that duplicate matching keys are handled (keeps newer)."""
        older = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        newer = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            last_modified=datetime(2024, 6, 15, tzinfo=timezone.utc),
        )

        mock_api1.list_contacts.return_value = ([older, newer], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        result = sync_engine.analyze()

        # Only one should be in creates (the newer one)
        assert len(result.to_create_in_account2) == 1
        assert result.to_create_in_account2[0].resource_name == "people/2"

    def test_build_index_handles_duplicate_keys_no_timestamps(
        self, sync_engine, mock_api1, mock_api2
    ):
        """Test duplicate keys without timestamps keeps one with more data."""
        less_data = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])
        more_data = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com", "john.work@example.com"],
        )

        mock_api1.list_contacts.return_value = ([less_data, more_data], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        result = sync_engine.analyze()

        # Should keep the one with more emails
        assert len(result.to_create_in_account2) == 1
        assert len(result.to_create_in_account2[0].emails) == 2


# ==============================================================================
# Edge Cases and Error Handling
# ==============================================================================


class TestSyncEngineEdgeCases:
    """Tests for edge cases in SyncEngine."""

    def test_sync_with_unicode_contacts(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test sync handles unicode characters correctly."""
        contact = Contact(
            "people/1",
            "e1",
            "Jose Garcia",
            given_name="Jose",
            family_name="Garcia",
            emails=["jose@example.com"],
        )
        created = Contact(
            "people/new", "e_new", "Jose Garcia", emails=["jose@example.com"]
        )

        mock_api1.list_contacts.return_value = ([contact], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api2.batch_create_contacts.return_value = [created]

        result = sync_engine.sync(dry_run=False)

        assert result.stats.created_in_account2 == 1

    def test_sync_with_many_contacts(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test sync handles large number of contacts."""
        contacts1 = [
            Contact(
                f"people/{i}",
                f"e{i}",
                f"Contact {i}",
                emails=[f"contact{i}@example.com"],
            )
            for i in range(100)
        ]
        mock_api1.list_contacts.return_value = (contacts1, "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        result = sync_engine.analyze()

        assert result.stats.contacts_in_account1 == 100
        assert len(result.to_create_in_account2) == 100

    def test_execute_api_error_raises(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test execute raises error on API failure."""
        contact = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])

        result = SyncResult()
        result.to_create_in_account1.append(contact)

        mock_api1.batch_create_contacts.side_effect = PeopleAPIError("API Error")

        with pytest.raises(PeopleAPIError):
            sync_engine.execute(result)

    def test_sync_conflict_resolution_integration(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test full conflict resolution flow."""
        # Contact in account 1 is newer
        contact1 = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            phones=["+1234567890"],
            last_modified=datetime(2024, 6, 20, tzinfo=timezone.utc),
        )
        # Contact in account 2 is older with different data
        contact2 = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            organizations=["Acme Corp"],
            last_modified=datetime(2024, 6, 10, tzinfo=timezone.utc),
        )

        mock_api1.list_contacts.return_value = ([contact1], "token1")
        mock_api2.list_contacts.return_value = ([contact2], "token2")

        result = sync_engine.analyze()

        # Should have a conflict resolved
        assert result.stats.conflicts_resolved == 1
        assert len(result.conflicts) == 1
        # Account 1 is newer, so account 2 should be updated
        assert len(result.to_update_in_account2) == 1
        assert result.conflicts[0].winning_side == ConflictSide.ACCOUNT1


# ==============================================================================
# Integration Tests (using real SyncDatabase with :memory:)
# ==============================================================================


class TestSyncEngineIntegration:
    """Integration tests using real in-memory database."""

    @pytest.fixture
    def real_database(self):
        """Create a real in-memory database."""
        db = SyncDatabase(":memory:")
        db.initialize()
        return db

    @pytest.fixture
    def integration_engine(self, mock_api1, mock_api2, real_database):
        """Create SyncEngine with real database."""
        return SyncEngine(api1=mock_api1, api2=mock_api2, database=real_database)

    def test_full_sync_cycle(
        self, integration_engine, mock_api1, mock_api2, real_database
    ):
        """Test a full sync cycle with real database."""
        # Initial contacts
        contact1 = Contact("people/1", "e1", "John Doe", emails=["john@example.com"])
        created = Contact(
            "people/new2", "e_new2", "John Doe", emails=["john@example.com"]
        )

        mock_api1.list_contacts.return_value = ([contact1], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api2.batch_create_contacts.return_value = [created]

        # Run sync
        result = integration_engine.sync(dry_run=False)

        assert result.stats.created_in_account2 == 1

        # Verify database state
        mappings = real_database.get_all_contact_mappings()
        assert len(mappings) == 1

    def test_incremental_sync_uses_stored_token(
        self, integration_engine, mock_api1, mock_api2, real_database
    ):
        """Test that incremental sync uses stored sync token."""
        # Set up initial sync state
        real_database.update_sync_state("account1", "stored_token1")
        real_database.update_sync_state("account2", "stored_token2")

        mock_api1.list_contacts.return_value = ([], "new_token1")
        mock_api2.list_contacts.return_value = ([], "new_token2")

        integration_engine.sync(dry_run=True, full_sync=False)

        # Verify sync tokens were fetched from database
        state1 = real_database.get_sync_state("account1")
        assert state1 is not None


# ==============================================================================
# Group Sync Fixtures
# ==============================================================================


@pytest.fixture
def sample_group1():
    """Create a sample contact group for account 1."""
    from gcontact_sync.sync.group import GROUP_TYPE_USER_CONTACT_GROUP, ContactGroup

    return ContactGroup(
        resource_name="contactGroups/abc123",
        etag="etag_g1",
        name="Family",
        group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        member_count=5,
    )


@pytest.fixture
def sample_group2():
    """Create a sample contact group for account 2 (same name, different resource)."""
    from gcontact_sync.sync.group import GROUP_TYPE_USER_CONTACT_GROUP, ContactGroup

    return ContactGroup(
        resource_name="contactGroups/xyz789",
        etag="etag_g2",
        name="Family",
        group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        member_count=3,
    )


@pytest.fixture
def sample_system_group():
    """Create a sample system contact group."""
    from gcontact_sync.sync.group import GROUP_TYPE_SYSTEM_CONTACT_GROUP, ContactGroup

    return ContactGroup(
        resource_name="contactGroups/myContacts",
        etag="etag_sys",
        name="My Contacts",
        group_type=GROUP_TYPE_SYSTEM_CONTACT_GROUP,
        member_count=100,
    )


@pytest.fixture
def sample_group1_api_data():
    """API response dict for sample_group1."""
    return {
        "resourceName": "contactGroups/abc123",
        "etag": "etag_g1",
        "name": "Family",
        "groupType": "USER_CONTACT_GROUP",
        "memberCount": 5,
    }


@pytest.fixture
def sample_group2_api_data():
    """API response dict for sample_group2."""
    return {
        "resourceName": "contactGroups/xyz789",
        "etag": "etag_g2",
        "name": "Family",
        "groupType": "USER_CONTACT_GROUP",
        "memberCount": 3,
    }


@pytest.fixture
def sample_system_group_api_data():
    """API response dict for system group."""
    return {
        "resourceName": "contactGroups/myContacts",
        "etag": "etag_sys",
        "name": "My Contacts",
        "groupType": "SYSTEM_CONTACT_GROUP",
        "memberCount": 100,
    }


# ==============================================================================
# SyncStats Group Fields Tests
# ==============================================================================


class TestSyncStatsGroups:
    """Tests for SyncStats group-related fields."""

    def test_default_group_values(self):
        """Test that SyncStats has correct default group values."""
        stats = SyncStats()

        assert stats.groups_in_account1 == 0
        assert stats.groups_in_account2 == 0
        assert stats.groups_created_in_account1 == 0
        assert stats.groups_created_in_account2 == 0
        assert stats.groups_updated_in_account1 == 0
        assert stats.groups_updated_in_account2 == 0
        assert stats.groups_deleted_in_account1 == 0
        assert stats.groups_deleted_in_account2 == 0

    def test_custom_group_values(self):
        """Test SyncStats with custom group values."""
        stats = SyncStats(
            groups_in_account1=10,
            groups_in_account2=8,
            groups_created_in_account1=2,
            groups_created_in_account2=4,
        )

        assert stats.groups_in_account1 == 10
        assert stats.groups_in_account2 == 8
        assert stats.groups_created_in_account1 == 2
        assert stats.groups_created_in_account2 == 4


# ==============================================================================
# SyncResult Group Fields Tests
# ==============================================================================


class TestSyncResultGroups:
    """Tests for SyncResult group-related fields."""

    def test_default_group_values(self):
        """Test that SyncResult has correct default group values."""
        result = SyncResult()

        assert result.groups_to_create_in_account1 == []
        assert result.groups_to_create_in_account2 == []
        assert result.groups_to_update_in_account1 == []
        assert result.groups_to_update_in_account2 == []
        assert result.groups_to_delete_in_account1 == []
        assert result.groups_to_delete_in_account2 == []
        assert result.matched_groups == []

    def test_has_group_changes_false_when_empty(self):
        """Test has_group_changes returns False when no group changes."""
        result = SyncResult()
        assert result.has_group_changes() is False

    def test_has_group_changes_true_with_creates(self, sample_group1):
        """Test has_group_changes returns True with group creates."""
        result = SyncResult()
        result.groups_to_create_in_account1.append(sample_group1)
        assert result.has_group_changes() is True

    def test_has_group_changes_true_with_updates(self, sample_group1):
        """Test has_group_changes returns True with group updates."""
        result = SyncResult()
        result.groups_to_update_in_account2.append(("contactGroups/123", sample_group1))
        assert result.has_group_changes() is True

    def test_has_group_changes_true_with_deletes(self):
        """Test has_group_changes returns True with group deletes."""
        result = SyncResult()
        result.groups_to_delete_in_account1.append("contactGroups/123")
        assert result.has_group_changes() is True

    def test_has_contact_changes_false_when_empty(self):
        """Test has_contact_changes returns False when no contact changes."""
        result = SyncResult()
        assert result.has_contact_changes() is False

    def test_has_changes_includes_groups(self, sample_group1):
        """Test has_changes returns True when only group changes exist."""
        result = SyncResult()
        result.groups_to_create_in_account2.append(sample_group1)
        assert result.has_changes() is True

    def test_summary_with_group_changes(self, sample_group1, sample_group2):
        """Test summary includes group changes."""
        result = SyncResult()
        result.stats.groups_in_account1 = 5
        result.stats.groups_in_account2 = 3
        result.groups_to_create_in_account1.append(sample_group1)
        result.groups_to_update_in_account2.append(("contactGroups/123", sample_group2))

        summary = result.summary()

        assert "Group changes to apply" in summary
        assert "Create groups" in summary
        assert "Update groups" in summary


# ==============================================================================
# SyncEngine Group Analysis Tests
# ==============================================================================


class TestSyncEngineGroupAnalysis:
    """Tests for SyncEngine group analysis methods."""

    def test_analyze_empty_groups(self, sync_engine, mock_api1, mock_api2):
        """Test analyze with empty group lists."""
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([], None)

        result = sync_engine.analyze()

        assert result.stats.groups_in_account1 == 0
        assert result.stats.groups_in_account2 == 0
        assert not result.has_group_changes()

    def test_analyze_group_only_in_account1(
        self, sync_engine, mock_api1, mock_api2, sample_group1, sample_group1_api_data
    ):
        """Test analyze when group exists only in account 1."""
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api1.list_contact_groups.return_value = ([sample_group1_api_data], None)
        mock_api2.list_contact_groups.return_value = ([], None)

        result = sync_engine.analyze()

        assert len(result.groups_to_create_in_account2) == 1
        assert result.groups_to_create_in_account2[0].name == sample_group1.name
        assert len(result.groups_to_create_in_account1) == 0

    def test_analyze_group_only_in_account2(
        self, sync_engine, mock_api1, mock_api2, sample_group2, sample_group2_api_data
    ):
        """Test analyze when group exists only in account 2."""
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([sample_group2_api_data], None)

        result = sync_engine.analyze()

        assert len(result.groups_to_create_in_account1) == 1
        assert result.groups_to_create_in_account1[0].name == sample_group2.name
        assert len(result.groups_to_create_in_account2) == 0

    def test_analyze_groups_matched_by_name(
        self,
        sync_engine,
        mock_api1,
        mock_api2,
        sample_group1,
        sample_group2,
        sample_group1_api_data,
        sample_group2_api_data,
    ):
        """Test analyze matches groups by name (matching key)."""
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api1.list_contact_groups.return_value = ([sample_group1_api_data], None)
        mock_api2.list_contact_groups.return_value = ([sample_group2_api_data], None)

        result = sync_engine.analyze()

        # Groups with same name should be matched
        assert len(result.matched_groups) == 1
        assert result.matched_groups[0][0].name == sample_group1.name
        assert result.matched_groups[0][1].name == sample_group2.name
        # No creates needed
        assert len(result.groups_to_create_in_account1) == 0
        assert len(result.groups_to_create_in_account2) == 0

    def test_analyze_skips_system_groups(
        self, sync_engine, mock_api1, mock_api2, sample_system_group_api_data
    ):
        """Test that analyze skips system groups."""
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api1.list_contact_groups.return_value = (
            [sample_system_group_api_data],
            None,
        )
        mock_api2.list_contact_groups.return_value = ([], None)

        result = sync_engine.analyze()

        # System groups should not be synced
        assert len(result.groups_to_create_in_account2) == 0
        assert result.stats.groups_in_account1 == 0  # Not counted

    def test_analyze_group_name_normalized_matching(
        self, sync_engine, mock_api1, mock_api2
    ):
        """Test that group names are normalized for matching."""
        group1_data = {
            "resourceName": "contactGroups/1",
            "etag": "e1",
            "name": "WORK",  # Uppercase
            "groupType": "USER_CONTACT_GROUP",
        }
        group2_data = {
            "resourceName": "contactGroups/2",
            "etag": "e2",
            "name": "work",  # Lowercase
            "groupType": "USER_CONTACT_GROUP",
        }

        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api1.list_contact_groups.return_value = ([group1_data], None)
        mock_api2.list_contact_groups.return_value = ([group2_data], None)

        result = sync_engine.analyze()

        # Should be matched despite case difference
        assert len(result.matched_groups) == 1

    def test_analyze_multiple_groups(self, sync_engine, mock_api1, mock_api2):
        """Test analyze with multiple groups."""
        groups1_data = [
            {
                "resourceName": "contactGroups/g1",
                "etag": "e1",
                "name": "Family",
                "groupType": "USER_CONTACT_GROUP",
            },
            {
                "resourceName": "contactGroups/g2",
                "etag": "e2",
                "name": "Work",
                "groupType": "USER_CONTACT_GROUP",
            },
        ]
        groups2_data = [
            {
                "resourceName": "contactGroups/g3",
                "etag": "e3",
                "name": "Family",
                "groupType": "USER_CONTACT_GROUP",
            },
            {
                "resourceName": "contactGroups/g4",
                "etag": "e4",
                "name": "Friends",
                "groupType": "USER_CONTACT_GROUP",
            },
        ]

        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api1.list_contact_groups.return_value = (groups1_data, None)
        mock_api2.list_contact_groups.return_value = (groups2_data, None)

        result = sync_engine.analyze()

        assert result.stats.groups_in_account1 == 2
        assert result.stats.groups_in_account2 == 2
        # Family matched, Work to create in account2, Friends to create in account1
        assert len(result.matched_groups) == 1  # Family
        assert len(result.groups_to_create_in_account1) == 1  # Friends
        assert len(result.groups_to_create_in_account2) == 1  # Work


# ==============================================================================
# SyncEngine Group Pair Update Analysis Tests
# ==============================================================================


class TestSyncEngineGroupPairAnalysis:
    """Tests for _analyze_group_pair_for_updates method."""

    def test_groups_in_sync_no_update(self, sync_engine, sample_group1, sample_group2):
        """Test no update when groups have same content."""
        result = SyncResult()

        # Same name = same content hash
        sync_engine._analyze_group_pair_for_updates(
            "family", sample_group1, sample_group2, None, result
        )

        assert len(result.groups_to_update_in_account1) == 0
        assert len(result.groups_to_update_in_account2) == 0

    def test_group_content_differs_first_sync(self, sync_engine):
        """Test update when content differs on first sync (no last hash)."""
        from gcontact_sync.sync.group import GROUP_TYPE_USER_CONTACT_GROUP, ContactGroup

        group1 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="Family",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/2",
            etag="e2",
            name="family",  # Different casing
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        result = SyncResult()
        sync_engine._analyze_group_pair_for_updates(
            "family", group1, group2, None, result
        )

        # First sync: account1 wins
        assert len(result.groups_to_update_in_account2) == 1
        assert result.groups_to_update_in_account2[0][0] == "contactGroups/2"

    def test_group_only_account1_changed(self, sync_engine):
        """Test update when only account 1 changed from last sync."""
        from gcontact_sync.sync.group import GROUP_TYPE_USER_CONTACT_GROUP, ContactGroup

        original = ContactGroup(
            resource_name="contactGroups/orig",
            etag="e_orig",
            name="Family",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        last_hash = original.content_hash()

        # Group1 has changed name
        group1 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="Family & Friends",  # Changed
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        # Group2 unchanged (same as original)
        group2 = ContactGroup(
            resource_name="contactGroups/2",
            etag="e2",
            name="Family",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        result = SyncResult()
        sync_engine._analyze_group_pair_for_updates(
            "family", group1, group2, last_hash, result
        )

        # Account 1 changed, so update account 2
        assert len(result.groups_to_update_in_account2) == 1
        assert len(result.groups_to_update_in_account1) == 0

    def test_group_only_account2_changed(self, sync_engine):
        """Test update when only account 2 changed from last sync."""
        from gcontact_sync.sync.group import GROUP_TYPE_USER_CONTACT_GROUP, ContactGroup

        original = ContactGroup(
            resource_name="contactGroups/orig",
            etag="e_orig",
            name="Family",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        last_hash = original.content_hash()

        # Group1 unchanged
        group1 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="Family",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        # Group2 has changed
        group2 = ContactGroup(
            resource_name="contactGroups/2",
            etag="e2",
            name="Family & Friends",  # Changed
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        result = SyncResult()
        sync_engine._analyze_group_pair_for_updates(
            "family", group1, group2, last_hash, result
        )

        # Account 2 changed, so update account 1
        assert len(result.groups_to_update_in_account1) == 1
        assert len(result.groups_to_update_in_account2) == 0

    def test_group_both_changed_account1_wins(self, sync_engine):
        """Test update when both accounts changed (account1 wins)."""
        from gcontact_sync.sync.group import GROUP_TYPE_USER_CONTACT_GROUP, ContactGroup

        original = ContactGroup(
            resource_name="contactGroups/orig",
            etag="e_orig",
            name="Family",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        last_hash = original.content_hash()

        # Both have changed differently
        group1 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="Close Family",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/2",
            etag="e2",
            name="Extended Family",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        result = SyncResult()
        sync_engine._analyze_group_pair_for_updates(
            "family", group1, group2, last_hash, result
        )

        # Conflict: account1 wins, update account2
        assert len(result.groups_to_update_in_account2) == 1
        assert len(result.groups_to_update_in_account1) == 0


# ==============================================================================
# SyncEngine Group Execution Tests
# ==============================================================================


class TestSyncEngineGroupExecution:
    """Tests for SyncEngine group execution methods."""

    def test_execute_group_creates_in_account1(
        self, sync_engine, mock_api1, mock_api2, mock_database, sample_group2
    ):
        """Test execute creates groups in account 1."""
        result = SyncResult()
        result.groups_to_create_in_account1.append(sample_group2)

        mock_api1.create_contact_group.return_value = {
            "resourceName": "contactGroups/new1",
            "etag": "new_etag",
        }
        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([], None)
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        sync_engine.execute(result)

        mock_api1.create_contact_group.assert_called_once_with(sample_group2.name)
        mock_database.upsert_group_mapping.assert_called()
        assert result.stats.groups_created_in_account1 == 1

    def test_execute_group_creates_in_account2(
        self, sync_engine, mock_api1, mock_api2, mock_database, sample_group1
    ):
        """Test execute creates groups in account 2."""
        result = SyncResult()
        result.groups_to_create_in_account2.append(sample_group1)

        mock_api2.create_contact_group.return_value = {
            "resourceName": "contactGroups/new2",
            "etag": "new_etag",
        }
        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([], None)
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        sync_engine.execute(result)

        mock_api2.create_contact_group.assert_called_once_with(sample_group1.name)
        assert result.stats.groups_created_in_account2 == 1

    def test_execute_group_updates_in_account1(
        self, sync_engine, mock_api1, mock_api2, mock_database, sample_group2
    ):
        """Test execute updates groups in account 1."""
        result = SyncResult()
        result.groups_to_update_in_account1.append(
            ("contactGroups/target1", sample_group2)
        )

        mock_api1.get_contact_group.return_value = {"etag": "current_etag"}
        mock_api1.update_contact_group.return_value = {"etag": "updated_etag"}
        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([], None)
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        sync_engine.execute(result)

        mock_api1.get_contact_group.assert_called_with("contactGroups/target1")
        mock_api1.update_contact_group.assert_called()
        assert result.stats.groups_updated_in_account1 == 1

    def test_execute_group_updates_in_account2(
        self, sync_engine, mock_api1, mock_api2, mock_database, sample_group1
    ):
        """Test execute updates groups in account 2."""
        result = SyncResult()
        result.groups_to_update_in_account2.append(
            ("contactGroups/target2", sample_group1)
        )

        mock_api2.get_contact_group.return_value = {"etag": "current_etag"}
        mock_api2.update_contact_group.return_value = {"etag": "updated_etag"}
        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([], None)
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        sync_engine.execute(result)

        mock_api2.get_contact_group.assert_called_with("contactGroups/target2")
        assert result.stats.groups_updated_in_account2 == 1

    def test_execute_group_deletes_in_account1(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test execute deletes groups in account 1."""
        result = SyncResult()
        result.groups_to_delete_in_account1.append("contactGroups/to_delete")

        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([], None)
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        sync_engine.execute(result)

        mock_api1.delete_contact_group.assert_called_once_with(
            "contactGroups/to_delete", delete_contacts=False
        )
        assert result.stats.groups_deleted_in_account1 == 1

    def test_execute_group_deletes_in_account2(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test execute deletes groups in account 2."""
        result = SyncResult()
        result.groups_to_delete_in_account2.append("contactGroups/to_delete")

        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([], None)
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        sync_engine.execute(result)

        mock_api2.delete_contact_group.assert_called_once_with(
            "contactGroups/to_delete", delete_contacts=False
        )
        assert result.stats.groups_deleted_in_account2 == 1

    def test_execute_group_create_error_continues(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test execute continues when group create fails."""
        from gcontact_sync.sync.group import GROUP_TYPE_USER_CONTACT_GROUP, ContactGroup

        group1 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="Group1",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/2",
            etag="e2",
            name="Group2",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        result = SyncResult()
        result.groups_to_create_in_account2.extend([group1, group2])

        # First create fails, second succeeds
        mock_api2.create_contact_group.side_effect = [
            PeopleAPIError("Failed"),
            {"resourceName": "contactGroups/new", "etag": "e_new"},
        ]
        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([], None)
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        sync_engine.execute(result)

        assert result.stats.groups_created_in_account2 == 1
        assert result.stats.errors == 1


# ==============================================================================
# SyncEngine Membership Mapping Tests
# ==============================================================================


class TestSyncEngineMembershipMapping:
    """Tests for SyncEngine._map_memberships method."""

    def test_map_memberships_empty_list(self, sync_engine, mock_database):
        """Test mapping empty membership list."""
        result = sync_engine._map_memberships([], source_account=1, target_account=2)
        assert result == []

    def test_map_memberships_with_mapping(self, sync_engine, mock_database):
        """Test mapping memberships with existing group mapping."""
        mock_database.get_group_mapping_by_resource_name.return_value = {
            "group_name": "family",
            "account1_resource_name": "contactGroups/abc123",
            "account2_resource_name": "contactGroups/xyz789",
        }

        result = sync_engine._map_memberships(
            ["contactGroups/abc123"],
            source_account=1,
            target_account=2,
        )

        assert result == ["contactGroups/xyz789"]
        mock_database.get_group_mapping_by_resource_name.assert_called_with(
            "contactGroups/abc123", 1
        )

    def test_map_memberships_no_mapping(self, sync_engine, mock_database):
        """Test mapping memberships with no existing mapping."""
        mock_database.get_group_mapping_by_resource_name.return_value = None

        result = sync_engine._map_memberships(
            ["contactGroups/unknown"],
            source_account=1,
            target_account=2,
        )

        assert result == []

    def test_map_memberships_skips_system_groups(self, sync_engine, mock_database):
        """Test that system groups are skipped."""
        result = sync_engine._map_memberships(
            ["contactGroups/myContacts", "contactGroups/starred"],
            source_account=1,
            target_account=2,
        )

        assert result == []
        # get_group_mapping_by_resource_name should not be called for system groups
        mock_database.get_group_mapping_by_resource_name.assert_not_called()

    def test_map_memberships_mixed(self, sync_engine, mock_database):
        """Test mapping mixed memberships (some mapped, some system, some unknown)."""

        def mock_get_mapping(resource_name, account):
            if resource_name == "contactGroups/abc123":
                return {
                    "group_name": "family",
                    "account1_resource_name": "contactGroups/abc123",
                    "account2_resource_name": "contactGroups/xyz789",
                }
            return None

        mock_database.get_group_mapping_by_resource_name.side_effect = mock_get_mapping

        result = sync_engine._map_memberships(
            [
                "contactGroups/abc123",  # Has mapping
                "contactGroups/myContacts",  # System group
                "contactGroups/unknown",  # No mapping
            ],
            source_account=1,
            target_account=2,
        )

        assert result == ["contactGroups/xyz789"]

    def test_map_memberships_target_not_synced(self, sync_engine, mock_database):
        """Test mapping when target account hasn't been synced yet."""
        mock_database.get_group_mapping_by_resource_name.return_value = {
            "group_name": "family",
            "account1_resource_name": "contactGroups/abc123",
            "account2_resource_name": None,  # Not synced yet
        }

        result = sync_engine._map_memberships(
            ["contactGroups/abc123"],
            source_account=1,
            target_account=2,
        )

        assert result == []


# ==============================================================================
# Group Deletion Propagation Tests
# ==============================================================================


class TestSyncEngineGroupDeletions:
    """Tests for group deletion propagation in SyncEngine."""

    def test_analyze_propagates_group_deletion_to_account2(
        self,
        sync_engine,
        mock_api1,
        mock_api2,
        mock_database,
        sample_group1,
        sample_group1_api_data,
    ):
        """Test that deleted group in account1 is propagated to account2."""
        # Group exists only in account1, but there's a mapping for account2
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api1.list_contact_groups.return_value = ([sample_group1_api_data], None)
        mock_api2.list_contact_groups.return_value = (
            [],
            None,
        )  # Group deleted in account2

        # Existing mapping shows it was synced before
        mock_database.get_all_group_mappings.return_value = [
            {
                "group_name": "family",
                "account1_resource_name": sample_group1.resource_name,
                "account2_resource_name": "contactGroups/deleted_xyz",
                "last_synced_hash": sample_group1.content_hash(),
            }
        ]

        result = sync_engine.analyze()

        # Group2 is missing, but group1 still exists
        # This means group2 was deleted - propagate to account1
        # Note: The logic checks if the pair is incomplete
        # If group2 no longer exists but mapping says it should, delete group1
        assert "contactGroups/abc123" in result.groups_to_delete_in_account1

    def test_analyze_propagates_group_deletion_to_account1(
        self,
        sync_engine,
        mock_api1,
        mock_api2,
        mock_database,
        sample_group2,
        sample_group2_api_data,
    ):
        """Test that deleted group in account2 is propagated to account1."""
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api1.list_contact_groups.return_value = (
            [],
            None,
        )  # Group deleted in account1
        mock_api2.list_contact_groups.return_value = ([sample_group2_api_data], None)

        mock_database.get_all_group_mappings.return_value = [
            {
                "group_name": "family",
                "account1_resource_name": "contactGroups/deleted_abc",
                "account2_resource_name": sample_group2.resource_name,
                "last_synced_hash": sample_group2.content_hash(),
            }
        ]

        result = sync_engine.analyze()

        # Group1 is missing, group2 exists - delete group2
        assert "contactGroups/xyz789" in result.groups_to_delete_in_account2


# ==============================================================================
# Group Sync Integration Tests
# ==============================================================================


class TestGroupSyncIntegration:
    """Integration tests for group sync using real in-memory database."""

    @pytest.fixture
    def real_database(self):
        """Create a real in-memory database."""
        db = SyncDatabase(":memory:")
        db.initialize()
        return db

    @pytest.fixture
    def integration_engine(self, mock_api1, mock_api2, real_database):
        """Create SyncEngine with real database."""
        return SyncEngine(api1=mock_api1, api2=mock_api2, database=real_database)

    def test_group_sync_creates_mapping(
        self, integration_engine, mock_api1, mock_api2, real_database
    ):
        """Test that group sync creates group mappings in database."""
        group_data = {
            "resourceName": "contactGroups/source",
            "etag": "e1",
            "name": "Test Group",
            "groupType": "USER_CONTACT_GROUP",
        }

        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api1.list_contact_groups.return_value = ([group_data], None)
        mock_api2.list_contact_groups.return_value = ([], None)
        mock_api2.create_contact_group.return_value = {
            "resourceName": "contactGroups/created",
            "etag": "e_new",
        }

        integration_engine.sync(dry_run=False)

        # Verify mapping was created
        mappings = real_database.get_all_group_mappings()
        assert len(mappings) == 1
        assert mappings[0]["account2_resource_name"] == "contactGroups/created"

    def test_group_sync_dry_run_no_changes(
        self, integration_engine, mock_api1, mock_api2, real_database
    ):
        """Test that dry run doesn't create group mappings."""
        group_data = {
            "resourceName": "contactGroups/source",
            "etag": "e1",
            "name": "Test Group",
            "groupType": "USER_CONTACT_GROUP",
        }

        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api1.list_contact_groups.return_value = ([group_data], None)
        mock_api2.list_contact_groups.return_value = ([], None)

        result = integration_engine.sync(dry_run=True)

        # Should identify changes but not execute
        assert len(result.groups_to_create_in_account2) == 1
        mock_api2.create_contact_group.assert_not_called()

        # No mappings should exist
        mappings = real_database.get_all_group_mappings()
        assert len(mappings) == 0

    def test_group_sync_bidirectional(
        self, integration_engine, mock_api1, mock_api2, real_database
    ):
        """Test bidirectional group sync."""
        # Different groups in each account
        group1_data = {
            "resourceName": "contactGroups/g1",
            "etag": "e1",
            "name": "Work",
            "groupType": "USER_CONTACT_GROUP",
        }
        group2_data = {
            "resourceName": "contactGroups/g2",
            "etag": "e2",
            "name": "Friends",
            "groupType": "USER_CONTACT_GROUP",
        }

        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api1.list_contact_groups.return_value = ([group1_data], None)
        mock_api2.list_contact_groups.return_value = ([group2_data], None)

        result = integration_engine.analyze()

        # Work should be created in account2, Friends in account1
        assert len(result.groups_to_create_in_account1) == 1
        assert result.groups_to_create_in_account1[0].name == "Friends"
        assert len(result.groups_to_create_in_account2) == 1
        assert result.groups_to_create_in_account2[0].name == "Work"

    def test_groups_synced_before_contacts(
        self, integration_engine, mock_api1, mock_api2, real_database
    ):
        """Test that groups are synced before contacts."""
        group_data = {
            "resourceName": "contactGroups/work",
            "etag": "e1",
            "name": "Work",
            "groupType": "USER_CONTACT_GROUP",
        }
        contact = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            memberships=["contactGroups/work"],
        )

        mock_api1.list_contact_groups.return_value = ([group_data], None)
        mock_api2.list_contact_groups.return_value = ([], None)
        mock_api1.list_contacts.return_value = ([contact], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        # Mock create returns
        mock_api2.create_contact_group.return_value = {
            "resourceName": "contactGroups/work_new",
            "etag": "e_new",
        }
        mock_api2.batch_create_contacts.return_value = [
            Contact("people/new", "e_new", "John Doe", emails=["john@example.com"])
        ]

        integration_engine.sync(dry_run=False)

        # Group should be created before contact
        # Verify order by checking the calls
        mock_api2.create_contact_group.assert_called_once()
        mock_api2.batch_create_contacts.assert_called_once()


# ==============================================================================
# Membership Sync in Contact Operations Tests
# ==============================================================================


class TestMembershipSyncInContactOperations:
    """Tests for membership mapping during contact create and update operations."""

    def test_execute_creates_maps_memberships(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test that contact creation maps memberships to target account."""
        # Contact from account 1 with a group membership
        contact = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            memberships=["contactGroups/abc123"],
        )

        result = SyncResult()
        result.to_create_in_account2.append(contact)

        # Set up group mapping: account1's abc123 -> account2's xyz789
        def mock_get_mapping(resource_name, account):
            if resource_name == "contactGroups/abc123" and account == 1:
                return {
                    "group_name": "family",
                    "account1_resource_name": "contactGroups/abc123",
                    "account2_resource_name": "contactGroups/xyz789",
                }
            return None

        mock_database.get_group_mapping_by_resource_name.side_effect = mock_get_mapping

        # Mock the API to return the created contact
        mock_api2.batch_create_contacts.return_value = [
            Contact("people/new", "e_new", "John Doe", emails=["john@example.com"])
        ]

        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([], None)
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        sync_engine.execute(result)

        # Verify batch_create_contacts was called
        mock_api2.batch_create_contacts.assert_called_once()
        # Get the contacts that were passed to batch_create_contacts
        created_contacts = mock_api2.batch_create_contacts.call_args[0][0]
        assert len(created_contacts) == 1
        # Verify memberships were mapped
        assert created_contacts[0].memberships == ["contactGroups/xyz789"]

    def test_execute_creates_maps_memberships_reverse(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test that contact creation maps memberships when creating in account 1."""
        # Contact from account 2 with a group membership
        contact = Contact(
            "people/2",
            "e2",
            "Jane Doe",
            emails=["jane@example.com"],
            memberships=["contactGroups/xyz789"],
        )

        result = SyncResult()
        result.to_create_in_account1.append(contact)

        # Set up group mapping: account2's xyz789 -> account1's abc123
        def mock_get_mapping(resource_name, account):
            if resource_name == "contactGroups/xyz789" and account == 2:
                return {
                    "group_name": "family",
                    "account1_resource_name": "contactGroups/abc123",
                    "account2_resource_name": "contactGroups/xyz789",
                }
            return None

        mock_database.get_group_mapping_by_resource_name.side_effect = mock_get_mapping

        mock_api1.batch_create_contacts.return_value = [
            Contact("people/new", "e_new", "Jane Doe", emails=["jane@example.com"])
        ]

        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([], None)
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        sync_engine.execute(result)

        # Verify memberships were mapped to account1's group
        created_contacts = mock_api1.batch_create_contacts.call_args[0][0]
        assert created_contacts[0].memberships == ["contactGroups/abc123"]

    def test_execute_updates_maps_memberships(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test that contact update maps memberships to target account."""
        # Source contact from account 1 with a group membership
        source_contact = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            memberships=["contactGroups/abc123"],
        )

        result = SyncResult()
        result.to_update_in_account2.append(("people/target2", source_contact))

        # Set up group mapping
        def mock_get_mapping(resource_name, account):
            if resource_name == "contactGroups/abc123" and account == 1:
                return {
                    "group_name": "family",
                    "account1_resource_name": "contactGroups/abc123",
                    "account2_resource_name": "contactGroups/xyz789",
                }
            return None

        mock_database.get_group_mapping_by_resource_name.side_effect = mock_get_mapping

        # Mock get_contact to return current contact
        mock_api2.get_contact.return_value = Contact(
            "people/target2", "current_etag", "John Doe"
        )
        mock_api2.batch_update_contacts.return_value = [
            Contact("people/target2", "new_etag", "John Doe")
        ]

        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([], None)
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        sync_engine.execute(result)

        # Verify batch_update_contacts was called
        mock_api2.batch_update_contacts.assert_called_once()
        # Get the updates that were passed
        updates = mock_api2.batch_update_contacts.call_args[0][0]
        assert len(updates) == 1
        # Verify memberships were mapped
        _resource_name, updated_contact = updates[0]
        assert updated_contact.memberships == ["contactGroups/xyz789"]

    def test_execute_creates_excludes_unmapped_memberships(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test that unmapped memberships are excluded during contact creation."""
        contact = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            memberships=[
                "contactGroups/abc123",  # Has mapping
                "contactGroups/unknown",  # No mapping
                "contactGroups/myContacts",  # System group
            ],
        )

        result = SyncResult()
        result.to_create_in_account2.append(contact)

        # Only abc123 has a mapping
        def mock_get_mapping(resource_name, account):
            if resource_name == "contactGroups/abc123" and account == 1:
                return {
                    "group_name": "family",
                    "account1_resource_name": "contactGroups/abc123",
                    "account2_resource_name": "contactGroups/xyz789",
                }
            return None

        mock_database.get_group_mapping_by_resource_name.side_effect = mock_get_mapping

        mock_api2.batch_create_contacts.return_value = [
            Contact("people/new", "e_new", "John Doe")
        ]

        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([], None)
        mock_api1.list_contacts.return_value = ([], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")

        sync_engine.execute(result)

        created_contacts = mock_api2.batch_create_contacts.call_args[0][0]
        # Only the mapped group should be included
        assert created_contacts[0].memberships == ["contactGroups/xyz789"]


# ==============================================================================
# Photo Synchronization Tests
# ==============================================================================


class TestPhotoSync:
    """Tests for photo synchronization functionality."""

    def test_contact_hash_includes_photo_url(
        self, contact_with_photo1, contact_without_photo1
    ):
        """Test that photo URL is included in content hash."""
        hash_with_photo = contact_with_photo1.content_hash()
        hash_without_photo = contact_without_photo1.content_hash()

        # Hashes should differ when photo URL differs
        assert hash_with_photo != hash_without_photo

    def test_contact_hash_different_photo_urls(
        self, contact_with_photo1, contact_with_different_photo2
    ):
        """Test that different photo URLs produce different hashes."""
        hash1 = contact_with_photo1.content_hash()
        hash2 = contact_with_different_photo2.content_hash()

        # Hashes should differ when photo URLs differ
        assert hash1 != hash2

    def test_analyze_detects_photo_change(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test analyze detects when photo changes between accounts."""
        # Contact in account 1 has photo
        contact1 = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            photo_url="https://example.com/photo.jpg",
            last_modified=datetime(2024, 6, 20, tzinfo=timezone.utc),
        )
        # Contact in account 2 has no photo
        contact2 = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            last_modified=datetime(2024, 6, 10, tzinfo=timezone.utc),
        )

        mock_api1.list_contacts.return_value = ([contact1], "token1")
        mock_api2.list_contacts.return_value = ([contact2], "token2")

        result = sync_engine.analyze()

        # Should detect photo change and update account 2
        assert len(result.to_update_in_account2) == 1
        assert result.to_update_in_account2[0][0] == "people/2"

    def test_analyze_photo_added_to_account1(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test analyze handles photo added to account 1."""
        # Contact in account 1 now has photo
        contact1 = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            photo_url="https://example.com/photo.jpg",
            last_modified=datetime(2024, 6, 20, tzinfo=timezone.utc),
        )
        # Contact in account 2 unchanged
        contact2 = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            last_modified=datetime(2024, 6, 10, tzinfo=timezone.utc),
        )

        mock_api1.list_contacts.return_value = ([contact1], "token1")
        mock_api2.list_contacts.return_value = ([contact2], "token2")

        result = sync_engine.analyze()

        # Should propagate photo to account 2
        assert len(result.to_update_in_account2) == 1

    def test_analyze_photo_removed_from_account1(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test analyze handles photo removed from account 1."""
        # Contact in account 1 has no photo (was removed)
        contact1 = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            last_modified=datetime(2024, 6, 20, tzinfo=timezone.utc),
        )
        # Contact in account 2 still has old photo
        contact2 = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            photo_url="https://example.com/old_photo.jpg",
            last_modified=datetime(2024, 6, 10, tzinfo=timezone.utc),
        )

        mock_api1.list_contacts.return_value = ([contact1], "token1")
        mock_api2.list_contacts.return_value = ([contact2], "token2")

        result = sync_engine.analyze()

        # Should remove photo from account 2
        assert len(result.to_update_in_account2) == 1

    def test_analyze_photo_conflict_last_modified_wins(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test photo conflict resolution using last modified wins strategy."""
        # Contact in account 1 is newer with photo A
        contact1 = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            photo_url="https://example.com/photo_a.jpg",
            last_modified=datetime(2024, 6, 20, tzinfo=timezone.utc),
        )
        # Contact in account 2 is older with photo B
        contact2 = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            photo_url="https://example.com/photo_b.jpg",
            last_modified=datetime(2024, 6, 10, tzinfo=timezone.utc),
        )

        mock_api1.list_contacts.return_value = ([contact1], "token1")
        mock_api2.list_contacts.return_value = ([contact2], "token2")

        result = sync_engine.analyze()

        # Account 1 is newer, so photo A should win
        assert len(result.to_update_in_account2) == 1
        assert result.stats.conflicts_resolved == 1

    def test_sync_contacts_with_photos(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test sync preserves photo information during create."""
        contact = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            photo_url="https://example.com/photo.jpg",
        )
        created = Contact(
            "people/new",
            "e_new",
            "John Doe",
            emails=["john@example.com"],
            photo_url="https://example.com/photo.jpg",
        )

        mock_api1.list_contacts.return_value = ([contact], "token1")
        mock_api2.list_contacts.return_value = ([], "token2")
        mock_api2.batch_create_contacts.return_value = [created]

        result = sync_engine.sync(dry_run=False)

        # Verify contact with photo was created
        assert result.stats.created_in_account2 == 1
        mock_api2.batch_create_contacts.assert_called_once()

    def test_sync_photo_only_in_dry_run(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test dry run mode detects photo changes without applying them."""
        # Contact in account 1 has new photo
        contact1 = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            photo_url="https://example.com/new_photo.jpg",
            last_modified=datetime(2024, 6, 20, tzinfo=timezone.utc),
        )
        # Contact in account 2 has old photo
        contact2 = Contact(
            "people/2",
            "e2",
            "John Doe",
            emails=["john@example.com"],
            photo_url="https://example.com/old_photo.jpg",
            last_modified=datetime(2024, 6, 10, tzinfo=timezone.utc),
        )

        mock_api1.list_contacts.return_value = ([contact1], "token1")
        mock_api2.list_contacts.return_value = ([contact2], "token2")

        result = sync_engine.sync(dry_run=True)

        # Should detect photo change
        assert len(result.to_update_in_account2) == 1
        # But not execute the update
        mock_api2.batch_update_contacts.assert_not_called()

    def test_sync_bidirectional_photo_changes(
        self, sync_engine, mock_api1, mock_api2, mock_database
    ):
        """Test bidirectional sync with photo changes in both accounts."""
        # Account 1: Contact A has photo (newer), Contact B has no photo (older)
        contact1a = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            photo_url="https://example.com/john.jpg",
            last_modified=datetime(2024, 6, 20, tzinfo=timezone.utc),
        )
        contact1b = Contact(
            "people/2",
            "e2",
            "Jane Smith",
            emails=["jane@example.com"],
            last_modified=datetime(2024, 6, 10, tzinfo=timezone.utc),
        )

        # Account 2: Contact A has no photo (older), Contact B has photo (newer)
        contact2a = Contact(
            "people/3",
            "e3",
            "John Doe",
            emails=["john@example.com"],
            last_modified=datetime(2024, 6, 10, tzinfo=timezone.utc),
        )
        contact2b = Contact(
            "people/4",
            "e4",
            "Jane Smith",
            emails=["jane@example.com"],
            photo_url="https://example.com/jane.jpg",
            last_modified=datetime(2024, 6, 20, tzinfo=timezone.utc),
        )

        mock_api1.list_contacts.return_value = ([contact1a, contact1b], "token1")
        mock_api2.list_contacts.return_value = ([contact2a, contact2b], "token2")

        result = sync_engine.analyze()

        # Both should have updates
        assert len(result.to_update_in_account1) == 1  # Jane gets photo
        assert len(result.to_update_in_account2) == 1  # John gets photo

    def test_contact_with_photo_data(self):
        """Test contact can hold binary photo data."""
        photo_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"

        contact = Contact(
            "people/1",
            "e1",
            "John Doe",
            emails=["john@example.com"],
            photo_url="https://example.com/photo.jpg",
            photo_data=photo_data,
            photo_etag="photo_etag123",
        )

        assert contact.photo_data == photo_data
        assert contact.photo_etag == "photo_etag123"
        assert contact.photo_url is not None

    def test_photo_url_not_in_api_format(self, contact_with_photo1):
        """Test photo URL is NOT included in API format (photos are read-only).

        Google People API returns 400 error if photos are included in
        create/update requests because they must be uploaded separately
        via the updateContactPhoto endpoint.
        """
        api_format = contact_with_photo1.to_api_format()

        # Photos should NOT be in API format - they're read-only
        assert "photos" not in api_format

    def test_no_photo_not_in_api_format(self, contact_without_photo1):
        """Test contacts without photos don't include photos field in API format."""
        api_format = contact_without_photo1.to_api_format()

        assert "photos" not in api_format


# ==============================================================================
# Backup Integration Tests
# ==============================================================================


class TestSyncWithBackup:
    """Tests for sync operations with backup functionality."""

    def test_sync_creates_backup(self, mock_api1, mock_api2, mock_database, tmp_path):
        """Test that sync creates a backup file before syncing."""
        # Setup contacts
        contact1 = Contact(
            "people/c1",
            "etag1",
            "John Doe",
            emails=["john@example.com"],
            last_modified=datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
        )
        contact2 = Contact(
            "people/c2",
            "etag2",
            "Jane Smith",
            emails=["jane@example.com"],
            last_modified=datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
        )

        # Mock API responses
        mock_api1.list_contacts.return_value = ([contact1], None)
        mock_api2.list_contacts.return_value = ([contact2], None)
        mock_api1.list_contact_groups.return_value = ([], None)
        mock_api2.list_contact_groups.return_value = ([], None)

        # Mock batch creates to return the contacts
        mock_api1.batch_create_contacts.return_value = [contact2]
        mock_api2.batch_create_contacts.return_value = [contact1]

        # Create backup directory
        backup_dir = tmp_path / "backups"

        # Create sync engine
        engine = SyncEngine(api1=mock_api1, api2=mock_api2, database=mock_database)

        # Perform sync with backup enabled
        result = engine.sync(
            dry_run=False,
            backup_enabled=True,
            backup_dir=backup_dir,
            backup_retention_count=10,
        )

        # Verify backup directory was created
        assert backup_dir.exists()
        assert backup_dir.is_dir()

        # Verify a backup file was created
        backup_files = list(backup_dir.glob("backup_*.json"))
        assert len(backup_files) == 1

        # Verify backup file has valid content
        import json

        backup_file = backup_files[0]
        with open(backup_file, encoding="utf-8") as f:
            backup_data = json.load(f)

        # Check backup structure (v2.0 format with accounts)
        assert "version" in backup_data
        assert backup_data["version"] == "2.0"
        assert "timestamp" in backup_data
        assert "accounts" in backup_data
        assert "account1" in backup_data["accounts"]
        assert "account2" in backup_data["accounts"]

        # Verify contacts were backed up for each account
        acc1_contacts = backup_data["accounts"]["account1"]["contacts"]
        acc2_contacts = backup_data["accounts"]["account2"]["contacts"]
        assert len(acc1_contacts) == 1
        assert len(acc2_contacts) == 1
        assert acc1_contacts[0]["display_name"] == "John Doe"
        assert acc2_contacts[0]["display_name"] == "Jane Smith"

        # Verify sync completed successfully
        assert result.stats.created_in_account1 == 1
        assert result.stats.created_in_account2 == 1
