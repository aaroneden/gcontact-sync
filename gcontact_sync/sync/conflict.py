"""
Conflict resolution module for bidirectional contact synchronization.

Provides strategies for resolving conflicts when contacts have been
modified in both Google accounts since the last sync.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from gcontact_sync.sync.contact import Contact


class ConflictStrategy(Enum):
    """Available conflict resolution strategies."""

    LAST_MODIFIED_WINS = "last_modified_wins"
    ACCOUNT1_WINS = "account1_wins"
    ACCOUNT2_WINS = "account2_wins"


class ConflictSide(Enum):
    """Indicates which side won a conflict resolution."""

    ACCOUNT1 = "account1"
    ACCOUNT2 = "account2"
    NO_CONFLICT = "no_conflict"
    EQUAL = "equal"


@dataclass
class ConflictResult:
    """
    Result of a conflict resolution operation.

    Attributes:
        winner: The contact that won the conflict
        loser: The contact that lost the conflict
        winning_side: Which account's contact won
        reason: Human-readable explanation of why this side won
        needs_update_in_account1: True if account1 needs to be updated
        needs_update_in_account2: True if account2 needs to be updated
    """

    winner: Contact
    loser: Contact
    winning_side: ConflictSide
    reason: str
    needs_update_in_account1: bool = False
    needs_update_in_account2: bool = False


class ConflictResolver:
    """
    Resolves conflicts between contacts from two Google accounts.

    Implements the last-modified-wins strategy as the default, with
    fallback options for other conflict resolution approaches.

    Usage:
        resolver = ConflictResolver()

        # Check if there's a conflict
        if resolver.has_conflict(contact1, contact2, last_synced_hash):
            result = resolver.resolve(contact1, contact2)
            if result.winning_side == ConflictSide.ACCOUNT1:
                # Update account2 with contact1's data
                pass

    Attributes:
        strategy: The conflict resolution strategy to use
    """

    def __init__(
        self, strategy: ConflictStrategy = ConflictStrategy.LAST_MODIFIED_WINS
    ):
        """
        Initialize the conflict resolver.

        Args:
            strategy: The conflict resolution strategy to use
        """
        self.strategy = strategy

    def has_conflict(
        self,
        contact1: Contact,
        contact2: Contact,
        last_synced_hash: Optional[str] = None,
    ) -> bool:
        """
        Determine if two contacts are in conflict.

        A conflict exists when:
        1. Both contacts have different content (different content_hash)
        2. Both contacts have changed since the last sync (if hash provided)
        3. The contacts represent the same logical entity (same matching_key)

        Args:
            contact1: Contact from account 1
            contact2: Contact from account 2
            last_synced_hash: Content hash from the last sync (optional)

        Returns:
            True if there is a conflict requiring resolution
        """
        # Same content means no conflict
        hash1 = contact1.content_hash()
        hash2 = contact2.content_hash()

        if hash1 == hash2:
            return False

        # Different matching keys means not the same contact
        if contact1.matching_key() != contact2.matching_key():
            return False

        # If we have a last synced hash, both must have changed for a conflict
        if last_synced_hash is not None:
            # If only one changed, it's not a conflict - just propagate the change
            contact1_changed = hash1 != last_synced_hash
            contact2_changed = hash2 != last_synced_hash

            # True conflict: both changed independently
            return contact1_changed and contact2_changed

        # Without last synced hash, any difference is a potential conflict
        return True

    def resolve(self, contact1: Contact, contact2: Contact) -> ConflictResult:
        """
        Resolve a conflict between two contacts.

        Applies the configured strategy to determine which contact's
        data should be used as the source of truth.

        Args:
            contact1: Contact from account 1
            contact2: Contact from account 2

        Returns:
            ConflictResult with the winner, loser, and update requirements
        """
        if self.strategy == ConflictStrategy.LAST_MODIFIED_WINS:
            return self._resolve_last_modified_wins(contact1, contact2)
        elif self.strategy == ConflictStrategy.ACCOUNT1_WINS:
            return self._resolve_account_wins(contact1, contact2, account=1)
        elif self.strategy == ConflictStrategy.ACCOUNT2_WINS:
            return self._resolve_account_wins(contact1, contact2, account=2)
        else:
            # Default to last-modified-wins
            return self._resolve_last_modified_wins(contact1, contact2)

    def _resolve_last_modified_wins(
        self, contact1: Contact, contact2: Contact
    ) -> ConflictResult:
        """
        Resolve conflict using last-modified-wins strategy.

        The contact with the most recent last_modified timestamp wins.
        If timestamps are equal or both missing, falls back to account1.

        Args:
            contact1: Contact from account 1
            contact2: Contact from account 2

        Returns:
            ConflictResult with resolution details
        """
        # Get timestamps, defaulting to epoch if not available
        # Use UTC epoch to ensure timezone-aware comparison
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        time1 = contact1.last_modified or epoch
        time2 = contact2.last_modified or epoch

        # Ensure both are comparable (handle mixed naive/aware datetimes)
        # If one has tzinfo and the other doesn't, assume UTC for the naive one
        if time1.tzinfo is None and time2.tzinfo is not None:
            time1 = time1.replace(tzinfo=timezone.utc)
        elif time2.tzinfo is None and time1.tzinfo is not None:
            time2 = time2.replace(tzinfo=timezone.utc)

        # Determine winner
        if time1 > time2:
            return ConflictResult(
                winner=contact1,
                loser=contact2,
                winning_side=ConflictSide.ACCOUNT1,
                reason=f"Account 1 has newer modification time ({time1} > {time2})",
                needs_update_in_account1=False,
                needs_update_in_account2=True,
            )
        elif time2 > time1:
            return ConflictResult(
                winner=contact2,
                loser=contact1,
                winning_side=ConflictSide.ACCOUNT2,
                reason=f"Account 2 has newer modification time ({time2} > {time1})",
                needs_update_in_account1=True,
                needs_update_in_account2=False,
            )
        else:
            # Equal timestamps - fallback to account1 as tie-breaker
            return ConflictResult(
                winner=contact1,
                loser=contact2,
                winning_side=ConflictSide.ACCOUNT1,
                reason=f"Equal timestamps ({time1}), defaulting to account 1",
                needs_update_in_account1=False,
                needs_update_in_account2=True,
            )

    def _resolve_account_wins(
        self, contact1: Contact, contact2: Contact, account: int
    ) -> ConflictResult:
        """
        Resolve conflict by always preferring one account.

        Args:
            contact1: Contact from account 1
            contact2: Contact from account 2
            account: Which account should always win (1 or 2)

        Returns:
            ConflictResult with resolution details
        """
        if account == 1:
            return ConflictResult(
                winner=contact1,
                loser=contact2,
                winning_side=ConflictSide.ACCOUNT1,
                reason="Account 1 always wins (configured strategy)",
                needs_update_in_account1=False,
                needs_update_in_account2=True,
            )
        else:
            return ConflictResult(
                winner=contact2,
                loser=contact1,
                winning_side=ConflictSide.ACCOUNT2,
                reason="Account 2 always wins (configured strategy)",
                needs_update_in_account1=True,
                needs_update_in_account2=False,
            )

    def compare_timestamps(
        self, contact1: Contact, contact2: Contact
    ) -> tuple[Optional[datetime], Optional[datetime], int]:
        """
        Compare modification timestamps of two contacts.

        Args:
            contact1: Contact from account 1
            contact2: Contact from account 2

        Returns:
            Tuple of (time1, time2, comparison_result) where comparison_result is:
            - -1 if time1 < time2 (contact2 is newer)
            -  0 if time1 == time2 (equal)
            -  1 if time1 > time2 (contact1 is newer)
        """
        time1 = contact1.last_modified
        time2 = contact2.last_modified

        # Handle None cases
        if time1 is None and time2 is None:
            return (None, None, 0)
        elif time1 is None:
            return (None, time2, -1)  # contact2 is newer (has timestamp)
        elif time2 is None:
            return (time1, None, 1)  # contact1 is newer (has timestamp)

        # Both have timestamps
        if time1 > time2:
            return (time1, time2, 1)
        elif time2 > time1:
            return (time1, time2, -1)
        else:
            return (time1, time2, 0)

    def needs_sync(
        self,
        contact1: Contact,
        contact2: Contact,
        last_synced_hash: Optional[str] = None,
    ) -> tuple[bool, bool]:
        """
        Determine which accounts need to be updated for sync.

        This is a convenience method that determines if contacts need
        to be synced without necessarily being in conflict.

        Args:
            contact1: Contact from account 1
            contact2: Contact from account 2
            last_synced_hash: Content hash from the last sync (optional)

        Returns:
            Tuple of (needs_update_in_account1, needs_update_in_account2)
        """
        hash1 = contact1.content_hash()
        hash2 = contact2.content_hash()

        # Same content means no sync needed
        if hash1 == hash2:
            return (False, False)

        # Check if this is a conflict (both changed) or one-way update
        if last_synced_hash is not None:
            contact1_changed = hash1 != last_synced_hash
            contact2_changed = hash2 != last_synced_hash

            if contact1_changed and not contact2_changed:
                # Only account1 changed - propagate to account2
                return (False, True)
            elif contact2_changed and not contact1_changed:
                # Only account2 changed - propagate to account1
                return (True, False)
            elif contact1_changed and contact2_changed:
                # Both changed - resolve conflict
                result = self.resolve(contact1, contact2)
                return (
                    result.needs_update_in_account1,
                    result.needs_update_in_account2,
                )
            else:
                # Neither changed from sync state but different from each other
                # This shouldn't happen in normal operation
                result = self.resolve(contact1, contact2)
                return (
                    result.needs_update_in_account1,
                    result.needs_update_in_account2,
                )
        else:
            # No last synced hash - resolve based on strategy
            result = self.resolve(contact1, contact2)
            return (result.needs_update_in_account1, result.needs_update_in_account2)

    def __repr__(self) -> str:
        """Return a readable string representation."""
        return f"ConflictResolver(strategy={self.strategy.value})"
