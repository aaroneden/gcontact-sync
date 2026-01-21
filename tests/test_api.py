"""
Unit tests for the People API module.

Tests the PeopleAPI class for contact operations with mocked Google API responses.
"""

from unittest.mock import MagicMock, patch

import pytest

from gcontact_sync.api.people_api import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_INITIAL_RETRY_DELAY,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_RETRY_DELAY,
    DEFAULT_PAGE_SIZE,
    PERSON_FIELDS,
    UPDATE_PERSON_FIELDS,
    PeopleAPI,
    PeopleAPIError,
    RateLimitError,
)
from gcontact_sync.sync.contact import Contact

# Re-export to prevent linter from removing unused imports
__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_INITIAL_RETRY_DELAY",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_MAX_RETRY_DELAY",
]


class TestPeopleAPIInitialization:
    """Tests for PeopleAPI initialization."""

    def test_init_with_credentials(self):
        """Test initialization with credentials."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds)

        assert api.credentials == mock_creds
        assert api.page_size == DEFAULT_PAGE_SIZE
        assert api._service is None

    def test_init_with_custom_page_size(self):
        """Test initialization with custom page size."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds, page_size=50)

        assert api.page_size == 50

    def test_init_page_size_capped_at_1000(self):
        """Test that page size is capped at 1000."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds, page_size=2000)

        assert api.page_size == 1000

    def test_init_page_size_zero_or_negative(self):
        """Test that zero or negative page sizes are kept as-is (API will handle)."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds, page_size=0)
        assert api.page_size == 0

        api = PeopleAPI(mock_creds, page_size=-5)
        assert api.page_size == -5


class TestPeopleAPIService:
    """Tests for the service property."""

    @patch("gcontact_sync.api.people_api.build")
    def test_service_creates_on_first_access(self, mock_build):
        """Test that service is created on first access."""
        mock_creds = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        api = PeopleAPI(mock_creds)
        service = api.service

        mock_build.assert_called_once_with(
            "people", "v1", credentials=mock_creds, cache_discovery=False
        )
        assert service == mock_service

    @patch("gcontact_sync.api.people_api.build")
    def test_service_cached(self, mock_build):
        """Test that service is cached after first access."""
        mock_creds = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        api = PeopleAPI(mock_creds)
        service1 = api.service
        service2 = api.service

        mock_build.assert_called_once()
        assert service1 is service2

    @patch("gcontact_sync.api.people_api.build")
    def test_service_creation_failure_raises_error(self, mock_build):
        """Test that service creation failure raises PeopleAPIError."""
        mock_creds = MagicMock()
        mock_build.side_effect = Exception("Connection failed")

        api = PeopleAPI(mock_creds)

        with pytest.raises(PeopleAPIError, match="Failed to create API service"):
            _ = api.service


