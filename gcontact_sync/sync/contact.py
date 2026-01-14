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
from typing import Any, Dict, List, Optional


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
    etag: str           # Required for updates
    display_name: str

    given_name: Optional[str] = None
    family_name: Optional[str] = None
    emails: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    organizations: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    last_modified: Optional[datetime] = None

    # Additional fields for sync tracking
    deleted: bool = False  # True if contact was deleted in source

    @classmethod
    def from_api_response(cls, person: Dict[str, Any]) -> 'Contact':
        """
        Create a Contact from a Google People API response.

        Args:
            person: Dictionary from Google People API containing contact data

        Returns:
            Contact instance populated from the API response

        Example API response structure:
            {
                'resourceName': 'people/c12345',
                'etag': 'abc123',
                'names': [{'displayName': 'John Doe', 'givenName': 'John', 'familyName': 'Doe'}],
                'emailAddresses': [{'value': 'john@example.com'}],
                'phoneNumbers': [{'value': '+1234567890'}],
                'organizations': [{'name': 'Acme Corp'}],
                'biographies': [{'value': 'Some notes'}],
                'metadata': {'sources': [{'updateTime': '2024-01-01T00:00:00Z'}]}
            }
        """
        # Extract name fields
        names = person.get('names', [{}])
        primary_name = names[0] if names else {}

        display_name = primary_name.get('displayName', '')
        given_name = primary_name.get('givenName')
        family_name = primary_name.get('familyName')

        # If no display name, construct from given/family names
        if not display_name and (given_name or family_name):
            parts = [p for p in [given_name, family_name] if p]
            display_name = ' '.join(parts)

        # Extract email addresses
        emails = [
            e.get('value', '')
            for e in person.get('emailAddresses', [])
            if e.get('value')
        ]

        # Extract phone numbers
        phones = [
            p.get('value', '')
            for p in person.get('phoneNumbers', [])
            if p.get('value')
        ]

        # Extract organizations
        organizations = [
            o.get('name', '')
            for o in person.get('organizations', [])
            if o.get('name')
        ]

        # Extract notes from biographies
        biographies = person.get('biographies', [])
        notes = biographies[0].get('value') if biographies else None

        # Extract last modified time from metadata
        last_modified = None
        metadata = person.get('metadata', {})
        sources = metadata.get('sources', [])
        if sources:
            update_time = sources[0].get('updateTime')
            if update_time:
                try:
                    # Parse ISO format timestamp
                    # Handle both 'Z' suffix and timezone offset
                    update_time = update_time.replace('Z', '+00:00')
                    last_modified = datetime.fromisoformat(update_time)
                except (ValueError, TypeError):
                    pass

        # Check if contact is deleted
        deleted = person.get('metadata', {}).get('deleted', False)

        return cls(
            resource_name=person.get('resourceName', ''),
            etag=person.get('etag', ''),
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

    def to_api_format(self) -> Dict[str, Any]:
        """
        Convert Contact to Google People API format for create/update operations.

        Returns:
            Dictionary in Google People API format

        Note:
            - Does not include resourceName (set by Google on create)
            - Does not include etag (should be passed separately for updates)
            - Only includes non-empty fields
        """
        person: Dict[str, Any] = {}

        # Add names if available
        if self.given_name or self.family_name or self.display_name:
            name_entry: Dict[str, str] = {}
            if self.given_name:
                name_entry['givenName'] = self.given_name
            if self.family_name:
                name_entry['familyName'] = self.family_name
            # Only add displayName if no given/family name
            if self.display_name and not (self.given_name or self.family_name):
                name_entry['displayName'] = self.display_name
            if name_entry:
                person['names'] = [name_entry]

        # Add email addresses
        if self.emails:
            person['emailAddresses'] = [{'value': e} for e in self.emails]

        # Add phone numbers
        if self.phones:
            person['phoneNumbers'] = [{'value': p} for p in self.phones]

        # Add organizations
        if self.organizations:
            person['organizations'] = [{'name': o} for o in self.organizations]

        # Add notes as biography
        if self.notes:
            person['biographies'] = [{'value': self.notes, 'contentType': 'TEXT_PLAIN'}]

        return person

    def matching_key(self) -> str:
        """
        Generate a normalized matching key for cross-account identification.

        The key is based on normalized display name + primary email (if available).
        This allows identifying the same contact across different accounts.

        Returns:
            Lowercase, normalized string key for matching

        Key generation rules:
            1. Normalize unicode characters (e.g., accents)
            2. Convert to lowercase
            3. Remove non-alphanumeric characters (except @)
            4. Combine name and primary email with separator
        """
        # Normalize and lowercase the display name
        name = self._normalize_string(self.display_name)

        # Get primary email (first in list) if available
        primary_email = ''
        if self.emails:
            primary_email = self._normalize_string(self.emails[0])

        # Combine name and email
        if primary_email:
            return f"{name}|{primary_email}"
        return name

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

        content_string = '\n'.join(content_parts)

        # Generate SHA-256 hash
        return hashlib.sha256(content_string.encode('utf-8')).hexdigest()

    def _normalize_string(self, value: str) -> str:
        """
        Normalize a string for matching key generation.

        Args:
            value: String to normalize

        Returns:
            Normalized lowercase string with special characters removed
        """
        if not value:
            return ''

        # Normalize unicode (decompose accents, etc.)
        normalized = unicodedata.normalize('NFKD', value)

        # Remove combining characters (accents)
        normalized = ''.join(
            c for c in normalized
            if not unicodedata.combining(c)
        )

        # Convert to lowercase
        normalized = normalized.lower()

        # Remove non-alphanumeric characters except @ and spaces
        # Replace multiple spaces with single space
        normalized = re.sub(r'[^a-z0-9@\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        # Remove spaces for key generation
        normalized = normalized.replace(' ', '')

        return normalized

    def _normalize_phones(self) -> List[str]:
        """
        Normalize phone numbers for consistent hashing.

        Removes all non-digit characters for comparison.

        Returns:
            List of normalized phone number strings
        """
        normalized = []
        for phone in self.phones:
            # Keep only digits
            digits = re.sub(r'\D', '', phone)
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
