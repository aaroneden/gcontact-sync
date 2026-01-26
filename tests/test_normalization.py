"""Tests for string normalization utility."""

from gcontact_sync.utils.normalization import normalize_string


class TestNormalizeStringBasic:
    """Test basic normalization functionality."""

    def test_empty_string_returns_empty(self):
        """Empty string should return empty string."""
        assert normalize_string("") == ""

    def test_lowercase_conversion(self):
        """String should be converted to lowercase."""
        assert normalize_string("HELLO") == "hello"

    def test_unicode_normalization(self):
        """Unicode characters should be normalized."""
        # Accented e (composed) should match e
        assert normalize_string("caf\u00e9") == "cafe"
        # Decomposed form should also normalize
        assert normalize_string("cafe\u0301") == "cafe"

    def test_combining_characters_removed(self):
        """Combining diacritical marks should be removed."""
        assert normalize_string("n\u0303") == "n"  # n with tilde combining mark


class TestNormalizeStringPunctuation:
    """Test punctuation handling."""

    def test_punctuation_removed_by_default(self):
        """Punctuation should be removed by default."""
        assert normalize_string("hello, world!") == "helloworld"

    def test_punctuation_preserved_when_disabled(self):
        """Punctuation should be preserved when strip_punctuation=False."""
        assert (
            normalize_string(
                "hello, world!", strip_punctuation=False, remove_spaces=False
            )
            == "hello, world!"
        )


class TestNormalizeStringEmail:
    """Test email character handling."""

    def test_at_symbol_removed_by_default(self):
        """@ symbol should be removed by default."""
        assert normalize_string("test@example.com") == "testexamplecom"

    def test_at_symbol_preserved_for_email(self):
        """@ symbol should be preserved when allow_email_chars=True."""
        assert (
            normalize_string("test@example.com", allow_email_chars=True)
            == "test@examplecom"
        )


class TestNormalizeStringSpaces:
    """Test whitespace handling."""

    def test_spaces_removed_by_default(self):
        """Spaces should be removed by default."""
        assert normalize_string("hello world") == "helloworld"

    def test_spaces_preserved_when_disabled(self):
        """Spaces should be preserved when remove_spaces=False."""
        assert normalize_string("hello world", remove_spaces=False) == "hello world"

    def test_multiple_spaces_collapsed(self):
        """Multiple spaces should be collapsed to single space."""
        assert normalize_string("hello   world", remove_spaces=False) == "hello world"

    def test_leading_trailing_spaces_stripped(self):
        """Leading and trailing spaces should be stripped."""
        assert normalize_string("  hello world  ", remove_spaces=False) == "hello world"


class TestNormalizeStringSortWords:
    """Test word sorting functionality."""

    def test_sort_words_alphabetically(self):
        """Words should be sorted alphabetically when sort_words=True."""
        assert (
            normalize_string("zebra apple banana", sort_words=True)
            == "applebananazebra"
        )

    def test_sort_words_handles_name_order_variations(self):
        """Should handle 'Last, First' vs 'First Last' variations."""
        assert normalize_string("Smith John", sort_words=True) == normalize_string(
            "John Smith", sort_words=True
        )

    def test_sort_words_removes_punctuation_first(self):
        """Punctuation should be removed before sorting."""
        assert normalize_string("Last, First", sort_words=True) == normalize_string(
            "First Last", sort_words=True
        )


class TestNormalizeStringContactScenarios:
    """Test scenarios specific to contact matching."""

    def test_contact_name_normalization(self):
        """Test name normalization for contact matching."""
        # Names with different formats should normalize the same
        assert normalize_string("John Doe", sort_words=True) == normalize_string(
            "Doe, John", sort_words=True
        )

    def test_email_normalization_preserves_structure(self):
        """Email normalization should preserve @ but remove other special chars."""
        assert (
            normalize_string("Test.User@Example.COM", allow_email_chars=True)
            == "testuser@examplecom"
        )

    def test_name_with_accents_matches_without(self):
        """Names with accents should match names without."""
        assert normalize_string("José García", sort_words=True) == normalize_string(
            "Jose Garcia", sort_words=True
        )


class TestNormalizeStringGroupScenarios:
    """Test scenarios specific to group matching."""

    def test_group_name_preserves_punctuation(self):
        """Group names should preserve punctuation when configured."""
        result = normalize_string(
            "Work (San Francisco)", strip_punctuation=False, remove_spaces=False
        )
        assert result == "work (san francisco)"

    def test_group_name_normalizes_case_and_whitespace(self):
        """Group names should normalize case and collapse whitespace."""
        result = normalize_string(
            "My   Custom   Group", strip_punctuation=False, remove_spaces=False
        )
        assert result == "my custom group"