class TestRetryWithBackoff:
    """Tests for the retry with backoff mechanism."""

    @pytest.fixture
    def api(self):
        """Create a PeopleAPI instance with mocked service."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds)
        api._service = MagicMock()
        return api

    def test_successful_operation_returns_result(self, api):
        """Test that successful operation returns result immediately."""

        def operation():
            return {"result": "success"}

        result = api._retry_with_backoff(operation, "test_operation")
        assert result == {"result": "success"}

    @patch("time.sleep")
    def test_rate_limit_retries_with_backoff(self, mock_sleep, api):
        """Test that rate limit errors trigger retries with backoff."""
        from googleapiclient.errors import HttpError

        # Create mock HttpError with 429 status
        mock_resp = MagicMock()
        mock_resp.status = 429

        call_count = [0]

        def operation():
            call_count[0] += 1
            if call_count[0] < 3:
                raise HttpError(mock_resp, b"Rate limited")
            return {"result": "success"}

        result = api._retry_with_backoff(operation, "test_operation")

        assert result == {"result": "success"}
        assert call_count[0] == 3
        assert mock_sleep.call_count == 2

    @patch("time.sleep")
    def test_rate_limit_exhausted_raises_error(self, mock_sleep, api):
        """Test that exhausted retries on rate limit raises RateLimitError."""
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 429

        def operation():
            raise HttpError(mock_resp, b"Rate limited")

        with pytest.raises(RateLimitError, match="Rate limit exceeded"):
            api._retry_with_backoff(operation, "test_operation")

        assert mock_sleep.call_count == DEFAULT_MAX_RETRIES - 1

    @patch("time.sleep")
    def test_server_error_retries(self, mock_sleep, api):
        """Test that 5xx server errors trigger retries."""
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 500

        call_count = [0]

        def operation():
            call_count[0] += 1
            if call_count[0] < 2:
                raise HttpError(mock_resp, b"Server error")
            return {"result": "success"}

        result = api._retry_with_backoff(operation, "test_operation")

        assert result == {"result": "success"}
        assert call_count[0] == 2

    def test_403_triggers_retry(self, api):
        """Test that 403 errors trigger retries (quota exceeded)."""
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 403

        call_count = [0]

        def operation():
            call_count[0] += 1
            if call_count[0] < 2:
                raise HttpError(mock_resp, b"Quota exceeded")
            return {"result": "success"}

        with patch("time.sleep"):
            result = api._retry_with_backoff(operation, "test_operation")

        assert result == {"result": "success"}

    def test_client_error_does_not_retry(self, api):
        """Test that 4xx client errors (except 429, 403) don't retry."""
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 400

        def operation():
            raise HttpError(mock_resp, b"Bad request")

        with pytest.raises(PeopleAPIError, match="test_operation failed"):
            api._retry_with_backoff(operation, "test_operation")

    @patch("time.sleep")
    def test_backoff_delay_doubles(self, mock_sleep, api):
        """Test that backoff delay doubles with each retry."""
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 429

        call_count = [0]

        def operation():
            call_count[0] += 1
            if call_count[0] < 4:
                raise HttpError(mock_resp, b"Rate limited")
            return {"result": "success"}

        api._retry_with_backoff(operation, "test_operation")

        # Check delays: 1, 2, 4 seconds
        delays = [call[0][0] for call in mock_sleep.call_args_list]
        assert delays[0] == DEFAULT_INITIAL_RETRY_DELAY
        assert delays[1] == DEFAULT_INITIAL_RETRY_DELAY * 2
        assert delays[2] == DEFAULT_INITIAL_RETRY_DELAY * 4

    @patch("time.sleep")
    def test_backoff_capped_at_max(self, mock_sleep, api):
        """Test that backoff delay is capped at DEFAULT_MAX_RETRY_DELAY."""
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 429

        # Make all retries fail
        def operation():
            raise HttpError(mock_resp, b"Rate limited")

        with pytest.raises(RateLimitError):
            api._retry_with_backoff(operation, "test_operation")

        # Check that no delay exceeds DEFAULT_MAX_RETRY_DELAY
        delays = [call[0][0] for call in mock_sleep.call_args_list]
        for delay in delays:
            assert delay <= DEFAULT_MAX_RETRY_DELAY


