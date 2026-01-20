"""
Unit tests for the authentication module.

Tests the GoogleAuth class for OAuth2 authentication, credential management,
and dual account support.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gcontact_sync.auth.google_auth import (
    ACCOUNT_1,
    ACCOUNT_2,
    DEFAULT_CONFIG_DIR,
    SCOPES,
    AuthenticationError,
    GoogleAuth,
)


class TestGoogleAuthInitialization:
    """Tests for GoogleAuth initialization."""

    def test_default_config_dir(self):
        """Test that default config dir is used when no argument provided."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove GCONTACT_SYNC_CONFIG_DIR if it exists
            os.environ.pop("GCONTACT_SYNC_CONFIG_DIR", None)
            auth = GoogleAuth()
            assert auth.config_dir == DEFAULT_CONFIG_DIR

    def test_custom_config_dir_via_argument(self, tmp_path):
        """Test that custom config dir can be passed as argument."""
        custom_dir = tmp_path / "custom_config"
        auth = GoogleAuth(config_dir=custom_dir)
        assert auth.config_dir == custom_dir

    def test_config_dir_from_environment_variable(self, tmp_path):
        """Test that config dir can be set via environment variable."""
        env_dir = str(tmp_path / "env_config")
        with patch.dict(os.environ, {"GCONTACT_SYNC_CONFIG_DIR": env_dir}):
            auth = GoogleAuth()
            assert auth.config_dir == Path(env_dir)

    def test_argument_takes_precedence_over_environment(self, tmp_path):
        """Test that explicit argument takes precedence over env variable."""
        arg_dir = tmp_path / "arg_config"
        env_dir = str(tmp_path / "env_config")
        with patch.dict(os.environ, {"GCONTACT_SYNC_CONFIG_DIR": env_dir}):
            auth = GoogleAuth(config_dir=arg_dir)
            assert auth.config_dir == arg_dir

    def test_credentials_path_is_set(self, tmp_path):
        """Test that credentials path is set correctly."""
        auth = GoogleAuth(config_dir=tmp_path)
        assert auth.credentials_path == tmp_path / "credentials.json"


class TestAccountValidation:
    """Tests for account ID validation."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        return GoogleAuth(config_dir=tmp_path)

    def test_valid_account1(self, auth):
        """Test that 'account1' is valid."""
        # Should not raise
        auth._validate_account_id(ACCOUNT_1)

    def test_valid_account2(self, auth):
        """Test that 'account2' is valid."""
        # Should not raise
        auth._validate_account_id(ACCOUNT_2)

    def test_invalid_account_raises_error(self, auth):
        """Test that invalid account ID raises ValueError."""
        with pytest.raises(ValueError, match="Invalid account_id"):
            auth._validate_account_id("account3")

    def test_invalid_account_empty_string(self, auth):
        """Test that empty string account ID raises ValueError."""
        with pytest.raises(ValueError, match="Invalid account_id"):
            auth._validate_account_id("")

    def test_invalid_account_none(self, auth):
        """Test that None account ID raises ValueError."""
        with pytest.raises(ValueError, match="Invalid account_id"):
            auth._validate_account_id(None)


class TestTokenPathGeneration:
    """Tests for token path generation."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        return GoogleAuth(config_dir=tmp_path)

    def test_token_path_account1(self, auth, tmp_path):
        """Test token path for account1."""
        path = auth._get_token_path(ACCOUNT_1)
        assert path == tmp_path / "token_account1.json"

    def test_token_path_account2(self, auth, tmp_path):
        """Test token path for account2."""
        path = auth._get_token_path(ACCOUNT_2)
        assert path == tmp_path / "token_account2.json"

    def test_token_path_invalid_account(self, auth):
        """Test that invalid account raises ValueError."""
        with pytest.raises(ValueError, match="Invalid account_id"):
            auth._get_token_path("invalid")


