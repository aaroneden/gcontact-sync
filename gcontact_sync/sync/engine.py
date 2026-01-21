"""
Sync engine for bidirectional Google Contacts synchronization.

Orchestrates the synchronization process between two Google accounts,
handling contact creation, updates, deletions, and conflict resolution.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gcontact_sync.config import SyncConfig
    from gcontact_sync.sync.matcher import MatchConfig

from gcontact_sync.api.people_api import PeopleAPI, PeopleAPIError
from gcontact_sync.auth.google_auth import ACCOUNT_1, ACCOUNT_2
from gcontact_sync.storage.db import SyncDatabase
from gcontact_sync.sync.conflict import (
    ConflictResolver,
    ConflictResult,
    ConflictSide,
    ConflictStrategy,
)
from gcontact_sync.sync.contact import Contact
from gcontact_sync.sync.group import ContactGroup
from gcontact_sync.sync.photo import PhotoError, download_photo, process_photo
from gcontact_sync.utils.logging import setup_matching_logger

logger = logging.getLogger(__name__)


class DuplicateHandling:
    """Strategy for handling potential duplicate contacts."""

    SKIP = "skip"  # Don't create, log as potential duplicate
    AUTO_MERGE = "auto_merge"  # Merge identifiers into existing matched contact
    REPORT_ONLY = "report_only"  # Create but track in report for user review


@dataclass
class PotentialDuplicate:
    """
    A contact that appears to be a duplicate of an already-matched contact.

    This occurs when one account has merged contacts and the other has them split.
    For example, Account 1 might have two "Jim Harris" contacts with different emails,
    while Account 2 has one "Jim Harris" with both emails.
    """

    # The unmatched contact that appears to be a duplicate
    unmatched_contact: Contact

    # The already-matched contact it shares identifiers with
    matched_contact: Contact

    # The matched contact's partner in the other account
    matched_partner: Contact

    # The shared identifiers (emails or phones)
    shared_identifiers: list[str]

    # Which account the unmatched contact is in (1 or 2)
    source_account: int

    # How the duplicate was handled
    action_taken: str = ""  # "skipped", "merged", "created", "reported"


@dataclass
class SyncStats:
    """
    Statistics from a sync operation.

    Tracks counts of all operations performed during sync.
    """

    # Contact statistics
    contacts_in_account1: int = 0
    contacts_in_account2: int = 0
    created_in_account1: int = 0
    created_in_account2: int = 0
    updated_in_account1: int = 0
    updated_in_account2: int = 0
    deleted_in_account1: int = 0
    deleted_in_account2: int = 0
    conflicts_resolved: int = 0
    skipped_invalid: int = 0
    errors: int = 0
    potential_duplicates_found: int = 0
    duplicates_skipped: int = 0
    duplicates_merged: int = 0
    duplicates_reported: int = 0
    photos_synced: int = 0
    photos_deleted: int = 0
    photos_failed: int = 0

    # Group statistics
    groups_in_account1: int = 0
    groups_in_account2: int = 0
    groups_created_in_account1: int = 0
    groups_created_in_account2: int = 0
    groups_updated_in_account1: int = 0
    groups_updated_in_account2: int = 0
    groups_deleted_in_account1: int = 0
    groups_deleted_in_account2: int = 0


@dataclass
class SyncResult:
    """
    Result of a sync operation.

    Contains lists of contacts and groups to sync and statistics.
    """

    # Contacts to create in each account
    to_create_in_account1: list[Contact] = field(default_factory=list)
    to_create_in_account2: list[Contact] = field(default_factory=list)

    # Contacts to update (resource_name, source_contact) pairs
    to_update_in_account1: list[tuple[str, Contact]] = field(default_factory=list)
    to_update_in_account2: list[tuple[str, Contact]] = field(default_factory=list)

    # Contact resource names to delete
    to_delete_in_account1: list[str] = field(default_factory=list)
    to_delete_in_account2: list[str] = field(default_factory=list)

    # Groups to create in each account
    groups_to_create_in_account1: list[ContactGroup] = field(default_factory=list)
    groups_to_create_in_account2: list[ContactGroup] = field(default_factory=list)

    # Groups to update (resource_name, source_group) pairs
    groups_to_update_in_account1: list[tuple[str, ContactGroup]] = field(
        default_factory=list
    )
    groups_to_update_in_account2: list[tuple[str, ContactGroup]] = field(
        default_factory=list
    )

    # Group resource names to delete
    groups_to_delete_in_account1: list[str] = field(default_factory=list)
    groups_to_delete_in_account2: list[str] = field(default_factory=list)

    # Conflicts that were resolved
    conflicts: list[ConflictResult] = field(default_factory=list)

    # Matched contacts (for debug output): list of (contact1, contact2) pairs
    matched_contacts: list[tuple[Contact, Contact]] = field(default_factory=list)

    # Potential duplicates detected (contacts sharing identifiers with matched)
    potential_duplicates: list[PotentialDuplicate] = field(default_factory=list)

    # Matched groups (for debug output): list of (group1, group2) pairs
    matched_groups: list[tuple[ContactGroup, ContactGroup]] = field(
        default_factory=list
    )

    # Statistics
    stats: SyncStats = field(default_factory=SyncStats)

    def has_changes(self) -> bool:
        """Check if there are any changes to apply."""
        return (
            # Contact changes
            bool(self.to_create_in_account1)
            or bool(self.to_create_in_account2)
            or bool(self.to_update_in_account1)
            or bool(self.to_update_in_account2)
            or bool(self.to_delete_in_account1)
            or bool(self.to_delete_in_account2)
            # Group changes
            or bool(self.groups_to_create_in_account1)
            or bool(self.groups_to_create_in_account2)
            or bool(self.groups_to_update_in_account1)
            or bool(self.groups_to_update_in_account2)
            or bool(self.groups_to_delete_in_account1)
            or bool(self.groups_to_delete_in_account2)
        )

    def has_group_changes(self) -> bool:
        """Check if there are any group changes to apply."""
        return (
            bool(self.groups_to_create_in_account1)
            or bool(self.groups_to_create_in_account2)
            or bool(self.groups_to_update_in_account1)
            or bool(self.groups_to_update_in_account2)
            or bool(self.groups_to_delete_in_account1)
            or bool(self.groups_to_delete_in_account2)
        )

    def has_contact_changes(self) -> bool:
        """Check if there are any contact changes to apply."""
        return (
            bool(self.to_create_in_account1)
            or bool(self.to_create_in_account2)
            or bool(self.to_update_in_account1)
            or bool(self.to_update_in_account2)
            or bool(self.to_delete_in_account1)
            or bool(self.to_delete_in_account2)
        )

    def summary(
        self, account1_label: str = "Account 1", account2_label: str = "Account 2"
    ) -> str:
        """
        Generate a human-readable summary of the sync result.

        Args:
            account1_label: Label for account 1 (e.g., email address)
            account2_label: Label for account 2 (e.g., email address)

        Returns:
            Formatted string summary of sync operations
        """
        lines = [
            "Sync Summary:",
            f"  {account1_label}: {self.stats.contacts_in_account1} contacts, "
            f"{self.stats.groups_in_account1} groups",
            f"  {account2_label}: {self.stats.contacts_in_account2} contacts, "
            f"{self.stats.groups_in_account2} groups",
            "",
        ]

        # Group changes (sync groups before contacts)
        if self.has_group_changes():
            lines.extend(
                [
                    "Group changes to apply:",
                    f"  Create groups in {account1_label}: "
                    f"{len(self.groups_to_create_in_account1)}",
                    f"  Create groups in {account2_label}: "
                    f"{len(self.groups_to_create_in_account2)}",
                    f"  Update groups in {account1_label}: "
                    f"{len(self.groups_to_update_in_account1)}",
                    f"  Update groups in {account2_label}: "
                    f"{len(self.groups_to_update_in_account2)}",
                    f"  Delete groups in {account1_label}: "
                    f"{len(self.groups_to_delete_in_account1)}",
                    f"  Delete groups in {account2_label}: "
                    f"{len(self.groups_to_delete_in_account2)}",
                    "",
                ]
            )

        # Contact changes
        lines.extend(
            [
                "Contact changes to apply:",
                f"  Create in {account1_label}: {len(self.to_create_in_account1)}",
                f"  Create in {account2_label}: {len(self.to_create_in_account2)}",
                f"  Update in {account1_label}: {len(self.to_update_in_account1)}",
                f"  Update in {account2_label}: {len(self.to_update_in_account2)}",
                f"  Delete in {account1_label}: {len(self.to_delete_in_account1)}",
                f"  Delete in {account2_label}: {len(self.to_delete_in_account2)}",
            ]
        )

        if self.conflicts:
            lines.append(f"  Conflicts resolved: {len(self.conflicts)}")

        if self.stats.skipped_invalid:
            lines.append(f"  Skipped (invalid): {self.stats.skipped_invalid}")

        # Add photo sync statistics if any photos were processed
        if (
            self.stats.photos_synced
            or self.stats.photos_deleted
            or self.stats.photos_failed
        ):
            lines.append("")
            lines.append("Photo sync:")
            if self.stats.photos_synced:
                lines.append(f"  Photos synced: {self.stats.photos_synced}")
            if self.stats.photos_deleted:
                lines.append(f"  Photos deleted: {self.stats.photos_deleted}")
            if self.stats.photos_failed:
                lines.append(f"  Photos failed: {self.stats.photos_failed}")

        return "\n".join(lines)


class SyncEngine:
    """
    Bidirectional sync engine for Google Contacts.

    Orchestrates the synchronization of contacts between two Google accounts,
    ensuring both accounts contain identical contact sets after sync.

    Features:
    - Bidirectional sync using matching keys (name + emails + phones)
    - Incremental sync using sync tokens
    - Conflict resolution with configurable strategy
    - Dry-run mode for previewing changes
    - Deleted contact propagation
    - State persistence in SQLite

    Usage:
        # Initialize with credentials and database
        engine = SyncEngine(
            api1=PeopleAPI(credentials1),
            api2=PeopleAPI(credentials2),
            database=SyncDatabase('/path/to/sync.db'),
            account1_email='user1@gmail.com',
            account2_email='user2@gmail.com'
        )

        # Analyze what needs to be synced
        result = engine.analyze()
        print(result.summary())

        # Execute sync
        engine.execute(result)

        # Or do both in one call
        result = engine.sync(dry_run=False)
    """

    def __init__(
        self,
        api1: PeopleAPI,
        api2: PeopleAPI,
        database: SyncDatabase,
        conflict_strategy: ConflictStrategy = ConflictStrategy.LAST_MODIFIED_WINS,
        account1_email: str | None = None,
        account2_email: str | None = None,
        use_llm_matching: bool = True,
        match_config: Optional["MatchConfig"] = None,
        duplicate_handling: str = DuplicateHandling.SKIP,
        config: Optional["SyncConfig"] = None,
    ):
        """
        Initialize the sync engine.

        Args:
            api1: PeopleAPI instance for account 1
            api2: PeopleAPI instance for account 2
            database: SyncDatabase instance for state persistence
            conflict_strategy: Strategy for resolving conflicts
                (default: last_modified_wins)
            account1_email: Email address of account 1 (for logging)
            account2_email: Email address of account 2 (for logging)
            use_llm_matching: Whether to use LLM for uncertain matches
                (ignored if match_config is provided)
            match_config: Optional MatchConfig for advanced matching configuration.
                If provided, use_llm_matching is ignored.
            duplicate_handling: Strategy for handling potential duplicates
                (skip, auto_merge, or report_only)
            config: Optional SyncConfig for tag-based contact filtering.
                If provided, contacts will be filtered by group membership
                according to the configuration. If None, all contacts are synced.
        """
        # Import here to avoid circular imports
        from gcontact_sync.sync.matcher import ContactMatcher, MatchConfig

        self.api1 = api1
        self.api2 = api2
        self.database = database
        self.conflict_resolver = ConflictResolver(strategy=conflict_strategy)
        # Store account emails for better logging
        self.account1_email = account1_email or ACCOUNT_1
        self.account2_email = account2_email or ACCOUNT_2

        # Initialize multi-tier contact matcher with database for LLM caching
        # Use provided match_config or create a default one
        if match_config is None:
            match_config = MatchConfig(use_llm_matching=use_llm_matching)
        self.matcher = ContactMatcher(config=match_config, database=database)

        # Duplicate handling strategy
        self.duplicate_handling = duplicate_handling

        # Sync configuration for tag-based filtering
        self.config = config

    def _get_account_label(self, account: int) -> str:
        """
        Get a human-readable label for an account.

        Args:
            account: Account number (1 or 2)

        Returns:
            Email address if available, otherwise 'account1' or 'account2'
        """
        if account == 1:
            return self.account1_email
        return self.account2_email

    def sync(self, dry_run: bool = False, full_sync: bool = False) -> SyncResult:
        """
        Perform a complete sync operation.

        This is the main entry point for synchronization. It analyzes
        both accounts, calculates required changes, and applies them
        (unless dry_run is True).

        Args:
            dry_run: If True, analyze and return changes without applying them
            full_sync: If True, ignore sync tokens and do a full comparison

        Returns:
            SyncResult with changes made (or to be made if dry_run)
        """
        # Set up the matching logger for this sync session
        self._matching_logger = setup_matching_logger()
        self._matching_logger.info(
            f"Sync session started: dry_run={dry_run}, full_sync={full_sync}"
        )
        self._matching_logger.info(
            f"Account 1: {self.account1_email}, Account 2: {self.account2_email}"
        )

        # Track matching key updates for contacts that were renamed
        self._pending_key_updates: list[tuple[str, str]] = []

        logger.info(f"Starting sync (dry_run={dry_run}, full_sync={full_sync})")

        # Analyze what needs to be synced
        result = self.analyze(full_sync=full_sync)

        # Apply changes if not dry run
        if not dry_run and result.has_changes():
            self.execute(result)

        return result

    def analyze(self, full_sync: bool = False) -> SyncResult:
        """
        Analyze groups and contacts in both accounts and determine sync operations.

        Groups are analyzed BEFORE contacts to ensure group mappings exist
        when contact memberships need to be translated.

        Uses a multi-tier matching approach for contacts:
        1. Fast key-based matching for exact matches
        2. Multi-tier fuzzy/LLM matching for remaining contacts

        Args:
            full_sync: If True, ignore sync tokens and do full comparison

        Returns:
            SyncResult containing all planned sync operations
        """
        logger.info("Analyzing groups and contacts for sync")

        result = SyncResult()

        # === ANALYZE GROUPS FIRST (before contacts) ===
        # Groups must be synced first so memberships can be mapped correctly
        self._analyze_groups(result)

        # Fetch contacts from both accounts
        contacts1, sync_token1 = self._fetch_contacts(self.api1, ACCOUNT_1, full_sync)
        contacts2, sync_token2 = self._fetch_contacts(self.api2, ACCOUNT_2, full_sync)

        result.stats.contacts_in_account1 = len(contacts1)
        result.stats.contacts_in_account2 = len(contacts2)

        logger.info(
            f"Fetched {len(contacts1)} contacts from {self.account1_email}, "
            f"{len(contacts2)} contacts from {self.account2_email}"
        )

        # Build indexes by matching key (for fast first-pass matching)
        index1 = self._build_contact_index(contacts1, self.account1_email)
        index2 = self._build_contact_index(contacts2, self.account2_email)

        logger.debug(
            f"Built indexes: {len(index1)} unique keys in {self.account1_email}, "
            f"{len(index2)} unique keys in {self.account2_email}"
        )

        mlog = getattr(self, "_matching_logger", None)

        # Build lookup by resource_name for fast access
        contacts1_by_resource: dict[str, Contact] = {
            c.resource_name: c for c in contacts1
        }
        contacts2_by_resource: dict[str, Contact] = {
            c.resource_name: c for c in contacts2
        }

        matched_from_1: set[str] = set()  # resource_names matched from account 1
        matched_from_2: set[str] = set()  # resource_names matched from account 2

        # === PHASE 0: Use existing database mappings (resource-name based) ===
        # This ensures already-paired contacts stay paired even if their
        # matching keys change (e.g., name or email updates)
        if mlog:
            mlog.info("=" * 60)
            mlog.info("PHASE 0: DATABASE MAPPING LOOKUP")
            mlog.info("=" * 60)

        existing_mappings = self.database.get_all_contact_mappings()
        if mlog:
            mlog.info(f"  Found {len(existing_mappings)} existing mappings in database")

        for mapping in existing_mappings:
            res1 = mapping.get("account1_resource_name")
            res2 = mapping.get("account2_resource_name")
            old_matching_key = mapping.get("matching_key")
            last_synced_hash = mapping.get("last_synced_hash")

            contact1 = contacts1_by_resource.get(res1) if res1 else None
            contact2 = contacts2_by_resource.get(res2) if res2 else None

            if contact1 and contact2:
                # Both contacts still exist - they remain paired
                matched_from_1.add(contact1.resource_name)
                matched_from_2.add(contact2.resource_name)

                # Use current matching key (may have changed if contact was renamed)
                current_key = contact1.matching_key()

                if mlog:
                    mlog.info(f"EXISTING PAIR: {contact1.display_name}")
                    mlog.info(f"  account1: {res1}")
                    mlog.info(f"  account2: {res2}")
                    if current_key != old_matching_key:
                        mlog.info(f"  matching_key changed: {old_matching_key}")
                        mlog.info(f"    -> {current_key}")

                # Analyze the pair (check for updates needed)
                self._analyze_existing_pair_with_mapping(
                    current_key,
                    contact1,
                    contact2,
                    last_synced_hash,
                    old_matching_key,
                    result,
                )

            elif contact1 and not contact2:
                # Contact 2 was deleted - will be handled in deletion analysis
                if mlog:
                    mlog.info(
                        f"MAPPING ORPHANED (account2 deleted): {contact1.display_name}"
                    )

            elif contact2 and not contact1:
                # Contact 1 was deleted - will be handled in deletion analysis
                if mlog:
                    mlog.info(
                        f"MAPPING ORPHANED (account1 deleted): {contact2.display_name}"
                    )

        # === PHASE 1: Fast key-based matching for NEW contacts ===
        if mlog:
            mlog.info("")
            mlog.info("=" * 60)
            mlog.info("PHASE 1: KEY-BASED MATCHING (new contacts)")
            mlog.info("=" * 60)

        # Step 1a: Single-key matching (fast path for primary key matches)
        all_keys = set(index1.keys()) | set(index2.keys())

        for key in all_keys:
            contact1 = index1.get(key)
            contact2 = index2.get(key)

            # Skip contacts already matched in Phase 0
            if contact1 and contact1.resource_name in matched_from_1:
                continue
            if contact2 and contact2.resource_name in matched_from_2:
                continue

            if contact1 and contact2:
                # Key-based match found for new contacts
                matched_from_1.add(contact1.resource_name)
                matched_from_2.add(contact2.resource_name)
                self._analyze_contact_pair(key, contact1, contact2, result)

        # Step 1b: Multi-key matching (for contacts sharing ANY identifier)
        # This catches cases where contacts share a non-primary identifier
        # e.g., two contacts share an email that isn't alphabetically first
        if mlog:
            mlog.info("")
            mlog.info("PHASE 1b: MULTI-KEY MATCHING")

        # Build multi-key indexes for remaining unmatched contacts
        unmatched_contacts1 = [
            c
            for c in contacts1
            if c.resource_name not in matched_from_1 and not c.deleted and c.is_valid()
        ]
        unmatched_contacts2 = [
            c
            for c in contacts2
            if c.resource_name not in matched_from_2 and not c.deleted and c.is_valid()
        ]

        if unmatched_contacts1 and unmatched_contacts2:
            multi_index1 = self._build_multi_key_index(
                unmatched_contacts1, self.account1_email
            )
            multi_index2 = self._build_multi_key_index(
                unmatched_contacts2, self.account2_email
            )

            # Find matches on shared keys
            shared_keys = set(multi_index1.keys()) & set(multi_index2.keys())

            for key in shared_keys:
                contacts_with_key_1 = multi_index1[key]
                contacts_with_key_2 = multi_index2[key]

                # Match first unmatched pair for each shared key
                for c1 in contacts_with_key_1:
                    if c1.resource_name in matched_from_1:
                        continue
                    for c2 in contacts_with_key_2:
                        if c2.resource_name in matched_from_2:
                            continue
                        # Found a match via shared identifier
                        matched_from_1.add(c1.resource_name)
                        matched_from_2.add(c2.resource_name)
                        # Use primary key for database storage (backward compat)
                        primary_key = c1.matching_key()
                        if mlog:
                            mlog.info(
                                f"MULTI-KEY MATCH: {c1.display_name} <-> "
                                f"{c2.display_name} via {key}"
                            )
                        self._analyze_contact_pair(primary_key, c1, c2, result)
                        break  # Only match one pair per contact

        # === PHASE 2: Multi-tier matching for unmatched contacts ===
        unmatched1 = [
            c for c in index1.values() if c.resource_name not in matched_from_1
        ]
        unmatched2 = [
            c for c in index2.values() if c.resource_name not in matched_from_2
        ]

        if mlog:
            mlog.info("")
            mlog.info("=" * 60)
            mlog.info("PHASE 2: MULTI-TIER MATCHING")
            mlog.info(f"  Unmatched in account1: {len(unmatched1)}")
            mlog.info(f"  Unmatched in account2: {len(unmatched2)}")
            mlog.info("=" * 60)

        if unmatched1 and unmatched2:
            # Try to match unmatched contacts using multi-tier matcher
            newly_matched = self._multi_tier_match(
                unmatched1, unmatched2, matched_from_1, matched_from_2, result
            )
            if mlog:
                mlog.info(f"  Multi-tier matches found: {newly_matched}")

        # === PHASE 3: Handle remaining unmatched contacts ===
        # Check for potential duplicates before creating
        if mlog:
            mlog.info("")
            mlog.info("=" * 60)
            mlog.info("PHASE 3: DUPLICATE DETECTION & UNMATCHED HANDLING")
            mlog.info("=" * 60)

        # Build identifier lookup from matched contacts for duplicate detection
        identifier_to_matched = self._build_matched_identifier_index(
            result.matched_contacts
        )

        # Process unmatched contacts from account 1
        for contact in index1.values():
            if contact.resource_name not in matched_from_1:
                self._handle_unmatched_contact(
                    contact,
                    source_account=1,
                    identifier_to_matched=identifier_to_matched,
                    result=result,
                    mlog=mlog,
                )

        # Process unmatched contacts from account 2
        for contact in index2.values():
            if contact.resource_name not in matched_from_2:
                self._handle_unmatched_contact(
                    contact,
                    source_account=2,
                    identifier_to_matched=identifier_to_matched,
                    result=result,
                    mlog=mlog,
                )

        # Log matching summary
        if mlog:
            mlog.info("")
            mlog.info("=" * 60)
            mlog.info("MATCHING SUMMARY")
            mlog.info(f"  Matched pairs: {len(result.matched_contacts)}")
            mlog.info(f"  To create in account1: {len(result.to_create_in_account1)}")
            mlog.info(f"  To create in account2: {len(result.to_create_in_account2)}")
            mlog.info(f"  To update in account1: {len(result.to_update_in_account1)}")
            mlog.info(f"  To update in account2: {len(result.to_update_in_account2)}")
            mlog.info(f"  Conflicts resolved: {len(result.conflicts)}")
            if result.potential_duplicates:
                mlog.info(f"  Potential duplicates: {len(result.potential_duplicates)}")
                mlog.info(f"    Skipped: {result.stats.duplicates_skipped}")
                mlog.info(f"    Merged: {result.stats.duplicates_merged}")
                mlog.info(f"    Reported: {result.stats.duplicates_reported}")
            mlog.info("=" * 60)

        # Handle deleted contacts
        self._analyze_deletions(contacts1, contacts2, result)

        summary = result.summary(self.account1_email, self.account2_email)
        logger.info(f"Analysis complete: {summary}")

        # Store sync tokens for next incremental sync
        self._pending_sync_tokens = {
            ACCOUNT_1: sync_token1,
            ACCOUNT_2: sync_token2,
        }

        return result

    def _multi_tier_match(
        self,
        unmatched1: list[Contact],
        unmatched2: list[Contact],
        matched_from_1: set[str],
        matched_from_2: set[str],
        result: SyncResult,
    ) -> int:
        """
        Use multi-tier matching for contacts that didn't match by key.

        Args:
            unmatched1: Unmatched contacts from account 1
            unmatched2: Unmatched contacts from account 2
            matched_from_1: Set of resource_names already matched from account 1
            matched_from_2: Set of resource_names already matched from account 2
            result: SyncResult to update

        Returns:
            Number of new matches found
        """
        mlog = getattr(self, "_matching_logger", None)
        matches_found = 0

        for contact1 in unmatched1:
            if contact1.resource_name in matched_from_1:
                continue

            # Find potential matches in account 2
            for contact2 in unmatched2:
                if contact2.resource_name in matched_from_2:
                    continue

                # Use multi-tier matcher
                match_result = self.matcher.match(contact1, contact2)

                if match_result.is_match:
                    if mlog:
                        mlog.info(
                            f"MULTI-TIER MATCH: {contact1.display_name} <-> "
                            f"{contact2.display_name}"
                        )
                        mlog.info(f"  Tier: {match_result.tier.value}")
                        mlog.info(f"  Confidence: {match_result.confidence.value}")
                        mlog.info(f"  Reason: {match_result.reason}")

                    matched_from_1.add(contact1.resource_name)
                    matched_from_2.add(contact2.resource_name)
                    matches_found += 1

                    # Analyze the matched pair
                    matching_key = contact1.matching_key()
                    self._analyze_contact_pair(matching_key, contact1, contact2, result)
                    break  # Move to next contact1

        return matches_found

    def _build_matched_identifier_index(
        self,
        matched_contacts: list[tuple[Contact, Contact]],
    ) -> dict[str, tuple[Contact, Contact]]:
        """
        Build an index mapping identifiers to matched contact pairs.

        This is used for duplicate detection - when an unmatched contact
        shares an identifier with an already-matched contact.

        Args:
            matched_contacts: List of (contact1, contact2) matched pairs

        Returns:
            Dictionary mapping normalized identifiers to matched pairs
        """
        index: dict[str, tuple[Contact, Contact]] = {}

        for contact1, contact2 in matched_contacts:
            # Index all emails from both contacts in the pair
            for email in contact1.emails + contact2.emails:
                if email:
                    normalized = self.matcher._normalize_email(email)
                    if normalized:
                        index[f"email:{normalized}"] = (contact1, contact2)

            # Index all valid phones from both contacts
            for phone in contact1.phones + contact2.phones:
                if phone:
                    normalized = self.matcher._normalize_phone(phone)
                    if self.matcher._is_valid_phone(normalized):
                        index[f"phone:{normalized}"] = (contact1, contact2)

        return index

    def _handle_unmatched_contact(
        self,
        contact: Contact,
        source_account: int,
        identifier_to_matched: dict[str, tuple[Contact, Contact]],
        result: SyncResult,
        mlog: logging.Logger | None,
    ) -> None:
        """
        Handle an unmatched contact, checking for potential duplicates.

        Args:
            contact: The unmatched contact
            source_account: Which account the contact is from (1 or 2)
            identifier_to_matched: Index of identifiers to matched pairs
            result: SyncResult to update
            mlog: Optional matching logger
        """
        # Check if this contact shares any identifiers with matched contacts
        shared_identifiers: list[str] = []
        matched_pair: tuple[Contact, Contact] | None = None

        # Check emails
        for email in contact.emails:
            if email:
                normalized = self.matcher._normalize_email(email)
                key = f"email:{normalized}"
                if key in identifier_to_matched:
                    shared_identifiers.append(email)
                    matched_pair = identifier_to_matched[key]

        # Check phones
        for phone in contact.phones:
            if phone:
                normalized = self.matcher._normalize_phone(phone)
                if self.matcher._is_valid_phone(normalized):
                    key = f"phone:{normalized}"
                    if key in identifier_to_matched:
                        shared_identifiers.append(phone)
                        matched_pair = identifier_to_matched[key]

        if matched_pair and shared_identifiers:
            # This is a potential duplicate!
            matched_contact = (
                matched_pair[0] if source_account == 1 else matched_pair[1]
            )
            matched_partner = (
                matched_pair[1] if source_account == 1 else matched_pair[0]
            )

            duplicate = PotentialDuplicate(
                unmatched_contact=contact,
                matched_contact=matched_contact,
                matched_partner=matched_partner,
                shared_identifiers=shared_identifiers,
                source_account=source_account,
            )

            result.potential_duplicates.append(duplicate)
            result.stats.potential_duplicates_found += 1

            # Handle based on strategy
            if self.duplicate_handling == DuplicateHandling.SKIP:
                duplicate.action_taken = "skipped"
                result.stats.duplicates_skipped += 1
                if mlog:
                    mlog.info(f"POTENTIAL DUPLICATE (skipped): {contact.display_name}")
                    mlog.info(f"  Shares: {', '.join(shared_identifiers)}")
                    mlog.info(f"  With matched: {matched_contact.display_name}")

            elif self.duplicate_handling == DuplicateHandling.AUTO_MERGE:
                duplicate.action_taken = "merged"
                result.stats.duplicates_merged += 1
                # Add identifiers from unmatched to the matched partner
                self._merge_identifiers_into_update(
                    contact, matched_partner, source_account, result
                )
                if mlog:
                    mlog.info(f"POTENTIAL DUPLICATE (merged): {contact.display_name}")
                    mlog.info(f"  Merging into: {matched_partner.display_name}")

            elif self.duplicate_handling == DuplicateHandling.REPORT_ONLY:
                duplicate.action_taken = "reported"
                result.stats.duplicates_reported += 1
                # Still create the contact, but track it
                if source_account == 1:
                    result.to_create_in_account2.append(contact)
                else:
                    result.to_create_in_account1.append(contact)
                if mlog:
                    mlog.info(f"POTENTIAL DUPLICATE (reported): {contact.display_name}")
                    mlog.info("  Creating anyway, flagged for review")
        else:
            # No duplicate detected - create normally
            if source_account == 1:
                result.to_create_in_account2.append(contact)
            else:
                result.to_create_in_account1.append(contact)
            if mlog:
                target = "account2" if source_account == 1 else "account1"
                mlog.info(f"UNMATCHED: {contact.display_name} -> create in {target}")

    def _merge_identifiers_into_update(
        self,
        source_contact: Contact,
        target_contact: Contact,
        source_account: int,
        result: SyncResult,
    ) -> None:
        """
        Merge identifiers from source into target contact as an update.

        Args:
            source_contact: Contact with additional identifiers
            target_contact: Matched contact to merge into
            source_account: Which account source_contact is from
            result: SyncResult to add update to
        """
        # Create a merged contact with combined identifiers
        merged_emails = list(target_contact.emails)
        merged_phones = list(target_contact.phones)

        for email in source_contact.emails:
            if email and email not in merged_emails:
                merged_emails.append(email)

        for phone in source_contact.phones:
            if phone and phone not in merged_phones:
                merged_phones.append(phone)

        # Only update if there's something new to add
        if len(merged_emails) > len(target_contact.emails) or len(merged_phones) > len(
            target_contact.phones
        ):
            # Create updated contact
            merged_contact = Contact(
                resource_name=target_contact.resource_name,
                etag=target_contact.etag,
                display_name=target_contact.display_name,
                given_name=target_contact.given_name,
                family_name=target_contact.family_name,
                emails=merged_emails,
                phones=merged_phones,
                organizations=target_contact.organizations,
                notes=target_contact.notes,
                last_modified=target_contact.last_modified,
            )

            # Add to appropriate update list (update in opposite account)
            if source_account == 1:
                # Source is in acct1, target is in acct2, update acct2
                result.to_update_in_account2.append(
                    (target_contact.resource_name, merged_contact)
                )
            else:
                # Source is in acct2, target is in acct1, update acct1
                result.to_update_in_account1.append(
                    (target_contact.resource_name, merged_contact)
                )

    # =========================================================================
    # Group Sync Analysis Methods
    # =========================================================================

    def _analyze_groups(self, result: SyncResult) -> None:
        """
        Analyze contact groups in both accounts and determine sync operations.

        Groups are synced BEFORE contacts to ensure group mappings exist
        when contact memberships need to be translated.

        Args:
            result: SyncResult to populate with group sync operations
        """
        logger.info("Analyzing contact groups for sync")
        mlog = getattr(self, "_matching_logger", None)

        if mlog:
            mlog.info("")
            mlog.info("=" * 60)
            mlog.info("GROUP SYNC ANALYSIS")
            mlog.info("=" * 60)

        # Fetch groups from both accounts
        groups1 = self._fetch_groups(self.api1, ACCOUNT_1)
        groups2 = self._fetch_groups(self.api2, ACCOUNT_2)

        result.stats.groups_in_account1 = len(groups1)
        result.stats.groups_in_account2 = len(groups2)

        logger.info(
            f"Fetched {len(groups1)} groups from {self.account1_email}, "
            f"{len(groups2)} groups from {self.account2_email}"
        )

        if mlog:
            mlog.info(f"Groups in {self.account1_email}: {len(groups1)}")
            mlog.info(f"Groups in {self.account2_email}: {len(groups2)}")

        # Build indexes by matching key (normalized name)
        index1 = self._build_group_index(groups1, self.account1_email)
        index2 = self._build_group_index(groups2, self.account2_email)

        # Build lookup by resource_name for fast access
        groups1_by_resource: dict[str, ContactGroup] = {
            g.resource_name: g for g in groups1 if g.is_syncable()
        }
        groups2_by_resource: dict[str, ContactGroup] = {
            g.resource_name: g for g in groups2 if g.is_syncable()
        }

        matched_from_1: set[str] = set()  # resource_names matched from account 1
        matched_from_2: set[str] = set()  # resource_names matched from account 2

        # === PHASE 0: Use existing database group mappings ===
        if mlog:
            mlog.info("")
            mlog.info("-" * 40)
            mlog.info("GROUP PHASE 0: DATABASE MAPPING LOOKUP")
            mlog.info("-" * 40)

        existing_mappings = self.database.get_all_group_mappings()
        if mlog:
            mlog.info(f"  Found {len(existing_mappings)} existing group mappings")

        for mapping in existing_mappings:
            res1 = mapping.get("account1_resource_name")
            res2 = mapping.get("account2_resource_name")
            group_name_val = mapping.get("group_name")
            last_synced_hash = mapping.get("last_synced_hash")

            # Skip invalid mappings (should always have group_name)
            if not group_name_val or not isinstance(group_name_val, str):
                continue
            group_name: str = group_name_val

            group1 = groups1_by_resource.get(res1) if res1 else None
            group2 = groups2_by_resource.get(res2) if res2 else None

            if group1 and group2:
                # Both groups still exist - they remain paired
                matched_from_1.add(group1.resource_name)
                matched_from_2.add(group2.resource_name)

                if mlog:
                    mlog.info(f"EXISTING GROUP PAIR: {group1.name}")
                    mlog.info(f"  account1: {res1}")
                    mlog.info(f"  account2: {res2}")

                # Track as matched pair
                result.matched_groups.append((group1, group2))

                # Check if updates are needed
                self._analyze_group_pair_for_updates(
                    group_name, group1, group2, last_synced_hash, result
                )

            elif group1 and not group2:
                # Group 2 was deleted - propagate deletion to account 1
                if mlog:
                    mlog.info(
                        f"GROUP MAPPING ORPHANED (account2 deleted): {group1.name}"
                    )
                result.groups_to_delete_in_account1.append(group1.resource_name)
                self.database.delete_group_mapping(group_name)

            elif group2 and not group1:
                # Group 1 was deleted - propagate deletion to account 2
                if mlog:
                    mlog.info(
                        f"GROUP MAPPING ORPHANED (account1 deleted): {group2.name}"
                    )
                result.groups_to_delete_in_account2.append(group2.resource_name)
                self.database.delete_group_mapping(group_name)

        # === PHASE 1: Key-based matching for new groups ===
        if mlog:
            mlog.info("")
            mlog.info("-" * 40)
            mlog.info("GROUP PHASE 1: KEY-BASED MATCHING (new groups)")
            mlog.info("-" * 40)

        all_keys = set(index1.keys()) | set(index2.keys())

        for key in all_keys:
            group1 = index1.get(key)
            group2 = index2.get(key)

            # Skip groups already matched in Phase 0
            if group1 and group1.resource_name in matched_from_1:
                continue
            if group2 and group2.resource_name in matched_from_2:
                continue

            if group1 and group2:
                # Key-based match found for new groups
                matched_from_1.add(group1.resource_name)
                matched_from_2.add(group2.resource_name)
                result.matched_groups.append((group1, group2))

                if mlog:
                    mlog.info(f"MATCHED GROUP (by key): {group1.name}")
                    mlog.info(f"  account1: {group1.resource_name}")
                    mlog.info(f"  account2: {group2.resource_name}")

                # Check if updates are needed (first sync of this pair)
                self._analyze_group_pair_for_updates(key, group1, group2, None, result)

            elif group1 and not group2:
                # Group only in account 1 - create in account 2
                result.groups_to_create_in_account2.append(group1)
                if mlog:
                    mlog.info(f"NEW GROUP (account1 only): {group1.name}")
                    mlog.info(f"  -> Will create in {self.account2_email}")

            elif group2 and not group1:
                # Group only in account 2 - create in account 1
                result.groups_to_create_in_account1.append(group2)
                if mlog:
                    mlog.info(f"NEW GROUP (account2 only): {group2.name}")
                    mlog.info(f"  -> Will create in {self.account1_email}")

        # Log group sync summary
        if mlog:
            mlog.info("")
            mlog.info("-" * 40)
            mlog.info("GROUP MATCHING SUMMARY")
            mlog.info(f"  Matched group pairs: {len(result.matched_groups)}")
            mlog.info(
                f"  Groups to create in account1: "
                f"{len(result.groups_to_create_in_account1)}"
            )
            mlog.info(
                f"  Groups to create in account2: "
                f"{len(result.groups_to_create_in_account2)}"
            )
            mlog.info(
                f"  Groups to update in account1: "
                f"{len(result.groups_to_update_in_account1)}"
            )
            mlog.info(
                f"  Groups to update in account2: "
                f"{len(result.groups_to_update_in_account2)}"
            )
            mlog.info(
                f"  Groups to delete in account1: "
                f"{len(result.groups_to_delete_in_account1)}"
            )
            mlog.info(
                f"  Groups to delete in account2: "
                f"{len(result.groups_to_delete_in_account2)}"
            )
            mlog.info("-" * 40)
            mlog.info("")

        logger.info(
            f"Group analysis complete: "
            f"matched={len(result.matched_groups)}, "
            f"to_create_in_1={len(result.groups_to_create_in_account1)}, "
            f"to_create_in_2={len(result.groups_to_create_in_account2)}"
        )

    def _fetch_groups(self, api: PeopleAPI, account_id: str) -> list[ContactGroup]:
        """
        Fetch contact groups from an account.

        Args:
            api: PeopleAPI instance for the account
            account_id: Account identifier

        Returns:
            List of ContactGroup objects (only user groups, not system groups)
        """
        try:
            # API returns tuple of (list[dict], sync_token)
            groups_data, _ = api.list_contact_groups()
            # Convert raw dicts to ContactGroup objects
            groups = [ContactGroup.from_api_response(g) for g in groups_data]
            # Filter to only syncable groups (user groups with names, not deleted)
            return [g for g in groups if g.is_syncable()]
        except PeopleAPIError as e:
            logger.error(f"Failed to fetch groups from {account_id}: {e}")
            return []

    def _resolve_group_filters(
        self,
        configured_groups: list[str],
        fetched_groups: list[ContactGroup],
        account_label: str = "unknown",
    ) -> frozenset[str]:
        """
        Resolve configured group names to resource names for filtering.

        Converts display names (like "Work", "Family") to resource names
        (like "contactGroups/abc123") using the fetched groups list.
        Supports both display name matching (case-insensitive) and
        direct resource name matching.

        Args:
            configured_groups: List of group identifiers from config.
                Can be display names ("Work") or resource names
                ("contactGroups/123abc").
            fetched_groups: List of ContactGroup objects fetched from
                the account to resolve against.
            account_label: Label for the account (for logging).

        Returns:
            Frozenset of resolved resource names for efficient membership
            checking. Empty frozenset if no groups could be resolved or
            configured_groups was empty.

        Note:
            - Display names are matched case-insensitively using normalized
              matching keys (same normalization as group.py).
            - Resource names (starting with "contactGroups/") are matched
              exactly.
            - Warnings are logged for configured groups that cannot be found.
            - If a display name matches multiple groups (ambiguous), the first
              match is used and a warning is logged.
        """
        if not configured_groups:
            return frozenset()

        resolved_resource_names: set[str] = set()
        unresolved_groups: list[str] = []

        # Build lookup indexes for efficient matching
        # 1. By resource name (exact match for contactGroups/... format)
        by_resource_name: dict[str, ContactGroup] = {
            g.resource_name: g for g in fetched_groups if g.resource_name
        }

        # 2. By normalized display name (case-insensitive matching)
        # Note: We include all groups here, even non-syncable ones like system groups,
        # in case the user wants to filter by system groups (e.g., "starred")
        by_normalized_name: dict[str, list[ContactGroup]] = {}
        for group in fetched_groups:
            if group.name:
                normalized_key = group.matching_key()
                if normalized_key not in by_normalized_name:
                    by_normalized_name[normalized_key] = []
                by_normalized_name[normalized_key].append(group)

        # Resolve each configured group
        for configured_group in configured_groups:
            resolved = False

            # Try exact resource name match first (for contactGroups/... format)
            if configured_group.startswith("contactGroups/"):
                if configured_group in by_resource_name:
                    resolved_resource_names.add(configured_group)
                    resolved = True
                    logger.debug(
                        f"Resolved filter group by resource name: {configured_group}"
                    )
            else:
                # Try case-insensitive display name match
                # Normalize the configured name the same way group.matching_key() does
                normalized_configured = self._normalize_group_name(configured_group)

                if normalized_configured in by_normalized_name:
                    matching_groups = by_normalized_name[normalized_configured]

                    if len(matching_groups) > 1:
                        # Ambiguous match - log warning but use first match
                        logger.warning(
                            f"Ambiguous group filter '{configured_group}' in "
                            f"{account_label}: matches {len(matching_groups)} groups. "
                            f"Using first match: {matching_groups[0].resource_name}"
                        )

                    resolved_resource_names.add(matching_groups[0].resource_name)
                    resolved = True
                    logger.debug(
                        f"Resolved filter group '{configured_group}' -> "
                        f"{matching_groups[0].resource_name} in {account_label}"
                    )

            if not resolved:
                unresolved_groups.append(configured_group)

        # Log warnings for unresolved groups
        if unresolved_groups:
            logger.warning(
                f"Could not resolve {len(unresolved_groups)} filter group(s) "
                f"in {account_label}: {', '.join(unresolved_groups)}. "
                f"These groups will be ignored."
            )

        if resolved_resource_names:
            logger.info(
                f"Resolved {len(resolved_resource_names)} filter group(s) "
                f"in {account_label}"
            )

        return frozenset(resolved_resource_names)

    def _normalize_group_name(self, name: str) -> str:
        """
        Normalize a group name for case-insensitive matching.

        Uses the same normalization logic as ContactGroup.matching_key()
        to ensure consistent matching between config values and group names.

        Args:
            name: Group display name to normalize.

        Returns:
            Normalized lowercase string with special characters handled.
        """
        import re
        import unicodedata

        if not name:
            return ""

        # Normalize unicode (decompose accents, etc.)
        normalized = unicodedata.normalize("NFKD", name)

        # Remove combining characters (accents)
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))

        # Convert to lowercase
        normalized = normalized.lower()

        # Replace multiple spaces with single space and strip
        normalized = re.sub(r"\s+", " ", normalized).strip()

        return normalized

    def _filter_contacts_by_groups(
        self,
        contacts: list[Contact],
        allowed_groups: frozenset[str],
        account_label: str = "unknown",
    ) -> list[Contact]:
        """
        Filter contacts to include only those belonging to specified groups.

        Implements OR logic: a contact is included if ANY of its group
        memberships match ANY of the allowed groups. If allowed_groups
        is empty, all contacts are returned (backwards compatibility).

        Args:
            contacts: List of contacts to filter.
            allowed_groups: Frozenset of group resource names
                (e.g., "contactGroups/abc123") to filter by.
                Empty frozenset means no filtering (include all).
            account_label: Label for the account (for logging).

        Returns:
            List of contacts that belong to at least one allowed group.
            If allowed_groups is empty, returns all contacts unchanged.

        Example:
            # Only include contacts in "Work" or "Family" groups
            allowed = frozenset(["contactGroups/work123", "contactGroups/family456"])
            filtered = engine._filter_contacts_by_groups(contacts, allowed, "Account 1")
        """
        # Empty filter = no filtering (backwards compatibility)
        if not allowed_groups:
            logger.debug(
                f"No group filter configured for {account_label}, "
                f"including all {len(contacts)} contacts"
            )
            return contacts

        filtered_contacts: list[Contact] = []
        excluded_count = 0
        included_count = 0

        for contact in contacts:
            # Check if contact belongs to any of the allowed groups (OR logic)
            contact_groups = frozenset(contact.memberships)
            matching_groups = contact_groups & allowed_groups

            if matching_groups:
                # Contact is in at least one allowed group - include it
                filtered_contacts.append(contact)
                included_count += 1
                logger.debug(
                    f"INCLUDED: {contact.display_name} ({contact.resource_name}) - "
                    f"matches groups: {list(matching_groups)}"
                )
            else:
                # Contact is not in any allowed group - exclude it
                excluded_count += 1
                logger.debug(
                    f"EXCLUDED: {contact.display_name} ({contact.resource_name}) - "
                    f"no matching groups (has: {list(contact_groups)})"
                )

        logger.info(
            f"Group filter applied for {account_label}: "
            f"{included_count} included, {excluded_count} excluded "
            f"(filter has {len(allowed_groups)} groups)"
        )

        return filtered_contacts

    def _build_group_index(
        self, groups: list[ContactGroup], account_label: str = "unknown"
    ) -> dict[str, ContactGroup]:
        """
        Build an index of groups by matching key (normalized name).

        Args:
            groups: List of groups to index
            account_label: Label for the account (for logging)

        Returns:
            Dictionary mapping matching keys to groups
        """
        index: dict[str, ContactGroup] = {}
        mlog = getattr(self, "_matching_logger", None)

        if mlog:
            mlog.debug(f"Building group index for {account_label}")
            mlog.debug(f"Processing {len(groups)} groups")

        for group in groups:
            # Skip system groups and deleted groups
            if not group.is_syncable():
                if mlog:
                    mlog.debug(f"SKIPPED (not syncable): {group.name}")
                continue

            key = group.matching_key()

            # Handle duplicate keys (same group name normalized differently)
            if key in index:
                existing = index[key]
                # Keep the one with more members or more recent update
                if group.member_count > existing.member_count:
                    if mlog:
                        mlog.debug(
                            f"DUPLICATE KEY - keeping one with more members: "
                            f"{group.name} ({group.member_count} members)"
                        )
                    index[key] = group
                else:
                    if mlog:
                        mlog.debug(f"DUPLICATE KEY - keeping existing: {existing.name}")
            else:
                index[key] = group
                if mlog:
                    mlog.debug(f"  INDEXED: {group.name} -> key: {key}")

        if mlog:
            mlog.debug(
                f"Group index complete: {len(index)} unique groups for {account_label}"
            )

        return index

    def _analyze_group_pair_for_updates(
        self,
        matching_key: str,
        group1: ContactGroup,
        group2: ContactGroup,
        last_synced_hash: str | None,
        result: SyncResult,
    ) -> None:
        """
        Analyze a matched group pair to determine if updates are needed.

        For groups, the only modifiable field is the name. If names differ
        and there's a previous sync hash, we can determine which side changed.

        Args:
            matching_key: The normalized group name (matching key)
            group1: Group from account 1
            group2: Group from account 2
            last_synced_hash: Content hash from last sync (if available)
            result: SyncResult to populate with update actions
        """
        mlog = getattr(self, "_matching_logger", None)
        hash1 = group1.content_hash()
        hash2 = group2.content_hash()

        # Same content - no sync needed
        if hash1 == hash2:
            if mlog:
                mlog.debug(f"  Group in sync: {group1.name}")
            return

        # Content differs - determine which side changed
        if mlog:
            mlog.info(f"  Group content differs: {group1.name} vs {group2.name}")
            mlog.info(f"    hash1: {hash1[:16]}...")
            mlog.info(f"    hash2: {hash2[:16]}...")
            if last_synced_hash:
                mlog.info(f"    last_synced: {last_synced_hash[:16]}...")

        if last_synced_hash:
            group1_changed = hash1 != last_synced_hash
            group2_changed = hash2 != last_synced_hash

            if group1_changed and not group2_changed:
                # Only account 1 changed - update account 2
                result.groups_to_update_in_account2.append(
                    (group2.resource_name, group1)
                )
                if mlog:
                    mlog.info(
                        f"  -> Update in {self.account2_email} "
                        "(account1 changed, account2 unchanged)"
                    )
            elif group2_changed and not group1_changed:
                # Only account 2 changed - update account 1
                result.groups_to_update_in_account1.append(
                    (group1.resource_name, group2)
                )
                if mlog:
                    mlog.info(
                        f"  -> Update in {self.account1_email} "
                        "(account2 changed, account1 unchanged)"
                    )
            else:
                # Both changed or unclear - account1 wins (last-write-wins fallback)
                result.groups_to_update_in_account2.append(
                    (group2.resource_name, group1)
                )
                if mlog:
                    mlog.info(
                        "  -> Conflict: both changed, account1 wins (updating account2)"
                    )
        else:
            # No previous hash - first sync, account1 wins as default
            result.groups_to_update_in_account2.append((group2.resource_name, group1))
            if mlog:
                mlog.info("  -> First sync of pair, account1 wins (updating account2)")

    def execute(self, result: SyncResult) -> None:
        """
        Execute the planned sync operations.

        Applies all changes from the analysis result to both accounts.
        Groups are synced BEFORE contacts to ensure group mappings exist
        when contact memberships need to be translated.
        Updates the database with new mappings and sync tokens.

        Args:
            result: SyncResult from analyze() containing planned operations
        """
        logger.info("Executing sync operations")

        try:
            # === EXECUTE GROUP OPERATIONS FIRST ===
            # Groups must be synced before contacts so membership mappings exist

            # Create groups in account 1
            if result.groups_to_create_in_account1:
                self._execute_group_creates(
                    result.groups_to_create_in_account1,
                    self.api1,
                    account=1,
                    result=result,
                )

            # Create groups in account 2
            if result.groups_to_create_in_account2:
                self._execute_group_creates(
                    result.groups_to_create_in_account2,
                    self.api2,
                    account=2,
                    result=result,
                )

            # Update groups in account 1
            if result.groups_to_update_in_account1:
                self._execute_group_updates(
                    result.groups_to_update_in_account1,
                    self.api1,
                    account=1,
                    result=result,
                )

            # Update groups in account 2
            if result.groups_to_update_in_account2:
                self._execute_group_updates(
                    result.groups_to_update_in_account2,
                    self.api2,
                    account=2,
                    result=result,
                )

            # Delete groups in account 1
            if result.groups_to_delete_in_account1:
                self._execute_group_deletes(
                    result.groups_to_delete_in_account1,
                    self.api1,
                    account=1,
                    result=result,
                )

            # Delete groups in account 2
            if result.groups_to_delete_in_account2:
                self._execute_group_deletes(
                    result.groups_to_delete_in_account2,
                    self.api2,
                    account=2,
                    result=result,
                )

            # === EXECUTE CONTACT OPERATIONS ===

            # Create contacts in account 1
            if result.to_create_in_account1:
                self._execute_creates(
                    result.to_create_in_account1, self.api1, account=1, result=result
                )

            # Create contacts in account 2
            if result.to_create_in_account2:
                self._execute_creates(
                    result.to_create_in_account2, self.api2, account=2, result=result
                )

            # Update contacts in account 1
            if result.to_update_in_account1:
                self._execute_updates(
                    result.to_update_in_account1, self.api1, account=1, result=result
                )

            # Update contacts in account 2
            if result.to_update_in_account2:
                self._execute_updates(
                    result.to_update_in_account2, self.api2, account=2, result=result
                )

            # Delete contacts in account 1
            if result.to_delete_in_account1:
                self._execute_deletes(
                    result.to_delete_in_account1, self.api1, account=1, result=result
                )

            # Delete contacts in account 2
            if result.to_delete_in_account2:
                self._execute_deletes(
                    result.to_delete_in_account2, self.api2, account=2, result=result
                )

            # Update matching keys for renamed contacts
            self._apply_key_updates()

            # Update sync tokens
            self._update_sync_tokens()

            # Calculate totals for logging
            groups_created = (
                result.stats.groups_created_in_account1
                + result.stats.groups_created_in_account2
            )
            groups_updated = (
                result.stats.groups_updated_in_account1
                + result.stats.groups_updated_in_account2
            )
            groups_deleted = (
                result.stats.groups_deleted_in_account1
                + result.stats.groups_deleted_in_account2
            )
            contacts_created = (
                result.stats.created_in_account1 + result.stats.created_in_account2
            )
            contacts_updated = (
                result.stats.updated_in_account1 + result.stats.updated_in_account2
            )
            contacts_deleted = (
                result.stats.deleted_in_account1 + result.stats.deleted_in_account2
            )

            # Log summary including groups if any group operations occurred
            if groups_created or groups_updated or groups_deleted:
                logger.info(
                    f"Sync complete: "
                    f"groups (created={groups_created}, updated={groups_updated}, "
                    f"deleted={groups_deleted}), "
                    f"contacts (created={contacts_created}, "
                    f"updated={contacts_updated}, deleted={contacts_deleted})"
                )
            else:
                logger.info(
                    f"Sync complete: created {contacts_created}, "
                    f"updated {contacts_updated}, deleted {contacts_deleted}"
                )

        except Exception as e:
            logger.error(f"Sync execution failed: {e}")
            raise

    def _fetch_contacts(
        self,
        api: PeopleAPI,
        account_id: str,
        full_sync: bool,
        allowed_groups: frozenset[str] | None = None,
        account_label: str | None = None,
    ) -> tuple[list[Contact], str | None]:
        """
        Fetch contacts from an account, optionally using sync token.

        Applies group-based filtering after fetching if allowed_groups is provided.
        Filtering is applied consistently for both full and incremental syncs.

        Args:
            api: PeopleAPI instance for the account
            account_id: Account identifier
            full_sync: If True, ignore stored sync token
            allowed_groups: Optional frozenset of group resource names to filter by.
                If provided and non-empty, only contacts belonging to at least
                one of these groups will be returned. If None or empty, all
                contacts are returned (backwards compatible behavior).
            account_label: Optional human-readable label for the account
                (used in logging). Defaults to account_id if not provided.

        Returns:
            Tuple of (list of contacts, new sync token)
        """
        # Use account_label for logging, fall back to account_id
        label = account_label or account_id
        sync_token = None

        if not full_sync:
            # Try to get stored sync token
            state = self.database.get_sync_state(account_id)
            if state:
                sync_token = state.get("sync_token")
                logger.debug(f"Using stored sync token for {account_id}")

        try:
            if sync_token:
                # Try incremental sync
                contacts, new_token = api.list_contacts(sync_token=sync_token)
            else:
                # Full sync
                contacts, new_token = api.list_contacts()

        except PeopleAPIError as e:
            if "expired" in str(e).lower():
                # Sync token expired, fall back to full sync
                logger.warning(
                    f"Sync token expired for {account_id}, performing full sync"
                )
                self.database.clear_sync_token(account_id)
                contacts, new_token = api.list_contacts()
            else:
                raise

        # Apply group-based filtering if configured
        # This happens after API call but before returning, preserving sync token
        if allowed_groups:
            original_count = len(contacts)
            contacts = self._filter_contacts_by_groups(contacts, allowed_groups, label)
            logger.debug(
                f"Applied group filter for {label}: "
                f"{original_count} fetched -> {len(contacts)} after filtering"
            )

        return contacts, new_token

    def _build_contact_index(
        self, contacts: list[Contact], account_label: str = "unknown"
    ) -> dict[str, Contact]:
        """
        Build an index of contacts by matching key.

        Filters out invalid contacts (those without name or email).

        Args:
            contacts: List of contacts to index
            account_label: Label for the account (for logging)

        Returns:
            Dictionary mapping matching keys to contacts
        """
        index: dict[str, Contact] = {}
        mlog = getattr(self, "_matching_logger", None)

        if mlog:
            mlog.info("-" * 60)
            mlog.info(f"Building contact index for {account_label}")
            mlog.info(f"Processing {len(contacts)} contacts")
            mlog.info("-" * 60)

        for contact in contacts:
            # Skip deleted contacts in the index (handled separately)
            if contact.deleted:
                if mlog:
                    mlog.debug(
                        f"SKIPPED (deleted): {contact.display_name} "
                        f"[{contact.resource_name}]"
                    )
                continue

            # Skip invalid contacts
            if not contact.is_valid():
                logger.debug(f"Skipping invalid contact: {contact.resource_name}")
                if mlog:
                    mlog.warning(
                        f"SKIPPED (invalid - no name or email): "
                        f"resource_name={contact.resource_name}"
                    )
                continue

            key = contact.matching_key()

            # Log the matching key generation details
            if mlog:
                mlog.debug(f"CONTACT: {contact.display_name} [{contact.resource_name}]")
                mlog.debug(f"  emails: {contact.emails}")
                mlog.debug(f"  phones: {contact.phones}")
                mlog.debug(f"  matching_key: {key}")

            # Handle duplicate keys (same contact in multiple forms)
            if key in index:
                existing = index[key]
                # Keep the one with more recent modification
                if contact.last_modified and existing.last_modified:
                    if contact.last_modified > existing.last_modified:
                        if mlog:
                            mlog.info(
                                f"DUPLICATE KEY - keeping newer: "
                                f"{contact.display_name} "
                                f"(modified: {contact.last_modified})"
                            )
                            mlog.info(
                                f"  over: {existing.display_name} "
                                f"(modified: {existing.last_modified})"
                            )
                        index[key] = contact
                    else:
                        if mlog:
                            mlog.info(
                                f"DUPLICATE KEY - keeping existing: "
                                f"{existing.display_name} "
                                f"(modified: {existing.last_modified})"
                            )
                            mlog.info(
                                f"  over: {contact.display_name} "
                                f"(modified: {contact.last_modified})"
                            )
                # Or keep the one with more data
                elif len(contact.emails) > len(existing.emails):
                    if mlog:
                        mlog.info(
                            f"DUPLICATE KEY - keeping one with more emails: "
                            f"{contact.display_name} ({len(contact.emails)} emails)"
                        )
                        mlog.info(
                            f"  over: {existing.display_name} "
                            f"({len(existing.emails)} emails)"
                        )
                    index[key] = contact
                else:
                    if mlog:
                        mlog.info(
                            f"DUPLICATE KEY - keeping existing: {existing.display_name}"
                        )
                        mlog.info(f"  (same or more data than {contact.display_name})")
            else:
                index[key] = contact
                if mlog:
                    mlog.debug(f"  -> INDEXED with key: {key}")

        if mlog:
            mlog.info(
                f"Index complete: {len(index)} unique contacts for {account_label}"
            )
            mlog.info("")

        return index

    def _build_multi_key_index(
        self, contacts: list[Contact], account_label: str = "unknown"
    ) -> dict[str, list[Contact]]:
        """
        Build a multi-key index mapping each identifier to contacts that have it.

        Unlike _build_contact_index which maps each contact to ONE key,
        this maps EACH email/phone to ALL contacts that have it.
        This enables matching contacts that share ANY identifier, not just
        the alphabetically-first one.

        Args:
            contacts: List of contacts to index
            account_label: Label for the account (for logging)

        Returns:
            Dictionary mapping identifier keys to lists of contacts
        """
        from gcontact_sync.sync.matcher import create_matching_keys

        index: dict[str, list[Contact]] = {}
        mlog = getattr(self, "_matching_logger", None)

        if mlog:
            mlog.debug(f"Building multi-key index for {account_label}")

        for contact in contacts:
            # Skip deleted or invalid contacts
            if contact.deleted or not contact.is_valid():
                continue

            # Generate all matching keys for this contact
            keys = create_matching_keys(contact, self.matcher)

            for key in keys:
                if key not in index:
                    index[key] = []
                index[key].append(contact)

        if mlog:
            mlog.debug(
                f"Multi-key index complete: {len(index)} unique keys "
                f"for {account_label}"
            )

        return index

    def _analyze_contact_pair(
        self,
        matching_key: str,
        contact1: Contact | None,
        contact2: Contact | None,
        result: SyncResult,
    ) -> None:
        """
        Analyze a pair of contacts (one from each account) and determine action.

        Args:
            matching_key: The normalized matching key
            contact1: Contact from account 1 (may be None)
            contact2: Contact from account 2 (may be None)
            result: SyncResult to populate with actions
        """
        mlog = getattr(self, "_matching_logger", None)

        # Get stored mapping if exists
        mapping = self.database.get_contact_mapping(matching_key)
        last_synced_hash = mapping.get("last_synced_hash") if mapping else None

        if contact1 and not contact2:
            # Contact only in account 1 - create in account 2
            result.to_create_in_account2.append(contact1)
            logger.debug(
                f"Will create in {self.account2_email}: {contact1.display_name}"
            )
            if mlog:
                mlog.info(f"UNMATCHED (account1 only): {contact1.display_name}")
                mlog.info(f"  matching_key: {matching_key}")
                mlog.info(f"  resource_name: {contact1.resource_name}")
                mlog.info(f"  emails: {contact1.emails}")
                mlog.info(f"  phones: {contact1.phones}")
                mlog.info(f"  ACTION: Will create in {self.account2_email}")
                mlog.info("")
            # Analyze photo for new contact creation
            if contact1.photo_url:
                result.stats.photos_synced += 1

        elif contact2 and not contact1:
            # Contact only in account 2 - create in account 1
            result.to_create_in_account1.append(contact2)
            logger.debug(
                f"Will create in {self.account1_email}: {contact2.display_name}"
            )
            if mlog:
                mlog.info(f"UNMATCHED (account2 only): {contact2.display_name}")
                mlog.info(f"  matching_key: {matching_key}")
                mlog.info(f"  resource_name: {contact2.resource_name}")
                mlog.info(f"  emails: {contact2.emails}")
                mlog.info(f"  phones: {contact2.phones}")
                mlog.info(f"  ACTION: Will create in {self.account1_email}")
                mlog.info("")
            # Analyze photo for new contact creation
            if contact2.photo_url:
                result.stats.photos_synced += 1

        elif contact1 and contact2:
            # Contact exists in both - track as matched pair and check if sync needed
            result.matched_contacts.append((contact1, contact2))
            if mlog:
                mlog.info(f"MATCHED: {contact1.display_name}")
                mlog.info(f"  matching_key: {matching_key}")
                mlog.info(f"  Account1: {contact1.resource_name}")
                mlog.info(f"    emails: {contact1.emails}")
                mlog.info(f"    phones: {contact1.phones}")
                mlog.info(f"  Account2: {contact2.resource_name}")
                mlog.info(f"    emails: {contact2.emails}")
                mlog.info(f"    phones: {contact2.phones}")
            self._analyze_existing_pair(
                matching_key, contact1, contact2, last_synced_hash, result
            )

    def _analyze_existing_pair(
        self,
        matching_key: str,
        contact1: Contact,
        contact2: Contact,
        last_synced_hash: str | None,
        result: SyncResult,
    ) -> None:
        """
        Analyze a contact that exists in both accounts.

        Determines if update is needed and which direction.

        This method detects all field changes including photos, since
        content_hash() includes all syncable fields (names, emails,
        phones, organizations, notes, and photo_url).

        Args:
            matching_key: The normalized matching key
            contact1: Contact from account 1
            contact2: Contact from account 2
            last_synced_hash: Content hash from last sync (if available)
            result: SyncResult to populate with actions
        """
        mlog = getattr(self, "_matching_logger", None)
        hash1 = contact1.content_hash()
        hash2 = contact2.content_hash()

        # Same content - no sync needed
        if hash1 == hash2:
            logger.debug(f"Contact in sync: {contact1.display_name}")
            if mlog:
                mlog.info("  STATUS: In sync (content hashes match)")
                mlog.info("")
            return

        # Log hash comparison
        if mlog:
            mlog.info(f"  content_hash account1: {hash1[:16]}...")
            mlog.info(f"  content_hash account2: {hash2[:16]}...")
            if last_synced_hash:
                mlog.info(f"  last_synced_hash: {last_synced_hash[:16]}...")
            else:
                mlog.info("  last_synced_hash: None (first sync)")

        # Check if this is a conflict or one-way change
        if last_synced_hash:
            contact1_changed = hash1 != last_synced_hash
            contact2_changed = hash2 != last_synced_hash

            if mlog:
                mlog.info(f"  account1_changed: {contact1_changed}")
                mlog.info(f"  account2_changed: {contact2_changed}")

            if contact1_changed and not contact2_changed:
                # Only account 1 changed - propagate to account 2
                result.to_update_in_account2.append((contact2.resource_name, contact1))
                logger.debug(
                    f"Will update in {self.account2_email}: {contact1.display_name}"
                )
                if mlog:
                    mlog.info(
                        f"  ACTION: Update in {self.account2_email} "
                        "(account1 changed, account2 unchanged)"
                    )
                    mlog.info("")
                # Analyze photo changes for dry-run stats
                self._analyze_photo_change(contact1, contact2, result)
                return

            elif contact2_changed and not contact1_changed:
                # Only account 2 changed - propagate to account 1
                result.to_update_in_account1.append((contact1.resource_name, contact2))
                logger.debug(
                    f"Will update in {self.account1_email}: {contact2.display_name}"
                )
                if mlog:
                    mlog.info(
                        f"  ACTION: Update in {self.account1_email} "
                        "(account2 changed, account1 unchanged)"
                    )
                    mlog.info("")
                # Analyze photo changes for dry-run stats
                self._analyze_photo_change(contact2, contact1, result)
                return

        # Both changed or no previous hash - conflict resolution needed
        conflict_result = self.conflict_resolver.resolve(contact1, contact2)
        result.conflicts.append(conflict_result)
        result.stats.conflicts_resolved += 1

        logger.debug(
            f"Conflict resolved for {contact1.display_name}: "
            f"{conflict_result.winning_side.value} wins - {conflict_result.reason}"
        )

        if mlog:
            mlog.info("  CONFLICT DETECTED: Both accounts changed or no prior sync")
            mlog.info(f"  Resolution strategy: {conflict_result.reason}")
            mlog.info(f"  Winner: {conflict_result.winning_side.value}")

        if conflict_result.winning_side == ConflictSide.ACCOUNT1:
            result.to_update_in_account2.append((contact2.resource_name, contact1))
            if mlog:
                mlog.info(f"  ACTION: Update in {self.account2_email} (account1 wins)")
            # Analyze photo changes for dry-run stats
            self._analyze_photo_change(contact1, contact2, result)
        else:
            result.to_update_in_account1.append((contact1.resource_name, contact2))
            if mlog:
                mlog.info(f"  ACTION: Update in {self.account1_email} (account2 wins)")
            # Analyze photo changes for dry-run stats
            self._analyze_photo_change(contact2, contact1, result)

        if mlog:
            mlog.info("")

    def _analyze_photo_change(
        self,
        source_contact: Contact,
        dest_contact: Contact,
        result: SyncResult,
    ) -> None:
        """
        Analyze photo differences between source and destination contacts.

        Updates statistics to reflect what photo operations would be performed.
        This is called during the analyze phase to provide accurate dry-run stats.

        Args:
            source_contact: Contact with winning photo data (source of truth)
            dest_contact: Contact to be updated with source photo
            result: SyncResult to update with photo statistics
        """
        # Check if photos differ
        if source_contact.photo_url != dest_contact.photo_url:
            if source_contact.photo_url:
                # Source has photo, destination doesn't (or has different photo)
                # This will be a photo sync operation
                result.stats.photos_synced += 1
                logger.debug(
                    f"Photo change detected for {source_contact.display_name}: "
                    f"will sync photo"
                )
            elif dest_contact.photo_url:
                # Source has no photo, but destination does
                # This will be a photo deletion operation
                result.stats.photos_deleted += 1
                logger.debug(
                    f"Photo change detected for {source_contact.display_name}: "
                    f"will delete photo"
                )

    def _analyze_existing_pair_with_mapping(
        self,
        current_key: str,
        contact1: Contact,
        contact2: Contact,
        last_synced_hash: str | None,
        old_matching_key: str | None,
        result: SyncResult,
    ) -> None:
        """
        Analyze an existing paired contact from database mapping.

        This is called for contacts that were previously matched and stored
        in the database. It handles the case where the matching key may have
        changed (e.g., contact was renamed) while maintaining the pairing.

        Args:
            current_key: The current matching key based on contact data
            contact1: Contact from account 1
            contact2: Contact from account 2
            last_synced_hash: Content hash from last sync
            old_matching_key: The matching key stored in the database
            result: SyncResult to populate with actions
        """
        # Track as matched pair
        result.matched_contacts.append((contact1, contact2))

        # Update matching key in database if it changed
        if old_matching_key and current_key != old_matching_key:
            logger.debug(
                f"Matching key changed for {contact1.display_name}: "
                f"{old_matching_key} -> {current_key}"
            )
            # Delete old mapping and let the execute phase create new one
            # with updated key when changes are applied
            self._pending_key_updates.append((old_matching_key, current_key))

        # Delegate to standard pair analysis
        self._analyze_existing_pair(
            current_key, contact1, contact2, last_synced_hash, result
        )

    def _analyze_deletions(
        self, contacts1: list[Contact], contacts2: list[Contact], result: SyncResult
    ) -> None:
        """
        Analyze deleted contacts and propagate deletions.

        Checks both accounts for contacts marked as deleted and
        propagates the deletion to the other account.

        Args:
            contacts1: Contacts from account 1 (may include deleted)
            contacts2: Contacts from account 2 (may include deleted)
            result: SyncResult to populate with deletions
        """
        # Find deleted contacts in account 1
        for contact in contacts1:
            if contact.deleted:
                self._handle_deleted_contact(contact, account=1, result=result)

        # Find deleted contacts in account 2
        for contact in contacts2:
            if contact.deleted:
                self._handle_deleted_contact(contact, account=2, result=result)

    def _handle_deleted_contact(
        self, deleted_contact: Contact, account: int, result: SyncResult
    ) -> None:
        """
        Handle a deleted contact by propagating deletion to other account.

        Args:
            deleted_contact: Contact marked as deleted
            account: Account number where contact was deleted (1 or 2)
            result: SyncResult to populate with deletions
        """
        # Look up mapping by resource name
        mappings = self.database.get_mappings_by_resource_name(
            deleted_contact.resource_name, account
        )

        if not mappings:
            logger.debug(
                f"No mapping found for deleted contact: {deleted_contact.resource_name}"
            )
            return

        for mapping in mappings:
            matching_key = mapping["matching_key"]

            if account == 1:
                # Deleted in account 1 - delete in account 2
                other_resource = mapping.get("account2_resource_name")
                if other_resource:
                    result.to_delete_in_account2.append(other_resource)
                    logger.debug(
                        f"Will delete in {self.account2_email}: {other_resource}"
                    )
            else:
                # Deleted in account 2 - delete in account 1
                other_resource = mapping.get("account1_resource_name")
                if other_resource:
                    result.to_delete_in_account1.append(other_resource)
                    logger.debug(
                        f"Will delete in {self.account1_email}: {other_resource}"
                    )

            # Remove the mapping
            self.database.delete_contact_mapping(matching_key)

    def _sync_photo_for_contact(
        self,
        source_contact: Contact,
        dest_resource_name: str,
        dest_api: PeopleAPI,
        account_label: str,
        result: SyncResult,
    ) -> None:
        """
        Synchronize photo for a single contact.

        Downloads photo from source contact and uploads to destination contact.
        If source has no photo, deletes photo from destination if present.

        Updates result statistics to track photo operation success/failure.

        Args:
            source_contact: Contact with photo data (from source account)
            dest_resource_name: Resource name in destination account
            dest_api: PeopleAPI instance for destination account
            account_label: Label for destination account (for logging)
            result: SyncResult to update with photo operation status
        """
        try:
            if source_contact.photo_url:
                # Source has photo - download, process, and upload to destination
                logger.debug(
                    f"Syncing photo for {source_contact.display_name} "
                    f"to {account_label}"
                )

                try:
                    # Download photo from source URL
                    photo_data = download_photo(source_contact.photo_url)

                    # Process photo (validate, convert to JPEG, resize if needed)
                    processed_photo = process_photo(photo_data)

                    # Upload to destination contact
                    dest_api.upload_photo(dest_resource_name, processed_photo)

                    logger.info(
                        f"Successfully synced photo for {source_contact.display_name} "
                        f"to {account_label}"
                    )

                except PhotoError as e:
                    logger.warning(
                        f"Failed to sync photo for {source_contact.display_name}: {e}"
                    )
                    # Track photo failure
                    # Decrement photos_synced (was counted in analyze phase)
                    # and increment photos_failed
                    result.stats.photos_synced -= 1
                    result.stats.photos_failed += 1
                    # Continue sync even if photo fails - don't break contact sync

            else:
                # Source has no photo - delete photo from destination if present
                # This ensures photo deletions are propagated
                try:
                    dest_api.delete_photo(dest_resource_name)
                    logger.debug(
                        f"Deleted photo from {source_contact.display_name} "
                        f"in {account_label}"
                    )
                except PeopleAPIError as e:
                    # Ignore errors when deleting (photo may not exist)
                    logger.debug(
                        f"Could not delete photo for {source_contact.display_name}: {e}"
                    )

        except Exception as e:
            # Catch any unexpected errors to prevent breaking the sync
            logger.error(
                f"Unexpected error syncing photo for {source_contact.display_name}: {e}"
            )
            # Track as failed if we were attempting to sync a photo
            if source_contact.photo_url:
                result.stats.photos_synced -= 1
                result.stats.photos_failed += 1

    def _execute_creates(
        self, contacts: list[Contact], api: PeopleAPI, account: int, result: SyncResult
    ) -> None:
        """
        Execute contact creation operations.

        Uses batch operations for efficiency. Memberships are mapped from source
        account to target account before creation.

        Args:
            contacts: Contacts to create
            api: PeopleAPI instance for target account
            account: Account number (1 or 2)
            result: SyncResult to update with stats
        """
        account_label = self._get_account_label(account)
        logger.info(f"Creating {len(contacts)} contacts in {account_label}")

        try:
            # Map memberships from source account to target account
            # If creating in account 1, source is account 2 (and vice versa)
            source_account = 2 if account == 1 else 1
            contacts_with_mapped_memberships = []
            for contact in contacts:
                mapped_memberships = self._map_memberships(
                    contact.memberships, source_account, account
                )
                # Create new contact with mapped memberships
                mapped_contact = Contact(
                    resource_name=contact.resource_name,
                    etag=contact.etag,
                    display_name=contact.display_name,
                    given_name=contact.given_name,
                    family_name=contact.family_name,
                    emails=contact.emails,
                    phones=contact.phones,
                    organizations=contact.organizations,
                    notes=contact.notes,
                    memberships=mapped_memberships,
                )
                contacts_with_mapped_memberships.append(mapped_contact)

            # Use batch create for efficiency
            created = api.batch_create_contacts(contacts_with_mapped_memberships)

            # Update mappings with new resource names
            for original, created_contact in zip(contacts, created, strict=True):
                matching_key = original.matching_key()
                content_hash = original.content_hash()

                if account == 1:
                    self.database.upsert_contact_mapping(
                        matching_key=matching_key,
                        account1_resource_name=created_contact.resource_name,
                        account1_etag=created_contact.etag,
                        last_synced_hash=content_hash,
                    )
                    result.stats.created_in_account1 += 1
                else:
                    self.database.upsert_contact_mapping(
                        matching_key=matching_key,
                        account2_resource_name=created_contact.resource_name,
                        account2_etag=created_contact.etag,
                        last_synced_hash=content_hash,
                    )
                    result.stats.created_in_account2 += 1

                # Sync photo after creating contact
                self._sync_photo_for_contact(
                    source_contact=original,
                    dest_resource_name=created_contact.resource_name,
                    dest_api=api,
                    account_label=account_label,
                    result=result,
                )

        except PeopleAPIError as e:
            logger.error(f"Failed to create contacts in {account_label}: {e}")
            result.stats.errors += len(contacts)
            raise

    def _execute_updates(
        self,
        updates: list[tuple[str, Contact]],
        api: PeopleAPI,
        account: int,
        result: SyncResult,
    ) -> None:
        """
        Execute contact update operations.

        Uses batch operations for efficiency. Memberships are mapped from source
        account to target account before updating.

        Args:
            updates: List of (resource_name, source_contact) tuples
            api: PeopleAPI instance for target account
            account: Account number (1 or 2)
            result: SyncResult to update with stats
        """
        account_label = self._get_account_label(account)
        logger.info(f"Updating {len(updates)} contacts in {account_label}")

        # Determine source account for membership mapping
        source_account = 2 if account == 1 else 1

        try:
            # Get current etags for the contacts being updated
            updates_with_etags = []
            for resource_name, source_contact in updates:
                try:
                    current = api.get_contact(resource_name)
                    # Map memberships from source account to target account
                    mapped_memberships = self._map_memberships(
                        source_contact.memberships, source_account, account
                    )
                    # Create a contact with source data but target's resource name
                    update_contact = Contact(
                        resource_name=resource_name,
                        etag=current.etag,
                        display_name=source_contact.display_name,
                        given_name=source_contact.given_name,
                        family_name=source_contact.family_name,
                        emails=source_contact.emails,
                        phones=source_contact.phones,
                        organizations=source_contact.organizations,
                        notes=source_contact.notes,
                        memberships=mapped_memberships,
                    )
                    updates_with_etags.append((resource_name, update_contact))
                except PeopleAPIError as e:
                    logger.warning(
                        f"Could not fetch contact for update: {resource_name}: {e}"
                    )
                    result.stats.errors += 1
                    continue

            # Use batch update for efficiency
            if updates_with_etags:
                updated = api.batch_update_contacts(updates_with_etags)

                # Update mappings with new etags and sync photos
                for (resource_name, source_contact), updated_contact in zip(
                    updates_with_etags, updated, strict=True
                ):
                    matching_key = source_contact.matching_key()
                    content_hash = source_contact.content_hash()

                    if account == 1:
                        self.database.upsert_contact_mapping(
                            matching_key=matching_key,
                            account1_etag=updated_contact.etag,
                            last_synced_hash=content_hash,
                        )
                        result.stats.updated_in_account1 += 1
                    else:
                        self.database.upsert_contact_mapping(
                            matching_key=matching_key,
                            account2_etag=updated_contact.etag,
                            last_synced_hash=content_hash,
                        )
                        result.stats.updated_in_account2 += 1

                    # Sync photo after updating contact
                    # Note: We need the original source contact from the updates list
                    # to get the photo_url
                    original_source = next(
                        src for res, src in updates if res == resource_name
                    )
                    self._sync_photo_for_contact(
                        source_contact=original_source,
                        dest_resource_name=resource_name,
                        dest_api=api,
                        account_label=account_label,
                        result=result,
                    )

        except PeopleAPIError as e:
            logger.error(f"Failed to update contacts in {account_label}: {e}")
            result.stats.errors += len(updates)
            raise

    def _execute_deletes(
        self,
        resource_names: list[str],
        api: PeopleAPI,
        account: int,
        result: SyncResult,
    ) -> None:
        """
        Execute contact deletion operations.

        Uses batch operations for efficiency.

        Args:
            resource_names: Resource names to delete
            api: PeopleAPI instance for target account
            account: Account number (1 or 2)
            result: SyncResult to update with stats
        """
        account_label = self._get_account_label(account)
        logger.info(f"Deleting {len(resource_names)} contacts in {account_label}")

        try:
            # Use batch delete for efficiency
            deleted_count = api.batch_delete_contacts(resource_names)

            if account == 1:
                result.stats.deleted_in_account1 += deleted_count
            else:
                result.stats.deleted_in_account2 += deleted_count

        except PeopleAPIError as e:
            logger.error(f"Failed to delete contacts in {account_label}: {e}")
            result.stats.errors += len(resource_names)
            raise

    # =========================================================================
    # Group Sync Execution Methods
    # =========================================================================

    def _execute_group_creates(
        self,
        groups: list[ContactGroup],
        api: PeopleAPI,
        account: int,
        result: SyncResult,
    ) -> None:
        """
        Execute group creation operations.

        Creates groups one at a time (no batch API for groups).

        Args:
            groups: Groups to create
            api: PeopleAPI instance for target account
            account: Account number (1 or 2)
            result: SyncResult to update with stats
        """
        account_label = self._get_account_label(account)
        logger.info(f"Creating {len(groups)} groups in {account_label}")

        for group in groups:
            try:
                # Create the group using the API
                created_response = api.create_contact_group(group.name)

                # Extract the created group info
                created_resource_name = created_response.get("resourceName", "")
                created_etag = created_response.get("etag", "")

                # Get the matching key (normalized group name)
                matching_key = group.matching_key()
                content_hash = group.content_hash()

                # Update the group mapping in the database
                if account == 1:
                    self.database.upsert_group_mapping(
                        group_name=matching_key,
                        account1_resource_name=created_resource_name,
                        account1_etag=created_etag,
                        last_synced_hash=content_hash,
                    )
                    result.stats.groups_created_in_account1 += 1
                else:
                    self.database.upsert_group_mapping(
                        group_name=matching_key,
                        account2_resource_name=created_resource_name,
                        account2_etag=created_etag,
                        last_synced_hash=content_hash,
                    )
                    result.stats.groups_created_in_account2 += 1

                logger.debug(
                    f"Created group '{group.name}' in {account_label}: "
                    f"{created_resource_name}"
                )

            except PeopleAPIError as e:
                logger.error(
                    f"Failed to create group '{group.name}' in {account_label}: {e}"
                )
                result.stats.errors += 1
                # Continue with other groups instead of failing completely
                continue

    def _execute_group_updates(
        self,
        updates: list[tuple[str, ContactGroup]],
        api: PeopleAPI,
        account: int,
        result: SyncResult,
    ) -> None:
        """
        Execute group update operations.

        Updates groups one at a time (no batch API for groups).

        Args:
            updates: List of (resource_name, source_group) tuples
            api: PeopleAPI instance for target account
            account: Account number (1 or 2)
            result: SyncResult to update with stats
        """
        account_label = self._get_account_label(account)
        logger.info(f"Updating {len(updates)} groups in {account_label}")

        for resource_name, source_group in updates:
            try:
                # Get current etag for optimistic locking
                current_group = api.get_contact_group(resource_name)
                current_etag = current_group.get("etag")

                # Update the group with the source group's name
                updated_response = api.update_contact_group(
                    resource_name=resource_name,
                    name=source_group.name,
                    etag=current_etag,
                )

                # Extract the updated group info
                updated_etag = updated_response.get("etag", "")

                # Get the matching key and content hash
                matching_key = source_group.matching_key()
                content_hash = source_group.content_hash()

                # Update the group mapping in the database
                if account == 1:
                    self.database.upsert_group_mapping(
                        group_name=matching_key,
                        account1_etag=updated_etag,
                        last_synced_hash=content_hash,
                    )
                    result.stats.groups_updated_in_account1 += 1
                else:
                    self.database.upsert_group_mapping(
                        group_name=matching_key,
                        account2_etag=updated_etag,
                        last_synced_hash=content_hash,
                    )
                    result.stats.groups_updated_in_account2 += 1

                logger.debug(f"Updated group '{source_group.name}' in {account_label}")

            except PeopleAPIError as e:
                logger.error(
                    f"Failed to update group '{source_group.name}' "
                    f"in {account_label}: {e}"
                )
                result.stats.errors += 1
                # Continue with other groups instead of failing completely
                continue

    def _execute_group_deletes(
        self,
        resource_names: list[str],
        api: PeopleAPI,
        account: int,
        result: SyncResult,
    ) -> None:
        """
        Execute group deletion operations.

        Deletes groups one at a time (no batch API for groups).
        Does not delete contacts within the group.

        Args:
            resource_names: Group resource names to delete
            api: PeopleAPI instance for target account
            account: Account number (1 or 2)
            result: SyncResult to update with stats
        """
        account_label = self._get_account_label(account)
        logger.info(f"Deleting {len(resource_names)} groups in {account_label}")

        for resource_name in resource_names:
            try:
                # Delete the group (preserve contacts within it)
                api.delete_contact_group(resource_name, delete_contacts=False)

                if account == 1:
                    result.stats.groups_deleted_in_account1 += 1
                else:
                    result.stats.groups_deleted_in_account2 += 1

                logger.debug(f"Deleted group in {account_label}: {resource_name}")

            except PeopleAPIError as e:
                logger.error(
                    f"Failed to delete group {resource_name} in {account_label}: {e}"
                )
                result.stats.errors += 1
                # Continue with other groups instead of failing completely
                continue

    def _map_memberships(
        self,
        memberships: list[str],
        source_account: int,
        target_account: int,
    ) -> list[str]:
        """
        Map contact group memberships from source account to target account.

        When syncing a contact from one account to another, this method translates
        group resource names (e.g., "contactGroups/abc123") from the source account
        to the corresponding group resource names in the target account.

        Uses the group_mapping table in the database to find corresponding groups
        that have been synced between accounts.

        Args:
            memberships: List of group resource names from the source account
            source_account: Account number where memberships originated (1 or 2)
            target_account: Account number where contact is being synced to (1 or 2)

        Returns:
            List of mapped group resource names for the target account.
            Groups that don't have a mapping (new groups, system groups) are skipped.

        Example:
            # Contact in account1 has memberships:
            # ["contactGroups/abc123", "contactGroups/myContacts"]
            #
            # If group "abc123" in account1 maps to "xyz789" in account2:
            mapped = engine._map_memberships(
                memberships=["contactGroups/abc123", "contactGroups/myContacts"],
                source_account=1,
                target_account=2
            )
            # Returns: ["contactGroups/xyz789"]
            # (myContacts is a system group, so it's skipped)
        """
        from gcontact_sync.sync.group import SYSTEM_GROUP_NAMES

        mapped_memberships: list[str] = []
        mlog = getattr(self, "_matching_logger", None)

        if mlog:
            mlog.debug(
                f"Mapping {len(memberships)} memberships from account{source_account} "
                f"to account{target_account}"
            )

        for group_resource in memberships:
            # Skip system groups - they are account-specific and shouldn't be mapped
            if group_resource in SYSTEM_GROUP_NAMES:
                if mlog:
                    mlog.debug(f"  Skipping system group: {group_resource}")
                continue

            # Look up the group mapping by the source account's resource name
            mapping = self.database.get_group_mapping_by_resource_name(
                group_resource, source_account
            )

            if mapping:
                # Get the target account's resource name from the mapping
                target_resource = mapping.get(f"account{target_account}_resource_name")
                if target_resource:
                    mapped_memberships.append(target_resource)
                    if mlog:
                        mlog.debug(
                            f"  Mapped group: {group_resource} -> {target_resource}"
                        )
                else:
                    # Mapping exists but target hasn't been synced yet
                    # This can happen if group sync is still in progress
                    if mlog:
                        mlog.debug(
                            f"  Group mapping found but no target resource: "
                            f"{group_resource}"
                        )
            else:
                # No mapping found - group may be new or a system group variant
                if mlog:
                    mlog.debug(f"  No mapping found for group: {group_resource}")

        if mlog:
            mlog.debug(
                f"  Membership mapping result: {len(memberships)} source -> "
                f"{len(mapped_memberships)} target"
            )

        return mapped_memberships

    def _apply_key_updates(self) -> None:
        """
        Apply pending matching key updates to the database.

        This handles contacts that were renamed - their matching key changes
        but the pairing should be maintained based on resource names.
        """
        if not hasattr(self, "_pending_key_updates"):
            return

        for old_key, new_key in self._pending_key_updates:
            if self.database.update_matching_key(old_key, new_key):
                logger.debug(f"Updated matching key: {old_key} -> {new_key}")
            else:
                logger.warning(f"Failed to update matching key: {old_key}")

    def _update_sync_tokens(self) -> None:
        """
        Update stored sync tokens after successful sync.
        """
        if not hasattr(self, "_pending_sync_tokens"):
            return

        for account_id, token in self._pending_sync_tokens.items():
            if token:
                self.database.update_sync_state(
                    account_id=account_id,
                    sync_token=token,
                    last_sync_at=datetime.utcnow(),
                )
                logger.debug(f"Updated sync token for {account_id}")

    def get_status(self) -> dict[str, object]:
        """
        Get current sync status information.

        Returns:
            Dictionary with sync status for both accounts
        """
        status: dict[str, object] = {
            "account1": None,
            "account2": None,
            "total_mappings": self.database.get_mapping_count(),
        }

        state1 = self.database.get_sync_state(ACCOUNT_1)
        if state1:
            last_sync_1: str | None = state1.get("last_sync_at")
            status["account1"] = {
                "last_sync": last_sync_1,
                "has_sync_token": bool(state1.get("sync_token")),
            }

        state2 = self.database.get_sync_state(ACCOUNT_2)
        if state2:
            last_sync_2: str | None = state2.get("last_sync_at")
            status["account2"] = {
                "last_sync": last_sync_2,
                "has_sync_token": bool(state2.get("sync_token")),
            }

        return status

    def reset(self) -> None:
        """
        Reset all sync state (forces full sync on next run).

        Clears sync tokens and contact mappings from the database.
        """
        logger.info("Resetting sync state")
        self.database.clear_all_state()

    def __repr__(self) -> str:
        """Return a readable string representation."""
        return (
            f"SyncEngine("
            f"strategy={self.conflict_resolver.strategy.value}, "
            f"db={self.database.db_path})"
        )