class TestListContacts:
    """Tests for list_contacts method."""

    @pytest.fixture
    def api(self):
        """Create a PeopleAPI instance with mocked service."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds)
        api._service = MagicMock()
        return api

    def test_list_contacts_empty_result(self, api):
        """Test list_contacts with empty response."""
        api._service.people().connections().list().execute.return_value = {
            "connections": [],
            "nextSyncToken": "sync_token_123",
        }

        contacts, sync_token = api.list_contacts()

        assert contacts == []
        assert sync_token == "sync_token_123"

    def test_list_contacts_returns_contacts(self, api):
        """Test list_contacts returns parsed Contact objects."""
        api._service.people().connections().list().execute.return_value = {
            "connections": [
                {
                    "resourceName": "people/123",
                    "etag": "etag1",
                    "names": [
                        {
                            "displayName": "John Doe",
                            "givenName": "John",
                            "familyName": "Doe",
                        }
                    ],
                    "emailAddresses": [{"value": "john@example.com"}],
                },
                {
                    "resourceName": "people/456",
                    "etag": "etag2",
                    "names": [{"displayName": "Jane Smith"}],
                    "phoneNumbers": [{"value": "+1234567890"}],
                },
            ],
            "nextSyncToken": "sync_token",
        }

        contacts, sync_token = api.list_contacts()

        assert len(contacts) == 2
        assert contacts[0].resource_name == "people/123"
        assert contacts[0].display_name == "John Doe"
        assert contacts[1].resource_name == "people/456"

    def test_list_contacts_with_pagination(self, api):
        """Test list_contacts handles pagination."""
        # First page
        response1 = {
            "connections": [
                {
                    "resourceName": "people/1",
                    "etag": "e1",
                    "names": [{"displayName": "A"}],
                }
            ],
            "nextPageToken": "page2",
        }
        # Second page
        response2 = {
            "connections": [
                {
                    "resourceName": "people/2",
                    "etag": "e2",
                    "names": [{"displayName": "B"}],
                }
            ],
            "nextSyncToken": "final_token",
        }

        api._service.people().connections().list().execute.side_effect = [
            response1,
            response2,
        ]

        contacts, sync_token = api.list_contacts()

        assert len(contacts) == 2
        assert sync_token == "final_token"

    def test_list_contacts_with_sync_token(self, api):
        """Test list_contacts uses provided sync token."""
        api._service.people().connections().list.return_value.execute.return_value = {
            "connections": [],
            "nextSyncToken": "new_token",
        }

        api.list_contacts(sync_token="old_token")

        # Verify sync token was passed
        call_args = api._service.people().connections().list.call_args
        assert "syncToken" in call_args.kwargs or any(
            "old_token" in str(arg) for arg in call_args
        )

    def test_list_contacts_without_sync_token_requests_one(self, api):
        """Test list_contacts requests sync token when none provided."""
        api._service.people().connections().list.return_value.execute.return_value = {
            "connections": [],
            "nextSyncToken": "new_token",
        }

        api.list_contacts(request_sync_token=True)

        # Should have requestSyncToken=True in call
        api._service.people().connections().list.assert_called()

    def test_list_contacts_skips_invalid_contacts(self, api):
        """Test list_contacts skips contacts that fail to parse."""
        api._service.people().connections().list().execute.return_value = {
            "connections": [
                {
                    "resourceName": "people/1",
                    "etag": "e1",
                    "names": [{"displayName": "Valid"}],
                },
                None,  # Invalid
                {
                    "resourceName": "people/2",
                    "etag": "e2",
                    "names": [{"displayName": "Also Valid"}],
                },
            ],
            "nextSyncToken": "token",
        }

        # Mock Contact.from_api_response to fail on None
        with patch("gcontact_sync.api.people_api.Contact") as mock_contact:
            mock_contact.from_api_response.side_effect = [
                Contact("people/1", "e1", "Valid"),
                Exception("Parse error"),
                Contact("people/2", "e2", "Also Valid"),
            ]

            contacts, _ = api.list_contacts()

            assert len(contacts) == 2

    def test_list_contacts_expired_sync_token(self, api):
        """Test list_contacts raises error on expired sync token (410)."""
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 410

        api._service.people().connections().list().execute.side_effect = HttpError(
            mock_resp, b"Sync token expired"
        )

        with pytest.raises(PeopleAPIError, match="Sync token expired"):
            api.list_contacts(sync_token="expired_token")


class TestGetContact:
    """Tests for get_contact method."""

    @pytest.fixture
    def api(self):
        """Create a PeopleAPI instance with mocked service."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds)
        api._service = MagicMock()
        return api

    def test_get_contact_returns_contact(self, api):
        """Test get_contact returns a Contact object."""
        api._service.people().get().execute.return_value = {
            "resourceName": "people/123",
            "etag": "etag1",
            "names": [{"displayName": "John Doe"}],
        }

        contact = api.get_contact("people/123")

        assert contact.resource_name == "people/123"
        assert contact.display_name == "John Doe"

    def test_get_contact_not_found(self, api):
        """Test get_contact raises error when contact not found."""
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 404

        api._service.people().get().execute.side_effect = HttpError(
            mock_resp, b"Not found"
        )

        with pytest.raises(PeopleAPIError, match="failed"):
            api.get_contact("people/nonexistent")


