"""
Sync engine for bidirectional Google Contacts synchronization.

Orchestrates the synchronization process between two Google accounts,
handling contact creation, updates, deletions, and conflict resolution.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

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
    to_create_in_account1: List[Contact] = field(default_factory=list)
    to_create_in_account2: List[Contact] = field(default_factory=list)

    # Contacts to update (resource_name, source_contact) pairs
    to_update_in_account1: List[Tuple[str, Contact]] = field(default_factory=list)
    to_update_in_account2: List[Tuple[str, Contact]] = field(default_factory=list)

    # Resource names to delete
    to_delete_in_account1: List[str] = field(default_factory=list)
    to_delete_in_account2: List[str] = field(default_factory=list)

    # Conflicts that were resolved
    conflicts: List[ConflictResult] = field(default_factory=list)

    # Statistics
    stats: SyncStats = field(default_factory=SyncStats)

    def has_changes(self) -> bool:
        """Check if there are any changes to apply."""
        return (
            bool(self.to_create_in_account1) or
            bool(self.to_create_in_account2) or
            bool(self.to_update_in_account1) or
            bool(self.to_update_in_account2) or
            bool(self.to_delete_in_account1) or
            bool(self.to_delete_in_account2)
        )

    def summary(
        self,
        account1_label: str = "Account 1",
        account2_label: str = "Account 2"
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

        return '\n'.join(lines)


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
        account2_email: Optional[str] = None
    ):
        """
        Initialize the sync engine.

        Args:
            api1: PeopleAPI instance for account 1
            api2: PeopleAPI instance for account 2
            database: SyncDatabase instance for state persistence
            conflict_strategy: Strategy for resolving conflicts (default: last_modified_wins)
            account1_email: Email address of account 1 (for logging)
            account2_email: Email address of account 2 (for logging)
        """
        self.api1 = api1
        self.api2 = api2
        self.database = database
        self.conflict_resolver = ConflictResolver(strategy=conflict_strategy)
        # Store account emails for better logging
        self.account1_email = account1_email or ACCOUNT_1
        self.account2_email = account2_email or ACCOUNT_2

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

        Fetches contacts from both accounts, compares them using matching
        keys, and builds a plan of operations to synchronize them.

        Args:
            full_sync: If True, ignore sync tokens and do full comparison

        Returns:
            SyncResult containing all planned sync operations
        """
        logger.info("Analyzing contacts for sync")

        result = SyncResult()

        # Fetch contacts from both accounts
        contacts1, sync_token1 = self._fetch_contacts(
            self.api1, ACCOUNT_1, full_sync
        )
        contacts2, sync_token2 = self._fetch_contacts(
            self.api2, ACCOUNT_2, full_sync
        )

        result.stats.contacts_in_account1 = len(contacts1)
        result.stats.contacts_in_account2 = len(contacts2)

        logger.info(
            f"Fetched {len(contacts1)} contacts from {self.account1_email}, "
            f"{len(contacts2)} contacts from {self.account2_email}"
        )

        # Build indexes by matching key
        index1 = self._build_contact_index(contacts1)
        index2 = self._build_contact_index(contacts2)

        logger.debug(
            f"Built indexes: {len(index1)} unique keys in {self.account1_email}, "
            f"{len(index2)} unique keys in {self.account2_email}"
        )

        # Get all unique matching keys
        all_keys = set(index1.keys()) | set(index2.keys())

        # Analyze each contact
        for key in all_keys:
            contact1 = index1.get(key)
            contact2 = index2.get(key)

            self._analyze_contact_pair(
                key, contact1, contact2, result
            )

        # Handle deleted contacts
        self._analyze_deletions(contacts1, contacts2, result)

        logger.info(f"Analysis complete: {result.summary()}")

        # Store sync tokens for next incremental sync
        self._pending_sync_tokens = {
            ACCOUNT_1: sync_token1,
            ACCOUNT_2: sync_token2,
        }

        return result

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
                    result.to_create_in_account1,
                    self.api1,
                    account=1,
                    result=result
                )

            # Create contacts in account 2
            if result.to_create_in_account2:
                self._execute_creates(
                    result.to_create_in_account2,
                    self.api2,
                    account=2,
                    result=result
                )

            # Update contacts in account 1
            if result.to_update_in_account1:
                self._execute_updates(
                    result.to_update_in_account1,
                    self.api1,
                    account=1,
                    result=result
                )

            # Update contacts in account 2
            if result.to_update_in_account2:
                self._execute_updates(
                    result.to_update_in_account2,
                    self.api2,
                    account=2,
                    result=result
                )

            # Delete contacts in account 1
            if result.to_delete_in_account1:
                self._execute_deletes(
                    result.to_delete_in_account1,
                    self.api1,
                    account=1,
                    result=result
                )

            # Delete contacts in account 2
            if result.to_delete_in_account2:
                self._execute_deletes(
                    result.to_delete_in_account2,
                    self.api2,
                    account=2,
                    result=result
                )

            # Update sync tokens
            self._update_sync_tokens()

            logger.info(
                f"Sync complete: "
                f"created {result.stats.created_in_account1 + result.stats.created_in_account2}, "
                f"updated {result.stats.updated_in_account1 + result.stats.updated_in_account2}, "
                f"deleted {result.stats.deleted_in_account1 + result.stats.deleted_in_account2}"
            )

        except Exception as e:
            logger.error(f"Sync execution failed: {e}")
            raise

    def _fetch_contacts(
        self,
        api: PeopleAPI,
        account_id: str,
        full_sync: bool
    ) -> Tuple[List[Contact], Optional[str]]:
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
                sync_token = state.get('sync_token')
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
        self,
        contacts: List[Contact]
    ) -> Dict[str, Contact]:
        """
        Build an index of contacts by matching key.

        Filters out invalid contacts (those without name or email).

        Args:
            contacts: List of contacts to index

        Returns:
            Dictionary mapping matching keys to contacts
        """
        index: Dict[str, Contact] = {}

        for contact in contacts:
            # Skip deleted contacts in the index (handled separately)
            if contact.deleted:
                continue

            # Skip invalid contacts
            if not contact.is_valid():
                logger.debug(
                    f"Skipping invalid contact: {contact.resource_name}"
                )
                continue

            key = contact.matching_key()

            # Handle duplicate keys (same contact in multiple forms)
            if key in index:
                existing = index[key]
                # Keep the one with more recent modification
                if contact.last_modified and existing.last_modified:
                    if contact.last_modified > existing.last_modified:
                        index[key] = contact
                # Or keep the one with more data
                elif len(contact.emails) > len(existing.emails):
                    index[key] = contact
            else:
                index[key] = contact

        return index

    def _analyze_contact_pair(
        self,
        matching_key: str,
        contact1: Optional[Contact],
        contact2: Optional[Contact],
        result: SyncResult
    ) -> None:
        """
        Analyze a pair of contacts (one from each account) and determine action.

        Args:
            matching_key: The normalized matching key
            contact1: Contact from account 1 (may be None)
            contact2: Contact from account 2 (may be None)
            result: SyncResult to populate with actions
        """
        # Get stored mapping if exists
        mapping = self.database.get_contact_mapping(matching_key)
        last_synced_hash = mapping.get('last_synced_hash') if mapping else None

        if contact1 and not contact2:
            # Contact only in account 1 - create in account 2
            result.to_create_in_account2.append(contact1)
            logger.debug(
                f"Will create in {self.account2_email}: {contact1.display_name}"
            )

        elif contact2 and not contact1:
            # Contact only in account 2 - create in account 1
            result.to_create_in_account1.append(contact2)
            logger.debug(
                f"Will create in {self.account1_email}: {contact2.display_name}"
            )

        elif contact1 and contact2:
            # Contact exists in both - check if sync needed
            self._analyze_existing_pair(
                matching_key, contact1, contact2, last_synced_hash, result
            )

    def _analyze_existing_pair(
        self,
        matching_key: str,
        contact1: Contact,
        contact2: Contact,
        last_synced_hash: Optional[str],
        result: SyncResult
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
        hash1 = contact1.content_hash()
        hash2 = contact2.content_hash()

        # Same content - no sync needed
        if hash1 == hash2:
            logger.debug(
                f"Contact in sync: {contact1.display_name}"
            )
            return

        # Check if this is a conflict or one-way change
        if last_synced_hash:
            contact1_changed = hash1 != last_synced_hash
            contact2_changed = hash2 != last_synced_hash

            if contact1_changed and not contact2_changed:
                # Only account 1 changed - propagate to account 2
                result.to_update_in_account2.append(
                    (contact2.resource_name, contact1)
                )
                logger.debug(
                    f"Will update in {self.account2_email}: {contact1.display_name}"
                )
                return

            elif contact2_changed and not contact1_changed:
                # Only account 2 changed - propagate to account 1
                result.to_update_in_account1.append(
                    (contact1.resource_name, contact2)
                )
                logger.debug(
                    f"Will update in {self.account1_email}: {contact2.display_name}"
                )
                return

        # Both changed or no previous hash - conflict resolution needed
        conflict_result = self.conflict_resolver.resolve(contact1, contact2)
        result.conflicts.append(conflict_result)
        result.stats.conflicts_resolved += 1

        logger.debug(
            f"Conflict resolved for {contact1.display_name}: "
            f"{conflict_result.winning_side.value} wins - {conflict_result.reason}"
        )

        if conflict_result.winning_side == ConflictSide.ACCOUNT1:
            result.to_update_in_account2.append(
                (contact2.resource_name, contact1)
            )
        else:
            result.to_update_in_account1.append(
                (contact1.resource_name, contact2)
            )

    def _analyze_deletions(
        self,
        contacts1: List[Contact],
        contacts2: List[Contact],
        result: SyncResult
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
        self,
        deleted_contact: Contact,
        account: int,
        result: SyncResult
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
                f"No mapping found for deleted contact: "
                f"{deleted_contact.resource_name}"
            )
            return

        for mapping in mappings:
            matching_key = mapping['matching_key']

            if account == 1:
                # Deleted in account 1 - delete in account 2
                other_resource = mapping.get('account2_resource_name')
                if other_resource:
                    result.to_delete_in_account2.append(other_resource)
                    logger.debug(
                        f"Will delete in {self.account2_email}: {other_resource}"
                    )
            else:
                # Deleted in account 2 - delete in account 1
                other_resource = mapping.get('account1_resource_name')
                if other_resource:
                    result.to_delete_in_account1.append(other_resource)
                    logger.debug(
                        f"Will delete in {self.account1_email}: {other_resource}"
                    )

            # Remove the mapping
            self.database.delete_contact_mapping(matching_key)

    def _execute_creates(
        self,
        contacts: List[Contact],
        api: PeopleAPI,
        account: int,
        result: SyncResult
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
                        last_synced_hash=content_hash
                    )
                    result.stats.created_in_account1 += 1
                else:
                    self.database.upsert_contact_mapping(
                        matching_key=matching_key,
                        account2_resource_name=created_contact.resource_name,
                        account2_etag=created_contact.etag,
                        last_synced_hash=content_hash
                    )
                    result.stats.created_in_account2 += 1

        except PeopleAPIError as e:
            logger.error(f"Failed to create contacts in {account_label}: {e}")
            result.stats.errors += len(contacts)
            raise

    def _execute_updates(
        self,
        updates: List[Tuple[str, Contact]],
        api: PeopleAPI,
        account: int,
        result: SyncResult
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
                for (resource_name, source_contact), updated_contact in zip(
                    updates_with_etags, updated
                ):
                    matching_key = source_contact.matching_key()
                    content_hash = source_contact.content_hash()

                    if account == 1:
                        self.database.upsert_contact_mapping(
                            matching_key=matching_key,
                            account1_etag=updated_contact.etag,
                            last_synced_hash=content_hash
                        )
                        result.stats.updated_in_account1 += 1
                    else:
                        self.database.upsert_contact_mapping(
                            matching_key=matching_key,
                            account2_etag=updated_contact.etag,
                            last_synced_hash=content_hash
                        )
                        result.stats.updated_in_account2 += 1

        except PeopleAPIError as e:
            logger.error(f"Failed to update contacts in {account_label}: {e}")
            result.stats.errors += len(updates)
            raise

    def _execute_deletes(
        self,
        resource_names: List[str],
        api: PeopleAPI,
        account: int,
        result: SyncResult
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

    def _update_sync_tokens(self) -> None:
        """
        Update stored sync tokens after successful sync.
        """
        if not hasattr(self, '_pending_sync_tokens'):
            return

        for account_id, token in self._pending_sync_tokens.items():
            if token:
                self.database.update_sync_state(
                    account_id=account_id,
                    sync_token=token,
                    last_sync_at=datetime.utcnow()
                )
                logger.debug(f"Updated sync token for {account_id}")

    def get_status(self) -> Dict[str, any]:
        """
        Get current sync status information.

        Returns:
            Dictionary with sync status for both accounts
        """
        status = {
            'account1': None,
            'account2': None,
            'total_mappings': self.database.get_mapping_count()
        }

        state1 = self.database.get_sync_state(ACCOUNT_1)
        if state1:
            status['account1'] = {
                'last_sync': state1.get('last_sync_at'),
                'has_sync_token': bool(state1.get('sync_token'))
            }

        state2 = self.database.get_sync_state(ACCOUNT_2)
        if state2:
            status['account2'] = {
                'last_sync': state2.get('last_sync_at'),
                'has_sync_token': bool(state2.get('sync_token'))
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
