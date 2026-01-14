"""
Unit tests for the Contact data model.

Tests the Contact class for API conversion, matching key generation,
content hashing, and comparison operations.
"""

from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from gcontact_sync.sync.contact import Contact


class TestContactBasics:
    """Tests for basic Contact instantiation and attributes."""

    def test_create_contact_with_required_fields(self):
        """Test creating a contact with only required fields."""
        contact = Contact(
            resource_name='people/c123',
            etag='abc123',
            display_name='John Doe'
        )
        assert contact.resource_name == 'people/c123'
        assert contact.etag == 'abc123'
        assert contact.display_name == 'John Doe'

    def test_create_contact_with_all_fields(self):
        """Test creating a contact with all fields."""
        last_mod = datetime.now(timezone.utc)
        contact = Contact(
            resource_name='people/c123',
            etag='abc123',
            display_name='John Doe',
            given_name='John',
            family_name='Doe',
            emails=['john@example.com', 'john.doe@work.com'],
            phones=['+1234567890', '+0987654321'],
            organizations=['Acme Corp'],
            notes='Important contact',
            last_modified=last_mod,
            deleted=False
        )
        assert contact.given_name == 'John'
        assert contact.family_name == 'Doe'
        assert contact.emails == ['john@example.com', 'john.doe@work.com']
        assert contact.phones == ['+1234567890', '+0987654321']
        assert contact.organizations == ['Acme Corp']
        assert contact.notes == 'Important contact'
        assert contact.last_modified == last_mod
        assert contact.deleted is False

    def test_contact_default_values(self):
        """Test that default values are applied correctly."""
        contact = Contact(
            resource_name='people/c123',
            etag='abc123',
            display_name='John Doe'
        )
        assert contact.given_name is None
        assert contact.family_name is None
        assert contact.emails == []
        assert contact.phones == []
        assert contact.organizations == []
        assert contact.notes is None
        assert contact.last_modified is None
        assert contact.deleted is False