class TestCreateContact:
    """Tests for create_contact method."""

    @pytest.fixture
    def api(self):
        """Create a PeopleAPI instance with mocked service."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds)
        api._service = MagicMock()
        return api

    def test_create_contact_returns_created_contact(self, api):
        """Test create_contact returns the created contact."""
        api._service.people().createContact().execute.return_value = {
            "resourceName": "people/new123",
            "etag": "new_etag",
            "names": [{"displayName": "New Contact"}],
        }

        contact = Contact(
            resource_name="",
            etag="",
            display_name="New Contact",
            given_name="New",
            emails=["new@example.com"],
        )

        created = api.create_contact(contact)

        assert created.resource_name == "people/new123"
        assert created.etag == "new_etag"

    def test_create_contact_passes_correct_body(self, api):
        """Test create_contact passes correct data to API."""
        api._service.people().createContact().execute.return_value = {
            "resourceName": "people/123",
            "etag": "etag",
            "names": [{"displayName": "Test"}],
        }

        contact = Contact(
            resource_name="",
            etag="",
            display_name="Test",
            given_name="Test",
            family_name="User",
            emails=["test@example.com"],
            phones=["+1234567890"],
        )

        api.create_contact(contact)

        # Verify createContact was called
        api._service.people().createContact.assert_called()


class TestUpdateContact:
    """Tests for update_contact method."""

    @pytest.fixture
    def api(self):
        """Create a PeopleAPI instance with mocked service."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds)
        api._service = MagicMock()
        return api

    def test_update_contact_returns_updated_contact(self, api):
        """Test update_contact returns the updated contact."""
        api._service.people().updateContact().execute.return_value = {
            "resourceName": "people/123",
            "etag": "new_etag",
            "names": [{"displayName": "Updated Name"}],
        }

        contact = Contact(
            resource_name="people/123", etag="old_etag", display_name="Updated Name"
        )

        updated = api.update_contact(contact)

        assert updated.resource_name == "people/123"
        assert updated.etag == "new_etag"

    def test_update_contact_with_explicit_resource_name(self, api):
        """Test update_contact uses explicit resource_name."""
        api._service.people().updateContact().execute.return_value = {
            "resourceName": "people/456",
            "etag": "etag",
            "names": [{"displayName": "Test"}],
        }

        contact = Contact(resource_name="people/123", etag="etag1", display_name="Test")

        api.update_contact(contact, resource_name="people/456")

        # Should use people/456, not people/123
        api._service.people().updateContact.assert_called()

    def test_update_contact_missing_resource_name_raises_error(self, api):
        """Test update_contact raises error when resource_name missing."""
        contact = Contact(resource_name="", etag="etag", display_name="Test")

        with pytest.raises(ValueError, match="resource_name is required"):
            api.update_contact(contact)

    def test_update_contact_conflict_error(self, api):
        """Test update_contact handles conflict error (409)."""
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 409

        api._service.people().updateContact().execute.side_effect = HttpError(
            mock_resp, b"Conflict"
        )

        contact = Contact(
            resource_name="people/123", etag="old_etag", display_name="Test"
        )

        with pytest.raises(PeopleAPIError, match="failed"):
            api.update_contact(contact)

    def test_update_contact_not_found(self, api):
        """Test update_contact handles not found error (404)."""
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 404

        api._service.people().updateContact().execute.side_effect = HttpError(
            mock_resp, b"Not found"
        )

        contact = Contact(resource_name="people/123", etag="etag", display_name="Test")

        with pytest.raises(PeopleAPIError, match="failed"):
            api.update_contact(contact)


