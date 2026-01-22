"""
Unit tests for the multi-tier contact matching system.

Tests the ContactMatcher class for deterministic, fuzzy, and LLM matching.
"""

import pytest

from gcontact_sync.sync.contact import Contact
from gcontact_sync.sync.matcher import (
    ContactMatcher,
    MatchConfidence,
    MatchConfig,
    MatchResult,
    MatchTier,
    create_matching_keys,
)


@pytest.fixture
def matcher():
    """Create a matcher with LLM disabled for fast testing."""
    config = MatchConfig(use_llm_matching=False)
    return ContactMatcher(config=config)


@pytest.fixture
def matcher_with_llm():
    """Create a matcher with LLM enabled."""
    config = MatchConfig(use_llm_matching=True)
    return ContactMatcher(config=config)


class TestMatchTier:
    """Tests for MatchTier enum values."""

    def test_exact_email_tier(self):
        assert MatchTier.EXACT_EMAIL.value == "exact_email"

    def test_exact_phone_tier(self):
        assert MatchTier.EXACT_PHONE.value == "exact_phone"

    def test_fuzzy_tiers(self):
        assert MatchTier.FUZZY_NAME_EMAIL.value == "fuzzy_name_email"
        assert MatchTier.FUZZY_NAME_PHONE.value == "fuzzy_name_phone"

    def test_llm_tiers(self):
        assert MatchTier.LLM_MATCHED.value == "llm_matched"
        assert MatchTier.LLM_NOT_MATCHED.value == "llm_not_matched"


class TestMatchConfidence:
    """Tests for MatchConfidence enum values."""

    def test_confidence_levels(self):
        assert MatchConfidence.HIGH.value == "high"
        assert MatchConfidence.MEDIUM.value == "medium"
        assert MatchConfidence.LOW.value == "low"
        assert MatchConfidence.UNCERTAIN.value == "uncertain"


class TestMatchResult:
    """Tests for MatchResult dataclass."""

    def test_match_result_creation(self):
        result = MatchResult(
            is_match=True,
            tier=MatchTier.EXACT_EMAIL,
            confidence=MatchConfidence.HIGH,
            score=1.0,
            reason="Shared email: test@example.com",
            matched_on=["test@example.com"],
        )
        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_EMAIL
        assert result.confidence == MatchConfidence.HIGH
        assert result.score == 1.0