class TestContactFromApiResponse:
    """Tests for Contact.from_api_response() class method."""

    def test_from_api_response_full_data(self):
        """Test creating contact from full API response."""
        api_response = {
            'resourceName': 'people/c12345',
            'etag': 'etag123',
            'names': [
                {
                    'displayName': 'John Doe',
                    'givenName': 'John',
                    'familyName': 'Doe'
                }
            ],
            'emailAddresses': [
                {'value': 'john@example.com'},
                {'value': 'john.doe@work.com'}
            ],
            'phoneNumbers': [
                {'value': '+1234567890'}
            ],
            'organizations': [
                {'name': 'Acme Corp'}
            ],
            'biographies': [
                {'value': 'Some notes about John'}
            ],
            'metadata': {
                'sources': [
                    {'updateTime': '2024-01-15T10:30:00Z'}
                ]
            }
        }

        contact = Contact.from_api_response(api_response)

        assert contact.resource_name == 'people/c12345'
        assert contact.etag == 'etag123'
        assert contact.display_name == 'John Doe'
        assert contact.given_name == 'John'
        assert contact.family_name == 'Doe'
        assert contact.emails == ['john@example.com', 'john.doe@work.com']
        assert contact.phones == ['+1234567890']
        assert contact.organizations == ['Acme Corp']
        assert contact.notes == 'Some notes about John'
        assert contact.last_modified is not None
        assert contact.deleted is False

    def test_from_api_response_minimal_data(self):
        """Test creating contact from minimal API response."""
        api_response = {
            'resourceName': 'people/c123',
            'etag': 'etag456',
            'names': [{'displayName': 'Jane Smith'}]
        }

        contact = Contact.from_api_response(api_response)

        assert contact.resource_name == 'people/c123'
        assert contact.etag == 'etag456'
        assert contact.display_name == 'Jane Smith'
        assert contact.given_name is None
        assert contact.family_name is None
        assert contact.emails == []
        assert contact.phones == []
        assert contact.organizations == []
        assert contact.notes is None

    def test_from_api_response_empty_response(self):
        """Test creating contact from empty API response."""
        contact = Contact.from_api_response({})

        assert contact.resource_name == ''
        assert contact.etag == ''
        assert contact.display_name == ''

    def test_from_api_response_constructs_display_name(self):
        """Test that display name is constructed from given/family when missing."""
        api_response = {
            'resourceName': 'people/c123',
            'etag': 'etag',
            'names': [
                {
                    'givenName': 'Alice',
                    'familyName': 'Johnson'
                }
            ]
        }

        contact = Contact.from_api_response(api_response)

        assert contact.display_name == 'Alice Johnson'
        assert contact.given_name == 'Alice'
        assert contact.family_name == 'Johnson'

    def test_from_api_response_constructs_display_name_given_only(self):
        """Test display name construction with only given name."""
        api_response = {
            'resourceName': 'people/c123',
            'etag': 'etag',
            'names': [{'givenName': 'Bob'}]
        }

        contact = Contact.from_api_response(api_response)

        assert contact.display_name == 'Bob'

    def test_from_api_response_constructs_display_name_family_only(self):
        """Test display name construction with only family name."""
        api_response = {
            'resourceName': 'people/c123',
            'etag': 'etag',
            'names': [{'familyName': 'Smith'}]
        }

        contact = Contact.from_api_response(api_response)

        assert contact.display_name == 'Smith'

    def test_from_api_response_empty_email_values_filtered(self):
        """Test that empty email values are filtered out."""
        api_response = {
            'resourceName': 'people/c123',
            'etag': 'etag',
            'names': [{'displayName': 'Test'}],
            'emailAddresses': [
                {'value': 'valid@example.com'},
                {'value': ''},
                {},
                {'value': 'another@example.com'}
            ]
        }

        contact = Contact.from_api_response(api_response)

        assert contact.emails == ['valid@example.com', 'another@example.com']

    def test_from_api_response_empty_phone_values_filtered(self):
        """Test that empty phone values are filtered out."""
        api_response = {
            'resourceName': 'people/c123',
            'etag': 'etag',
            'names': [{'displayName': 'Test'}],
            'phoneNumbers': [
                {'value': '+1234567890'},
                {'value': ''},
                {},
            ]
        }

        contact = Contact.from_api_response(api_response)

        assert contact.phones == ['+1234567890']

    def test_from_api_response_empty_organization_values_filtered(self):
        """Test that empty organization values are filtered out."""
        api_response = {
            'resourceName': 'people/c123',
            'etag': 'etag',
            'names': [{'displayName': 'Test'}],
            'organizations': [
                {'name': 'Acme Corp'},
                {'name': ''},
                {},
            ]
        }

        contact = Contact.from_api_response(api_response)

        assert contact.organizations == ['Acme Corp']

    def test_from_api_response_deleted_contact(self):
        """Test creating contact marked as deleted."""
        api_response = {
            'resourceName': 'people/c123',
            'etag': 'etag',
            'names': [{'displayName': 'Deleted User'}],
            'metadata': {
                'deleted': True
            }
        }

        contact = Contact.from_api_response(api_response)

        assert contact.deleted is True

    def test_from_api_response_timestamp_parsing(self):
        """Test that timestamp is correctly parsed."""
        api_response = {
            'resourceName': 'people/c123',
            'etag': 'etag',
            'names': [{'displayName': 'Test'}],
            'metadata': {
                'sources': [
                    {'updateTime': '2024-06-15T14:30:45Z'}
                ]
            }
        }

        contact = Contact.from_api_response(api_response)

        assert contact.last_modified is not None
        assert contact.last_modified.year == 2024
        assert contact.last_modified.month == 6
        assert contact.last_modified.day == 15

    def test_from_api_response_invalid_timestamp(self):
        """Test handling of invalid timestamp."""
        api_response = {
            'resourceName': 'people/c123',
            'etag': 'etag',
            'names': [{'displayName': 'Test'}],
            'metadata': {
                'sources': [
                    {'updateTime': 'invalid-timestamp'}
                ]
            }
        }

        contact = Contact.from_api_response(api_response)

        assert contact.last_modified is None


