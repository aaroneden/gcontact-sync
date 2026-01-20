"""
Unit tests for the Photo module.

Tests the photo download and processing functions with mocked HTTP and image operations.
"""

import io
from unittest.mock import MagicMock, Mock, patch

import pytest
from PIL import Image
from requests.exceptions import RequestException, Timeout

from gcontact_sync.sync.photo import (
    DOWNLOAD_TIMEOUT,
    INITIAL_RETRY_DELAY,
    JPEG_QUALITY,
    MAX_PHOTO_DIMENSION,
    MAX_PHOTO_SIZE,
    MAX_RETRIES,
    MAX_RETRY_DELAY,
    PhotoDownloadError,
    PhotoError,
    download_photo,
    process_photo,
)


class TestDownloadPhotoBasics:
    """Tests for basic download_photo functionality."""

    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_success(self, mock_get):
        """Test successful photo download."""
        mock_response = Mock()
        mock_response.content = b"fake image data"
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = download_photo("https://example.com/photo.jpg")

        assert result == b"fake image data"
        mock_get.assert_called_once_with(
            "https://example.com/photo.jpg",
            timeout=DOWNLOAD_TIMEOUT,
            headers={"User-Agent": "gcontact-sync/0.1.0"},
        )

    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_with_custom_timeout(self, mock_get):
        """Test download with custom timeout."""
        mock_response = Mock()
        mock_response.content = b"fake image data"
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = download_photo("https://example.com/photo.jpg", timeout=60.0)

        assert result == b"fake image data"
        mock_get.assert_called_once_with(
            "https://example.com/photo.jpg",
            timeout=60.0,
            headers={"User-Agent": "gcontact-sync/0.1.0"},
        )

    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_http_url(self, mock_get):
        """Test download with HTTP URL (not HTTPS)."""
        mock_response = Mock()
        mock_response.content = b"fake image data"
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = download_photo("http://example.com/photo.jpg")

        assert result == b"fake image data"


class TestDownloadPhotoValidation:
    """Tests for download_photo input validation."""

    def test_download_photo_empty_url(self):
        """Test that empty URL raises PhotoError."""
        with pytest.raises(PhotoError, match="Photo URL cannot be empty"):
            download_photo("")

    def test_download_photo_invalid_url_scheme(self):
        """Test that invalid URL scheme raises PhotoError."""
        with pytest.raises(PhotoError, match="Invalid photo URL scheme"):
            download_photo("ftp://example.com/photo.jpg")

    def test_download_photo_invalid_url_scheme_file(self):
        """Test that file:// URL scheme raises PhotoError."""
        with pytest.raises(PhotoError, match="Invalid photo URL scheme"):
            download_photo("file:///tmp/photo.jpg")

    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_empty_response(self, mock_get):
        """Test that empty response raises PhotoError."""
        mock_response = Mock()
        mock_response.content = b""
        mock_response.headers = {}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(PhotoError, match="Empty response"):
            download_photo("https://example.com/photo.jpg")

    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_non_image_content_type(self, mock_get):
        """Test that non-image content type logs warning but succeeds."""
        mock_response = Mock()
        mock_response.content = b"fake image data"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Should still succeed but log warning
        result = download_photo("https://example.com/photo.jpg")
        assert result == b"fake image data"