class TestTier1DeterministicMatching:
    """Tests for Tier 1: Deterministic matching (exact email/phone/name)."""

    def test_exact_email_match(self, matcher):
        """Test that identical emails result in a match."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@example.com"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jonathan Smith",  # Different name
            emails=["john@example.com"],  # Same email
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_EMAIL
        assert result.confidence == MatchConfidence.HIGH
        assert result.score == 1.0

    def test_exact_email_match_case_insensitive(self, matcher):
        """Test that email matching is case-insensitive."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John",
            emails=["JOHN@EXAMPLE.COM"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="John",
            emails=["john@example.com"],
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_EMAIL

    def test_exact_email_match_multiple_emails(self, matcher):
        """Test matching when contacts have multiple emails with one in common."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Maria",
            emails=["maria@work.com", "maria@personal.com"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Maria P",
            emails=["maria@personal.com", "maria@other.com"],
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_EMAIL
        assert "maria@personal.com" in result.reason

    def test_exact_phone_match(self, matcher):
        """Test that identical phones result in a match."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Bob Jones",
            emails=[],
            phones=["5551234567"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Robert Jones",  # Different name
            emails=[],
            phones=["5551234567"],  # Same phone
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_PHONE
        assert result.confidence == MatchConfidence.HIGH

    def test_phone_normalization(self, matcher):
        """Test that phone matching normalizes formats."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Test",
            emails=[],
            phones=["(555) 123-4567"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Test",
            emails=[],
            phones=["555-123-4567"],
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_PHONE

    def test_us_phone_country_code_normalization(self, matcher):
        """Test that US phone numbers with/without +1 match."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Test",
            emails=[],
            phones=["+15551234567"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Test",
            emails=[],
            phones=["5551234567"],
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_PHONE

    def test_exact_name_match(self, matcher):
        """Test that identical names (normalized) result in a match."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@company1.com"],  # Different email
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="John Smith",  # Same name
            emails=["john@company2.com"],  # Different email
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_NAME
        assert result.confidence == MatchConfidence.HIGH
        assert result.score == 1.0

    def test_exact_name_match_case_insensitive(self, matcher):
        """Test that name matching is case-insensitive."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="JOHN SMITH",
            emails=["john1@example.com"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="john smith",
            emails=["john2@example.com"],
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_NAME
        assert result.confidence == MatchConfidence.HIGH

    def test_exact_name_match_with_accents(self, matcher):
        """Test that name matching handles accented characters."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="José García",
            emails=["jose1@example.com"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jose Garcia",  # Without accents
            emails=["jose2@example.com"],
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_NAME
        assert result.confidence == MatchConfidence.HIGH

    def test_exact_name_match_with_special_chars(self, matcher):
        """Test that name matching handles special characters."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John O'Brien",
            emails=["john1@example.com"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="John OBrien",  # Without apostrophe
            emails=["john2@example.com"],
        )

        result = matcher.match(contact1, contact2)

        # These should match because normalization removes special chars
        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_NAME

    def test_exact_name_match_no_identifiers(self, matcher):
        """Test exact name match when neither contact has email/phone."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Kara Festa",
            emails=[],
            phones=[],
            organizations=["Carollo Engineers"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Kara Festa",
            emails=[],
            phones=[],
            organizations=["Carollo Engineers"],
        )

        result = matcher.match(contact1, contact2)

        # Should match via Tier 1 exact name with HIGH confidence
        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_NAME
        assert result.confidence == MatchConfidence.HIGH

    def test_email_takes_precedence_over_name(self, matcher):
        """Test that email match is returned even if name also matches."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@example.com"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="John Smith",  # Same name
            emails=["john@example.com"],  # Same email
        )

        result = matcher.match(contact1, contact2)

        # Email should be checked first, so EXACT_EMAIL tier
        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_EMAIL

    def test_no_match_different_names_and_identifiers(self, matcher):
        """Test that different names and different identifiers don't match."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@company1.com"],
            phones=["5551111111"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jane Doe",  # Different name
            emails=["jane@company2.com"],
            phones=["5552222222"],
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is False
        assert result.tier == MatchTier.NO_MATCH


class TestTier2FuzzyMatching:
    """Tests for Tier 2: Fuzzy matching (similar name + shared identifier)."""

    def test_fuzzy_name_with_shared_email(self, matcher):
        """Test fuzzy name match with a shared email."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@example.com"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jon Smith",  # Slightly different name
            emails=["jon@personal.com", "john@example.com"],  # Shared email
        )

        result = matcher.match(contact1, contact2)

        # Should match via exact email (Tier 1) since they share an email
        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_EMAIL

    def test_fuzzy_name_with_shared_phone(self, matcher):
        """Test fuzzy name match with a shared phone."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Michael Johnson",
            emails=[],
            phones=["5551234567"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Mike Johnson",  # Nickname
            emails=[],
            phones=["5551234567"],  # Same phone
        )

        result = matcher.match(contact1, contact2)

        # Should match via exact phone (Tier 1)
        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_PHONE

    def test_exact_name_no_identifiers(self, matcher):
        """Test exact name match when neither has identifiers."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Kara Festa",
            emails=[],
            phones=[],
            organizations=["Carollo Engineers"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Kara Festa",  # Exact same name
            emails=[],
            phones=[],
            organizations=["Carollo Engineers"],
        )

        result = matcher.match(contact1, contact2)

        # Should match via Tier 1 exact name with HIGH confidence
        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_NAME
        assert result.confidence == MatchConfidence.HIGH

    def test_similar_name_no_shared_identifiers(self, matcher):
        """Test similar names without shared identifiers."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Robert Smith",
            emails=["robert@company1.com"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Bob Smith",  # Similar but not exact
            emails=["bob@company2.com"],  # Different email
        )

        result = matcher.match(contact1, contact2)

        # Should NOT match - similar names but different emails
        # (This is uncertain, would need LLM to decide)
        assert result.is_match is False

    def test_completely_different_names(self, matcher):
        """Test that completely different names don't match."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@example.com"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Mary Johnson",  # Completely different
            emails=["mary@example.com"],
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is False
        assert result.tier == MatchTier.NO_MATCH


class TestMatcherConfiguration:
    """Tests for matcher configuration options."""

    def test_custom_name_threshold(self):
        """Test that custom name similarity threshold works."""
        # Very strict threshold
        strict_config = MatchConfig(name_similarity_threshold=0.99)
        strict_matcher = ContactMatcher(config=strict_config)

        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["shared@example.com"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jon Smith",  # 1 character different
            emails=["shared@example.com"],
        )

        # Should still match via exact email
        result = strict_matcher.match(contact1, contact2)
        assert result.is_match is True

    def test_llm_disabled(self):
        """Test that LLM can be disabled."""
        config = MatchConfig(use_llm_matching=False)
        matcher = ContactMatcher(config=config)

        assert matcher.config.use_llm_matching is False


class TestFindMatches:
    """Tests for the find_matches method."""

    def test_find_matches_returns_sorted_by_score(self, matcher):
        """Test that find_matches returns results sorted by score."""
        source = Contact(
            resource_name="people/source",
            etag="e1",
            display_name="John Smith",
            emails=["john@example.com"],
        )

        candidates = [
            Contact(
                resource_name="people/c1",
                etag="e1",
                display_name="Jane Doe",
                emails=["jane@example.com"],
            ),
            Contact(
                resource_name="people/c2",
                etag="e2",
                display_name="John Smith",  # Exact match
                emails=["john@example.com"],
            ),
            Contact(
                resource_name="people/c3",
                etag="e3",
                display_name="Johnny Smith",
                emails=["johnny@other.com"],
            ),
        ]

        matches = matcher.find_matches(source, candidates)

        # Should find the exact email match
        assert len(matches) >= 1
        # Best match should be first (highest score)
        best_match, best_result = matches[0]
        assert best_match.resource_name == "people/c2"
        assert best_result.tier == MatchTier.EXACT_EMAIL

    def test_find_matches_empty_candidates(self, matcher):
        """Test find_matches with empty candidate list."""
        source = Contact(
            resource_name="people/source",
            etag="e1",
            display_name="John",
            emails=["john@example.com"],
        )

        matches = matcher.find_matches(source, [])

        assert matches == []


class TestNormalization:
    """Tests for the normalization methods."""

    def test_email_normalization(self, matcher):
        """Test email normalization."""
        assert matcher._normalize_email("TEST@EXAMPLE.COM") == "test@example.com"
        assert matcher._normalize_email("  test@example.com  ") == "test@example.com"
        assert matcher._normalize_email("") == ""

    def test_phone_normalization(self, matcher):
        """Test phone normalization."""
        assert matcher._normalize_phone("(555) 123-4567") == "5551234567"
        assert matcher._normalize_phone("+1-555-123-4567") == "5551234567"
        assert matcher._normalize_phone("555.123.4567") == "5551234567"
        assert matcher._normalize_phone("") == ""

    def test_name_normalization(self, matcher):
        """Test name normalization."""
        assert matcher._normalize_name("John Doe") == "john doe"
        assert matcher._normalize_name("José García") == "jose garcia"
        assert matcher._normalize_name("John O'Brien-Smith") == "john obriensmith"
        assert matcher._normalize_name("") == ""


class TestRealWorldScenarios:
    """Tests based on real-world contact matching scenarios."""

    def test_maria_damiana_perrin_scenario(self, matcher):
        """Test the Maria Damiana Perrin scenario from the bug report."""
        # Account 1: Has 2 emails
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Maria Damiana Perrin",
            emails=["mariaperrin@msn.com", "maria@oldadoberealty.com"],
            phones=["(520) 207-3535", "(520) 975-0301"],
            organizations=["Concept 100 Realty"],
        )
        # Account 2: Same emails
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Maria Damiana Perrin",
            emails=["maria@oldadoberealty.com", "mariaperrin@msn.com"],
            phones=["5202073535"],
            organizations=["Concept 100 Realty"],
        )

        result = matcher.match(contact1, contact2)

        # Should match via shared email
        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_EMAIL

    def test_dave_lim_scenario(self, matcher):
        """Test the Dave Lim scenario from the bug report."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Dave Lim TM",
            emails=["david@innovationx.asia"],
            phones=["6596396050"],
            organizations=["Innovation X powered by The Coca-Cola Company"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Dave Lim",  # Slightly different name (no TM)
            emails=["david@innovationx.asia"],
            phones=["6596396050"],
        )

        result = matcher.match(contact1, contact2)

        # Should match via shared email
        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_EMAIL

    def test_kara_festa_scenario(self, matcher):
        """Test the Kara Festa scenario (org only, no email/phone match)."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Kara Festa",
            emails=[],
            phones=[],
            organizations=["Carollo Engineers"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Kara Festa",
            emails=[],
            phones=[],
            organizations=["Carollo Engineers"],
        )

        result = matcher.match(contact1, contact2)

        # Should match via Tier 1 exact name with HIGH confidence
        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_NAME
        assert result.confidence == MatchConfidence.HIGH