class TestConfigDirCreation:
    """Tests for config directory creation."""

    def test_ensure_config_dir_creates_directory(self, tmp_path):
        """Test that config dir is created if it doesn't exist."""
        config_dir = tmp_path / "new_config"
        auth = GoogleAuth(config_dir=config_dir)

        assert not config_dir.exists()
        auth._ensure_config_dir()
        assert config_dir.exists()

    def test_ensure_config_dir_sets_permissions(self, tmp_path):
        """Test that config dir is created with secure permissions."""
        config_dir = tmp_path / "secure_config"
        auth = GoogleAuth(config_dir=config_dir)

        auth._ensure_config_dir()

        # Check permissions (700 = owner read/write/execute only)
        mode = config_dir.stat().st_mode & 0o777
        assert mode == 0o700

    def test_ensure_config_dir_idempotent(self, tmp_path):
        """Test that ensure_config_dir can be called multiple times."""
        config_dir = tmp_path / "repeat_config"
        auth = GoogleAuth(config_dir=config_dir)

        auth._ensure_config_dir()
        auth._ensure_config_dir()  # Should not raise

        assert config_dir.exists()


class TestCredentialLoading:
    """Tests for credential loading from token files."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        return GoogleAuth(config_dir=tmp_path)

    def test_load_credentials_no_file(self, auth):
        """Test loading credentials when token file doesn't exist."""
        result = auth._load_credentials(ACCOUNT_1)
        assert result is None

    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_load_credentials_from_file(self, mock_creds_class, auth, tmp_path):
        """Test loading credentials from existing token file."""
        # Create a valid token file
        token_path = tmp_path / "token_account1.json"
        token_data = {
            "token": "test_token",
            "refresh_token": "test_refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "test_client",
            "client_secret": "test_secret",
            "scopes": SCOPES,
        }
        token_path.write_text(json.dumps(token_data))

        mock_creds = MagicMock()
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        result = auth._load_credentials(ACCOUNT_1)

        mock_creds_class.from_authorized_user_file.assert_called_once_with(
            str(token_path), SCOPES
        )
        assert result == mock_creds

    def test_load_credentials_invalid_json(self, auth, tmp_path):
        """Test loading credentials from invalid JSON file."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text("invalid json {{{")

        result = auth._load_credentials(ACCOUNT_1)
        assert result is None

    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_load_credentials_value_error(self, mock_creds_class, auth, tmp_path):
        """Test loading credentials when Credentials raises ValueError."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text("{}")

        mock_creds_class.from_authorized_user_file.side_effect = ValueError(
            "Invalid token"
        )

        result = auth._load_credentials(ACCOUNT_1)
        assert result is None


class TestCredentialSaving:
    """Tests for credential saving."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        return GoogleAuth(config_dir=tmp_path)

    def test_save_credentials_creates_file(self, auth, tmp_path):
        """Test that saving credentials creates token file."""
        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "test"}'

        auth._save_credentials(ACCOUNT_1, mock_creds)

        token_path = tmp_path / "token_account1.json"
        assert token_path.exists()
        assert token_path.read_text() == '{"token": "test"}'

    def test_save_credentials_sets_permissions(self, auth, tmp_path):
        """Test that saved token file has secure permissions."""
        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "test"}'

        auth._save_credentials(ACCOUNT_1, mock_creds)

        token_path = tmp_path / "token_account1.json"
        mode = token_path.stat().st_mode & 0o777
        assert mode == 0o600  # Owner read/write only

    def test_save_credentials_creates_config_dir(self, tmp_path):
        """Test that saving credentials creates config dir if needed."""
        config_dir = tmp_path / "new_dir"
        auth = GoogleAuth(config_dir=config_dir)

        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "test"}'

        assert not config_dir.exists()
        auth._save_credentials(ACCOUNT_1, mock_creds)
        assert config_dir.exists()


class TestCredentialRefresh:
    """Tests for credential refresh."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        return GoogleAuth(config_dir=tmp_path)

    def test_refresh_credentials_no_refresh_token(self, auth):
        """Test refresh returns False when no refresh token available."""
        mock_creds = MagicMock()
        mock_creds.refresh_token = None

        result = auth._refresh_credentials(mock_creds)
        assert result is False

    @patch("gcontact_sync.auth.google_auth.Request")
    def test_refresh_credentials_success(self, mock_request_class, auth):
        """Test successful credential refresh."""
        mock_creds = MagicMock()
        mock_creds.refresh_token = "refresh_token"

        result = auth._refresh_credentials(mock_creds)

        assert result is True
        mock_creds.refresh.assert_called_once()

    @patch("gcontact_sync.auth.google_auth.Request")
    def test_refresh_credentials_failure(self, mock_request_class, auth):
        """Test credential refresh failure."""
        from google.auth.exceptions import RefreshError

        mock_creds = MagicMock()
        mock_creds.refresh_token = "refresh_token"
        mock_creds.refresh.side_effect = RefreshError("Refresh failed")

        result = auth._refresh_credentials(mock_creds)
        assert result is False


