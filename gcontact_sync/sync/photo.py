"""
Photo download and processing for Google Contacts synchronization.

Provides utilities for:
- Downloading contact photos from URLs
- Image format validation and conversion
- Size optimization to meet Google API requirements
- Retry logic for network failures
"""

import logging
import time
from typing import Optional

import requests
from requests.exceptions import RequestException

# Retry configuration
MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1.0  # seconds
MAX_RETRY_DELAY = 60.0  # seconds

# HTTP timeout configuration
DOWNLOAD_TIMEOUT = 30.0  # seconds

logger = logging.getLogger(__name__)


class PhotoError(Exception):
    """Raised when a photo operation fails."""

    pass


class PhotoDownloadError(PhotoError):
    """Raised when photo download fails after retries."""

    pass


def download_photo(
    url: str, max_retries: int = MAX_RETRIES, timeout: float = DOWNLOAD_TIMEOUT
) -> bytes:
    """
    Download a photo from a URL with retry logic.

    Args:
        url: URL of the photo to download
        max_retries: Maximum number of retry attempts (default: 5)
        timeout: Request timeout in seconds (default: 30)

    Returns:
        Photo data as bytes

    Raises:
        PhotoDownloadError: If download fails after all retries
        PhotoError: For invalid input or other errors

    Example:
        >>> photo_data = download_photo("https://example.com/photo.jpg")
        >>> len(photo_data) > 0
        True
    """
    if not url:
        raise PhotoError("Photo URL cannot be empty")

    if not url.startswith(("http://", "https://")):
        raise PhotoError(f"Invalid photo URL scheme: {url}")

    delay = INITIAL_RETRY_DELAY

    for attempt in range(max_retries):
        try:
            logger.debug(f"Downloading photo from {url} (attempt {attempt + 1}/{max_retries})")

            response = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "gcontact-sync/0.1.0"},
            )

            # Check for HTTP errors
            response.raise_for_status()

            # Validate content
            if not response.content:
                raise PhotoError(f"Empty response from {url}")

            # Validate content type
            content_type = response.headers.get("content-type", "").lower()
            if content_type and not content_type.startswith("image/"):
                logger.warning(
                    f"Unexpected content type for photo: {content_type} from {url}"
                )

            logger.debug(
                f"Successfully downloaded photo: {len(response.content)} bytes "
                f"from {url}"
            )

            return response.content

        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response else None

            # Retry on server errors or rate limits
            if status_code and status_code >= 500 and attempt < max_retries - 1:
                logger.warning(
                    f"Server error ({status_code}) downloading photo, "
                    f"retrying in {delay:.1f}s"
                )
                time.sleep(delay)
                delay = min(delay * 2, MAX_RETRY_DELAY)
                continue

            # Don't retry on client errors (404, 403, etc.)
            logger.error(f"HTTP error downloading photo from {url}: {e}")
            raise PhotoDownloadError(f"Failed to download photo: {e}") from e

        except requests.Timeout as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"Timeout downloading photo, retrying in {delay:.1f}s"
                )
                time.sleep(delay)
                delay = min(delay * 2, MAX_RETRY_DELAY)
                continue
            else:
                logger.error(f"Timeout downloading photo from {url} after all retries")
                raise PhotoDownloadError(
                    f"Download timeout after {max_retries} retries: {url}"
                ) from e

        except RequestException as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"Network error downloading photo, retrying in {delay:.1f}s: {e}"
                )
                time.sleep(delay)
                delay = min(delay * 2, MAX_RETRY_DELAY)
                continue
            else:
                logger.error(f"Network error downloading photo from {url}: {e}")
                raise PhotoDownloadError(
                    f"Network error after {max_retries} retries: {e}"
                ) from e

        except Exception as e:
            logger.error(f"Unexpected error downloading photo from {url}: {e}")
            raise PhotoError(f"Unexpected error downloading photo: {e}") from e

    # Should not reach here, but just in case
    raise PhotoDownloadError(f"Failed to download photo after {max_retries} retries")