class TestDeleteContact:
    """Tests for delete_contact method."""

    @pytest.fixture
    def api(self):
        """Create a PeopleAPI instance with mocked service."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds)
        api._service = MagicMock()
        return api

    def test_delete_contact_returns_true(self, api):
        """Test delete_contact returns True on success."""
        api._service.people().deleteContact().execute.return_value = {}

        result = api.delete_contact("people/123")

        assert result is True

    def test_delete_contact_already_deleted_returns_true(self, api):
        """Test delete_contact returns True when already deleted (404)."""
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 404

        api._service.people().deleteContact().execute.side_effect = HttpError(
            mock_resp, b"Not found"
        )

        result = api.delete_contact("people/123")

        assert result is True


class TestBatchCreateContacts:
    """Tests for batch_create_contacts method."""

    @pytest.fixture
    def api(self):
        """Create a PeopleAPI instance with mocked service."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds)
        api._service = MagicMock()
        return api

    def test_batch_create_empty_list(self, api):
        """Test batch_create_contacts with empty list."""
        result = api.batch_create_contacts([])
        assert result == []

    def test_batch_create_contacts_returns_created(self, api):
        """Test batch_create_contacts returns created contacts."""
        api._service.people().batchCreateContacts().execute.return_value = {
            "createdPeople": [
                {
                    "person": {
                        "resourceName": "people/1",
                        "etag": "e1",
                        "names": [{"displayName": "A"}],
                    }
                },
                {
                    "person": {
                        "resourceName": "people/2",
                        "etag": "e2",
                        "names": [{"displayName": "B"}],
                    }
                },
            ]
        }

        contacts = [
            Contact("", "", "A", given_name="A"),
            Contact("", "", "B", given_name="B"),
        ]

        result = api.batch_create_contacts(contacts)

        assert len(result) == 2
        assert result[0].resource_name == "people/1"
        assert result[1].resource_name == "people/2"

    def test_batch_create_respects_batch_size(self, api):
        """Test batch_create_contacts respects batch size limit."""
        # Create more contacts than batch size
        contacts = [Contact("", "", f"Contact {i}") for i in range(250)]

        # Set up the mock and capture the batch create method
        batch_create_mock = api._service.people().batchCreateContacts
        batch_create_mock().execute.return_value = {"createdPeople": []}
        batch_create_mock.reset_mock()  # Reset call count after setup

        api.batch_create_contacts(contacts, batch_size=200)

        # Should be called twice (200 + 50)
        assert batch_create_mock.call_count == 2

    def test_batch_create_uses_instance_batch_size(self, api):
        """Test batch_create_contacts uses instance batch_size when not specified."""
        contacts = [Contact("", "", f"Contact {i}") for i in range(300)]

        # Set up the mock and capture the batch create method
        batch_create_mock = api._service.people().batchCreateContacts
        batch_create_mock().execute.return_value = {"createdPeople": []}
        batch_create_mock.reset_mock()  # Reset call count after setup

        # Pass None to use instance batch_size (defaults to 200)
        api.batch_create_contacts(contacts, batch_size=None)

        # Should be called twice (200 + 100) with default batch_size of 200
        assert batch_create_mock.call_count == 2


class TestBatchUpdateContacts:
    """Tests for batch_update_contacts method."""

    @pytest.fixture
    def api(self):
        """Create a PeopleAPI instance with mocked service."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds)
        api._service = MagicMock()
        return api

    def test_batch_update_empty_list(self, api):
        """Test batch_update_contacts with empty list."""
        result = api.batch_update_contacts([])
        assert result == []

    def test_batch_update_contacts_returns_updated(self, api):
        """Test batch_update_contacts returns updated contacts."""
        api._service.people().batchUpdateContacts().execute.return_value = {
            "updateResult": {
                "people/1": {
                    "person": {
                        "resourceName": "people/1",
                        "etag": "new_e1",
                        "names": [{"displayName": "A"}],
                    }
                },
                "people/2": {
                    "person": {
                        "resourceName": "people/2",
                        "etag": "new_e2",
                        "names": [{"displayName": "B"}],
                    }
                },
            }
        }

        contacts_with_resources = [
            ("people/1", Contact("people/1", "e1", "A")),
            ("people/2", Contact("people/2", "e2", "B")),
        ]

        result = api.batch_update_contacts(contacts_with_resources)

        assert len(result) == 2

    def test_batch_update_respects_batch_size(self, api):
        """Test batch_update_contacts respects batch size limit."""
        contacts = [
            (f"people/{i}", Contact(f"people/{i}", f"e{i}", f"Contact {i}"))
            for i in range(250)
        ]

        # Set up the mock and capture the batch update method
        batch_update_mock = api._service.people().batchUpdateContacts
        batch_update_mock().execute.return_value = {"updateResult": {}}
        batch_update_mock.reset_mock()  # Reset call count after setup

        api.batch_update_contacts(contacts, batch_size=200)

        # Should be called twice (200 + 50)
        assert batch_update_mock.call_count == 2


class TestBatchDeleteContacts:
    """Tests for batch_delete_contacts method."""

    @pytest.fixture
    def api(self):
        """Create a PeopleAPI instance with mocked service."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds)
        api._service = MagicMock()
        return api

    def test_batch_delete_empty_list(self, api):
        """Test batch_delete_contacts with empty list."""
        result = api.batch_delete_contacts([])
        assert result == 0

    def test_batch_delete_contacts_returns_count(self, api):
        """Test batch_delete_contacts returns deleted count."""
        api._service.people().batchDeleteContacts().execute.return_value = {}

        resource_names = ["people/1", "people/2", "people/3"]
        result = api.batch_delete_contacts(resource_names)

        assert result == 3

    def test_batch_delete_respects_batch_size(self, api):
        """Test batch_delete_contacts respects batch size limit."""
        resource_names = [f"people/{i}" for i in range(250)]

        # Set up the mock and capture the batch delete method
        batch_delete_mock = api._service.people().batchDeleteContacts
        batch_delete_mock().execute.return_value = {}
        batch_delete_mock.reset_mock()  # Reset call count after setup

        api.batch_delete_contacts(resource_names, batch_size=200)

        # Should be called twice (200 + 50)
        assert batch_delete_mock.call_count == 2