class TestContactToApiFormat:
    """Tests for Contact.to_api_format() method."""

    def test_to_api_format_full_contact(self):
        """Test conversion to API format with all fields."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            given_name='John',
            family_name='Doe',
            emails=['john@example.com'],
            phones=['+1234567890'],
            organizations=['Acme Corp'],
            notes='Some notes'
        )

        result = contact.to_api_format()

        assert 'names' in result
        assert result['names'][0]['givenName'] == 'John'
        assert result['names'][0]['familyName'] == 'Doe'
        assert 'emailAddresses' in result
        assert result['emailAddresses'] == [{'value': 'john@example.com'}]
        assert 'phoneNumbers' in result
        assert result['phoneNumbers'] == [{'value': '+1234567890'}]
        assert 'organizations' in result
        assert result['organizations'] == [{'name': 'Acme Corp'}]
        assert 'biographies' in result
        assert result['biographies'][0]['value'] == 'Some notes'
        assert result['biographies'][0]['contentType'] == 'TEXT_PLAIN'

    def test_to_api_format_excludes_resource_name(self):
        """Test that resourceName is not included in output."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='Test'
        )

        result = contact.to_api_format()

        assert 'resourceName' not in result
        assert 'etag' not in result

    def test_to_api_format_display_name_only(self):
        """Test conversion with display name only (no given/family)."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='Single Name'
        )

        result = contact.to_api_format()

        assert 'names' in result
        assert result['names'][0]['displayName'] == 'Single Name'
        assert 'givenName' not in result['names'][0]
        assert 'familyName' not in result['names'][0]

    def test_to_api_format_excludes_empty_lists(self):
        """Test that empty lists are not included in output."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='Test',
            emails=[],
            phones=[],
            organizations=[]
        )

        result = contact.to_api_format()

        assert 'emailAddresses' not in result
        assert 'phoneNumbers' not in result
        assert 'organizations' not in result

    def test_to_api_format_excludes_empty_notes(self):
        """Test that empty notes are not included."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='Test',
            notes=None
        )

        result = contact.to_api_format()

        assert 'biographies' not in result

    def test_to_api_format_multiple_emails(self):
        """Test conversion with multiple emails."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='Test',
            emails=['email1@test.com', 'email2@test.com', 'email3@test.com']
        )

        result = contact.to_api_format()

        assert len(result['emailAddresses']) == 3
        assert result['emailAddresses'][0] == {'value': 'email1@test.com'}
        assert result['emailAddresses'][1] == {'value': 'email2@test.com'}
        assert result['emailAddresses'][2] == {'value': 'email3@test.com'}


