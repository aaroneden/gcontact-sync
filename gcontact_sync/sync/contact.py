"""
Contact data model for Google Contacts synchronization.

Provides a normalized Contact representation with methods for:
- Converting to/from Google People API format
- Generating matching keys for cross-account identification
- Computing content hashes for change detection
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class Contact:
    """
    Normalized contact representation for bidirectional sync.

    Attributes:
        resource_name: Google's unique ID (e.g., "people/c12345")
        etag: Required for updates, prevents concurrent modification conflicts
        display_name: Full display name of the contact
        given_name: First name
        family_name: Last name
        emails: List of email addresses
        phones: List of phone numbers
        organizations: List of organization names
        notes: Contact notes
        last_modified: Timestamp of last modification
        photo_url: URL to contact's photo
        photo_data: Binary photo data
        photo_etag: ETag for photo version tracking

    Usage:
        # Create from API response
        contact = Contact.from_api_response(api_response)

        # Generate matching key for comparison
        key = contact.matching_key()

        # Check for changes
        hash_value = contact.content_hash()

        # Convert back to API format
        api_data = contact.to_api_format()
    """

    resource_name: str  # Google's unique ID (e.g., "people/c12345")
    etag: str  # Required for updates
    display_name: str

    given_name: Optional[str] = None
    family_name: Optional[str] = None
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)
    notes: Optional[str] = None
    last_modified: Optional[datetime] = None

    # Photo fields
    photo_url: Optional[str] = None
    photo_data: Optional[bytes] = None
    photo_etag: Optional[str] = None

    # Additional fields for sync tracking
    deleted: bool = False  # True if contact was deleted in source

    @classmethod
    def from_api_response(cls, person: dict[str, Any]) -> "Contact":
        """
        Create a Contact from a Google People API response.

        Args:
            person: Dictionary from Google People API containing contact data

        Returns:
            Contact instance populated from the API response

        Example API response structure::

            {
                'resourceName': 'people/c12345',
                'etag': 'abc123',
                'names': [{'displayName': 'John Doe', ...}],
                'emailAddresses': [{'value': 'john@example.com'}],
                'phoneNumbers': [{'value': '+1234567890'}],
                'organizations': [{'name': 'Acme Corp'}],
                'biographies': [{'value': 'Some notes'}],
                'metadata': {'sources': [{'updateTime': '...'}]}
            }
        """
        # Extract name fields
        names = person.get("names", [{}])
        primary_name = names[0] if names else {}

        display_name = primary_name.get("displayName", "")
        given_name = primary_name.get("givenName")
        family_name = primary_name.get("familyName")

        # If no display name, construct from given/family names
        if not display_name and (given_name or family_name):
            parts = [p for p in [given_name, family_name] if p]
            display_name = " ".join(parts)

        # Extract email addresses
        emails = [
            e.get("value", "")
            for e in person.get("emailAddresses", [])
            if e.get("value")
        ]

        # Extract phone numbers
        phones = [
            p.get("value", "") for p in person.get("phoneNumbers", []) if p.get("value")
        ]

        # Extract organizations
        organizations = [
            o.get("name", "") for o in person.get("organizations", []) if o.get("name")
        ]

        # Extract notes from biographies
        biographies = person.get("biographies", [])
        notes = biographies[0].get("value") if biographies else None

        # Extract last modified time from metadata
        last_modified = None
        metadata = person.get("metadata", {})
        sources = metadata.get("sources", [])
        if sources:
            update_time = sources[0].get("updateTime")
            if update_time:
                try:
                    # Parse ISO format timestamp
                    # Handle both 'Z' suffix and timezone offset
                    update_time = update_time.replace("Z", "+00:00")
                    last_modified = datetime.fromisoformat(update_time)
                except (ValueError, TypeError):
                    pass

        # Check if contact is deleted
        deleted = person.get("metadata", {}).get("deleted", False)

        return cls(
            resource_name=person.get("resourceName", ""),
            etag=person.get("etag", ""),
            display_name=display_name,
            given_name=given_name,
            family_name=family_name,
            emails=emails,
            phones=phones,
            organizations=organizations,
            notes=notes,
            last_modified=last_modified,
            deleted=deleted,
        )

    def to_api_format(self) -> dict[str, Any]:
        """
        Convert Contact to Google People API format for create/update operations.

        Returns:
            Dictionary in Google People API format

        Note:
            - Does not include resourceName (set by Google on create)
            - Does not include etag (should be passed separately for updates)
            - Only includes non-empty fields
        """
        person: dict[str, Any] = {}

        # Add names if available
        if self.given_name or self.family_name or self.display_name:
            name_entry: dict[str, str] = {}
            if self.given_name:
                name_entry["givenName"] = self.given_name
            if self.family_name:
                name_entry["familyName"] = self.family_name
            # Only add displayName if no given/family name
            if self.display_name and not (self.given_name or self.family_name):
                name_entry["displayName"] = self.display_name
            if name_entry:
                person["names"] = [name_entry]

        # Add email addresses
        if self.emails:
            person["emailAddresses"] = [{"value": e} for e in self.emails]

        # Add phone numbers
        if self.phones:
            person["phoneNumbers"] = [{"value": p} for p in self.phones]

        # Add organizations
        if self.organizations:
            person["organizations"] = [{"name": o} for o in self.organizations]

        # Add notes as biography
        if self.notes:
            person["biographies"] = [{"value": self.notes, "contentType": "TEXT_PLAIN"}]

        return person

    def matching_key(self) -> str:
        """
        Generate a normalized matching key for cross-account identification.

        Uses a single-identifier strategy to robustly identify the same
        contact across different accounts, even when fields are organized
        differently (e.g., work vs. home email, different phone field types,
        or one account has more emails than the other).

        Returns:
            Lowercase, normalized string key for matching

        Key generation strategy (in order of priority):
            1. If emails exist: name + first email (alphabetically sorted)
            2. If phones exist (no emails): name + first phone (sorted)
            3. If neither: name only

        This prevents duplicates by:
            - Using the FIRST email (alphabetically) for consistent matching
            - Matching contacts even when one account has additional emails
            - Sorting ensures same "primary" email is chosen in both accounts
            - Using phone numbers as fallback identifiers
            - Normalizing all values for consistent comparison

        Note:
            Using only the first email (instead of all) allows contacts to
            match even when one account has additional emails that the other
            doesn't have. This is the common case in contact sync scenarios.
        """
        # Normalize and lowercase the display name
        name = self._normalize_string(self.display_name)

        # Get all normalized emails, sorted for consistency
        normalized_emails = sorted(
            [
                self._normalize_string(email)
                for email in self.emails
                if email and self._normalize_string(email)
            ]
        )

        # Get all normalized phone numbers, sorted for consistency
        normalized_phones = sorted(
            [
                phone
                for phone in self._normalize_phones()
                if phone  # Filter out empty strings
            ]
        )

        # Priority: name + first email > name + first phone > name only
        if normalized_emails:
            # Use FIRST email only (sorted alphabetically for consistency)
            # This allows matching when accounts have different email sets
            first_email = normalized_emails[0]
            return f"{name}|email:{first_email}"
        elif normalized_phones:
            # Fall back to first phone number if no emails
            first_phone = normalized_phones[0]
            return f"{name}|phone:{first_phone}"
        else:
            # Last resort: name only (higher risk of false matches)
            return f"{name}|name_only"

    def alternate_matching_keys(self) -> list[str]:
        """
        Generate alternate matching keys for fuzzy duplicate detection.

        These additional keys can be used to find potential duplicates when
        the primary matching key doesn't match exactly. Useful for detecting
        contacts that might be the same person but with slightly different data.

        Returns:
            List of alternate matching keys

        Alternate keys include:
            - Individual email addresses (for matching by any single email)
            - Individual phone numbers (for matching by any single phone)
            - Name + each individual email combination
            - Name + each individual phone combination
        """
        keys: list[str] = []
        name = self._normalize_string(self.display_name)

        # Add individual email-based keys
        for email in self.emails:
            if email:
                normalized_email = self._normalize_string(email)
                if normalized_email:
                    keys.append(f"email:{normalized_email}")
                    keys.append(f"{name}|email:{normalized_email}")

        # Add individual phone-based keys
        for phone in self._normalize_phones():
            if phone:
                keys.append(f"phone:{phone}")
                keys.append(f"{name}|phone:{phone}")

        return keys

    def content_hash(self) -> str:
        """
        Generate a hash of the contact's content for change detection.

        The hash includes all syncable fields but excludes:
            - resource_name (different per account)
            - etag (different per account)
            - last_modified (metadata, not content)

        Returns:
            SHA-256 hash string of contact content

        Note:
            Lists are sorted before hashing to ensure consistent ordering.
        """
        # Build a deterministic string from all content fields
        content_parts = [
            f"display_name:{self.display_name}",
            f"given_name:{self.given_name or ''}",
            f"family_name:{self.family_name or ''}",
            f"emails:{','.join(sorted(self.emails))}",
            f"phones:{','.join(sorted(self._normalize_phones()))}",
            f"organizations:{','.join(sorted(self.organizations))}",
            f"notes:{self.notes or ''}",
        ]

        content_string = "\n".join(content_parts)

        # Generate SHA-256 hash
        return hashlib.sha256(content_string.encode("utf-8")).hexdigest()

    def _normalize_string(self, value: str) -> str:
        """
        Normalize a string for matching key generation.

        Args:
            value: String to normalize

        Returns:
            Normalized lowercase string with special characters removed
        """
        if not value:
            return ""

        # Normalize unicode (decompose accents, etc.)
        normalized = unicodedata.normalize("NFKD", value)

        # Remove combining characters (accents)
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))

        # Convert to lowercase
        normalized = normalized.lower()

        # Remove non-alphanumeric characters except @ and spaces
        # Replace multiple spaces with single space
        normalized = re.sub(r"[^a-z0-9@\s]", "", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        # Remove spaces for key generation
        normalized = normalized.replace(" ", "")

        return normalized

    def _normalize_phones(self) -> list[str]:
        """
        Normalize phone numbers for consistent hashing.

        Removes all non-digit characters for comparison.

        Returns:
            List of normalized phone number strings
        """
        normalized = []
        for phone in self.phones:
            # Keep only digits
            digits = re.sub(r"\D", "", phone)
            normalized.append(digits)
        return normalized

    def is_valid(self) -> bool:
        """
        Check if the contact has enough information to be synced.

        A contact is valid if it has at least a display name or an email.

        Returns:
            True if the contact is valid for syncing
        """
        return bool(self.display_name or self.emails)

    def __eq__(self, other: object) -> bool:
        """
        Check equality based on content (not resource_name or etag).

        Two contacts are equal if their content hash matches.
        """
        if not isinstance(other, Contact):
            return NotImplemented
        return self.content_hash() == other.content_hash()

    def __hash__(self) -> int:
        """
        Generate hash based on matching key.

        Note: This allows using Contact in sets/dicts keyed by matching identity.
        """
        return hash(self.matching_key())

    def __repr__(self) -> str:
        """Return a readable string representation."""
        return (
            f"Contact(resource_name={self.resource_name!r}, "
            f"display_name={self.display_name!r}, "
            f"emails={self.emails!r})"
        )