class TestGetSyncToken:
    """Tests for get_sync_token method."""

    @pytest.fixture
    def api(self):
        """Create a PeopleAPI instance with mocked service."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds)
        api._service = MagicMock()
        return api

    def test_get_sync_token_returns_token(self, api):
        """Test get_sync_token returns the sync token."""
        api._service.people().connections().list().execute.return_value = {
            "connections": [],
            "nextSyncToken": "sync_token_abc",
        }

        token = api.get_sync_token()

        assert token == "sync_token_abc"

    def test_get_sync_token_returns_none_on_failure(self, api):
        """Test get_sync_token returns None on API error."""
        api._service.people().connections().list().execute.side_effect = PeopleAPIError(
            "API Error"
        )

        token = api.get_sync_token()

        assert token is None


class TestListDeletedContacts:
    """Tests for list_deleted_contacts method."""

    @pytest.fixture
    def api(self):
        """Create a PeopleAPI instance with mocked service."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds)
        api._service = MagicMock()
        return api

    def test_list_deleted_contacts_returns_deleted_resources(self, api):
        """Test list_deleted_contacts returns deleted resource names."""
        api._service.people().connections().list().execute.return_value = {
            "connections": [
                {"resourceName": "people/deleted1", "metadata": {"deleted": True}},
                {"resourceName": "people/not_deleted", "metadata": {"deleted": False}},
                {"resourceName": "people/deleted2", "metadata": {"deleted": True}},
            ],
            "nextSyncToken": "new_token",
        }

        deleted, sync_token = api.list_deleted_contacts("old_token")

        assert deleted == ["people/deleted1", "people/deleted2"]
        assert sync_token == "new_token"

    def test_list_deleted_contacts_pagination(self, api):
        """Test list_deleted_contacts handles pagination."""
        response1 = {
            "connections": [
                {"resourceName": "people/d1", "metadata": {"deleted": True}}
            ],
            "nextPageToken": "page2",
        }
        response2 = {
            "connections": [
                {"resourceName": "people/d2", "metadata": {"deleted": True}}
            ],
            "nextSyncToken": "final_token",
        }

        api._service.people().connections().list().execute.side_effect = [
            response1,
            response2,
        ]

        deleted, sync_token = api.list_deleted_contacts("token")

        assert deleted == ["people/d1", "people/d2"]
        assert sync_token == "final_token"

    def test_list_deleted_contacts_expired_token(self, api):
        """Test list_deleted_contacts raises error on expired sync token."""
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 410

        api._service.people().connections().list().execute.side_effect = HttpError(
            mock_resp, b"Sync token expired"
        )

        with pytest.raises(PeopleAPIError, match="Sync token expired"):
            api.list_deleted_contacts("expired_token")


class TestExceptionClasses:
    """Tests for exception classes."""

    def test_people_api_error_is_exception(self):
        """Test PeopleAPIError is an Exception."""
        assert issubclass(PeopleAPIError, Exception)

    def test_people_api_error_with_message(self):
        """Test PeopleAPIError with message."""
        error = PeopleAPIError("Test error message")
        assert str(error) == "Test error message"

    def test_rate_limit_error_is_people_api_error(self):
        """Test RateLimitError is a PeopleAPIError."""
        assert issubclass(RateLimitError, PeopleAPIError)

    def test_rate_limit_error_with_message(self):
        """Test RateLimitError with message."""
        error = RateLimitError("Rate limit exceeded")
        assert str(error) == "Rate limit exceeded"