class TestPhoneValidationBugs:
    """Tests for phone number validation bugs discovered in production.

    These tests document real bugs found during debug analysis:
    1. Empty phone strings matching each other (Bug #1)
    2. Invalid phone values (no digits) being treated as valid (Bug #3)
    """

    def test_empty_phone_strings_should_not_match(self, matcher):
        """
        Bug #1: Invalid phones that normalize to empty strings should NOT match.

        Real case from production:
        - Will S Murphy has phones: ['9012639400', '9017522753', 'Wp',
          'william.murphy@fedex.com']
        - Siddhant Jain has phones: ['LLMs']
        - 'Wp' and 'LLMs' both normalize to empty strings and matched!

        This caused a FALSE POSITIVE match between completely unrelated people.
        """
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Will S Murphy",
            emails=["will.s.murphy@gmail.com"],
            phones=["9012639400", "9017522753", "Wp", "william.murphy@fedex.com"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Siddhant Jain",
            emails=["sjain35@buffalo.edu"],
            phones=["LLMs"],  # This normalizes to empty string
        )

        result = matcher.match(contact1, contact2)

        # These should NOT match - they are completely different people
        assert result.is_match is False, (
            "Contacts with invalid phones that normalize to empty strings "
            "should NOT match on those empty strings"
        )

    def test_text_only_phone_should_not_create_valid_key(self, matcher):
        """
        Bug #1 variant: Phone values with no digits should not create matching keys.

        Values like 'Wp', 'LLMs', 'Home', etc. have no digits and should be ignored.
        """
        contact = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Test Person",
            emails=[],
            phones=["Wp", "LLMs", "Home"],  # All invalid - no digits
        )

        keys = create_matching_keys(contact, matcher)

        # Should fall back to name-only key since no valid phones
        assert len(keys) == 1
        assert keys[0].startswith("name:")
        # Should NOT have any phone keys
        assert not any("phone:" in k for k in keys)

    def test_email_in_phone_field_should_not_match(self, matcher):
        """
        Bug #1 variant: Email addresses stored in phone fields should not match.

        Real case: 'william.murphy@fedex.com' was in a phone field,
        normalized to empty string (no digits), and matched other empty phones.
        """
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Person One",
            emails=[],
            phones=["william.murphy@fedex.com"],  # Email in phone field
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Person Two",
            emails=[],
            phones=["info@example.com"],  # Another email in phone field
        )

        result = matcher.match(contact1, contact2)

        # Should NOT match on invalid phone values
        assert result.is_match is False

    def test_minimum_phone_length_validation(self, matcher):
        """
        Bug #3: Phone numbers should have a minimum length to be valid.

        Very short digit sequences (1-6 digits) are likely not real phone numbers
        and could cause false matches. Real phone numbers typically have 7+ digits.
        """
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Person One",
            emails=[],
            phones=["123"],  # Too short to be a real phone
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Person Two",
            emails=[],
            phones=["123"],  # Same short "phone"
        )

        result = matcher.match(contact1, contact2)

        # Should NOT match on phone numbers that are too short
        assert result.is_match is False, (
            "Phone numbers with fewer than 7 digits should not be used for matching"
        )

    def test_short_phone_should_not_create_key(self, matcher):
        """
        Bug #3 variant: Short digit sequences should not create phone keys.

        Phone numbers should have at least 7 digits to be valid for matching.
        """
        contact = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Test Person",
            emails=[],
            phones=["123", "1234", "12345", "123456"],  # All too short
        )

        keys = create_matching_keys(contact, matcher)

        # Should fall back to name-only key since no valid phones
        assert len(keys) == 1
        assert keys[0].startswith("name:")
        # Should NOT have any phone keys for short numbers
        assert not any("phone:" in k for k in keys)

    def test_valid_phone_length_seven_digits(self, matcher):
        """Test that 7-digit phone numbers ARE valid (local numbers)."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Person One",
            emails=[],
            phones=["5551234"],  # 7 digits - valid local number
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Person Two",
            emails=[],
            phones=["5551234"],  # Same phone
        )

        result = matcher.match(contact1, contact2)

        # Should match on valid 7-digit phone
        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_PHONE

    def test_valid_phone_length_ten_digits(self, matcher):
        """Test that 10-digit phone numbers ARE valid (US standard)."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Person One",
            emails=[],
            phones=["5551234567"],  # 10 digits - standard US
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Person Two",
            emails=[],
            phones=["5551234567"],
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_PHONE

    def test_mixed_valid_and_invalid_phones(self, matcher):
        """Test that valid phones still match even when invalid ones are present."""
        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="Person One",
            emails=[],
            phones=["5551234567", "Wp", "123"],  # One valid, two invalid
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Person Two",
            emails=[],
            phones=["LLMs", "5551234567", "456"],  # One valid (shared), two invalid
        )

        result = matcher.match(contact1, contact2)

        # Should match on the valid shared phone
        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_PHONE
        assert "5551234567" in result.reason


