"""
Photo download and processing for Google Contacts synchronization.

Provides utilities for:
- Downloading contact photos from URLs
- Image format validation and conversion
- Size optimization to meet Google API requirements
- Retry logic for network failures
"""

import io
import logging
import time

import requests
from PIL import Image
from requests.exceptions import RequestException

# Retry configuration
MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1.0  # seconds
MAX_RETRY_DELAY = 60.0  # seconds

# HTTP timeout configuration
DOWNLOAD_TIMEOUT = 30.0  # seconds

# Photo processing configuration
MAX_PHOTO_SIZE = 5 * 1024 * 1024  # 5MB - Google API limit
MAX_PHOTO_DIMENSION = 2048  # pixels - reasonable max dimension
JPEG_QUALITY = 85  # Balance between quality and file size

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
            logger.debug(
                f"Downloading photo from {url} (attempt {attempt + 1}/{max_retries})"
            )

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
                logger.warning(f"Timeout downloading photo, retrying in {delay:.1f}s")
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


def process_photo(
    photo_data: bytes,
    max_size: int = MAX_PHOTO_SIZE,
    max_dimension: int = MAX_PHOTO_DIMENSION,
) -> bytes:
    """
    Process and validate photo data, converting format and size as needed.

    Validates the photo is a valid image format, converts to JPEG if necessary,
    and resizes to meet Google API requirements (max 5MB, reasonable dimensions).

    Args:
        photo_data: Raw photo data as bytes
        max_size: Maximum file size in bytes (default: 5MB)
        max_dimension: Maximum width/height in pixels (default: 2048)

    Returns:
        Processed photo data as bytes in JPEG format

    Raises:
        PhotoError: If photo is invalid or processing fails

    Example:
        >>> photo_data = download_photo("https://example.com/photo.jpg")
        >>> processed = process_photo(photo_data)
        >>> len(processed) > 0
        True
        >>> len(processed) <= MAX_PHOTO_SIZE
        True
    """
    if not photo_data:
        raise PhotoError("Photo data cannot be empty")

    try:
        # Load and validate the image
        logger.debug(f"Processing photo: {len(photo_data)} bytes")
        image = Image.open(io.BytesIO(photo_data))

        # Validate it's a real image by loading data
        image.load()

        # Convert to RGB if needed (handles RGBA, P, L, etc.)
        if image.mode not in ("RGB", "L"):
            logger.debug(f"Converting image from {image.mode} to RGB")
            if image.mode == "RGBA":
                # Create white background for transparency
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[3])  # Use alpha as mask
                image = background
            else:
                image = image.convert("RGB")

        # Check if resizing is needed
        original_size = image.size
        width, height = image.size

        if width > max_dimension or height > max_dimension:
            # Calculate new dimensions maintaining aspect ratio
            if width > height:
                new_width = max_dimension
                new_height = int(height * (max_dimension / width))
            else:
                new_height = max_dimension
                new_width = int(width * (max_dimension / height))

            logger.debug(
                f"Resizing photo from {width}x{height} to {new_width}x{new_height}"
            )
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Convert to JPEG format
        output = io.BytesIO()
        quality = JPEG_QUALITY

        # Try saving with initial quality
        image.save(output, format="JPEG", quality=quality, optimize=True)
        output_data = output.getvalue()

        # If still too large, reduce quality iteratively
        while len(output_data) > max_size and quality > 20:
            quality -= 5
            logger.debug(
                f"Photo too large ({len(output_data)} bytes), "
                f"reducing quality to {quality}"
            )
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            output_data = output.getvalue()

        # Final size check
        if len(output_data) > max_size:
            raise PhotoError(
                f"Unable to reduce photo size below {max_size} bytes "
                f"(current: {len(output_data)} bytes)"
            )

        resize_msg = ""
        if original_size != image.size:
            resize_msg = f" (resized from {original_size})"
        logger.debug(
            f"Successfully processed photo: "
            f"{len(photo_data)} -> {len(output_data)} bytes{resize_msg}"
        )

        return output_data

    except Image.UnidentifiedImageError as e:
        logger.error(f"Invalid image format: {e}")
        raise PhotoError("Invalid or unsupported image format") from e

    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        raise PhotoError(f"Failed to process photo: {e}") from e