class TestDownloadPhotoRetries:
    """Tests for download_photo retry logic."""

    @patch("time.sleep")
    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_retry_on_server_error(self, mock_get, mock_sleep):
        """Test retry on 500 server error."""
        from requests import HTTPError

        # First call fails with 500, second succeeds
        mock_error_response = Mock()
        mock_error_response.status_code = 500

        mock_success_response = Mock()
        mock_success_response.content = b"fake image data"
        mock_success_response.headers = {"content-type": "image/jpeg"}
        mock_success_response.raise_for_status = Mock()

        mock_get.side_effect = [
            Mock(raise_for_status=Mock(side_effect=HTTPError(response=mock_error_response))),
            mock_success_response,
        ]

        result = download_photo("https://example.com/photo.jpg")

        assert result == b"fake image data"
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()

    @patch("time.sleep")
    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_retry_on_503(self, mock_get, mock_sleep):
        """Test retry on 503 service unavailable."""
        from requests import HTTPError

        mock_error_response = Mock()
        mock_error_response.status_code = 503

        mock_success_response = Mock()
        mock_success_response.content = b"fake image data"
        mock_success_response.headers = {"content-type": "image/jpeg"}
        mock_success_response.raise_for_status = Mock()

        mock_get.side_effect = [
            Mock(raise_for_status=Mock(side_effect=HTTPError(response=mock_error_response))),
            mock_success_response,
        ]

        result = download_photo("https://example.com/photo.jpg")

        assert result == b"fake image data"
        assert mock_get.call_count == 2

    @patch("time.sleep")
    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_no_retry_on_404(self, mock_get, mock_sleep):
        """Test that 404 errors don't retry."""
        from requests import HTTPError

        mock_error_response = Mock()
        mock_error_response.status_code = 404

        mock_get.return_value = Mock(
            raise_for_status=Mock(side_effect=HTTPError(response=mock_error_response))
        )

        with pytest.raises(PhotoDownloadError, match="Failed to download photo"):
            download_photo("https://example.com/photo.jpg")

        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_no_retry_on_403(self, mock_get, mock_sleep):
        """Test that 403 errors don't retry."""
        from requests import HTTPError

        mock_error_response = Mock()
        mock_error_response.status_code = 403

        mock_get.return_value = Mock(
            raise_for_status=Mock(side_effect=HTTPError(response=mock_error_response))
        )

        with pytest.raises(PhotoDownloadError, match="Failed to download photo"):
            download_photo("https://example.com/photo.jpg")

        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_retry_on_timeout(self, mock_get, mock_sleep):
        """Test retry on timeout."""
        mock_success_response = Mock()
        mock_success_response.content = b"fake image data"
        mock_success_response.headers = {"content-type": "image/jpeg"}
        mock_success_response.raise_for_status = Mock()

        mock_get.side_effect = [
            Timeout("Connection timeout"),
            mock_success_response,
        ]

        result = download_photo("https://example.com/photo.jpg")

        assert result == b"fake image data"
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()

    @patch("time.sleep")
    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_timeout_exhausted(self, mock_get, mock_sleep):
        """Test that exhausted retries on timeout raise error."""
        mock_get.side_effect = Timeout("Connection timeout")

        with pytest.raises(PhotoDownloadError, match="Download timeout after .* retries"):
            download_photo("https://example.com/photo.jpg", max_retries=3)

        assert mock_get.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("time.sleep")
    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_retry_on_network_error(self, mock_get, mock_sleep):
        """Test retry on network error."""
        mock_success_response = Mock()
        mock_success_response.content = b"fake image data"
        mock_success_response.headers = {"content-type": "image/jpeg"}
        mock_success_response.raise_for_status = Mock()

        mock_get.side_effect = [
            RequestException("Network error"),
            mock_success_response,
        ]

        result = download_photo("https://example.com/photo.jpg")

        assert result == b"fake image data"
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()

    @patch("time.sleep")
    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_network_error_exhausted(self, mock_get, mock_sleep):
        """Test that exhausted retries on network error raise error."""
        mock_get.side_effect = RequestException("Network error")

        with pytest.raises(PhotoDownloadError, match="Network error after .* retries"):
            download_photo("https://example.com/photo.jpg", max_retries=3)

        assert mock_get.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("time.sleep")
    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_exponential_backoff(self, mock_get, mock_sleep):
        """Test that retry delay increases exponentially."""
        mock_get.side_effect = Timeout("Connection timeout")

        with pytest.raises(PhotoDownloadError):
            download_photo("https://example.com/photo.jpg", max_retries=4)

        # Check that delays increase: 1.0, 2.0, 4.0
        assert mock_sleep.call_count == 3
        calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert calls[0] == INITIAL_RETRY_DELAY
        assert calls[1] == INITIAL_RETRY_DELAY * 2
        assert calls[2] == INITIAL_RETRY_DELAY * 4

    @patch("gcontact_sync.sync.photo.requests.get")
    def test_download_photo_unexpected_error(self, mock_get):
        """Test that unexpected errors raise PhotoError."""
        mock_get.side_effect = Exception("Unexpected error")

        with pytest.raises(PhotoError, match="Unexpected error downloading photo"):
            download_photo("https://example.com/photo.jpg")