class TestContactMatchingKey:
    """Tests for Contact.matching_key() method."""

    def test_matching_key_name_and_email(self):
        """Test matching key with name and email."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            emails=['john@example.com']
        )

        key = contact.matching_key()

        assert '|' in key
        assert 'johndoe' in key
        assert 'johnexamplecom' in key

    def test_matching_key_name_only(self):
        """Test matching key with name only (no email)."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            emails=[]
        )

        key = contact.matching_key()

        assert '|' not in key
        assert key == 'johndoe'

    def test_matching_key_normalizes_unicode(self):
        """Test that unicode characters are normalized."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='José García',
            emails=['jose@example.com']
        )

        key = contact.matching_key()

        # Accents should be removed
        assert 'jose' in key
        assert 'garcia' in key

    def test_matching_key_case_insensitive(self):
        """Test that matching key is lowercase."""
        contact1 = Contact(
            resource_name='people/c1',
            etag='e1',
            display_name='JOHN DOE',
            emails=['JOHN@EXAMPLE.COM']
        )
        contact2 = Contact(
            resource_name='people/c2',
            etag='e2',
            display_name='john doe',
            emails=['john@example.com']
        )

        assert contact1.matching_key() == contact2.matching_key()

    def test_matching_key_removes_special_characters(self):
        """Test that special characters are removed."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name="John O'Brien-Smith",
            emails=['john.obrien@example.com']
        )

        key = contact.matching_key()

        # Special characters like apostrophe and hyphen should be removed
        assert "'" not in key
        assert '-' not in key
        assert '.' not in key

    def test_matching_key_preserves_at_symbol(self):
        """Test that @ symbol in email is preserved."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='Test',
            emails=['test@example.com']
        )

        key = contact.matching_key()

        assert '@' in key

    def test_matching_key_uses_primary_email_only(self):
        """Test that only the first email is used."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='Test',
            emails=['primary@example.com', 'secondary@example.com']
        )

        key = contact.matching_key()

        assert 'primary' in key
        assert 'secondary' not in key

    def test_matching_key_empty_display_name(self):
        """Test matching key with empty display name."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='',
            emails=['test@example.com']
        )

        key = contact.matching_key()

        assert key == '|test@examplecom'


class TestContactContentHash:
    """Tests for Contact.content_hash() method."""

    def test_content_hash_is_deterministic(self):
        """Test that same content produces same hash."""
        contact1 = Contact(
            resource_name='people/c1',
            etag='e1',
            display_name='John Doe',
            given_name='John',
            family_name='Doe',
            emails=['john@example.com']
        )
        contact2 = Contact(
            resource_name='people/c2',
            etag='e2',
            display_name='John Doe',
            given_name='John',
            family_name='Doe',
            emails=['john@example.com']
        )

        assert contact1.content_hash() == contact2.content_hash()

    def test_content_hash_ignores_resource_name(self):
        """Test that resource_name is excluded from hash."""
        contact1 = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe'
        )
        contact2 = Contact(
            resource_name='people/c456',
            etag='etag',
            display_name='John Doe'
        )

        assert contact1.content_hash() == contact2.content_hash()

    def test_content_hash_ignores_etag(self):
        """Test that etag is excluded from hash."""
        contact1 = Contact(
            resource_name='people/c123',
            etag='etag1',
            display_name='John Doe'
        )
        contact2 = Contact(
            resource_name='people/c123',
            etag='etag2',
            display_name='John Doe'
        )

        assert contact1.content_hash() == contact2.content_hash()

    def test_content_hash_ignores_last_modified(self):
        """Test that last_modified is excluded from hash."""
        contact1 = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            last_modified=datetime(2024, 1, 1)
        )
        contact2 = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            last_modified=datetime(2024, 6, 15)
        )

        assert contact1.content_hash() == contact2.content_hash()

    def test_content_hash_differs_for_different_content(self):
        """Test that different content produces different hash."""
        contact1 = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe'
        )
        contact2 = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='Jane Smith'
        )

        assert contact1.content_hash() != contact2.content_hash()

    def test_content_hash_differs_for_email_change(self):
        """Test that email change produces different hash."""
        contact1 = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            emails=['john@example.com']
        )
        contact2 = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            emails=['john.doe@example.com']
        )

        assert contact1.content_hash() != contact2.content_hash()

    def test_content_hash_normalizes_phone_numbers(self):
        """Test that phone numbers are normalized before hashing."""
        contact1 = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            phones=['+1 (234) 567-8900']
        )
        contact2 = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            phones=['12345678900']
        )

        # Normalized phone numbers should produce same hash
        assert contact1.content_hash() == contact2.content_hash()

    def test_content_hash_sorts_lists(self):
        """Test that list order doesn't affect hash."""
        contact1 = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            emails=['a@test.com', 'b@test.com', 'c@test.com']
        )
        contact2 = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            emails=['c@test.com', 'a@test.com', 'b@test.com']
        )

        assert contact1.content_hash() == contact2.content_hash()

    def test_content_hash_is_sha256(self):
        """Test that hash is a valid SHA-256 hash."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe'
        )

        hash_value = contact.content_hash()

        # SHA-256 produces 64 character hex string
        assert len(hash_value) == 64
        assert all(c in '0123456789abcdef' for c in hash_value)


class TestContactIsValid:
    """Tests for Contact.is_valid() method."""

    def test_is_valid_with_display_name(self):
        """Test that contact with display name is valid."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe'
        )

        assert contact.is_valid() is True

    def test_is_valid_with_email(self):
        """Test that contact with email is valid."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='',
            emails=['john@example.com']
        )

        assert contact.is_valid() is True

    def test_is_valid_with_both(self):
        """Test that contact with name and email is valid."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            emails=['john@example.com']
        )

        assert contact.is_valid() is True

    def test_is_not_valid_without_name_or_email(self):
        """Test that contact without name or email is invalid."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='',
            emails=[]
        )

        assert contact.is_valid() is False

    def test_is_not_valid_with_empty_email_list(self):
        """Test that empty display name and empty email list is invalid."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='',
            emails=[]
        )

        assert contact.is_valid() is False