class TestCreateMatchingKeys:
    """Tests for the create_matching_keys function."""

    def test_generates_key_for_each_email(self, matcher):
        """Test that a key is generated for each email address."""
        contact = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@work.com", "john@personal.com", "john@other.com"],
        )

        keys = create_matching_keys(contact, matcher)

        assert len(keys) == 3
        assert "email:john@work.com" in keys
        assert "email:john@personal.com" in keys
        assert "email:john@other.com" in keys

    def test_generates_key_for_each_phone(self, matcher):
        """Test that a key is generated for each phone number."""
        contact = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=[],
            phones=["5551234567", "5559876543"],
        )

        keys = create_matching_keys(contact, matcher)

        assert len(keys) == 2
        assert "phone:5551234567" in keys
        assert "phone:5559876543" in keys

    def test_generates_keys_for_both_emails_and_phones(self, matcher):
        """Test that keys are generated for both emails and phones."""
        contact = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@example.com"],
            phones=["5551234567"],
        )

        keys = create_matching_keys(contact, matcher)

        assert len(keys) == 2
        assert "email:john@example.com" in keys
        assert "phone:5551234567" in keys

    def test_falls_back_to_name_only_key(self, matcher):
        """Test that a name-only key is generated when no identifiers exist."""
        contact = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=[],
            phones=[],
        )

        keys = create_matching_keys(contact, matcher)

        assert len(keys) == 1
        assert keys[0] == "name:john smith"

    def test_normalizes_emails(self, matcher):
        """Test that emails are normalized (lowercased, stripped)."""
        contact = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John",
            emails=["  JOHN@EXAMPLE.COM  "],
        )

        keys = create_matching_keys(contact, matcher)

        assert "email:john@example.com" in keys

    def test_normalizes_phones(self, matcher):
        """Test that phones are normalized (digits only, no country code)."""
        contact = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John",
            emails=[],
            phones=["+1 (555) 123-4567"],
        )

        keys = create_matching_keys(contact, matcher)

        assert "phone:5551234567" in keys

    def test_shared_identifier_generates_matching_key(self, matcher):
        """
        Test that contacts sharing any identifier will have a matching key.

        This is the critical test - the old alphabetical-first approach would
        fail if the shared identifier wasn't alphabetically first.
        """
        # Contact A has work email first alphabetically
        contact_a = Contact(
            resource_name="people/a",
            etag="e1",
            display_name="John Smith",
            emails=["aaron@company.com", "john@personal.com"],
        )
        # Contact B only has the personal email (which is NOT first alphabetically in A)
        contact_b = Contact(
            resource_name="people/b",
            etag="e2",
            display_name="John Smith",
            emails=["john@personal.com"],
        )

        keys_a = create_matching_keys(contact_a, matcher)
        keys_b = create_matching_keys(contact_b, matcher)

        # Both should have a key for john@personal.com
        shared_key = "email:john@personal.com"
        assert shared_key in keys_a
        assert shared_key in keys_b

        # There should be overlap between the key sets
        assert set(keys_a) & set(keys_b), (
            "Contacts with shared email must have overlapping keys"
        )

    def test_skips_empty_identifiers(self, matcher):
        """Test that empty strings are skipped."""
        contact = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John",
            emails=["john@example.com", "", None],  # type: ignore
            phones=["5551234567", ""],
        )

        keys = create_matching_keys(contact, matcher)

        # Should only have keys for non-empty values
        assert len(keys) == 2
        assert "email:john@example.com" in keys
        assert "phone:5551234567" in keys


