"""
Sync engine for bidirectional Google Contacts synchronization.

Orchestrates the synchronization process between two Google accounts,
handling contact creation, updates, deletions, and conflict resolution.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

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
from gcontact_sync.utils.logging import setup_matching_logger

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    """
    Statistics from a sync operation.

    Tracks counts of all operations performed during sync.
    """

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


@dataclass
class SyncResult:
    """
    Result of a sync operation.

    Contains lists of contacts to sync and statistics.
    """

    # Contacts to create in each account
    to_create_in_account1: list[Contact] = field(default_factory=list)
    to_create_in_account2: list[Contact] = field(default_factory=list)

    # Contacts to update (resource_name, source_contact) pairs
    to_update_in_account1: list[tuple[str, Contact]] = field(default_factory=list)
    to_update_in_account2: list[tuple[str, Contact]] = field(default_factory=list)

    # Resource names to delete
    to_delete_in_account1: list[str] = field(default_factory=list)
    to_delete_in_account2: list[str] = field(default_factory=list)

    # Conflicts that were resolved
    conflicts: list[ConflictResult] = field(default_factory=list)

    # Matched contacts (for debug output): list of (contact1, contact2) pairs
    matched_contacts: list[tuple[Contact, Contact]] = field(default_factory=list)

    # Statistics
    stats: SyncStats = field(default_factory=SyncStats)

    def has_changes(self) -> bool:
        """Check if there are any changes to apply."""
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
            f"  {account1_label}: {self.stats.contacts_in_account1} contacts",
            f"  {account2_label}: {self.stats.contacts_in_account2} contacts",
            "",
            "Changes to apply:",
            f"  Create in {account1_label}: {len(self.to_create_in_account1)}",
            f"  Create in {account2_label}: {len(self.to_create_in_account2)}",
            f"  Update in {account1_label}: {len(self.to_update_in_account1)}",
            f"  Update in {account2_label}: {len(self.to_update_in_account2)}",
            f"  Delete in {account1_label}: {len(self.to_delete_in_account1)}",
            f"  Delete in {account2_label}: {len(self.to_delete_in_account2)}",
        ]

        if self.conflicts:
            lines.append(f"  Conflicts resolved: {len(self.conflicts)}")

        if self.stats.skipped_invalid:
            lines.append(f"  Skipped (invalid): {self.stats.skipped_invalid}")

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
        account1_email: Optional[str] = None,
        account2_email: Optional[str] = None,
        use_llm_matching: bool = True,
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
        match_config = MatchConfig(use_llm_matching=use_llm_matching)
        self.matcher = ContactMatcher(config=match_config, database=database)

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
        Analyze contacts in both accounts and determine sync operations.

        Uses a multi-tier matching approach:
        1. Fast key-based matching for exact matches
        2. Multi-tier fuzzy/LLM matching for remaining contacts

        Args:
            full_sync: If True, ignore sync tokens and do full comparison

        Returns:
            SyncResult containing all planned sync operations
        """
        logger.info("Analyzing contacts for sync")

        result = SyncResult()

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

        # Remaining unmatched contacts need to be created
        for contact in index1.values():
            if contact.resource_name not in matched_from_1:
                result.to_create_in_account2.append(contact)
                if mlog:
                    mlog.info(
                        f"UNMATCHED: {contact.display_name} -> create in account2"
                    )

        for contact in index2.values():
            if contact.resource_name not in matched_from_2:
                result.to_create_in_account1.append(contact)
                if mlog:
                    mlog.info(
                        f"UNMATCHED: {contact.display_name} -> create in account1"
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

    def execute(self, result: SyncResult) -> None:
        """
        Execute the planned sync operations.

        Applies all changes from the analysis result to both accounts.
        Updates the database with new mappings and sync tokens.

        Args:
            result: SyncResult from analyze() containing planned operations
        """
        logger.info("Executing sync operations")

        try:
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

            created = (
                result.stats.created_in_account1 + result.stats.created_in_account2
            )
            updated = (
                result.stats.updated_in_account1 + result.stats.updated_in_account2
            )
            deleted = (
                result.stats.deleted_in_account1 + result.stats.deleted_in_account2
            )
            logger.info(
                f"Sync complete: created {created}, "
                f"updated {updated}, deleted {deleted}"
            )

        except Exception as e:
            logger.error(f"Sync execution failed: {e}")
            raise

    def _fetch_contacts(
        self, api: PeopleAPI, account_id: str, full_sync: bool
    ) -> tuple[list[Contact], Optional[str]]:
        """
        Fetch contacts from an account, optionally using sync token.

        Args:
            api: PeopleAPI instance for the account
            account_id: Account identifier
            full_sync: If True, ignore stored sync token

        Returns:
            Tuple of (list of contacts, new sync token)
        """
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
                return contacts, new_token
            else:
                # Full sync
                contacts, new_token = api.list_contacts()
                return contacts, new_token

        except PeopleAPIError as e:
            if "expired" in str(e).lower():
                # Sync token expired, fall back to full sync
                logger.warning(
                    f"Sync token expired for {account_id}, performing full sync"
                )
                self.database.clear_sync_token(account_id)
                contacts, new_token = api.list_contacts()
                return contacts, new_token
            raise

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

    def _analyze_contact_pair(
        self,
        matching_key: str,
        contact1: Optional[Contact],
        contact2: Optional[Contact],
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
        last_synced_hash: Optional[str],
        result: SyncResult,
    ) -> None:
        """
        Analyze a contact that exists in both accounts.

        Determines if update is needed and which direction.

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
        else:
            result.to_update_in_account1.append((contact1.resource_name, contact2))
            if mlog:
                mlog.info(f"  ACTION: Update in {self.account1_email} (account2 wins)")

        if mlog:
            mlog.info("")

    def _analyze_existing_pair_with_mapping(
        self,
        current_key: str,
        contact1: Contact,
        contact2: Contact,
        last_synced_hash: Optional[str],
        old_matching_key: Optional[str],
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

    def _execute_creates(
        self, contacts: list[Contact], api: PeopleAPI, account: int, result: SyncResult
    ) -> None:
        """
        Execute contact creation operations.

        Uses batch operations for efficiency.

        Args:
            contacts: Contacts to create
            api: PeopleAPI instance for target account
            account: Account number (1 or 2)
            result: SyncResult to update with stats
        """
        account_label = self._get_account_label(account)
        logger.info(f"Creating {len(contacts)} contacts in {account_label}")

        try:
            # Use batch create for efficiency
            created = api.batch_create_contacts(contacts)

            # Update mappings with new resource names
            for original, created_contact in zip(contacts, created):
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

        Uses batch operations for efficiency.

        Args:
            updates: List of (resource_name, source_contact) tuples
            api: PeopleAPI instance for target account
            account: Account number (1 or 2)
            result: SyncResult to update with stats
        """
        account_label = self._get_account_label(account)
        logger.info(f"Updating {len(updates)} contacts in {account_label}")

        try:
            # Get current etags for the contacts being updated
            updates_with_etags = []
            for resource_name, source_contact in updates:
                try:
                    current = api.get_contact(resource_name)
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

                # Update mappings with new etags
                for (_resource_name, source_contact), updated_contact in zip(
                    updates_with_etags, updated
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
