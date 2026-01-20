"""
Unit tests for the ContactGroup data model.

Tests the ContactGroup class for API conversion, matching key generation,
content hashing, and comparison operations.
"""

from gcontact_sync.sync.group import (
    GROUP_TYPE_SYSTEM_CONTACT_GROUP,
    GROUP_TYPE_UNSPECIFIED,
    GROUP_TYPE_USER_CONTACT_GROUP,
    SYSTEM_GROUP_NAMES,
    ContactGroup,
)


class TestContactGroupBasics:
    """Tests for basic ContactGroup instantiation and attributes."""

    def test_create_group_with_required_fields(self):
        """Test creating a group with only required fields."""
        group = ContactGroup(
            resource_name="contactGroups/abc123",
            etag="etag123",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        assert group.resource_name == "contactGroups/abc123"
        assert group.etag == "etag123"
        assert group.name == "My Group"
        assert group.group_type == GROUP_TYPE_USER_CONTACT_GROUP

    def test_create_group_with_all_fields(self):
        """Test creating a group with all fields."""
        group = ContactGroup(
            resource_name="contactGroups/abc123",
            etag="etag123",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
            member_count=5,
            member_resource_names=["people/c1", "people/c2", "people/c3"],
            formatted_name="My Group",
            deleted=False,
        )
        assert group.member_count == 5
        assert group.member_resource_names == ["people/c1", "people/c2", "people/c3"]
        assert group.formatted_name == "My Group"
        assert group.deleted is False

    def test_group_default_values(self):
        """Test that default values are applied correctly."""
        group = ContactGroup(
            resource_name="contactGroups/abc123",
            etag="etag123",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        assert group.member_count == 0
        assert group.member_resource_names == []
        assert group.formatted_name is None
        assert group.deleted is False


class TestContactGroupFromApiResponse:
    """Tests for ContactGroup.from_api_response() class method."""

    def test_from_api_response_full_data(self):
        """Test creating group from full API response."""
        api_response = {
            "resourceName": "contactGroups/abc123",
            "etag": "etag456",
            "name": "Work Contacts",
            "formattedName": "Work Contacts",
            "groupType": "USER_CONTACT_GROUP",
            "memberCount": 10,
            "memberResourceNames": ["people/c1", "people/c2"],
            "metadata": {
                "deleted": False,
                "updateTime": "2024-01-15T10:30:00Z",
            },
        }

        group = ContactGroup.from_api_response(api_response)

        assert group.resource_name == "contactGroups/abc123"
        assert group.etag == "etag456"
        assert group.name == "Work Contacts"
        assert group.formatted_name == "Work Contacts"
        assert group.group_type == GROUP_TYPE_USER_CONTACT_GROUP
        assert group.member_count == 10
        assert group.member_resource_names == ["people/c1", "people/c2"]
        assert group.deleted is False

    def test_from_api_response_minimal_data(self):
        """Test creating group from minimal API response."""
        api_response = {
            "resourceName": "contactGroups/xyz",
            "etag": "etag789",
            "name": "Friends",
            "groupType": "USER_CONTACT_GROUP",
        }

        group = ContactGroup.from_api_response(api_response)

        assert group.resource_name == "contactGroups/xyz"
        assert group.etag == "etag789"
        assert group.name == "Friends"
        assert group.group_type == GROUP_TYPE_USER_CONTACT_GROUP
        assert group.member_count == 0
        assert group.member_resource_names == []
        assert group.formatted_name is None
        assert group.deleted is False

    def test_from_api_response_empty_response(self):
        """Test creating group from empty API response."""
        group = ContactGroup.from_api_response({})

        assert group.resource_name == ""
        assert group.etag == ""
        assert group.name == ""
        assert group.group_type == GROUP_TYPE_UNSPECIFIED

    def test_from_api_response_deleted_group(self):
        """Test creating group marked as deleted."""
        api_response = {
            "resourceName": "contactGroups/deleted123",
            "etag": "etag",
            "name": "Deleted Group",
            "groupType": "USER_CONTACT_GROUP",
            "metadata": {"deleted": True},
        }

        group = ContactGroup.from_api_response(api_response)

        assert group.deleted is True

    def test_from_api_response_system_group(self):
        """Test creating a system contact group."""
        api_response = {
            "resourceName": "contactGroups/myContacts",
            "etag": "etag",
            "name": "My Contacts",
            "groupType": "SYSTEM_CONTACT_GROUP",
        }

        group = ContactGroup.from_api_response(api_response)

        assert group.group_type == GROUP_TYPE_SYSTEM_CONTACT_GROUP
        assert group.is_system_group() is True


class TestContactGroupToApiFormat:
    """Tests for ContactGroup.to_api_format() method."""

    def test_to_api_format_user_group(self):
        """Test conversion to API format for user group."""
        group = ContactGroup(
            resource_name="contactGroups/abc123",
            etag="etag",
            name="My Custom Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        result = group.to_api_format()

        assert "name" in result
        assert result["name"] == "My Custom Group"
        # resourceName and etag should NOT be included
        assert "resourceName" not in result
        assert "etag" not in result
        assert "groupType" not in result
        assert "memberCount" not in result
        assert "memberResourceNames" not in result

    def test_to_api_format_excludes_metadata(self):
        """Test that API format excludes non-writable fields."""
        group = ContactGroup(
            resource_name="contactGroups/abc123",
            etag="etag",
            name="Test Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
            member_count=5,
            member_resource_names=["people/c1"],
            formatted_name="Test Group",
        )

        result = group.to_api_format()

        # Only name should be included
        assert result == {"name": "Test Group"}

    def test_to_api_format_empty_name(self):
        """Test conversion with empty name."""
        group = ContactGroup(
            resource_name="contactGroups/abc123",
            etag="etag",
            name="",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        result = group.to_api_format()

        # Empty name should result in empty dict
        assert result == {}


class TestContactGroupMatchingKey:
    """Tests for ContactGroup.matching_key() method."""

    def test_matching_key_basic(self):
        """Test matching key generation for basic group."""
        group = ContactGroup(
            resource_name="contactGroups/abc123",
            etag="etag",
            name="Work Contacts",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        key = group.matching_key()

        assert key == "work contacts"

    def test_matching_key_case_insensitive(self):
        """Test that matching key is case insensitive."""
        group1 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="MY GROUP",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/2",
            etag="e2",
            name="my group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        assert group1.matching_key() == group2.matching_key()

    def test_matching_key_normalizes_unicode(self):
        """Test that unicode characters are normalized."""
        group = ContactGroup(
            resource_name="contactGroups/abc123",
            etag="etag",
            name="Café Friends",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        key = group.matching_key()

        # Accent should be removed
        assert "cafe" in key
        assert "é" not in key

    def test_matching_key_normalizes_whitespace(self):
        """Test that extra whitespace is normalized."""
        group1 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="My   Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/2",
            etag="e2",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        assert group1.matching_key() == group2.matching_key()

    def test_matching_key_empty_name(self):
        """Test matching key with empty name."""
        group = ContactGroup(
            resource_name="contactGroups/abc123",
            etag="etag",
            name="",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        key = group.matching_key()

        assert key == ""


class TestContactGroupContentHash:
    """Tests for ContactGroup.content_hash() method."""

    def test_content_hash_is_deterministic(self):
        """Test that same content produces same hash."""
        group1 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="Test Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/2",
            etag="e2",
            name="Test Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        assert group1.content_hash() == group2.content_hash()

    def test_content_hash_ignores_resource_name(self):
        """Test that resource_name is excluded from hash."""
        group1 = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/xyz",
            etag="etag",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        assert group1.content_hash() == group2.content_hash()

    def test_content_hash_ignores_etag(self):
        """Test that etag is excluded from hash."""
        group1 = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag1",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag2",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        assert group1.content_hash() == group2.content_hash()

    def test_content_hash_ignores_member_count(self):
        """Test that member_count is excluded from hash."""
        group1 = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
            member_count=5,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
            member_count=10,
        )

        assert group1.content_hash() == group2.content_hash()

    def test_content_hash_differs_for_different_name(self):
        """Test that different name produces different hash."""
        group1 = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="Group A",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="Group B",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        assert group1.content_hash() != group2.content_hash()

    def test_content_hash_is_sha256(self):
        """Test that hash is a valid SHA-256 hash."""
        group = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="Test",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        hash_value = group.content_hash()

        # SHA-256 produces 64 character hex string
        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)


class TestContactGroupTypeChecks:
    """Tests for group type checking methods."""

    def test_is_user_group_true(self):
        """Test is_user_group returns True for user groups."""
        group = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        assert group.is_user_group() is True

    def test_is_user_group_false_for_system(self):
        """Test is_user_group returns False for system groups."""
        group = ContactGroup(
            resource_name="contactGroups/myContacts",
            etag="etag",
            name="My Contacts",
            group_type=GROUP_TYPE_SYSTEM_CONTACT_GROUP,
        )

        assert group.is_user_group() is False

    def test_is_system_group_true(self):
        """Test is_system_group returns True for system groups."""
        group = ContactGroup(
            resource_name="contactGroups/starred",
            etag="etag",
            name="Starred",
            group_type=GROUP_TYPE_SYSTEM_CONTACT_GROUP,
        )

        assert group.is_system_group() is True

    def test_is_system_group_true_by_resource_name(self):
        """Test is_system_group returns True for known system resource names."""
        for system_name in SYSTEM_GROUP_NAMES:
            group = ContactGroup(
                resource_name=system_name,
                etag="etag",
                name="Some Name",
                group_type=GROUP_TYPE_USER_CONTACT_GROUP,  # Even if type says user
            )

            assert group.is_system_group() is True

    def test_is_system_group_false(self):
        """Test is_system_group returns False for user groups."""
        group = ContactGroup(
            resource_name="contactGroups/abc123",
            etag="etag",
            name="My Custom Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        assert group.is_system_group() is False


class TestContactGroupIsSyncable:
    """Tests for ContactGroup.is_syncable() method."""

    def test_is_syncable_user_group(self):
        """Test that user group with name is syncable."""
        group = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        assert group.is_syncable() is True

    def test_is_syncable_false_for_system_group(self):
        """Test that system group is not syncable."""
        group = ContactGroup(
            resource_name="contactGroups/myContacts",
            etag="etag",
            name="My Contacts",
            group_type=GROUP_TYPE_SYSTEM_CONTACT_GROUP,
        )

        assert group.is_syncable() is False

    def test_is_syncable_false_for_empty_name(self):
        """Test that group without name is not syncable."""
        group = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        assert group.is_syncable() is False

    def test_is_syncable_false_for_deleted_group(self):
        """Test that deleted group is not syncable."""
        group = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="Deleted Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
            deleted=True,
        )

        assert group.is_syncable() is False


class TestContactGroupEquality:
    """Tests for ContactGroup equality and hashing."""

    def test_equality_based_on_content_hash(self):
        """Test that equality is based on content hash."""
        group1 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="Same Name",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/2",
            etag="e2",
            name="Same Name",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        assert group1 == group2

    def test_inequality_for_different_names(self):
        """Test that different names produces inequality."""
        group1 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="Group A",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="Group B",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        assert group1 != group2

    def test_equality_with_non_group_returns_not_implemented(self):
        """Test that comparison with non-ContactGroup returns NotImplemented."""
        group = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="Test",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        result = group.__eq__("not a group")

        assert result is NotImplemented

    def test_hash_based_on_matching_key(self):
        """Test that hash is based on matching key."""
        group1 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="Same Name",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/2",
            etag="e2",
            name="Same Name",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        assert hash(group1) == hash(group2)

    def test_groups_can_be_used_in_set(self):
        """Test that groups can be stored in a set."""
        group1 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="Group A",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/2",
            etag="e2",
            name="Group A",  # Same name as group1
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group3 = ContactGroup(
            resource_name="contactGroups/3",
            etag="e3",
            name="Group B",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        group_set = {group1, group2, group3}

        # group1 and group2 have same matching key, so only 2 in set
        assert len(group_set) == 2

    def test_groups_can_be_used_as_dict_keys(self):
        """Test that groups can be used as dictionary keys."""
        group1 = ContactGroup(
            resource_name="contactGroups/1",
            etag="e1",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )
        group2 = ContactGroup(
            resource_name="contactGroups/2",
            etag="e2",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        d = {group1: "value1"}
        d[group2] = "value2"

        # Same matching key, so should overwrite
        assert len(d) == 1
        assert d[group1] == "value2"


class TestContactGroupRepr:
    """Tests for ContactGroup __repr__ method."""

    def test_repr_contains_key_info(self):
        """Test that repr contains key information."""
        group = ContactGroup(
            resource_name="contactGroups/abc123",
            etag="etag",
            name="My Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
            member_count=5,
        )

        repr_str = repr(group)

        assert "ContactGroup" in repr_str
        assert "contactGroups/abc123" in repr_str
        assert "My Group" in repr_str
        assert "USER_CONTACT_GROUP" in repr_str
        assert "5" in repr_str

    def test_repr_is_readable(self):
        """Test that repr is properly formatted."""
        group = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="Test",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        repr_str = repr(group)

        assert repr_str.startswith("ContactGroup(")
        assert repr_str.endswith(")")


class TestContactGroupEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_unicode_handling_in_name(self):
        """Test that unicode is handled correctly in name."""
        group = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="北京朋友",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        # Should not raise
        api_format = group.to_api_format()
        matching_key = group.matching_key()
        content_hash = group.content_hash()

        assert api_format is not None
        assert matching_key is not None
        assert content_hash is not None

    def test_very_long_name(self):
        """Test handling of very long group name."""
        long_name = "A" * 1000
        group = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name=long_name,
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        key = group.matching_key()
        hash_val = group.content_hash()

        assert key is not None
        assert hash_val is not None

    def test_group_with_many_members(self):
        """Test group with many member resource names."""
        members = [f"people/c{i}" for i in range(100)]
        group = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="Large Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
            member_count=100,
            member_resource_names=members,
        )

        assert len(group.member_resource_names) == 100

    def test_group_roundtrip_conversion(self):
        """Test that group survives API format roundtrip."""
        original = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="My Custom Group",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        # Convert to API format
        api_format = original.to_api_format()

        # Add back metadata that would come from API
        api_format["resourceName"] = "contactGroups/new123"
        api_format["etag"] = "new_etag"
        api_format["groupType"] = GROUP_TYPE_USER_CONTACT_GROUP

        # Convert back
        restored = ContactGroup.from_api_response(api_format)

        # Name should match
        assert restored.name == original.name

    def test_from_api_response_with_missing_metadata(self):
        """Test handling of API response without metadata section."""
        api_response = {
            "resourceName": "contactGroups/abc",
            "etag": "etag",
            "name": "Test Group",
            "groupType": "USER_CONTACT_GROUP",
        }

        group = ContactGroup.from_api_response(api_response)

        assert group.deleted is False

    def test_special_characters_in_name(self):
        """Test group name with special characters."""
        group = ContactGroup(
            resource_name="contactGroups/abc",
            etag="etag",
            name="O'Brien & Associates (2024)",
            group_type=GROUP_TYPE_USER_CONTACT_GROUP,
        )

        key = group.matching_key()
        hash_val = group.content_hash()

        assert key is not None
        assert hash_val is not None
        # Special characters are preserved in matching key (only accents removed)
        assert "o'brien" in key
        assert "associates" in key


class TestContactGroupConstants:
    """Tests for module constants."""

    def test_group_type_constants(self):
        """Test that group type constants are defined correctly."""
        assert GROUP_TYPE_UNSPECIFIED == "GROUP_TYPE_UNSPECIFIED"
        assert GROUP_TYPE_USER_CONTACT_GROUP == "USER_CONTACT_GROUP"
        assert GROUP_TYPE_SYSTEM_CONTACT_GROUP == "SYSTEM_CONTACT_GROUP"

    def test_system_group_names_is_frozenset(self):
        """Test that SYSTEM_GROUP_NAMES is a frozenset."""
        assert isinstance(SYSTEM_GROUP_NAMES, frozenset)

    def test_system_group_names_contains_expected_groups(self):
        """Test that SYSTEM_GROUP_NAMES contains expected system groups."""
        expected = {
            "contactGroups/myContacts",
            "contactGroups/starred",
            "contactGroups/all",
            "contactGroups/friends",
            "contactGroups/family",
            "contactGroups/coworkers",
        }
        assert expected <= SYSTEM_GROUP_NAMES