class TestContactEquality:
    """Tests for Contact equality and hashing."""

    def test_equality_based_on_content_hash(self):
        """Test that equality is based on content hash."""
        contact1 = Contact(
            resource_name='people/c1',
            etag='e1',
            display_name='John Doe',
            emails=['john@example.com']
        )
        contact2 = Contact(
            resource_name='people/c2',
            etag='e2',
            display_name='John Doe',
            emails=['john@example.com']
        )

        assert contact1 == contact2

    def test_inequality_for_different_content(self):
        """Test that different content produces inequality."""
        contact1 = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe'
        )
        contact2 = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='Jane Smith'
        )

        assert contact1 != contact2

    def test_equality_with_non_contact_returns_not_implemented(self):
        """Test that comparison with non-Contact returns NotImplemented."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe'
        )

        result = contact.__eq__("not a contact")

        assert result is NotImplemented

    def test_hash_based_on_matching_key(self):
        """Test that hash is based on matching key."""
        contact1 = Contact(
            resource_name='people/c1',
            etag='e1',
            display_name='John Doe',
            emails=['john@example.com']
        )
        contact2 = Contact(
            resource_name='people/c2',
            etag='e2',
            display_name='John Doe',
            emails=['john@example.com']
        )

        assert hash(contact1) == hash(contact2)

    def test_contacts_can_be_used_in_set(self):
        """Test that contacts can be stored in a set."""
        contact1 = Contact(
            resource_name='people/c1',
            etag='e1',
            display_name='John Doe',
            emails=['john@example.com']
        )
        contact2 = Contact(
            resource_name='people/c2',
            etag='e2',
            display_name='John Doe',
            emails=['john@example.com']
        )
        contact3 = Contact(
            resource_name='people/c3',
            etag='e3',
            display_name='Jane Smith',
            emails=['jane@example.com']
        )

        contact_set = {contact1, contact2, contact3}

        # contact1 and contact2 have same matching key, so only 2 in set
        assert len(contact_set) == 2

    def test_contacts_can_be_used_as_dict_keys(self):
        """Test that contacts can be used as dictionary keys."""
        contact1 = Contact(
            resource_name='people/c1',
            etag='e1',
            display_name='John Doe',
            emails=['john@example.com']
        )
        contact2 = Contact(
            resource_name='people/c2',
            etag='e2',
            display_name='John Doe',
            emails=['john@example.com']
        )

        d = {contact1: 'value1'}
        d[contact2] = 'value2'

        # Same matching key, so should overwrite
        assert len(d) == 1
        assert d[contact1] == 'value2'


class TestContactRepr:
    """Tests for Contact __repr__ method."""

    def test_repr_contains_key_info(self):
        """Test that repr contains key information."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            emails=['john@example.com', 'john2@example.com']
        )

        repr_str = repr(contact)

        assert 'Contact' in repr_str
        assert 'people/c123' in repr_str
        assert 'John Doe' in repr_str
        assert 'john@example.com' in repr_str

    def test_repr_is_readable(self):
        """Test that repr is properly formatted."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='Test User',
            emails=[]
        )

        repr_str = repr(contact)

        assert repr_str.startswith('Contact(')
        assert repr_str.endswith(')')


class TestContactEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_unicode_handling_in_all_fields(self):
        """Test that unicode is handled correctly in all fields."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='北京用户',
            given_name='北京',
            family_name='用户',
            emails=['beijing@example.com'],
            organizations=['北京公司'],
            notes='用户备注'
        )

        # Should not raise
        api_format = contact.to_api_format()
        matching_key = contact.matching_key()
        content_hash = contact.content_hash()

        assert api_format is not None
        assert matching_key is not None
        assert content_hash is not None

    def test_very_long_display_name(self):
        """Test handling of very long display name."""
        long_name = 'A' * 1000
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name=long_name
        )

        key = contact.matching_key()
        hash_val = contact.content_hash()

        assert key is not None
        assert hash_val is not None

    def test_contact_with_many_emails(self):
        """Test contact with many email addresses."""
        emails = [f'email{i}@example.com' for i in range(100)]
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='Test User',
            emails=emails
        )

        api_format = contact.to_api_format()

        assert len(api_format['emailAddresses']) == 100

    def test_contact_with_special_email_characters(self):
        """Test contact with special characters in email."""
        contact = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='Test',
            emails=['test+tag@example.com', 'test.name@sub.domain.com']
        )

        key = contact.matching_key()

        # Email normalization should handle special chars
        assert '+' not in key or '@' in key  # @ should be preserved

    def test_contact_roundtrip_conversion(self):
        """Test that contact survives API format roundtrip."""
        original = Contact(
            resource_name='people/c123',
            etag='etag',
            display_name='John Doe',
            given_name='John',
            family_name='Doe',
            emails=['john@example.com'],
            phones=['+1234567890'],
            organizations=['Acme Corp'],
            notes='Test notes'
        )

        # Convert to API format
        api_format = original.to_api_format()

        # Add back metadata that would come from API
        api_format['resourceName'] = 'people/new123'
        api_format['etag'] = 'new_etag'

        # Convert back
        restored = Contact.from_api_response(api_format)

        # Core content should match
        assert restored.given_name == original.given_name
        assert restored.family_name == original.family_name
        assert restored.emails == original.emails
        assert restored.phones == original.phones
        assert restored.organizations == original.organizations
        assert restored.notes == original.notes

    def test_contact_with_empty_strings(self):
        """Test contact with empty strings in fields."""
        contact = Contact(
            resource_name='',
            etag='',
            display_name='',
            given_name='',
            family_name='',
            notes=''
        )

        # Should not raise
        api_format = contact.to_api_format()
        key = contact.matching_key()
        hash_val = contact.content_hash()

        assert api_format is not None
        assert key is not None
        assert hash_val is not None

    def test_from_api_response_with_empty_names_list(self):
        """Test handling of empty names list in API response."""
        api_response = {
            'resourceName': 'people/c123',
            'etag': 'etag',
            'names': [],
            'emailAddresses': [{'value': 'test@example.com'}]
        }

        contact = Contact.from_api_response(api_response)

        assert contact.display_name == ''
        assert contact.given_name is None
        assert contact.family_name is None

    def test_phone_normalization_various_formats(self):
        """Test phone number normalization with various formats."""
        contact1 = Contact(
            resource_name='people/c1',
            etag='e1',
            display_name='Test',
            phones=['(123) 456-7890']
        )
        contact2 = Contact(
            resource_name='people/c2',
            etag='e2',
            display_name='Test',
            phones=['123-456-7890']
        )
        contact3 = Contact(
            resource_name='people/c3',
            etag='e3',
            display_name='Test',
            phones=['1234567890']
        )

        # All should produce the same content hash due to phone normalization
        assert contact1.content_hash() == contact2.content_hash()
        assert contact2.content_hash() == contact3.content_hash()
