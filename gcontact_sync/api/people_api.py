"""
Google People API wrapper for contact synchronization.

Provides a high-level interface to the Google People API for:
- Listing contacts with pagination and sync token support
- Creating, updating, and deleting contacts
- Batch operations for efficient bulk processing
- Exponential backoff retry logic for rate limits
"""

import logging
import time
from typing import Any, Callable, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from gcontact_sync.sync.contact import Contact

# Person fields to request from the API
# These are the fields we sync between accounts
PERSON_FIELDS = ",".join(
    [
        "names",
        "emailAddresses",
        "phoneNumbers",
        "organizations",
        "biographies",
        "photos",
        "metadata",
    ]
)

# Fields to update when modifying contacts
UPDATE_PERSON_FIELDS = ",".join(
    [
        "names",
        "emailAddresses",
        "phoneNumbers",
        "organizations",
        "biographies",
        "photos",
    ]
)

# Maximum number of contacts per page when listing
DEFAULT_PAGE_SIZE = 100

# Maximum contacts per batch operation
MAX_BATCH_SIZE = 200

# Retry configuration
MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1.0  # seconds
MAX_RETRY_DELAY = 60.0  # seconds

logger = logging.getLogger(__name__)


class PeopleAPIError(Exception):
    """Raised when a People API operation fails."""

    pass


class RateLimitError(PeopleAPIError):
    """Raised when rate limit is exceeded and retries are exhausted."""

    pass