class TestProcessPhotoBasics:
    """Tests for basic process_photo functionality."""

    def test_process_photo_valid_jpeg(self):
        """Test processing a valid JPEG image."""
        # Create a simple test image
        img = Image.new("RGB", (100, 100), color="red")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        photo_data = img_bytes.getvalue()

        result = process_photo(photo_data)

        assert result is not None
        assert len(result) > 0
        assert len(result) <= MAX_PHOTO_SIZE

        # Verify it's a valid JPEG
        result_img = Image.open(io.BytesIO(result))
        assert result_img.format == "JPEG"

    def test_process_photo_valid_png(self):
        """Test processing a valid PNG image (converts to JPEG)."""
        # Create a PNG image
        img = Image.new("RGB", (100, 100), color="blue")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        photo_data = img_bytes.getvalue()

        result = process_photo(photo_data)

        assert result is not None
        assert len(result) > 0

        # Verify it's converted to JPEG
        result_img = Image.open(io.BytesIO(result))
        assert result_img.format == "JPEG"

    def test_process_photo_rgba_to_rgb(self):
        """Test that RGBA images are converted to RGB."""
        # Create an RGBA image with transparency
        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        photo_data = img_bytes.getvalue()

        result = process_photo(photo_data)

        # Verify it's converted to RGB JPEG
        result_img = Image.open(io.BytesIO(result))
        assert result_img.format == "JPEG"
        assert result_img.mode == "RGB"

    def test_process_photo_grayscale(self):
        """Test processing a grayscale image."""
        # Create a grayscale image
        img = Image.new("L", (100, 100), color=128)
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        photo_data = img_bytes.getvalue()

        result = process_photo(photo_data)

        assert result is not None
        assert len(result) > 0

        # Grayscale can stay as-is
        result_img = Image.open(io.BytesIO(result))
        assert result_img.format == "JPEG"


class TestProcessPhotoResizing:
    """Tests for process_photo resizing functionality."""

    def test_process_photo_resize_width_exceeds(self):
        """Test resizing when width exceeds max dimension."""
        # Create an image wider than max dimension
        img = Image.new("RGB", (3000, 1000), color="green")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        photo_data = img_bytes.getvalue()

        result = process_photo(photo_data)

        result_img = Image.open(io.BytesIO(result))
        assert result_img.width <= MAX_PHOTO_DIMENSION
        assert result_img.height <= MAX_PHOTO_DIMENSION

        # Check aspect ratio maintained
        original_ratio = 3000 / 1000
        result_ratio = result_img.width / result_img.height
        assert abs(original_ratio - result_ratio) < 0.1

    def test_process_photo_resize_height_exceeds(self):
        """Test resizing when height exceeds max dimension."""
        # Create an image taller than max dimension
        img = Image.new("RGB", (1000, 3000), color="yellow")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        photo_data = img_bytes.getvalue()

        result = process_photo(photo_data)

        result_img = Image.open(io.BytesIO(result))
        assert result_img.width <= MAX_PHOTO_DIMENSION
        assert result_img.height <= MAX_PHOTO_DIMENSION

        # Check aspect ratio maintained
        original_ratio = 1000 / 3000
        result_ratio = result_img.width / result_img.height
        assert abs(original_ratio - result_ratio) < 0.1

    def test_process_photo_no_resize_needed(self):
        """Test that small images are not resized."""
        # Create a small image
        img = Image.new("RGB", (500, 500), color="purple")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        photo_data = img_bytes.getvalue()

        result = process_photo(photo_data)

        result_img = Image.open(io.BytesIO(result))
        # Should maintain original dimensions
        assert result_img.size == (500, 500)

    def test_process_photo_custom_max_dimension(self):
        """Test processing with custom max dimension."""
        # Create an image
        img = Image.new("RGB", (1500, 1500), color="orange")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        photo_data = img_bytes.getvalue()

        result = process_photo(photo_data, max_dimension=1000)

        result_img = Image.open(io.BytesIO(result))
        assert result_img.width <= 1000
        assert result_img.height <= 1000


