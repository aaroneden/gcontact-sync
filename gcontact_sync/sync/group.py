"""
ContactGroup data model for Google Contacts group synchronization.

Provides a normalized ContactGroup representation with methods for:
- Converting to/from Google People API contactGroups format
- Generating matching keys for cross-account identification
- Computing content hashes for change detection
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from gcontact_sync.utils import normalize_string

# Group types as defined by Google People API
GROUP_TYPE_UNSPECIFIED = "GROUP_TYPE_UNSPECIFIED"
GROUP_TYPE_USER_CONTACT_GROUP = "USER_CONTACT_GROUP"
GROUP_TYPE_SYSTEM_CONTACT_GROUP = "SYSTEM_CONTACT_GROUP"

# System group resource names (these should not be synced)
SYSTEM_GROUP_NAMES = frozenset(
    {
        "contactGroups/myContacts",
        "contactGroups/starred",
        "contactGroups/all",
        "contactGroups/friends",
        "contactGroups/family",
        "contactGroups/coworkers",
    }
)


@dataclass
class ContactGroup:
    """
    Normalized contact group representation for bidirectional sync.

    Attributes:
        resource_name: Google's unique ID (e.g., "contactGroups/123abc")
        etag: Required for updates, prevents concurrent modification conflicts
        name: Display name of the group (e.g., "Family", "Work")
        group_type: Type of group (USER_CONTACT_GROUP or SYSTEM_CONTACT_GROUP)
        member_count: Number of members in the group (optional, from API)
        member_resource_names: List of contact resource names in the group (optional)
        formatted_name: Formatted name returned by API (may differ from name)
        deleted: True if group was deleted in source

    Usage:
        # Create from API response
        group = ContactGroup.from_api_response(api_response)

        # Generate matching key for comparison
        key = group.matching_key()

        # Check for changes
        hash_value = group.content_hash()

        # Convert back to API format
        api_data = group.to_api_format()
    """

    resource_name: str  # Google's unique ID (e.g., "contactGroups/123abc")
    etag: str  # Required for updates
    name: str  # Group name (user-defined label)
    group_type: str  # USER_CONTACT_GROUP or SYSTEM_CONTACT_GROUP

    # Optional fields from API
    member_count: int = 0
    member_resource_names: list[str] = field(default_factory=list)
    formatted_name: str | None = None

    # Additional fields for sync tracking
    deleted: bool = False  # True if group was deleted in source

    @classmethod
    def from_api_response(cls, group_data: dict[str, Any]) -> ContactGroup:
        """
        Create a ContactGroup from a Google People API response.

        Args:
            group_data: Dictionary from Google People API containing group data

        Returns:
            ContactGroup instance populated from the API response

        Example API response structure::

            {
                'resourceName': 'contactGroups/123abc',
                'etag': 'xyz789',
                'name': 'My Custom Group',
                'formattedName': 'My Custom Group',
                'groupType': 'USER_CONTACT_GROUP',
                'memberCount': 5,
                'memberResourceNames': ['people/c1', 'people/c2', ...],
                'metadata': {
                    'deleted': False,
                    'updateTime': '2024-01-01T00:00:00Z'
                }
            }
        """
        # Extract basic fields
        resource_name = group_data.get("resourceName", "")
        etag = group_data.get("etag", "")
        name = group_data.get("name", "")
        formatted_name = group_data.get("formattedName")
        group_type = group_data.get("groupType", GROUP_TYPE_UNSPECIFIED)

        # Extract member information
        member_count = group_data.get("memberCount", 0)
        member_resource_names = group_data.get("memberResourceNames", [])

        # Check if group is deleted
        metadata = group_data.get("metadata", {})
        deleted = metadata.get("deleted", False)

        return cls(
            resource_name=resource_name,
            etag=etag,
            name=name,
            group_type=group_type,
            member_count=member_count,
            member_resource_names=member_resource_names,
            formatted_name=formatted_name,
            deleted=deleted,
        )

    def to_api_format(self) -> dict[str, Any]:
        """
        Convert ContactGroup to Google People API format for create/update operations.

        Returns:
            Dictionary in Google People API contactGroup format

        Note:
            - Does not include resourceName (set by Google on create)
            - Does not include etag (should be passed separately for updates)
            - Does not include memberCount or memberResourceNames (managed separately)
            - Only includes the name field for user contact groups
        """
        group: dict[str, Any] = {}

        # Only include name - this is the only writable field for contactGroups
        if self.name:
            group["name"] = self.name

        return group

    def matching_key(self) -> str:
        """
        Generate a normalized matching key for cross-account identification.

        For contact groups, the matching key is based on the normalized group name.
        This allows matching groups across accounts by their display name.

        Returns:
            Lowercase, normalized string key for matching

        Note:
            Group names are unique within an account, so the normalized name
            serves as a reliable matching key across accounts.
        """
        return normalize_string(self.name, strip_punctuation=False, remove_spaces=False)

    def content_hash(self) -> str:
        """
        Generate a hash of the group's content for change detection.

        The hash includes only the name field, as that's the only
        user-modifiable field for contact groups.

        Excludes:
            - resource_name (different per account)
            - etag (different per account)
            - member_count (can change without group update)
            - member_resource_names (managed separately)
            - group_type (immutable)

        Returns:
            SHA-256 hash string of group content
        """
        # Build a deterministic string from content fields
        content_parts = [
            f"name:{self.name}",
        ]

        content_string = "\n".join(content_parts)

        # Generate SHA-256 hash
        return hashlib.sha256(content_string.encode("utf-8")).hexdigest()

    def is_user_group(self) -> bool:
        """
        Check if this is a user-created contact group.

        Returns:
            True if the group is a user contact group (not system)
        """
        return self.group_type == GROUP_TYPE_USER_CONTACT_GROUP

    def is_system_group(self) -> bool:
        """
        Check if this is a system contact group.

        System groups (myContacts, starred, etc.) should not be synced
        as they are account-specific.

        Returns:
            True if the group is a system contact group
        """
        return (
            self.group_type == GROUP_TYPE_SYSTEM_CONTACT_GROUP
            or self.resource_name in SYSTEM_GROUP_NAMES
        )

    def is_syncable(self) -> bool:
        """
        Check if the group can be synced between accounts.

        A group is syncable if:
            - It's a user contact group
            - It has a name
            - It's not deleted

        Returns:
            True if the group is valid for syncing
        """
        return self.is_user_group() and bool(self.name) and not self.deleted

    def __eq__(self, other: object) -> bool:
        """
        Check equality based on content (not resource_name or etag).

        Two groups are equal if their content hash matches.
        """
        if not isinstance(other, ContactGroup):
            return NotImplemented
        return self.content_hash() == other.content_hash()

    def __hash__(self) -> int:
        """
        Generate hash based on matching key.

        Note: This allows using ContactGroup in sets/dicts keyed by matching identity.
        """
        return hash(self.matching_key())

    def __repr__(self) -> str:
        """Return a readable string representation."""
        return (
            f"ContactGroup(resource_name={self.resource_name!r}, "
            f"name={self.name!r}, "
            f"group_type={self.group_type!r}, "
            f"member_count={self.member_count})"
        )
