"""
Multi-tier contact matching system for cross-account identification.

Implements a tiered matching strategy:
- Tier 1: Deterministic matching (exact email, phone, or name match)
- Tier 2: Fuzzy matching (similar name + shared identifier)
- Tier 3: LLM-assisted matching (for uncertain cases)

This allows robust matching even when contacts have:
- Different email sets between accounts
- Name variations (nicknames, middle names, typos)
- Missing or different phone formats
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

from rapidfuzz import fuzz

if TYPE_CHECKING:
    from gcontact_sync.storage.db import SyncDatabase
    from gcontact_sync.sync.contact import Contact
    from gcontact_sync.sync.llm_matcher import LLMMatcher

logger = logging.getLogger(__name__)


class MatchTier(Enum):
    """Classification of how a match was determined."""

    EXACT_EMAIL = "exact_email"  # Same email address
    EXACT_PHONE = "exact_phone"  # Same phone number
    FUZZY_NAME_EMAIL = "fuzzy_name_email"  # Similar name + shared email
    FUZZY_NAME_PHONE = "fuzzy_name_phone"  # Similar name + shared phone
    EXACT_NAME = "exact_name"  # Exact name match (no identifier overlap)
    LLM_MATCHED = "llm_matched"  # LLM determined as match
    LLM_NOT_MATCHED = "llm_not_matched"  # LLM determined as not match
    NO_MATCH = "no_match"  # No match found


class MatchConfidence(Enum):
    """Confidence level of a match."""

    HIGH = "high"  # Deterministic match (Tier 1)
    MEDIUM = "medium"  # Fuzzy match (Tier 2)
    LOW = "low"  # Name-only or LLM match (Tier 3)
    UNCERTAIN = "uncertain"  # Needs LLM review


@dataclass
class MatchResult:
    """Result of a contact matching attempt."""

    is_match: bool
    tier: MatchTier
    confidence: MatchConfidence
    score: float  # 0.0 to 1.0 similarity score
    reason: str  # Human-readable explanation
    matched_on: list[str] = field(default_factory=list)  # Fields that matched


@dataclass
class MatchConfig:
    """Configuration for the contact matcher."""

    # Fuzzy name matching threshold (0.0 to 1.0)
    # 0.85 = 85% similarity required for fuzzy name match
    name_similarity_threshold: float = 0.85

    # Stricter threshold for name-only matches (no email/phone)
    name_only_threshold: float = 0.95

    # Whether to use LLM for uncertain matches
    use_llm_matching: bool = True

    # Maximum contacts to send to LLM for batch matching
    llm_batch_size: int = 20


class ContactMatcher:
    """
    Multi-tier contact matching system.

    Matches contacts across accounts using a tiered approach:

    Tier 1 - Deterministic (High Confidence):
        - Exact email match (normalized, case-insensitive)
        - Exact phone match (digits only)
        - Exact name match (normalized, case-insensitive)

    Tier 2 - Fuzzy (Medium Confidence):
        - Fuzzy name match (≥85% Jaro-Winkler) + shared email
        - Fuzzy name match (≥85% Jaro-Winkler) + shared phone

    Tier 3 - LLM-Assisted (Variable Confidence):
        - Similar name (70-85%) but no shared identifiers
        - Uncertain cases sent to LLM for review

    Usage:
        matcher = ContactMatcher()

        # Match two contacts
        result = matcher.match(contact1, contact2)
        if result.is_match:
            print(f"Match found via {result.tier.value}")

        # Find matches for a contact in a list
        matches = matcher.find_matches(contact, candidate_list)
    """

    def __init__(
        self,
        config: Optional[MatchConfig] = None,
        database: Optional["SyncDatabase"] = None,
    ):
        """
        Initialize the contact matcher.

        Args:
            config: Optional configuration. Uses defaults if not provided.
            database: Optional SyncDatabase for LLM decision caching.
        """
        self.config = config or MatchConfig()
        self._database = database
        self._llm_client: Optional[LLMMatcher] = None  # Lazy-loaded when needed

    def match(self, contact1: "Contact", contact2: "Contact") -> MatchResult:
        """
        Determine if two contacts represent the same person.

        Uses tiered matching: deterministic first, then fuzzy, then LLM if needed.

        Args:
            contact1: First contact to compare
            contact2: Second contact to compare

        Returns:
            MatchResult with match decision and metadata
        """
        # Tier 1: Deterministic matching
        result = self._tier1_deterministic_match(contact1, contact2)
        if result.is_match:
            return result

        # Tier 2: Fuzzy matching
        result = self._tier2_fuzzy_match(contact1, contact2)
        if result.is_match:
            return result

        # Check if we should escalate to LLM
        if (
            result.confidence == MatchConfidence.UNCERTAIN
            and self.config.use_llm_matching
        ):
            # Tier 3: LLM matching (to be implemented)
            return self._tier3_llm_match(contact1, contact2)

        return result

    def find_matches(
        self, contact: "Contact", candidates: list["Contact"]
    ) -> list[tuple["Contact", MatchResult]]:
        """
        Find all matching contacts from a list of candidates.

        Args:
            contact: The contact to find matches for
            candidates: List of candidate contacts to check

        Returns:
            List of (matched_contact, match_result) tuples, sorted by score
        """
        matches = []
        uncertain = []

        for candidate in candidates:
            result = self.match(contact, candidate)
            if result.is_match:
                matches.append((candidate, result))
            elif result.confidence == MatchConfidence.UNCERTAIN:
                uncertain.append((candidate, result))

        # Sort by score (highest first)
        matches.sort(key=lambda x: x[1].score, reverse=True)

        # If we have uncertain matches, batch process with LLM
        if uncertain and self.config.use_llm_matching:
            llm_results = self._batch_llm_match(contact, uncertain)
            matches.extend(llm_results)
            matches.sort(key=lambda x: x[1].score, reverse=True)

        return matches

    def _tier1_deterministic_match(
        self, contact1: "Contact", contact2: "Contact"
    ) -> MatchResult:
        """
        Tier 1: Deterministic matching based on exact identifiers or exact name.

        Matches if contacts share any email, phone number, or have identical names
        (normalized, case-insensitive).
        """
        # Normalize emails for comparison
        emails1 = {self._normalize_email(e) for e in contact1.emails if e}
        emails2 = {self._normalize_email(e) for e in contact2.emails if e}

        # Check for shared email
        shared_emails = emails1 & emails2
        if shared_emails:
            return MatchResult(
                is_match=True,
                tier=MatchTier.EXACT_EMAIL,
                confidence=MatchConfidence.HIGH,
                score=1.0,
                reason=f"Shared email: {list(shared_emails)[0]}",
                matched_on=list(shared_emails),
            )

        # Normalize phones for comparison
        phones1 = {self._normalize_phone(p) for p in contact1.phones if p}
        phones2 = {self._normalize_phone(p) for p in contact2.phones if p}

        # Check for shared phone
        shared_phones = phones1 & phones2
        if shared_phones:
            return MatchResult(
                is_match=True,
                tier=MatchTier.EXACT_PHONE,
                confidence=MatchConfidence.HIGH,
                score=1.0,
                reason=f"Shared phone: {list(shared_phones)[0]}",
                matched_on=list(shared_phones),
            )

        # Check for exact name match (normalized, case-insensitive)
        name1 = self._normalize_name(contact1.display_name)
        name2 = self._normalize_name(contact2.display_name)

        if name1 and name2 and name1 == name2:
            return MatchResult(
                is_match=True,
                tier=MatchTier.EXACT_NAME,
                confidence=MatchConfidence.HIGH,
                score=1.0,
                reason=f"Exact name match: {contact1.display_name}",
                matched_on=["name"],
            )

        # No deterministic match
        return MatchResult(
            is_match=False,
            tier=MatchTier.NO_MATCH,
            confidence=MatchConfidence.UNCERTAIN,
            score=0.0,
            reason="No shared email, phone, or exact name",
        )

    def _tier2_fuzzy_match(
        self, contact1: "Contact", contact2: "Contact"
    ) -> MatchResult:
        """
        Tier 2: Fuzzy matching based on name similarity + shared identifiers.

        Matches if names are similar (≥85%) AND they share at least one email or phone.
        Note: Exact name matches are handled in Tier 1.
        """
        # Calculate name similarity
        name1 = self._normalize_name(contact1.display_name)
        name2 = self._normalize_name(contact2.display_name)

        if not name1 or not name2:
            return MatchResult(
                is_match=False,
                tier=MatchTier.NO_MATCH,
                confidence=MatchConfidence.LOW,
                score=0.0,
                reason="One or both contacts have no name",
            )

        # Use Jaro-Winkler for name similarity (good for names)
        name_score = fuzz.ratio(name1, name2) / 100.0
        jaro_score = fuzz.WRatio(name1, name2) / 100.0

        # Use the better of the two scores
        similarity = max(name_score, jaro_score)

        # Check for shared identifiers
        emails1 = {self._normalize_email(e) for e in contact1.emails if e}
        emails2 = {self._normalize_email(e) for e in contact2.emails if e}
        shared_emails = emails1 & emails2

        phones1 = {self._normalize_phone(p) for p in contact1.phones if p}
        phones2 = {self._normalize_phone(p) for p in contact2.phones if p}
        shared_phones = phones1 & phones2

        # Fuzzy name + shared email
        if similarity >= self.config.name_similarity_threshold and shared_emails:
            return MatchResult(
                is_match=True,
                tier=MatchTier.FUZZY_NAME_EMAIL,
                confidence=MatchConfidence.MEDIUM,
                score=similarity,
                reason=(
                    f"Similar name ({similarity:.0%}) + "
                    f"shared email: {list(shared_emails)[0]}"
                ),
                matched_on=["name", *list(shared_emails)],
            )

        # Fuzzy name + shared phone
        if similarity >= self.config.name_similarity_threshold and shared_phones:
            return MatchResult(
                is_match=True,
                tier=MatchTier.FUZZY_NAME_PHONE,
                confidence=MatchConfidence.MEDIUM,
                score=similarity,
                reason=(
                    f"Similar name ({similarity:.0%}) + "
                    f"shared phone: {list(shared_phones)[0]}"
                ),
                matched_on=["name", *list(shared_phones)],
            )

        # Exact name match (very high similarity) with no identifiers
        if similarity >= self.config.name_only_threshold:
            # Both have no identifiers - likely same person
            has_identifiers1 = bool(emails1 or phones1)
            has_identifiers2 = bool(emails2 or phones2)

            if not has_identifiers1 and not has_identifiers2:
                return MatchResult(
                    is_match=True,
                    tier=MatchTier.EXACT_NAME,
                    confidence=MatchConfidence.LOW,
                    score=similarity,
                    reason=f"Exact name match ({similarity:.0%}), no identifiers",
                    matched_on=["name"],
                )

            # One has identifiers, other doesn't - could be same person
            # Mark as uncertain for LLM review
            return MatchResult(
                is_match=False,
                tier=MatchTier.NO_MATCH,
                confidence=MatchConfidence.UNCERTAIN,
                score=similarity,
                reason=(
                    f"Exact name match ({similarity:.0%}) but "
                    "different/missing identifiers"
                ),
                matched_on=["name"],
            )

        # Similar but not matching
        if similarity >= 0.7:
            return MatchResult(
                is_match=False,
                tier=MatchTier.NO_MATCH,
                confidence=MatchConfidence.UNCERTAIN,
                score=similarity,
                reason=f"Similar name ({similarity:.0%}), no shared identifiers",
            )

        return MatchResult(
            is_match=False,
            tier=MatchTier.NO_MATCH,
            confidence=MatchConfidence.LOW,
            score=similarity,
            reason=f"Different names ({similarity:.0%})",
        )

    def _tier3_llm_match(self, contact1: "Contact", contact2: "Contact") -> MatchResult:
        """
        Tier 3: LLM-assisted matching for uncertain cases.

        Uses an LLM to analyze contacts and determine if they're the same person.
        LLM decisions are cached in the database if one is configured.
        """
        from gcontact_sync.sync.llm_matcher import LLMMatcher

        if self._llm_client is None:
            try:
                self._llm_client = LLMMatcher(database=self._database)
            except Exception as e:
                logger.warning(f"Could not initialize LLM matcher: {e}")
                return MatchResult(
                    is_match=False,
                    tier=MatchTier.NO_MATCH,
                    confidence=MatchConfidence.UNCERTAIN,
                    score=0.5,
                    reason=f"LLM matching unavailable: {e}",
                )

        try:
            decision = self._llm_client.match_pair(contact1, contact2)

            if decision.is_match:
                return MatchResult(
                    is_match=True,
                    tier=MatchTier.LLM_MATCHED,
                    confidence=MatchConfidence.LOW,
                    score=decision.confidence,
                    reason=f"LLM match: {decision.reasoning}",
                    matched_on=["llm_analysis"],
                )
            else:
                return MatchResult(
                    is_match=False,
                    tier=MatchTier.LLM_NOT_MATCHED,
                    confidence=MatchConfidence.LOW,
                    score=decision.confidence,
                    reason=f"LLM no match: {decision.reasoning}",
                )

        except Exception as e:
            logger.error(f"LLM matching failed: {e}")
            return MatchResult(
                is_match=False,
                tier=MatchTier.NO_MATCH,
                confidence=MatchConfidence.UNCERTAIN,
                score=0.5,
                reason=f"LLM matching error: {e}",
            )

    def _batch_llm_match(
        self,
        contact: "Contact",
        uncertain_pairs: list[tuple["Contact", MatchResult]],
    ) -> list[tuple["Contact", MatchResult]]:
        """
        Batch process uncertain matches with LLM.

        Args:
            contact: The source contact
            uncertain_pairs: List of (candidate, result) tuples to review

        Returns:
            List of (contact, result) tuples that LLM confirmed as matches
        """
        if not uncertain_pairs:
            return []

        from gcontact_sync.sync.llm_matcher import LLMMatcher

        if self._llm_client is None:
            try:
                self._llm_client = LLMMatcher(database=self._database)
            except Exception as e:
                logger.warning(f"Could not initialize LLM matcher: {e}")
                return []

        try:
            candidates = [pair[0] for pair in uncertain_pairs]
            llm_results = self._llm_client.match_batch(contact, candidates)

            matches = []
            for matched_contact, decision in llm_results:
                result = MatchResult(
                    is_match=True,
                    tier=MatchTier.LLM_MATCHED,
                    confidence=MatchConfidence.LOW,
                    score=decision.confidence,
                    reason=f"LLM batch match: {decision.reasoning}",
                    matched_on=["llm_analysis"],
                )
                matches.append((matched_contact, result))

            return matches

        except Exception as e:
            logger.error(f"Batch LLM matching failed: {e}")
            return []

    def _normalize_email(self, email: str) -> str:
        """Normalize an email address for comparison."""
        if not email:
            return ""
        # Lowercase and strip whitespace
        return email.lower().strip()

    def _normalize_phone(self, phone: str) -> str:
        """Normalize a phone number for comparison (digits only)."""
        if not phone:
            return ""
        # Keep only digits
        digits = re.sub(r"\D", "", phone)
        # Remove leading 1 for US numbers if 11 digits
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        return digits

    def _normalize_name(self, name: str) -> str:
        """Normalize a name for comparison."""
        if not name:
            return ""

        # Normalize unicode
        normalized = unicodedata.normalize("NFKD", name)

        # Remove combining characters (accents)
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))

        # Lowercase
        normalized = normalized.lower()

        # Remove special characters but keep spaces
        normalized = re.sub(r"[^a-z0-9\s]", "", normalized)

        # Normalize whitespace
        normalized = " ".join(normalized.split())

        return normalized


def create_matching_keys(contact: "Contact", matcher: ContactMatcher) -> list[str]:
    """
    Generate all matching keys for a contact.

    Creates a key for EACH identifier (email and phone) so that contacts
    can be matched on any shared identifier, not just the alphabetically first one.

    Args:
        contact: The contact to generate keys for
        matcher: The matcher instance (for normalization methods)

    Returns:
        List of normalized matching key strings
    """
    keys = []
    name = matcher._normalize_name(contact.display_name)

    # Create a key for each email
    for email in contact.emails:
        if email:
            normalized = matcher._normalize_email(email)
            keys.append(f"email:{normalized}")

    # Create a key for each phone
    for phone in contact.phones:
        if phone:
            normalized = matcher._normalize_phone(phone)
            if normalized:  # Phone normalization can return empty string
                keys.append(f"phone:{normalized}")

    # If no identifiers, use name-only key
    if not keys:
        keys.append(f"name:{name}")

    return keys