class TestProcessPhotoSizeOptimization:
    """Tests for process_photo size optimization."""

    def test_process_photo_reduce_quality_if_too_large(self):
        """Test that quality is reduced if photo is too large."""
        # Create a large, complex image that might exceed size limit
        img = Image.new("RGB", (2000, 2000), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG", quality=100)
        photo_data = img_bytes.getvalue()

        # Process with a very small max size to force quality reduction
        result = process_photo(photo_data, max_size=50000)

        assert len(result) <= 50000

    def test_process_photo_respects_max_size(self):
        """Test that processed photo respects max size."""
        img = Image.new("RGB", (500, 500), color="red")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        photo_data = img_bytes.getvalue()

        result = process_photo(photo_data, max_size=100000)

        assert len(result) <= 100000

    def test_process_photo_unable_to_reduce_size(self):
        """Test that error is raised if unable to reduce size enough."""
        # Create a simple image
        img = Image.new("RGB", (100, 100), color="red")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        photo_data = img_bytes.getvalue()

        # Set an impossibly small max size
        with pytest.raises(PhotoError, match="Unable to reduce photo size"):
            process_photo(photo_data, max_size=100)


class TestProcessPhotoValidation:
    """Tests for process_photo input validation and error handling."""

    def test_process_photo_empty_data(self):
        """Test that empty photo data raises PhotoError."""
        with pytest.raises(PhotoError, match="Photo data cannot be empty"):
            process_photo(b"")

    def test_process_photo_invalid_image_data(self):
        """Test that invalid image data raises PhotoError."""
        with pytest.raises(PhotoError, match="Invalid or unsupported image format"):
            process_photo(b"not an image")

    def test_process_photo_corrupt_image_data(self):
        """Test that corrupt image data raises PhotoError."""
        with pytest.raises(PhotoError, match="Invalid or unsupported image format"):
            process_photo(b"\x00\x01\x02\x03\x04\x05")

    def test_process_photo_text_data(self):
        """Test that text data raises PhotoError."""
        with pytest.raises(PhotoError, match="Invalid or unsupported image format"):
            process_photo(b"This is just text, not an image")


class TestPhotoConstants:
    """Tests that constants are defined correctly."""

    def test_constants_are_defined(self):
        """Test that all expected constants are defined."""
        assert MAX_RETRIES > 0
        assert INITIAL_RETRY_DELAY > 0
        assert MAX_RETRY_DELAY > INITIAL_RETRY_DELAY
        assert DOWNLOAD_TIMEOUT > 0
        assert MAX_PHOTO_SIZE > 0
        assert MAX_PHOTO_DIMENSION > 0
        assert JPEG_QUALITY > 0
        assert JPEG_QUALITY <= 100

    def test_max_photo_size_is_5mb(self):
        """Test that max photo size is 5MB (Google API limit)."""
        assert MAX_PHOTO_SIZE == 5 * 1024 * 1024

    def test_retry_constants_reasonable(self):
        """Test that retry constants are reasonable."""
        assert MAX_RETRIES >= 3
        assert INITIAL_RETRY_DELAY >= 0.5
        assert MAX_RETRY_DELAY <= 120


class TestPhotoExceptions:
    """Tests for photo exception classes."""

    def test_photo_error_is_exception(self):
        """Test that PhotoError is an Exception."""
        assert issubclass(PhotoError, Exception)

    def test_photo_download_error_is_photo_error(self):
        """Test that PhotoDownloadError is a PhotoError."""
        assert issubclass(PhotoDownloadError, PhotoError)

    def test_raise_photo_error(self):
        """Test raising PhotoError."""
        with pytest.raises(PhotoError, match="test error"):
            raise PhotoError("test error")

    def test_raise_photo_download_error(self):
        """Test raising PhotoDownloadError."""
        with pytest.raises(PhotoDownloadError, match="download failed"):
            raise PhotoDownloadError("download failed")