class TestGetCredentials:
    """Tests for get_credentials method."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        return GoogleAuth(config_dir=tmp_path)

    def test_get_credentials_invalid_account(self, auth):
        """Test get_credentials with invalid account raises ValueError."""
        with pytest.raises(ValueError, match="Invalid account_id"):
            auth.get_credentials("invalid")

    def test_get_credentials_no_token_file(self, auth):
        """Test get_credentials returns None when no token file exists."""
        result = auth.get_credentials(ACCOUNT_1)
        assert result is None

    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_get_credentials_valid_credentials(self, mock_creds_class, auth, tmp_path):
        """Test get_credentials returns valid credentials."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text('{"token": "test"}')

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        result = auth.get_credentials(ACCOUNT_1)

        assert result == mock_creds

    @patch("gcontact_sync.auth.google_auth.Request")
    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_get_credentials_expired_refreshes(
        self, mock_creds_class, mock_request, auth, tmp_path
    ):
        """Test get_credentials refreshes expired credentials."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text('{"token": "test"}')

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_token"
        mock_creds.to_json.return_value = '{"refreshed": true}'
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        result = auth.get_credentials(ACCOUNT_1)

        mock_creds.refresh.assert_called_once()
        assert result == mock_creds

    @patch("gcontact_sync.auth.google_auth.Request")
    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_get_credentials_refresh_failure_returns_none(
        self, mock_creds_class, mock_request, auth, tmp_path
    ):
        """Test get_credentials returns None when refresh fails."""
        from google.auth.exceptions import RefreshError

        token_path = tmp_path / "token_account1.json"
        token_path.write_text('{"token": "test"}')

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_token"
        mock_creds.refresh.side_effect = RefreshError("Failed")
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        result = auth.get_credentials(ACCOUNT_1)

        assert result is None


class TestAuthenticate:
    """Tests for authenticate method."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        auth = GoogleAuth(config_dir=tmp_path)
        # Create credentials file
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text(
            json.dumps(
                {
                    "installed": {
                        "client_id": "test_client",
                        "client_secret": "test_secret",
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                }
            )
        )
        return auth

    def test_authenticate_invalid_account(self, auth):
        """Test authenticate with invalid account raises ValueError."""
        with pytest.raises(ValueError, match="Invalid account_id"):
            auth.authenticate("invalid")

    def test_authenticate_missing_credentials_file(self, tmp_path):
        """Test authenticate raises FileNotFoundError when credentials missing."""
        auth = GoogleAuth(config_dir=tmp_path)
        # No credentials.json file created

        with pytest.raises(FileNotFoundError, match="OAuth credentials file not found"):
            auth.authenticate(ACCOUNT_1)

    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_authenticate_uses_existing_credentials(
        self, mock_creds_class, auth, tmp_path
    ):
        """Test authenticate returns existing valid credentials."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text('{"token": "existing"}')

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        result = auth.authenticate(ACCOUNT_1)

        assert result == mock_creds

    @patch("gcontact_sync.auth.google_auth.InstalledAppFlow")
    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_authenticate_starts_oauth_flow(
        self, mock_creds_class, mock_flow_class, auth, tmp_path
    ):
        """Test authenticate starts OAuth flow when no credentials."""
        mock_creds_class.from_authorized_user_file.side_effect = FileNotFoundError()

        mock_flow = MagicMock()
        mock_new_creds = MagicMock()
        mock_new_creds.to_json.return_value = '{"new": true}'
        mock_flow.run_local_server.return_value = mock_new_creds
        mock_flow_class.from_client_secrets_file.return_value = mock_flow

        result = auth.authenticate(ACCOUNT_1)

        mock_flow_class.from_client_secrets_file.assert_called_once()
        mock_flow.run_local_server.assert_called_once_with(port=0)
        assert result == mock_new_creds

    @patch("gcontact_sync.auth.google_auth.InstalledAppFlow")
    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_authenticate_force_reauth(
        self, mock_creds_class, mock_flow_class, auth, tmp_path
    ):
        """Test authenticate with force_reauth ignores existing credentials."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text('{"token": "existing"}')

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        mock_flow = MagicMock()
        mock_new_creds = MagicMock()
        mock_new_creds.to_json.return_value = '{"new": true}'
        mock_flow.run_local_server.return_value = mock_new_creds
        mock_flow_class.from_client_secrets_file.return_value = mock_flow

        result = auth.authenticate(ACCOUNT_1, force_reauth=True)

        mock_flow.run_local_server.assert_called_once()
        assert result == mock_new_creds

    @patch("gcontact_sync.auth.google_auth.InstalledAppFlow")
    def test_authenticate_oauth_flow_failure(self, mock_flow_class, auth):
        """Test authenticate raises AuthenticationError on OAuth failure."""
        mock_flow = MagicMock()
        mock_flow.run_local_server.side_effect = Exception("OAuth failed")
        mock_flow_class.from_client_secrets_file.return_value = mock_flow

        with pytest.raises(AuthenticationError, match="Failed to authenticate"):
            auth.authenticate(ACCOUNT_1, force_reauth=True)


class TestIsAuthenticated:
    """Tests for is_authenticated method."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        return GoogleAuth(config_dir=tmp_path)

    def test_is_authenticated_no_credentials(self, auth):
        """Test is_authenticated returns False when no credentials."""
        result = auth.is_authenticated(ACCOUNT_1)
        assert result is False

    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_is_authenticated_with_valid_credentials(
        self, mock_creds_class, auth, tmp_path
    ):
        """Test is_authenticated returns True with valid credentials."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text('{"token": "test"}')

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        result = auth.is_authenticated(ACCOUNT_1)
        assert result is True

    def test_is_authenticated_invalid_account(self, auth):
        """Test is_authenticated with invalid account raises ValueError."""
        with pytest.raises(ValueError, match="Invalid account_id"):
            auth.is_authenticated("invalid")


class TestGetBothCredentials:
    """Tests for get_both_credentials method."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        return GoogleAuth(config_dir=tmp_path)

    def test_get_both_credentials_none(self, auth):
        """Test get_both_credentials returns (None, None) when no credentials."""
        result = auth.get_both_credentials()
        assert result == (None, None)

    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_get_both_credentials_one_authenticated(
        self, mock_creds_class, auth, tmp_path
    ):
        """Test get_both_credentials with only one account authenticated."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text('{"token": "test"}')

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        result = auth.get_both_credentials()

        assert result[0] == mock_creds
        assert result[1] is None

    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_get_both_credentials_both_authenticated(
        self, mock_creds_class, auth, tmp_path
    ):
        """Test get_both_credentials with both accounts authenticated."""
        (tmp_path / "token_account1.json").write_text('{"token": "test1"}')
        (tmp_path / "token_account2.json").write_text('{"token": "test2"}')

        mock_creds1 = MagicMock()
        mock_creds1.valid = True
        mock_creds2 = MagicMock()
        mock_creds2.valid = True

        def side_effect(path, scopes):
            if "account1" in path:
                return mock_creds1
            return mock_creds2

        mock_creds_class.from_authorized_user_file.side_effect = side_effect

        result = auth.get_both_credentials()

        assert result[0] == mock_creds1
        assert result[1] == mock_creds2


class TestAuthenticateBoth:
    """Tests for authenticate_both method."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        auth = GoogleAuth(config_dir=tmp_path)
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text(
            json.dumps(
                {
                    "installed": {
                        "client_id": "test",
                        "client_secret": "test",
                        "auth_uri": "https://test.com/auth",
                        "token_uri": "https://test.com/token",
                    }
                }
            )
        )
        return auth

    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_authenticate_both_with_existing_credentials(
        self, mock_creds_class, auth, tmp_path
    ):
        """Test authenticate_both with existing credentials."""
        (tmp_path / "token_account1.json").write_text('{"token": "test1"}')
        (tmp_path / "token_account2.json").write_text('{"token": "test2"}')

        mock_creds1 = MagicMock()
        mock_creds1.valid = True
        mock_creds2 = MagicMock()
        mock_creds2.valid = True

        def side_effect(path, scopes):
            if "account1" in path:
                return mock_creds1
            return mock_creds2

        mock_creds_class.from_authorized_user_file.side_effect = side_effect

        result = auth.authenticate_both()

        assert result == (mock_creds1, mock_creds2)


class TestClearCredentials:
    """Tests for clear_credentials method."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        return GoogleAuth(config_dir=tmp_path)

    def test_clear_credentials_removes_file(self, auth, tmp_path):
        """Test clear_credentials removes token file."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text('{"token": "test"}')

        assert token_path.exists()
        result = auth.clear_credentials(ACCOUNT_1)
        assert result is True
        assert not token_path.exists()

    def test_clear_credentials_nonexistent_file(self, auth):
        """Test clear_credentials returns False when file doesn't exist."""
        result = auth.clear_credentials(ACCOUNT_1)
        assert result is False

    def test_clear_credentials_invalid_account(self, auth):
        """Test clear_credentials with invalid account raises ValueError."""
        with pytest.raises(ValueError, match="Invalid account_id"):
            auth.clear_credentials("invalid")


class TestClearAllCredentials:
    """Tests for clear_all_credentials method."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        return GoogleAuth(config_dir=tmp_path)

    def test_clear_all_credentials_removes_both(self, auth, tmp_path):
        """Test clear_all_credentials removes both token files."""
        token1 = tmp_path / "token_account1.json"
        token2 = tmp_path / "token_account2.json"
        token1.write_text('{"token": "test1"}')
        token2.write_text('{"token": "test2"}')

        result = auth.clear_all_credentials()

        assert result == (True, True)
        assert not token1.exists()
        assert not token2.exists()

    def test_clear_all_credentials_partial(self, auth, tmp_path):
        """Test clear_all_credentials when only one file exists."""
        token1 = tmp_path / "token_account1.json"
        token1.write_text('{"token": "test1"}')

        result = auth.clear_all_credentials()

        assert result == (True, False)

    def test_clear_all_credentials_none_exist(self, auth):
        """Test clear_all_credentials when no files exist."""
        result = auth.clear_all_credentials()
        assert result == (False, False)


class TestGetAuthStatus:
    """Tests for get_auth_status method."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        return GoogleAuth(config_dir=tmp_path)

    def test_get_auth_status_no_credentials(self, auth, tmp_path):
        """Test get_auth_status with no credentials."""
        status = auth.get_auth_status()

        assert "account1" in status
        assert "account2" in status
        assert status["account1"]["authenticated"] is False
        assert status["account2"]["authenticated"] is False
        assert status["account1"]["token_exists"] is False
        assert status["account2"]["token_exists"] is False
        assert status["credentials_exist"] is False
        assert status["config_dir"] == str(tmp_path)

    def test_get_auth_status_with_credentials_file(self, auth, tmp_path):
        """Test get_auth_status when credentials.json exists."""
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text('{"installed": {}}')

        status = auth.get_auth_status()

        assert status["credentials_exist"] is True
        assert status["credentials_path"] == str(creds_file)

    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_get_auth_status_with_valid_token(self, mock_creds_class, auth, tmp_path):
        """Test get_auth_status with valid token file."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text('{"token": "test"}')

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        status = auth.get_auth_status()

        assert status["account1"]["authenticated"] is True
        assert status["account1"]["token_exists"] is True
        assert status["account1"]["credentials_valid"] is True


class TestGetAccountEmail:
    """Tests for get_account_email method."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        return GoogleAuth(config_dir=tmp_path)

    def test_get_account_email_no_token(self, auth):
        """Test get_account_email returns None when no token file."""
        result = auth.get_account_email(ACCOUNT_1)
        assert result is None

    def test_get_account_email_with_email(self, auth, tmp_path):
        """Test get_account_email returns email from token file."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text(
            json.dumps({"token": "test", "email": "test@example.com"})
        )

        result = auth.get_account_email(ACCOUNT_1)
        assert result == "test@example.com"

    def test_get_account_email_no_email_field(self, auth, tmp_path):
        """Test get_account_email returns None when no email in token."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text(json.dumps({"token": "test"}))

        result = auth.get_account_email(ACCOUNT_1)
        assert result is None

    def test_get_account_email_invalid_json(self, auth, tmp_path):
        """Test get_account_email returns None for invalid JSON."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text("invalid json")

        result = auth.get_account_email(ACCOUNT_1)
        assert result is None

    def test_get_account_email_invalid_account(self, auth):
        """Test get_account_email with invalid account raises ValueError."""
        with pytest.raises(ValueError, match="Invalid account_id"):
            auth.get_account_email("invalid")


class TestAuthenticationErrorException:
    """Tests for AuthenticationError exception."""

    def test_authentication_error_is_exception(self):
        """Test that AuthenticationError is an Exception."""
        assert issubclass(AuthenticationError, Exception)

    def test_authentication_error_message(self):
        """Test AuthenticationError with message."""
        error = AuthenticationError("Test error message")
        assert str(error) == "Test error message"


class TestModuleConstants:
    """Tests for module constants."""

    def test_scopes_includes_contacts(self):
        """Test that SCOPES includes contacts permission."""
        assert "https://www.googleapis.com/auth/contacts" in SCOPES

    def test_account_constants(self):
        """Test account ID constants."""
        assert ACCOUNT_1 == "account1"
        assert ACCOUNT_2 == "account2"

    def test_default_config_dir(self):
        """Test default config directory is in home."""
        assert Path.home() / ".gcontact-sync" == DEFAULT_CONFIG_DIR


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    @pytest.fixture
    def auth(self, tmp_path):
        """Create a GoogleAuth instance with temp config dir."""
        return GoogleAuth(config_dir=tmp_path)

    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_credentials_invalid_but_not_expired(
        self, mock_creds_class, auth, tmp_path
    ):
        """Test handling of invalid but not expired credentials."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text('{"token": "test"}')

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = False
        mock_creds.refresh_token = None
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        result = auth.get_credentials(ACCOUNT_1)
        assert result is None

    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_credentials_expired_no_refresh_token(
        self, mock_creds_class, auth, tmp_path
    ):
        """Test handling of expired credentials without refresh token."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text('{"token": "test"}')

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = None
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        result = auth.get_credentials(ACCOUNT_1)
        assert result is None

    def test_config_dir_with_special_characters(self, tmp_path):
        """Test config dir path with special characters."""
        special_dir = tmp_path / "config with spaces"
        auth = GoogleAuth(config_dir=special_dir)
        auth._ensure_config_dir()
        assert special_dir.exists()

    def test_multiple_auth_instances_same_config(self, tmp_path):
        """Test multiple GoogleAuth instances with same config dir."""
        auth1 = GoogleAuth(config_dir=tmp_path)
        auth2 = GoogleAuth(config_dir=tmp_path)

        # Create token via auth1
        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "shared"}'
        auth1._save_credentials(ACCOUNT_1, mock_creds)

        # Should be visible to auth2
        token_path = auth2._get_token_path(ACCOUNT_1)
        assert token_path.exists()

    def test_path_as_string(self, tmp_path):
        """Test that string paths are converted to Path objects."""
        auth = GoogleAuth(config_dir=str(tmp_path))
        assert isinstance(auth.config_dir, Path)

    @patch("gcontact_sync.auth.google_auth.Request")
    @patch("gcontact_sync.auth.google_auth.Credentials")
    def test_refresh_saves_updated_credentials(
        self, mock_creds_class, mock_request, auth, tmp_path
    ):
        """Test that refreshed credentials are saved."""
        token_path = tmp_path / "token_account1.json"
        token_path.write_text('{"token": "old"}')

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh"
        mock_creds.to_json.return_value = '{"token": "refreshed"}'
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        auth.get_credentials(ACCOUNT_1)

        # Verify credentials were saved after refresh
        saved_content = token_path.read_text()
        assert saved_content == '{"token": "refreshed"}'