class TestOrganizationMatching:
    """Tests for organization-based matching (Tier 2 enhancement)."""

    def test_fuzzy_name_with_shared_organization(self):
        """Test that similar names with shared organization match."""
        config = MatchConfig(use_llm_matching=False, use_organization_matching=True)
        matcher = ContactMatcher(config=config)

        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@company1.com"],
            phones=[],
            organizations=["Acme Corporation"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jon Smith",  # Similar name
            emails=["jon@company2.com"],  # Different email
            phones=[],
            organizations=["Acme Corporation"],  # Same org
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.FUZZY_NAME_ORG
        assert result.confidence == MatchConfidence.MEDIUM
        assert (
            "Acme" in result.reason.lower() or "organization" in result.reason.lower()
        )

    def test_organization_matching_disabled(self):
        """Test that organization matching can be disabled via config."""
        config = MatchConfig(use_llm_matching=False, use_organization_matching=False)
        matcher = ContactMatcher(config=config)

        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@company1.com"],
            phones=[],
            organizations=["Acme Corporation"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jon Smith",
            emails=["jon@company2.com"],
            phones=[],
            organizations=["Acme Corporation"],
        )

        result = matcher.match(contact1, contact2)

        # Should NOT match when org matching is disabled
        assert result.is_match is False
        assert result.tier != MatchTier.FUZZY_NAME_ORG

    def test_organization_normalization_inc(self):
        """Test that 'Inc' suffix is normalized away."""
        config = MatchConfig(use_llm_matching=False, use_organization_matching=True)
        matcher = ContactMatcher(config=config)

        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@company1.com"],
            phones=[],
            organizations=["Acme Inc"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jon Smith",
            emails=["jon@company2.com"],
            phones=[],
            organizations=["Acme"],  # Without Inc
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.FUZZY_NAME_ORG

    def test_organization_normalization_corporation(self):
        """Test that 'Corporation' suffix is normalized away."""
        config = MatchConfig(use_llm_matching=False, use_organization_matching=True)
        matcher = ContactMatcher(config=config)

        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@company1.com"],
            phones=[],
            organizations=["Acme Corporation"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jon Smith",
            emails=["jon@company2.com"],
            phones=[],
            organizations=["Acme Corp"],  # Different suffix
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.FUZZY_NAME_ORG

    def test_organization_normalization_llc(self):
        """Test that 'LLC' suffix is normalized away."""
        config = MatchConfig(use_llm_matching=False, use_organization_matching=True)
        matcher = ContactMatcher(config=config)

        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@company1.com"],
            phones=[],
            organizations=["Smith Consulting LLC"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jon Smith",
            emails=["jon@company2.com"],
            phones=[],
            organizations=["Smith Consulting"],  # Without LLC
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.FUZZY_NAME_ORG

    def test_organization_case_insensitive(self):
        """Test that organization matching is case-insensitive."""
        config = MatchConfig(use_llm_matching=False, use_organization_matching=True)
        matcher = ContactMatcher(config=config)

        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@company1.com"],
            phones=[],
            organizations=["ACME CORPORATION"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jon Smith",
            emails=["jon@company2.com"],
            phones=[],
            organizations=["acme corporation"],
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.FUZZY_NAME_ORG

    def test_no_match_different_organizations(self):
        """Test that different organizations don't trigger org match."""
        config = MatchConfig(use_llm_matching=False, use_organization_matching=True)
        matcher = ContactMatcher(config=config)

        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@company1.com"],
            phones=[],
            organizations=["Acme Corp"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jon Smith",
            emails=["jon@company2.com"],
            phones=[],
            organizations=["Widget Inc"],  # Different org
        )

        result = matcher.match(contact1, contact2)

        # Should NOT match on different organizations
        assert result.tier != MatchTier.FUZZY_NAME_ORG

    def test_no_match_dissimilar_names_same_org(self):
        """Test that dissimilar names with same org don't match."""
        config = MatchConfig(use_llm_matching=False, use_organization_matching=True)
        matcher = ContactMatcher(config=config)

        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@company1.com"],
            phones=[],
            organizations=["Acme Corp"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Mary Johnson",  # Completely different name
            emails=["mary@company2.com"],
            phones=[],
            organizations=["Acme Corp"],  # Same org
        )

        result = matcher.match(contact1, contact2)

        # Should NOT match - names are too different
        assert result.is_match is False
        assert result.tier != MatchTier.FUZZY_NAME_ORG

    def test_email_match_takes_precedence_over_org(self):
        """Test that email match (Tier 1) takes precedence over org match."""
        config = MatchConfig(use_llm_matching=False, use_organization_matching=True)
        matcher = ContactMatcher(config=config)

        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@example.com"],
            phones=[],
            organizations=["Acme Corp"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jon Smith",
            emails=["john@example.com"],  # Same email
            phones=[],
            organizations=["Acme Corp"],  # Same org
        )

        result = matcher.match(contact1, contact2)

        # Email match should take precedence (Tier 1)
        assert result.is_match is True
        assert result.tier == MatchTier.EXACT_EMAIL

    def test_multiple_organizations_one_shared(self):
        """Test matching when contacts have multiple orgs with one in common."""
        config = MatchConfig(use_llm_matching=False, use_organization_matching=True)
        matcher = ContactMatcher(config=config)

        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@company1.com"],
            phones=[],
            organizations=["Previous Corp", "Current Inc"],
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jon Smith",
            emails=["jon@company2.com"],
            phones=[],
            organizations=["Current Inc", "Side Project LLC"],  # One shared
        )

        result = matcher.match(contact1, contact2)

        assert result.is_match is True
        assert result.tier == MatchTier.FUZZY_NAME_ORG
        assert "current" in result.reason.lower()

    def test_empty_organization_no_match(self):
        """Test that empty organizations don't cause false matches."""
        config = MatchConfig(use_llm_matching=False, use_organization_matching=True)
        matcher = ContactMatcher(config=config)

        contact1 = Contact(
            resource_name="people/c1",
            etag="e1",
            display_name="John Smith",
            emails=["john@company1.com"],
            phones=[],
            organizations=[""],  # Empty org
        )
        contact2 = Contact(
            resource_name="people/c2",
            etag="e2",
            display_name="Jon Smith",
            emails=["jon@company2.com"],
            phones=[],
            organizations=[""],  # Empty org
        )

        result = matcher.match(contact1, contact2)

        # Should NOT match on empty organizations
        assert result.tier != MatchTier.FUZZY_NAME_ORG
