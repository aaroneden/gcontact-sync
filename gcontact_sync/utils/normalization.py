"""
String normalization utilities for contact and group matching.

Provides consistent string normalization for generating matching keys
used in cross-account contact and group identification.
"""

from __future__ import annotations

import re
import unicodedata


def normalize_string(
    value: str,
    sort_words: bool = False,
    allow_email_chars: bool = False,
    remove_spaces: bool = True,
    strip_punctuation: bool = True,
) -> str:
    """
    Normalize a string for matching key generation.

    Args:
        value: String to normalize
        sort_words: If True, sort words alphabetically before joining.
                   This handles name order variations like "Last, First"
                   vs "First Last".
        allow_email_chars: If True, preserve @ symbol for email normalization.
                          Only applies when strip_punctuation is True.
        remove_spaces: If True, remove all spaces from the result.
                      If False, multiple spaces are collapsed to single space.
        strip_punctuation: If True, remove non-alphanumeric characters.
                          If False, only normalize unicode and whitespace.

    Returns:
        Normalized lowercase string with special characters handled
    """
    if not value:
        return ""

    # Normalize unicode (decompose accents, etc.)
    normalized = unicodedata.normalize("NFKD", value)

    # Remove combining characters (accents)
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))

    # Convert to lowercase
    normalized = normalized.lower()

    # Optionally remove punctuation and special characters
    if strip_punctuation:
        # Build character pattern based on options
        pattern = r"[^a-z0-9@\s]" if allow_email_chars else r"[^a-z0-9\s]"
        normalized = re.sub(pattern, "", normalized)

    # Normalize whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()

    # Sort words alphabetically if requested (for name normalization)
    # This handles "Last, First" vs "First Last" variations
    if sort_words:
        words = normalized.split()
        normalized = "".join(sorted(words))
    elif remove_spaces:
        # Remove spaces for key generation
        normalized = normalized.replace(" ", "")

    return normalized