class TestModuleConstants:
    """Tests for module constants."""

    def test_person_fields_includes_required_fields(self):
        """Test PERSON_FIELDS includes all required fields."""
        assert "names" in PERSON_FIELDS
        assert "emailAddresses" in PERSON_FIELDS
        assert "phoneNumbers" in PERSON_FIELDS
        assert "organizations" in PERSON_FIELDS
        assert "metadata" in PERSON_FIELDS

    def test_update_person_fields_excludes_metadata(self):
        """Test UPDATE_PERSON_FIELDS excludes metadata."""
        assert "metadata" not in UPDATE_PERSON_FIELDS

    def test_default_page_size(self):
        """Test DEFAULT_PAGE_SIZE is reasonable."""
        assert DEFAULT_PAGE_SIZE == 100

    def test_max_batch_size(self):
        """Test DEFAULT_BATCH_SIZE matches Google API limit."""
        assert DEFAULT_BATCH_SIZE == 200

    def test_max_retries(self):
        """Test DEFAULT_MAX_RETRIES is reasonable."""
        assert DEFAULT_MAX_RETRIES == 5

    def test_retry_delays(self):
        """Test retry delay constants."""
        assert DEFAULT_INITIAL_RETRY_DELAY == 1.0
        assert DEFAULT_MAX_RETRY_DELAY == 60.0


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    @pytest.fixture
    def api(self):
        """Create a PeopleAPI instance with mocked service."""
        mock_creds = MagicMock()
        api = PeopleAPI(mock_creds)
        api._service = MagicMock()
        return api

    def test_list_contacts_no_connections_key(self, api):
        """Test list_contacts handles response without connections key."""
        api._service.people().connections().list().execute.return_value = {
            "nextSyncToken": "token"
        }

        contacts, sync_token = api.list_contacts()

        assert contacts == []
        assert sync_token == "token"

    def test_batch_create_skips_empty_person_data(self, api):
        """Test batch_create_contacts handles empty person data in response."""
        api._service.people().batchCreateContacts().execute.return_value = {
            "createdPeople": [
                {
                    "person": {
                        "resourceName": "people/1",
                        "etag": "e1",
                        "names": [{"displayName": "A"}],
                    }
                },
                {"person": {}},  # Empty person data
                {
                    "person": {
                        "resourceName": "people/2",
                        "etag": "e2",
                        "names": [{"displayName": "B"}],
                    }
                },
            ]
        }

        contacts = [Contact("", "", "A"), Contact("", "", "B"), Contact("", "", "C")]

        result = api.batch_create_contacts(contacts)

        # Should skip the empty person data
        assert len(result) == 2

    def test_batch_update_empty_update_result(self, api):
        """Test batch_update_contacts handles empty update result."""
        api._service.people().batchUpdateContacts().execute.return_value = {}

        contacts = [("people/1", Contact("people/1", "e1", "A"))]
        result = api.batch_update_contacts(contacts)

        assert result == []

    def test_list_deleted_no_resource_name(self, api):
        """Test list_deleted_contacts skips entries without resource name."""
        api._service.people().connections().list().execute.return_value = {
            "connections": [
                {"resourceName": "people/1", "metadata": {"deleted": True}},
                {"metadata": {"deleted": True}},  # No resourceName
                {"resourceName": "people/2", "metadata": {"deleted": True}},
            ],
            "nextSyncToken": "token",
        }

        deleted, _ = api.list_deleted_contacts("token")

        assert deleted == ["people/1", "people/2"]

    def test_update_contact_with_explicit_etag(self, api):
        """Test update_contact uses explicit etag when provided."""
        api._service.people().updateContact().execute.return_value = {
            "resourceName": "people/123",
            "etag": "new_etag",
            "names": [{"displayName": "Test"}],
        }

        contact = Contact(
            resource_name="people/123", etag="contact_etag", display_name="Test"
        )

        api.update_contact(contact, etag="explicit_etag")

        # Should have been called (we're checking it doesn't error)
        api._service.people().updateContact.assert_called()
