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

from gcontact_sync.api.people_api import ContactNotFoundError, PeopleAPIError
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
        raise ContactNotFoundError(f"Contact not found: {resource_name}")

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
        delta) but still exists. The engine must NOT queue a duplicate.
        Because the fetched side is unchanged since the last sync, the pair
        is kept without even needing a get_contact verification call."""
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
        assert api1.get_contact_calls == []
        assert api1.full_fetches == 0

    def test_changed_contact_verifies_partner_and_queues_update(self, database):
        """A genuinely edited contact (hash differs from the mapping) must
        fetch its absent partner directly and queue an update for it - not
        a create."""
        partner_a = make_contact("people/PARTNER_A")
        edited_b = make_contact("people/EDITED_B")
        edited_b.notes = "edited since last sync"

        database.upsert_contact_mapping(
            matching_key=partner_a.matching_key(),
            account1_resource_name=partner_a.resource_name,
            account2_resource_name=edited_b.resource_name,
            account1_etag=partner_a.etag,
            account2_etag=edited_b.etag,
            last_synced_hash=partner_a.content_hash(),
        )

        api1 = FakePeopleAPI("a1", full_contacts=[partner_a], delta_contacts=[])
        api2 = FakePeopleAPI("a2", full_contacts=[edited_b], delta_contacts=[edited_b])
        engine = build_engine(api1, api2, database)

        result = analyze_with_sync(engine)

        assert partner_a.resource_name in api1.get_contact_calls
        assert result.to_create_in_account1 == []
        assert result.to_create_in_account2 == []
        assert len(result.to_update_in_account1) == 1

    def test_tombstone_present_side_is_left_to_deletion_analysis(self, database):
        """A deletion tombstone arriving in the delta must not be paired
        with its live partner (that would push emptied fields onto it);
        deletion analysis alone handles it."""
        partner_a = make_contact("people/PARTNER_A")
        tombstone_b = make_contact("people/TOMBSTONE_B")
        tombstone_b.deleted = True
        tombstone_b.emails = []
        tombstone_b.display_name = ""

        database.upsert_contact_mapping(
            matching_key=partner_a.matching_key(),
            account1_resource_name=partner_a.resource_name,
            account2_resource_name=tombstone_b.resource_name,
            account1_etag=partner_a.etag,
            account2_etag="etag-tombstone",
            last_synced_hash=partner_a.content_hash(),
        )

        api1 = FakePeopleAPI("a1", full_contacts=[partner_a], delta_contacts=[])
        api2 = FakePeopleAPI("a2", full_contacts=[], delta_contacts=[tombstone_b])
        engine = build_engine(api1, api2, database)

        result = analyze_with_sync(engine)

        assert result.to_update_in_account1 == []
        assert result.to_update_in_account2 == []
        assert result.to_create_in_account1 == []
        assert result.to_create_in_account2 == []
        assert result.to_delete_in_account1 == [partner_a.resource_name]

    def test_full_sync_absence_is_authoritative_no_get_needed(self, database):
        """Under a full sync, a partner absent from the fetch is genuinely
        gone: the stale mapping is dropped without a get_contact call and
        the survivor re-pairs by key against its real twin."""
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

        result = engine.sync(dry_run=True, full_sync=True, backup_enabled=False)

        assert api1.get_contact_calls == []
        assert result.to_create_in_account1 == []
        assert result.to_create_in_account2 == []
        mapping = database.get_contact_mapping(survivor_b.matching_key())
        assert mapping is None or mapping.get("account1_resource_name") != (
            "people/GONE_A"
        )

    def test_truly_deleted_partner_drops_stale_mapping(self, database):
        """If a changed contact's mapped partner genuinely no longer exists
        (404), the stale mapping must be removed so matching can re-pair
        against the real surviving twin instead of resurrecting the deleted
        copy. (An UNCHANGED survivor skips verification entirely - stale
        mappings are cleaned up lazily, on the survivor's next edit.)"""
        twin_a = make_contact("people/TWIN_A")
        survivor_b = make_contact("people/SURVIVOR_B")
        survivor_b.notes = "edited since last sync"

        database.upsert_contact_mapping(
            matching_key=survivor_b.matching_key(),
            account1_resource_name="people/GONE_A",
            account2_resource_name=survivor_b.resource_name,
            account1_etag="etag-gone",
            account2_etag=survivor_b.etag,
            last_synced_hash=make_contact("people/SURVIVOR_B").content_hash(),
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


# ==============================================================================
# _reanalyze_full: incremental-pass deletions must survive the full re-analysis
# ==============================================================================


class TestReanalyzeFullCarryOver:
    def _engine_with_patched_analyze(self, database, full_result):
        api1 = FakePeopleAPI("a1")
        api2 = FakePeopleAPI("a2")
        engine = build_engine(api1, api2, database)
        engine.analyze = lambda full_sync=False: full_result  # type: ignore[method-assign]
        engine._pending_key_updates = []
        return engine

    def test_contact_and_group_deletions_carry_over(self, database):
        from gcontact_sync.sync.engine import SyncResult

        incremental = SyncResult()
        incremental.to_delete_in_account1.append("people/DEL_A")
        incremental.to_delete_in_account2.append("people/DEL_B")
        incremental.groups_to_delete_in_account1.append("contactGroups/G_A")
        incremental.groups_to_delete_in_account2.append("contactGroups/G_B")

        engine = self._engine_with_patched_analyze(database, SyncResult())
        merged = engine._reanalyze_full(incremental)

        assert merged.to_delete_in_account1 == ["people/DEL_A"]
        assert merged.to_delete_in_account2 == ["people/DEL_B"]
        assert merged.groups_to_delete_in_account1 == ["contactGroups/G_A"]
        assert merged.groups_to_delete_in_account2 == ["contactGroups/G_B"]

    def test_creates_of_pending_deleted_sources_are_dropped(self, database):
        from gcontact_sync.sync.contact import Contact as C
        from gcontact_sync.sync.engine import SyncResult
        from gcontact_sync.sync.group import ContactGroup

        pending_delete_b = make_contact("people/DEL_B")
        survivor_group_a = ContactGroup(
            resource_name="contactGroups/G_A",
            etag="e",
            name="Orphaned Group",
            group_type="USER_CONTACT_GROUP",
        )

        full_result = SyncResult()
        full_result.to_create_in_account1.append(pending_delete_b)
        full_result.groups_to_create_in_account2.append(survivor_group_a)
        full_result.to_create_in_account2.append(
            C(resource_name="people/KEEP_A", etag="e", display_name="Keep Me")
        )

        incremental = SyncResult()
        incremental.to_delete_in_account2.append(pending_delete_b.resource_name)
        incremental.groups_to_delete_in_account1.append(survivor_group_a.resource_name)

        engine = self._engine_with_patched_analyze(database, full_result)
        merged = engine._reanalyze_full(incremental)

        assert merged.to_create_in_account1 == []
        assert merged.groups_to_create_in_account2 == []
        assert [c.resource_name for c in merged.to_create_in_account2] == [
            "people/KEEP_A"
        ]
