"""
Regression tests for the incremental-sync duplicate creation loop.

Under incremental sync, list_contacts returns only contacts changed since
the stored sync token. The engine previously conflated "absent from the
delta" with "deleted", which caused it to re-create the surviving side of
a mapped pair in the other account on every run (daily ping-pong loop).

These tests simulate incremental deltas with a fake People API that
distinguishes full fetches from token-based delta fetches.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from gcontact_sync.api.people_api import PeopleAPIError
from gcontact_sync.storage.db import SyncDatabase
from gcontact_sync.sync.contact import Contact
from gcontact_sync.sync.engine import SyncEngine

# ==============================================================================
# Helpers
# ==============================================================================


def make_contact(resource_name: str, name: str = "Aaron Eden") -> Contact:
    """Create a contact with a stable matching key."""
    first, _, last = name.partition(" ")
    email = f"{first.lower()}@example.com"
    return Contact(
        resource_name=resource_name,
        etag="etag-" + resource_name.split("/")[-1],
        display_name=name,
        given_name=first,
        family_name=last or None,
        emails=[email],
        last_modified=datetime(2026, 7, 9, 16, 39, tzinfo=timezone.utc),
    )


class FakePeopleAPI:
    """Fake People API distinguishing full fetches from delta fetches.

    ``full_contacts`` is the complete account state; ``delta_contacts`` is
    what an incremental (sync-token) fetch returns.
    """

    def __init__(
        self,
        name: str,
        full_contacts: list[Contact] | None = None,
        delta_contacts: list[Contact] | None = None,
    ):
        self.name = name
        self.full_contacts = full_contacts or []
        self.delta_contacts = delta_contacts or []
        self.full_fetches = 0
        self.delta_fetches = 0
        self.get_contact_calls: list[str] = []

    def list_contacts(self, sync_token=None, **kwargs):
        if sync_token:
            self.delta_fetches += 1
            return list(self.delta_contacts), f"token-{self.name}-delta"
        self.full_fetches += 1
        return list(self.full_contacts), f"token-{self.name}-full"

    def get_contact(self, resource_name: str) -> Contact:
        self.get_contact_calls.append(resource_name)
        for contact in self.full_contacts:
            if contact.resource_name == resource_name:
                return contact
        raise PeopleAPIError(f"Contact not found: {resource_name}")

    def list_contact_groups(self, **kwargs):
        return [], None


@pytest.fixture
def database(tmp_path: Path) -> SyncDatabase:
    db = SyncDatabase(str(tmp_path / "sync.db"))
    db.initialize()
    db.update_sync_state("account1", sync_token="stale-token-1")
    db.update_sync_state("account2", sync_token="stale-token-2")
    return db


def build_engine(
    api1: FakePeopleAPI, api2: FakePeopleAPI, database: SyncDatabase
) -> SyncEngine:
    return SyncEngine(
        api1=api1,
        api2=api2,
        database=database,
        account1_email="account1@example.com",
        account2_email="account2@example.com",
        use_llm_matching=False,
    )


def analyze_with_sync(engine: SyncEngine):
    """Run the full sync pipeline in dry-run mode (analysis + escalation)."""
    return engine.sync(dry_run=True, full_sync=False, backup_enabled=False)


# ==============================================================================
# Layer 1: mapped partner absent from delta must be verified, not assumed dead
# ==============================================================================


class TestOrphanedMappingVerification:
    def test_unchanged_partner_is_not_treated_as_deleted(self, database):
        """The production loop: yesterday's created copy echoes back in the
        account2 delta; its account1 partner is unchanged (absent from the
        delta) but still exists. The engine must NOT queue a duplicate."""
        partner_a = make_contact("people/PARTNER_A")
        survivor_b = make_contact("people/SURVIVOR_B")

        database.upsert_contact_mapping(
            matching_key=survivor_b.matching_key(),
            account1_resource_name=partner_a.resource_name,
            account2_resource_name=survivor_b.resource_name,
            account1_etag=partner_a.etag,
            account2_etag=survivor_b.etag,
            last_synced_hash=survivor_b.content_hash(),
        )

        api1 = FakePeopleAPI("a1", full_contacts=[partner_a], delta_contacts=[])
        api2 = FakePeopleAPI(
            "a2", full_contacts=[survivor_b], delta_contacts=[survivor_b]
        )
        engine = build_engine(api1, api2, database)

        result = analyze_with_sync(engine)

        assert result.to_create_in_account1 == []
        assert result.to_create_in_account2 == []
        assert result.to_delete_in_account1 == []
        assert result.to_delete_in_account2 == []
        assert partner_a.resource_name in api1.get_contact_calls

    def test_truly_deleted_partner_drops_stale_mapping(self, database):
        """If the mapped partner genuinely no longer exists (404), the stale
        mapping must be removed so matching can re-pair against the real
        surviving twin instead of resurrecting the deleted copy."""
        twin_a = make_contact("people/TWIN_A")
        survivor_b = make_contact("people/SURVIVOR_B")

        database.upsert_contact_mapping(
            matching_key=survivor_b.matching_key(),
            account1_resource_name="people/GONE_A",
            account2_resource_name=survivor_b.resource_name,
            account1_etag="etag-gone",
            account2_etag=survivor_b.etag,
            last_synced_hash=survivor_b.content_hash(),
        )

        api1 = FakePeopleAPI("a1", full_contacts=[twin_a], delta_contacts=[])
        api2 = FakePeopleAPI(
            "a2", full_contacts=[survivor_b], delta_contacts=[survivor_b]
        )
        engine = build_engine(api1, api2, database)

        result = analyze_with_sync(engine)

        assert result.to_create_in_account1 == []
        assert result.to_create_in_account2 == []
        mapping = database.get_contact_mapping(survivor_b.matching_key())
        assert mapping is None or mapping.get("account1_resource_name") != (
            "people/GONE_A"
        )

    def test_transient_get_error_does_not_create_duplicate(self, database):
        """A non-404 API error while verifying the partner must fail safe:
        no create, no delete, mapping preserved."""
        survivor_b = make_contact("people/SURVIVOR_B")

        database.upsert_contact_mapping(
            matching_key=survivor_b.matching_key(),
            account1_resource_name="people/PARTNER_A",
            account2_resource_name=survivor_b.resource_name,
            account1_etag="etag-a",
            account2_etag=survivor_b.etag,
            last_synced_hash=survivor_b.content_hash(),
        )

        class FlakyAPI(FakePeopleAPI):
            def get_contact(self, resource_name: str) -> Contact:
                self.get_contact_calls.append(resource_name)
                raise PeopleAPIError("Rate limit exceeded")

        api1 = FlakyAPI("a1", full_contacts=[], delta_contacts=[])
        api2 = FakePeopleAPI(
            "a2", full_contacts=[survivor_b], delta_contacts=[survivor_b]
        )
        engine = build_engine(api1, api2, database)

        result = analyze_with_sync(engine)

        assert result.to_create_in_account1 == []
        assert result.to_delete_in_account2 == []
        assert database.get_contact_mapping(survivor_b.matching_key()) is not None


# ==============================================================================
# Layer 2: creates decided under an incremental view must be re-verified
# against full account state
# ==============================================================================


class TestFullSyncEscalation:
    def test_incremental_create_escalates_and_finds_existing_twin(self, database):
        """A contact new to the delta whose twin exists (unchanged) in the
        target account must not be created: the escalated full analysis
        must match them instead."""
        twin_a = make_contact("people/TWIN_A")
        new_b = make_contact("people/NEW_B")

        api1 = FakePeopleAPI("a1", full_contacts=[twin_a], delta_contacts=[])
        api2 = FakePeopleAPI("a2", full_contacts=[new_b], delta_contacts=[new_b])
        engine = build_engine(api1, api2, database)

        result = analyze_with_sync(engine)

        assert result.to_create_in_account1 == []
        assert result.to_create_in_account2 == []
        assert api1.full_fetches >= 1

    def test_genuinely_new_contact_is_still_created_once(self, database):
        """Escalation must not suppress legitimate creates: a contact with
        no twin anywhere is still queued exactly once."""
        new_b = make_contact("people/NEW_B", name="Brand New")

        api1 = FakePeopleAPI("a1", full_contacts=[], delta_contacts=[])
        api2 = FakePeopleAPI("a2", full_contacts=[new_b], delta_contacts=[new_b])
        engine = build_engine(api1, api2, database)

        result = analyze_with_sync(engine)

        assert [c.resource_name for c in result.to_create_in_account1] == [
            new_b.resource_name
        ]
        assert result.to_create_in_account2 == []
        assert api1.full_fetches >= 1

    def test_no_escalation_when_nothing_to_create(self, database):
        """Quiet incremental runs must stay cheap: no creates queued means
        no full re-fetch."""
        api1 = FakePeopleAPI("a1", full_contacts=[], delta_contacts=[])
        api2 = FakePeopleAPI("a2", full_contacts=[], delta_contacts=[])
        engine = build_engine(api1, api2, database)

        result = analyze_with_sync(engine)

        assert not result.has_changes()
        assert api1.full_fetches == 0
        assert api2.full_fetches == 0