class PeopleAPI:
    """
    Google People API wrapper for contact operations.

    Provides methods for listing, creating, updating, and deleting contacts
    with support for pagination, sync tokens, and batch operations.

    Attributes:
        credentials: Google OAuth2 credentials
        service: Google API service object

    Usage:
        api = PeopleAPI(credentials)

        # List all contacts
        contacts, next_sync_token = api.list_contacts()

        # List changes since last sync
        contacts, next_sync_token = api.list_contacts(sync_token=token)

        # Create a new contact
        new_contact = api.create_contact(contact)

        # Update existing contact
        updated_contact = api.update_contact(contact)

        # Delete a contact
        api.delete_contact(resource_name)

        # Batch create contacts
        created = api.batch_create_contacts(contacts_list)
    """

    def __init__(self, credentials: Credentials, page_size: int = DEFAULT_PAGE_SIZE):
        """
        Initialize the People API wrapper.

        Args:
            credentials: Valid Google OAuth2 credentials with contacts scope
            page_size: Number of contacts per page when listing (default 100)
        """
        self.credentials = credentials
        self.page_size = min(page_size, 1000)  # API max is 1000
        self._service = None

    @property
    def service(self) -> Any:
        """
        Get or create the Google API service object.

        Returns:
            Google People API service resource

        Raises:
            PeopleAPIError: If service cannot be created
        """
        if self._service is None:
            try:
                self._service = build(
                    "people", "v1", credentials=self.credentials, cache_discovery=False
                )
                logger.debug("Created People API service")
            except Exception as e:
                logger.error(f"Failed to create People API service: {e}")
                raise PeopleAPIError(f"Failed to create API service: {e}") from e
        return self._service

    def _retry_with_backoff(
        self, operation: Callable[[], Any], operation_name: str
    ) -> Any:
        """
        Execute an operation with exponential backoff retry.

        Args:
            operation: Callable to execute
            operation_name: Name for logging purposes

        Returns:
            Result of the operation

        Raises:
            RateLimitError: If retries are exhausted due to rate limits
            PeopleAPIError: For other API errors
        """
        delay = INITIAL_RETRY_DELAY

        for attempt in range(MAX_RETRIES):
            try:
                return operation()

            except HttpError as e:
                status_code = e.resp.status

                # Rate limit or quota exceeded - retry with backoff
                if status_code in (429, 403):
                    if attempt < MAX_RETRIES - 1:
                        logger.warning(
                            f"{operation_name} rate limited, retrying in "
                            f"{delay:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})"
                        )
                        time.sleep(delay)
                        delay = min(delay * 2, MAX_RETRY_DELAY)
                        continue
                    else:
                        raise RateLimitError(
                            f"Rate limit exceeded for {operation_name} "
                            f"after {MAX_RETRIES} retries"
                        ) from e

                # Server error - retry with backoff
                if status_code >= 500 and attempt < MAX_RETRIES - 1:
                    logger.warning(
                        f"{operation_name} server error ({status_code}), "
                        f"retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)
                    delay = min(delay * 2, MAX_RETRY_DELAY)
                    continue

                # Other errors - don't retry
                logger.error(f"{operation_name} failed with status {status_code}: {e}")
                raise PeopleAPIError(f"{operation_name} failed: {e}") from e

        # Should not reach here, but just in case
        raise PeopleAPIError(f"{operation_name} failed after all retries")

    def list_contacts(
        self, sync_token: Optional[str] = None, request_sync_token: bool = True
    ) -> tuple[list[Contact], Optional[str]]:
        """
        List all contacts or get changes since last sync.

        If sync_token is provided, returns only contacts modified since that token.
        Otherwise, returns all contacts.

        Args:
            sync_token: Token from previous sync for incremental updates
            request_sync_token: Whether to request a new sync token (default True)

        Returns:
            Tuple of (list of Contact objects, new sync token or None)

        Raises:
            PeopleAPIError: If listing fails
            RateLimitError: If rate limit exceeded

        Note:
            If sync_token is expired or invalid, API returns 410 GONE.
            In this case, caller should retry without sync_token for full sync.
        """
        logger.debug(f"Listing contacts (sync_token={bool(sync_token)})")

        contacts: list[Contact] = []
        page_token: Optional[str] = None
        next_sync_token: Optional[str] = None

        while True:
            # Build request parameters
            params: dict[str, Any] = {
                "resourceName": "people/me",
                "personFields": PERSON_FIELDS,
                "pageSize": self.page_size,
            }

            if page_token:
                params["pageToken"] = page_token

            if sync_token:
                params["syncToken"] = sync_token
            elif request_sync_token:
                params["requestSyncToken"] = True

            # Execute request with retry
            def execute_list(p: dict[str, Any] = params) -> Any:
                return self.service.people().connections().list(**p).execute()

            try:
                response = self._retry_with_backoff(execute_list, "list_contacts")
            except HttpError as e:
                # 410 GONE means sync token expired
                if e.resp.status == 410:
                    logger.warning(
                        "Sync token expired (410 GONE). "
                        "Caller should perform full sync."
                    )
                    raise PeopleAPIError(
                        "Sync token expired. Please perform a full sync."
                    ) from e
                raise

            # Parse contacts from response
            connections = response.get("connections", [])
            for person in connections:
                try:
                    contact = Contact.from_api_response(person)
                    contacts.append(contact)
                except Exception as e:
                    logger.warning(f"Failed to parse contact: {e}")
                    continue

            # Get next page token or sync token
            page_token = response.get("nextPageToken")
            next_sync_token = response.get("nextSyncToken")

            if not page_token:
                break

        logger.info(f"Listed {len(contacts)} contacts")
        return contacts, next_sync_token

    def get_contact(self, resource_name: str) -> Contact:
        """
        Get a single contact by resource name.

        Args:
            resource_name: Contact's resource name (e.g., "people/c12345")

        Returns:
            Contact object

        Raises:
            PeopleAPIError: If contact not found or request fails
        """
        logger.debug(f"Getting contact: {resource_name}")

        def execute_get() -> Any:
            return (
                self.service.people()
                .get(resourceName=resource_name, personFields=PERSON_FIELDS)
                .execute()
            )

        try:
            response = self._retry_with_backoff(
                execute_get, f"get_contact({resource_name})"
            )
            return Contact.from_api_response(response)
        except HttpError as e:
            if e.resp.status == 404:
                raise PeopleAPIError(f"Contact not found: {resource_name}") from e
            raise

    def create_contact(self, contact: Contact) -> Contact:
        """
        Create a new contact.

        Args:
            contact: Contact to create (resource_name will be ignored)

        Returns:
            Created Contact with resource_name and etag populated

        Raises:
            PeopleAPIError: If creation fails
        """
        logger.debug(f"Creating contact: {contact.display_name}")

        body = contact.to_api_format()

        def execute_create() -> Any:
            return (
                self.service.people()
                .createContact(body=body, personFields=PERSON_FIELDS)
                .execute()
            )

        response = self._retry_with_backoff(execute_create, "create_contact")
        created_contact = Contact.from_api_response(response)

        logger.info(f"Created contact: {created_contact.resource_name}")
        return created_contact

    def update_contact(
        self,
        contact: Contact,
        resource_name: Optional[str] = None,
        etag: Optional[str] = None,
    ) -> Contact:
        """
        Update an existing contact.

        Args:
            contact: Contact with updated data
            resource_name: Resource name to update (uses contact.resource_name if None)
            etag: Etag for optimistic locking (uses contact.etag if None)

        Returns:
            Updated Contact with new etag

        Raises:
            PeopleAPIError: If update fails
            ValueError: If resource_name is missing
        """
        target_resource = resource_name or contact.resource_name
        target_etag = etag or contact.etag

        if not target_resource:
            raise ValueError("resource_name is required for update")

        logger.debug(f"Updating contact: {target_resource}")

        body = contact.to_api_format()
        body["etag"] = target_etag

        def execute_update() -> Any:
            return (
                self.service.people()
                .updateContact(
                    resourceName=target_resource,
                    body=body,
                    updatePersonFields=UPDATE_PERSON_FIELDS,
                    personFields=PERSON_FIELDS,
                )
                .execute()
            )

        try:
            response = self._retry_with_backoff(
                execute_update, f"update_contact({target_resource})"
            )
            updated_contact = Contact.from_api_response(response)
            logger.info(f"Updated contact: {target_resource}")
            return updated_contact

        except HttpError as e:
            if e.resp.status == 409:
                raise PeopleAPIError(
                    f"Contact {target_resource} was modified by another client. "
                    f"Please refresh and try again."
                ) from e
            if e.resp.status == 404:
                raise PeopleAPIError(f"Contact not found: {target_resource}") from e
            raise

    def delete_contact(self, resource_name: str) -> bool:
        """
        Delete a contact.

        Args:
            resource_name: Contact's resource name to delete

        Returns:
            True if deletion succeeded

        Raises:
            PeopleAPIError: If deletion fails (except 404, which returns True)
        """
        logger.debug(f"Deleting contact: {resource_name}")

        def execute_delete() -> Any:
            return (
                self.service.people()
                .deleteContact(resourceName=resource_name)
                .execute()
            )

        try:
            self._retry_with_backoff(execute_delete, f"delete_contact({resource_name})")
            logger.info(f"Deleted contact: {resource_name}")
            return True

        except PeopleAPIError as e:
            # Check if the underlying cause was a 404 (already deleted)
            cause = e.__cause__
            if cause and isinstance(cause, HttpError) and cause.resp.status == 404:
                logger.debug(f"Contact already deleted: {resource_name}")
                return True
            raise

    def batch_create_contacts(
        self, contacts: list[Contact], batch_size: int = MAX_BATCH_SIZE
    ) -> list[Contact]:
        """
        Create multiple contacts in batches.

        Uses batchCreateContacts API for efficiency.

        Args:
            contacts: List of contacts to create
            batch_size: Maximum contacts per batch (default 200)

        Returns:
            List of created contacts with resource_names and etags

        Raises:
            PeopleAPIError: If batch creation fails
        """
        if not contacts:
            return []

        logger.debug(f"Batch creating {len(contacts)} contacts")

        batch_size = min(batch_size, MAX_BATCH_SIZE)
        created_contacts: list[Contact] = []

        # Process in batches
        for i in range(0, len(contacts), batch_size):
            batch = contacts[i : i + batch_size]
            logger.debug(
                f"Processing batch {i // batch_size + 1} ({len(batch)} contacts)"
            )

            # Build batch request body
            batch_body = {
                "contacts": [
                    {"contactPerson": contact.to_api_format()} for contact in batch
                ],
                "readMask": PERSON_FIELDS,
            }

            def execute_batch_create(
                b: dict[str, Any] = batch_body,
            ) -> Any:
                return self.service.people().batchCreateContacts(body=b).execute()

            response = self._retry_with_backoff(
                execute_batch_create,
                f"batch_create_contacts(batch {i // batch_size + 1})",
            )

            # Parse created contacts
            for created_person in response.get("createdPeople", []):
                person_data = created_person.get("person", {})
                if person_data:
                    contact = Contact.from_api_response(person_data)
                    created_contacts.append(contact)

        logger.info(f"Batch created {len(created_contacts)} contacts")
        return created_contacts

    def batch_update_contacts(
        self,
        contacts_with_resources: list[tuple[str, Contact]],
        batch_size: int = MAX_BATCH_SIZE,
    ) -> list[Contact]:
        """
        Update multiple contacts in batches.

        Uses batchUpdateContacts API for efficiency.

        Args:
            contacts_with_resources: List of (resource_name, Contact) tuples
            batch_size: Maximum contacts per batch (default 200)

        Returns:
            List of updated contacts

        Raises:
            PeopleAPIError: If batch update fails
        """
        if not contacts_with_resources:
            return []

        logger.debug(f"Batch updating {len(contacts_with_resources)} contacts")

        batch_size = min(batch_size, MAX_BATCH_SIZE)
        updated_contacts: list[Contact] = []

        # Process in batches
        for i in range(0, len(contacts_with_resources), batch_size):
            batch = contacts_with_resources[i : i + batch_size]
            logger.debug(
                f"Processing batch {i // batch_size + 1} ({len(batch)} contacts)"
            )

            # Build batch request body
            contacts_dict = {}
            for resource_name, contact in batch:
                person_data = contact.to_api_format()
                person_data["etag"] = contact.etag
                contacts_dict[resource_name] = person_data

            batch_body = {
                "contacts": contacts_dict,
                "updateMask": UPDATE_PERSON_FIELDS,
                "readMask": PERSON_FIELDS,
            }

            def execute_batch_update(
                b: dict[str, Any] = batch_body,
            ) -> Any:
                return self.service.people().batchUpdateContacts(body=b).execute()

            response = self._retry_with_backoff(
                execute_batch_update,
                f"batch_update_contacts(batch {i // batch_size + 1})",
            )

            # Parse updated contacts
            update_results = response.get("updateResult", {})
            for _resource_name, result in update_results.items():
                person_data = result.get("person", {})
                if person_data:
                    contact = Contact.from_api_response(person_data)
                    updated_contacts.append(contact)

        logger.info(f"Batch updated {len(updated_contacts)} contacts")
        return updated_contacts

    def batch_delete_contacts(
        self, resource_names: list[str], batch_size: int = MAX_BATCH_SIZE
    ) -> int:
        """
        Delete multiple contacts in batches.

        Uses batchDeleteContacts API for efficiency.

        Args:
            resource_names: List of resource names to delete
            batch_size: Maximum contacts per batch (default 200)

        Returns:
            Number of contacts deleted

        Raises:
            PeopleAPIError: If batch delete fails
        """
        if not resource_names:
            return 0

        logger.debug(f"Batch deleting {len(resource_names)} contacts")

        batch_size = min(batch_size, MAX_BATCH_SIZE)
        deleted_count = 0

        # Process in batches
        for i in range(0, len(resource_names), batch_size):
            batch = resource_names[i : i + batch_size]
            logger.debug(
                f"Processing batch {i // batch_size + 1} ({len(batch)} contacts)"
            )

            batch_body: dict[str, list[str]] = {"resourceNames": batch}

            def execute_batch_delete(
                b: dict[str, list[str]] = batch_body,
            ) -> Any:
                return self.service.people().batchDeleteContacts(body=b).execute()

            self._retry_with_backoff(
                execute_batch_delete,
                f"batch_delete_contacts(batch {i // batch_size + 1})",
            )

            deleted_count += len(batch)

        logger.info(f"Batch deleted {deleted_count} contacts")
        return deleted_count

    def get_sync_token(self) -> Optional[str]:
        """
        Get a sync token without fetching contacts.

        Useful for initializing sync state.

        Returns:
            Sync token string, or None if unavailable
        """
        logger.debug("Getting sync token")

        # Request with page size 1 to minimize data transfer
        params = {
            "resourceName": "people/me",
            "personFields": "names",
            "pageSize": 1,
            "requestSyncToken": True,
        }

        def execute_list() -> Any:
            return self.service.people().connections().list(**params).execute()

        try:
            response = self._retry_with_backoff(execute_list, "get_sync_token")
            token: Optional[str] = response.get("nextSyncToken")
            return token
        except PeopleAPIError:
            logger.warning("Failed to get sync token")
            return None

    def list_deleted_contacts(self, sync_token: str) -> tuple[list[str], Optional[str]]:
        """
        List contacts deleted since the given sync token.

        Args:
            sync_token: Sync token from previous sync

        Returns:
            Tuple of (list of deleted resource names, new sync token)

        Raises:
            PeopleAPIError: If sync token is expired or invalid
        """
        logger.debug("Listing deleted contacts")

        deleted_resources: list[str] = []
        page_token: Optional[str] = None
        next_sync_token: Optional[str] = None

        while True:
            params: dict[str, Any] = {
                "resourceName": "people/me",
                "personFields": "metadata",
                "pageSize": self.page_size,
                "syncToken": sync_token,
            }

            if page_token:
                params["pageToken"] = page_token

            def execute_list(p: dict[str, Any] = params) -> Any:
                return self.service.people().connections().list(**p).execute()

            try:
                response = self._retry_with_backoff(
                    execute_list, "list_deleted_contacts"
                )
            except HttpError as e:
                if e.resp.status == 410:
                    raise PeopleAPIError(
                        "Sync token expired. Please perform a full sync."
                    ) from e
                raise

            # Check for deleted contacts in response
            for person in response.get("connections", []):
                metadata = person.get("metadata", {})
                if metadata.get("deleted"):
                    resource_name = person.get("resourceName")
                    if resource_name:
                        deleted_resources.append(resource_name)

            page_token = response.get("nextPageToken")
            next_sync_token = response.get("nextSyncToken")

            if not page_token:
                break

        logger.info(f"Found {len(deleted_resources)} deleted contacts")
        return deleted_resources, next_sync_token

    def upload_photo(self, resource_name: str, photo_bytes: bytes) -> bool:
        """
        Upload a photo for a contact.

        Args:
            resource_name: Contact's resource name (e.g., "people/c12345")
            photo_bytes: Raw photo data as bytes

        Returns:
            True if upload succeeded

        Raises:
            PeopleAPIError: If upload fails
            ValueError: If resource_name or photo_bytes is missing
        """
        if not resource_name:
            raise ValueError("resource_name is required")
        if not photo_bytes:
            raise ValueError("photo_bytes is required")

        logger.debug(f"Uploading photo for contact: {resource_name}")

        import base64

        photo_base64 = base64.b64encode(photo_bytes).decode("utf-8")
        body = {"photoBytes": photo_base64}

        def execute_upload() -> Any:
            return (
                self.service.people()
                .updateContactPhoto(resourceName=resource_name, body=body)
                .execute()
            )

        try:
            self._retry_with_backoff(
                execute_upload, f"upload_photo({resource_name})"
            )
            logger.info(f"Uploaded photo for contact: {resource_name}")
            return True

        except PeopleAPIError as e:
            # Check if the underlying cause was a 404 (contact not found)
            cause = e.__cause__
            if cause and isinstance(cause, HttpError) and cause.resp.status == 404:
                raise PeopleAPIError(f"Contact not found: {resource_name}") from e
            raise

    def delete_photo(self, resource_name: str) -> bool:
        """
        Delete a contact's photo.

        Args:
            resource_name: Contact's resource name (e.g., "people/c12345")

        Returns:
            True if deletion succeeded

        Raises:
            PeopleAPIError: If deletion fails (except 404, which returns True)
            ValueError: If resource_name is missing
        """
        if not resource_name:
            raise ValueError("resource_name is required")

        logger.debug(f"Deleting photo for contact: {resource_name}")

        def execute_delete_photo() -> Any:
            return (
                self.service.people()
                .deleteContactPhoto(resourceName=resource_name)
                .execute()
            )

        try:
            self._retry_with_backoff(
                execute_delete_photo, f"delete_photo({resource_name})"
            )
            logger.info(f"Deleted photo for contact: {resource_name}")
            return True

        except PeopleAPIError as e:
            # Check if the underlying cause was a 404 (already deleted or no photo)
            cause = e.__cause__
            if cause and isinstance(cause, HttpError) and cause.resp.status == 404:
                logger.debug(f"Photo already deleted or not found: {resource_name}")
                return True
            raise
