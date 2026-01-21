"""
OAuth2 authentication module for Google Contacts synchronization.

Provides OAuth 2.0 authentication with support for:
- Dual account authentication (two separate Google accounts)
- Automatic token refresh
- Secure credential storage in user's home directory
- Graceful handling of expired tokens
"""

import json
import logging
import os
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# OAuth2 scopes required for Google Contacts access
SCOPES = [
    "https://www.googleapis.com/auth/contacts",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",  # Required by Google when requesting userinfo.email
]

# Default configuration directory
DEFAULT_CONFIG_DIR = Path.home() / ".gcontact-sync"

# Account identifiers
ACCOUNT_1 = "account1"
ACCOUNT_2 = "account2"

# Default auth timeout for network requests (in seconds)
DEFAULT_AUTH_TIMEOUT = 10

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails or credentials are invalid."""

    pass


class GoogleAuth:
    """
    OAuth2 authentication manager for dual Google account support.

    Handles credential loading, token refresh, and OAuth flow for
    two separate Google accounts.

    Attributes:
        config_dir: Directory for storing credentials and tokens
        credentials_path: Path to OAuth client credentials file

    Usage:
        auth = GoogleAuth()

        # Authenticate first account
        creds1 = auth.authenticate('account1')

        # Authenticate second account
        creds2 = auth.authenticate('account2')

        # Get credentials if already authenticated
        creds = auth.get_credentials('account1')
    """

    def __init__(
        self,
        config_dir: Path | None = None,
        auth_timeout: int = DEFAULT_AUTH_TIMEOUT,
    ):
        """
        Initialize the authentication manager.

        Args:
            config_dir: Directory for storing credentials and tokens.
                       Defaults to ~/.gcontact-sync/ or $GCONTACT_SYNC_CONFIG_DIR
            auth_timeout: Timeout in seconds for network requests (default: 10)
        """
        # Use environment variable if set, otherwise default
        if config_dir is not None:
            self.config_dir = Path(config_dir)
        else:
            env_dir = os.environ.get("GCONTACT_SYNC_CONFIG_DIR")
            if env_dir:
                self.config_dir = Path(env_dir)
            else:
                self.config_dir = DEFAULT_CONFIG_DIR

        self.credentials_path = self.config_dir / "credentials.json"
        self.auth_timeout = auth_timeout

    def _get_token_path(self, account_id: str) -> Path:
        """
        Get the token file path for an account.

        Args:
            account_id: Account identifier ('account1' or 'account2')

        Returns:
            Path to the token file for the specified account
        """
        self._validate_account_id(account_id)
        return self.config_dir / f"token_{account_id}.json"

    def _validate_account_id(self, account_id: str) -> None:
        """
        Validate account identifier.

        Args:
            account_id: Account identifier to validate

        Raises:
            ValueError: If account_id is not valid
        """
        valid_accounts = (ACCOUNT_1, ACCOUNT_2)
        if account_id not in valid_accounts:
            raise ValueError(
                f"Invalid account_id '{account_id}'. "
                f"Must be one of: {', '.join(valid_accounts)}"
            )

    def _ensure_config_dir(self) -> None:
        """
        Ensure the configuration directory exists.

        Creates the directory with secure permissions (700) if it doesn't exist.
        """
        if not self.config_dir.exists():
            self.config_dir.mkdir(parents=True, mode=0o700)
            logger.debug(f"Created config directory: {self.config_dir}")

    def _load_credentials(self, account_id: str) -> Credentials | None:
        """
        Load credentials from token file if it exists.

        Args:
            account_id: Account identifier

        Returns:
            Credentials object if token file exists and is valid, None otherwise
        """
        token_path = self._get_token_path(account_id)

        if not token_path.exists():
            logger.debug(f"No token file found for {account_id}")
            return None

        try:
            creds: Credentials = Credentials.from_authorized_user_file(
                str(token_path), SCOPES
            )
            logger.debug(f"Loaded credentials for {account_id}")
            return creds
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Invalid token file for {account_id}: {e}")
            return None

    def _save_credentials(
        self, account_id: str, creds: Credentials, email: str | None = None
    ) -> None:
        """
        Save credentials to token file.

        Args:
            account_id: Account identifier
            creds: Credentials object to save
            email: Optional email address to store with credentials
        """
        self._ensure_config_dir()
        token_path = self._get_token_path(account_id)

        # Parse credentials JSON and add email if provided
        token_data = json.loads(creds.to_json())
        if email:
            token_data["email"] = email

        # Write with secure permissions
        token_path.write_text(json.dumps(token_data))
        token_path.chmod(0o600)
        logger.debug(f"Saved credentials for {account_id}")

    def _refresh_credentials(self, creds: Credentials) -> bool:
        """
        Attempt to refresh expired credentials.

        Args:
            creds: Credentials object to refresh

        Returns:
            True if refresh succeeded, False otherwise
        """
        if not creds.refresh_token:
            logger.debug("No refresh token available")
            return False

        try:
            creds.refresh(Request())
            logger.debug("Successfully refreshed credentials")
            return True
        except RefreshError as e:
            logger.warning(f"Failed to refresh credentials: {e}")
            return False

    def _fetch_user_email(self, creds: Credentials) -> str | None:
        """
        Fetch the authenticated user's email address from Google.

        Args:
            creds: Valid credentials with userinfo.email scope

        Returns:
            Email address if available, None otherwise
        """
        import urllib.request
        from urllib.error import HTTPError

        try:
            url = "https://www.googleapis.com/oauth2/v2/userinfo"
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {creds.token}")

            with urllib.request.urlopen(req, timeout=self.auth_timeout) as response:  # nosec B310
                data: dict[str, str] = json.loads(response.read().decode("utf-8"))
                return data.get("email")
        except HTTPError as e:
            if e.code == 401:
                # Token doesn't have email scope - need re-auth with new scopes
                logger.debug(
                    "Token missing email scope. Re-authentication required "
                    "to display email addresses."
                )
            else:
                logger.debug(f"Failed to fetch user email: {e}")
            return None
        except Exception as e:
            logger.debug(f"Failed to fetch user email: {e}")
            return None

    def get_credentials(self, account_id: str) -> Credentials | None:
        """
        Get valid credentials for an account if available.

        Attempts to load and refresh credentials without user interaction.
        Returns None if credentials are not available or cannot be refreshed.

        Args:
            account_id: Account identifier ('account1' or 'account2')

        Returns:
            Valid Credentials object, or None if not available

        Raises:
            ValueError: If account_id is invalid
        """
        self._validate_account_id(account_id)

        creds = self._load_credentials(account_id)

        if creds is None:
            return None

        # Check if credentials are valid
        if creds.valid:
            return creds

        # Try to refresh if expired
        if creds.expired and creds.refresh_token and self._refresh_credentials(creds):
            self._save_credentials(account_id, creds)
            return creds

        return None

    def authenticate(self, account_id: str, force_reauth: bool = False) -> Credentials:
        """
        Authenticate a Google account.

        If valid credentials exist and force_reauth is False, returns existing
        credentials. Otherwise, initiates OAuth flow to obtain new credentials.

        Args:
            account_id: Account identifier ('account1' or 'account2')
            force_reauth: If True, ignore existing credentials and re-authenticate

        Returns:
            Valid Credentials object

        Raises:
            ValueError: If account_id is invalid
            AuthenticationError: If authentication fails
            FileNotFoundError: If credentials.json is not found
        """
        self._validate_account_id(account_id)

        # Check for existing valid credentials
        if not force_reauth:
            creds = self.get_credentials(account_id)
            if creds is not None:
                logger.info(f"Using existing credentials for {account_id}")
                return creds

        # Need to authenticate
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"OAuth credentials file not found: {self.credentials_path}\n"
                "Please download your OAuth client credentials from "
                "Google Cloud Console and save them to this location."
            )

        logger.info(f"Starting OAuth flow for {account_id}")

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.credentials_path), SCOPES
            )
            new_creds: Credentials = flow.run_local_server(port=0)

            # Fetch user email to store with credentials
            email = self._fetch_user_email(new_creds)

            self._save_credentials(account_id, new_creds, email=email)
            logger.info(f"Successfully authenticated {account_id}")

            return new_creds

        except Exception as e:
            logger.error(f"Authentication failed for {account_id}: {e}")
            raise AuthenticationError(
                f"Failed to authenticate {account_id}: {e}"
            ) from e

    def is_authenticated(self, account_id: str) -> bool:
        """
        Check if an account is authenticated with valid credentials.

        Args:
            account_id: Account identifier ('account1' or 'account2')

        Returns:
            True if valid credentials exist, False otherwise

        Raises:
            ValueError: If account_id is invalid
        """
        return self.get_credentials(account_id) is not None

    def get_both_credentials(
        self,
    ) -> tuple[Credentials | None, Credentials | None]:
        """
        Get credentials for both accounts.

        Returns:
            Tuple of (account1_credentials, account2_credentials)
            Either or both may be None if not authenticated
        """
        creds1 = self.get_credentials(ACCOUNT_1)
        creds2 = self.get_credentials(ACCOUNT_2)
        return (creds1, creds2)

    def authenticate_both(
        self, force_reauth: bool = False
    ) -> tuple[Credentials, Credentials]:
        """
        Authenticate both accounts.

        Args:
            force_reauth: If True, ignore existing credentials and re-authenticate

        Returns:
            Tuple of (account1_credentials, account2_credentials)

        Raises:
            AuthenticationError: If authentication fails for either account
            FileNotFoundError: If credentials.json is not found
        """
        creds1 = self.authenticate(ACCOUNT_1, force_reauth=force_reauth)
        creds2 = self.authenticate(ACCOUNT_2, force_reauth=force_reauth)
        return (creds1, creds2)

    def clear_credentials(self, account_id: str) -> bool:
        """
        Remove stored credentials for an account.

        Args:
            account_id: Account identifier ('account1' or 'account2')

        Returns:
            True if credentials were removed, False if they didn't exist

        Raises:
            ValueError: If account_id is invalid
        """
        self._validate_account_id(account_id)
        token_path = self._get_token_path(account_id)

        if token_path.exists():
            token_path.unlink()
            logger.info(f"Cleared credentials for {account_id}")
            return True

        return False

    def clear_all_credentials(self) -> tuple[bool, bool]:
        """
        Remove stored credentials for both accounts.

        Returns:
            Tuple of (account1_cleared, account2_cleared) indicating
            whether each account's credentials were removed
        """
        cleared1 = self.clear_credentials(ACCOUNT_1)
        cleared2 = self.clear_credentials(ACCOUNT_2)
        return (cleared1, cleared2)

    def get_auth_status(self) -> dict[str, object]:
        """
        Get authentication status for both accounts.

        Returns:
            Dictionary with status information for each account:
            {
                'account1': {
                    'authenticated': bool,
                    'token_path': str,
                    'token_exists': bool
                },
                'account2': {...}
            }
        """
        status: dict[str, object] = {}

        for account_id in (ACCOUNT_1, ACCOUNT_2):
            token_path = self._get_token_path(account_id)
            creds = self.get_credentials(account_id)

            status[account_id] = {
                "authenticated": creds is not None,
                "token_path": str(token_path),
                "token_exists": token_path.exists(),
                "credentials_valid": creds is not None and creds.valid
                if creds
                else False,
            }

        status["credentials_path"] = str(self.credentials_path)
        status["credentials_exist"] = self.credentials_path.exists()
        status["config_dir"] = str(self.config_dir)

        return status

    def get_account_email(self, account_id: str) -> str | None:
        """
        Get the email address associated with an authenticated account.

        First checks if email is stored in the token file. If not, attempts
        to fetch it from Google's userinfo API and stores it for future use.

        Args:
            account_id: Account identifier

        Returns:
            Email address if available, None otherwise
        """
        self._validate_account_id(account_id)
        token_path = self._get_token_path(account_id)

        if not token_path.exists():
            return None

        try:
            token_data: dict[str, str] = json.loads(token_path.read_text())
            email: str | None = token_data.get("email")

            # If email not stored, try to fetch it and update the token file
            if not email:
                creds = self.get_credentials(account_id)
                if creds:
                    email = self._fetch_user_email(creds)
                    if email:
                        # Update stored token with email
                        token_data["email"] = email
                        token_path.write_text(json.dumps(token_data))
                        logger.debug(f"Updated stored email for {account_id}")

            return email
        except (json.JSONDecodeError, OSError):
            return None
