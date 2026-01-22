"""
Tests for the CLI module.

Tests the command-line interface using Click's testing utilities.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from gcontact_sync.cli import (
    DEFAULT_CONFIG_DIR,
    VALID_ACCOUNTS,
    cli,
    get_config_dir,
    validate_account,
)


class TestHelperFunctions:
    """Tests for CLI helper functions."""

    def test_valid_accounts_contains_expected_values(self):
        """Test that VALID_ACCOUNTS contains account1 and account2."""
        assert "account1" in VALID_ACCOUNTS
        assert "account2" in VALID_ACCOUNTS
        assert len(VALID_ACCOUNTS) == 2

    def test_default_config_dir_is_in_home(self):
        """Test that DEFAULT_CONFIG_DIR is in user's home directory."""
        assert Path.home() / ".gcontact-sync" == DEFAULT_CONFIG_DIR

    def test_validate_account_with_valid_account1(self):
        """Test validate_account with account1."""
        result = validate_account(None, None, "account1")
        assert result == "account1"

    def test_validate_account_with_valid_account2(self):
        """Test validate_account with account2."""
        result = validate_account(None, None, "account2")
        assert result == "account2"

    def test_validate_account_with_none_returns_none(self):
        """Test validate_account with None returns None."""
        result = validate_account(None, None, None)
        assert result is None

    def test_validate_account_with_invalid_raises_error(self):
        """Test validate_account with invalid account raises BadParameter."""
        import click

        with pytest.raises(click.BadParameter, match="Invalid account"):
            validate_account(None, None, "invalid")

    def test_get_config_dir_with_custom_path(self):
        """Test get_config_dir returns custom path when provided."""
        result = get_config_dir("/custom/path")
        assert result == Path("/custom/path")

    def test_get_config_dir_with_none_returns_default(self):
        """Test get_config_dir returns DEFAULT_CONFIG_DIR when None."""
        result = get_config_dir(None)
        assert result == DEFAULT_CONFIG_DIR


class TestCliGroup:
    """Tests for the main CLI group."""

    def test_cli_help(self):
        """Test that CLI shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Bidirectional Google Contacts Sync" in result.output

    def test_cli_version(self):
        """Test that CLI shows version."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "gcontact-sync" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    def test_cli_verbose_flag(self, mock_setup_logging):
        """Test that --verbose flag is passed to context."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--verbose", "--help"])
        assert result.exit_code == 0

    @patch("gcontact_sync.cli.setup_logging")
    def test_cli_config_dir_option(self, mock_setup_logging):
        """Test that --config-dir option is handled."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            os.makedirs("custom-config", exist_ok=True)
            result = runner.invoke(cli, ["--config-dir", "custom-config", "--help"])
            assert result.exit_code == 0


class TestAuthCommand:
    """Tests for the auth command."""

    def test_auth_help(self):
        """Test that auth command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "--help"])
        assert result.exit_code == 0
        assert "Authenticate a Google account" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_auth_already_authenticated(self, mock_setup_logging, mock_auth_class):
        """Test auth when already authenticated without --force."""
        mock_auth = MagicMock()
        mock_auth.is_authenticated.return_value = True
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["auth", "--account", "account1"])
            assert result.exit_code == 0
            assert "already authenticated" in result.output
            mock_auth.authenticate.assert_not_called()

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_auth_force_reauth(self, mock_setup_logging, mock_auth_class):
        """Test auth with --force flag forces re-authentication."""
        mock_auth = MagicMock()
        mock_auth.is_authenticated.return_value = True
        mock_auth.get_account_email.return_value = "test@example.com"
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["auth", "--account", "account1", "--force"])
            assert result.exit_code == 0
            mock_auth.authenticate.assert_called_once_with(
                "account1", force_reauth=True
            )
            assert "Successfully authenticated" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_auth_new_authentication(self, mock_setup_logging, mock_auth_class):
        """Test auth for new authentication."""
        mock_auth = MagicMock()
        mock_auth.is_authenticated.return_value = False
        mock_auth.get_account_email.return_value = "test@example.com"
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["auth", "--account", "account1"])
            assert result.exit_code == 0
            mock_auth.authenticate.assert_called_once()
            assert "Successfully authenticated" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_auth_no_email_available(self, mock_setup_logging, mock_auth_class):
        """Test auth when email cannot be retrieved."""
        mock_auth = MagicMock()
        mock_auth.is_authenticated.return_value = False
        mock_auth.get_account_email.return_value = None
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["auth", "--account", "account1"])
            assert result.exit_code == 0
            assert "Successfully authenticated account1" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_auth_credentials_not_found(self, mock_setup_logging, mock_auth_class):
        """Test auth when credentials.json is not found."""
        mock_auth_class.side_effect = FileNotFoundError("credentials.json not found")

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["auth", "--account", "account1"])
            assert result.exit_code == 1
            assert "Error:" in result.output
            assert "credentials.json" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_auth_authentication_error(self, mock_setup_logging, mock_auth_class):
        """Test auth when authentication fails."""
        from gcontact_sync.auth.google_auth import AuthenticationError

        mock_auth = MagicMock()
        mock_auth.is_authenticated.return_value = False
        mock_auth.authenticate.side_effect = AuthenticationError("Auth failed")
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["auth", "--account", "account1"])
            assert result.exit_code == 1
            assert "Authentication failed" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_auth_unexpected_error(self, mock_setup_logging, mock_auth_class):
        """Test auth when unexpected error occurs."""
        mock_auth = MagicMock()
        mock_auth.is_authenticated.return_value = False
        mock_auth.authenticate.side_effect = RuntimeError("Unexpected")
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["auth", "--account", "account1"])
            assert result.exit_code == 1
            assert "Error:" in result.output


class TestStatusCommand:
    """Tests for the status command."""

    def test_status_help(self):
        """Test that status command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0
        assert "Show authentication and sync status" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_status_both_authenticated(self, mock_setup_logging, mock_auth_class):
        """Test status when both accounts are authenticated."""
        mock_auth = MagicMock()
        mock_auth.get_auth_status.return_value = {
            "config_dir": "/test/config",
            "credentials_exist": True,
            "account1": {"authenticated": True, "token_exists": True},
            "account2": {"authenticated": True, "token_exists": True},
        }
        mock_auth.is_authenticated.return_value = True
        mock_auth.get_account_email.side_effect = lambda acc: f"{acc}@test.com"
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "Google Contacts Sync Status" in result.output
            assert "Authenticated" in result.output
            assert "Ready to sync" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_status_not_authenticated(self, mock_setup_logging, mock_auth_class):
        """Test status when accounts are not authenticated."""
        mock_auth = MagicMock()
        mock_auth.get_auth_status.return_value = {
            "config_dir": "/test/config",
            "credentials_exist": True,
            "credentials_path": "/test/config/credentials.json",
            "account1": {"authenticated": False, "token_exists": False},
            "account2": {"authenticated": False, "token_exists": False},
        }
        mock_auth.is_authenticated.return_value = False
        mock_auth.get_account_email.return_value = None
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "Not authenticated" in result.output
            assert "Authentication required" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_status_no_credentials(self, mock_setup_logging, mock_auth_class):
        """Test status when credentials.json doesn't exist."""
        mock_auth = MagicMock()
        mock_auth.get_auth_status.return_value = {
            "config_dir": "/test/config",
            "credentials_exist": False,
            "credentials_path": "/test/config/credentials.json",
            "account1": {"authenticated": False, "token_exists": False},
            "account2": {"authenticated": False, "token_exists": False},
        }
        mock_auth.is_authenticated.return_value = False
        mock_auth.get_account_email.return_value = None
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "Not found" in result.output
            assert "Setup required" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_status_with_sync_database(self, mock_setup_logging, mock_auth_class):
        """Test status with existing sync database."""
        mock_auth = MagicMock()
        mock_auth.get_auth_status.return_value = {
            "config_dir": str(Path.cwd()),
            "credentials_exist": True,
            "account1": {"authenticated": True, "token_exists": True},
            "account2": {"authenticated": True, "token_exists": True},
        }
        mock_auth.is_authenticated.return_value = True
        mock_auth.get_account_email.return_value = "test@test.com"
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create a sync database
            from gcontact_sync.storage.db import SyncDatabase

            db = SyncDatabase("sync.db")
            db.initialize()
            db.upsert_contact_mapping("test_key")

            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "Sync Status" in result.output
            assert "Contact mappings:" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_status_error_handling(self, mock_setup_logging, mock_auth_class):
        """Test status handles errors gracefully."""
        mock_auth_class.side_effect = RuntimeError("Config error")

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 1
            assert "Error:" in result.output


class TestSyncCommand:
    """Tests for the sync command."""

    def test_sync_help(self):
        """Test that sync command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["sync", "--help"])
        assert result.exit_code == 0
        assert "Synchronize contacts and groups between accounts" in result.output

    @patch("gcontact_sync.sync.engine.SyncEngine")
    @patch("gcontact_sync.storage.db.SyncDatabase")
    @patch("gcontact_sync.api.people_api.PeopleAPI")
    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_sync_account1_not_authenticated(
        self,
        mock_setup_logging,
        mock_auth_class,
        mock_api_class,
        mock_db_class,
        mock_engine_class,
    ):
        """Test sync fails when account1 is not authenticated."""
        mock_auth = MagicMock()
        mock_auth.get_credentials.side_effect = lambda acc: (
            None if acc == "account1" else MagicMock()
        )
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["sync"])
            assert result.exit_code == 1
            assert "account1 is not authenticated" in result.output

    @patch("gcontact_sync.sync.engine.SyncEngine")
    @patch("gcontact_sync.storage.db.SyncDatabase")
    @patch("gcontact_sync.api.people_api.PeopleAPI")
    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_sync_account2_not_authenticated(
        self,
        mock_setup_logging,
        mock_auth_class,
        mock_api_class,
        mock_db_class,
        mock_engine_class,
    ):
        """Test sync fails when account2 is not authenticated."""
        mock_auth = MagicMock()
        mock_auth.get_credentials.side_effect = lambda acc: (
            MagicMock() if acc == "account1" else None
        )
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["sync"])
            assert result.exit_code == 1
            assert "account2 is not authenticated" in result.output

    @patch("gcontact_sync.cli.ConfigLoader")
    @patch("gcontact_sync.sync.engine.SyncEngine")
    @patch("gcontact_sync.storage.db.SyncDatabase")
    @patch("gcontact_sync.api.people_api.PeopleAPI")
    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_sync_dry_run(
        self,
        mock_setup_logging,
        mock_auth_class,
        mock_api_class,
        mock_db_class,
        mock_engine_class,
        mock_config_loader,
    ):
        """Test sync with --dry-run flag."""
        # Mock ConfigLoader to return empty config
        mock_loader = MagicMock()
        mock_loader.load_from_file.return_value = {}
        mock_config_loader.return_value = mock_loader

        mock_auth = MagicMock()
        mock_auth.get_credentials.return_value = MagicMock()
        mock_auth.get_account_email.return_value = "test@test.com"
        mock_auth_class.return_value = mock_auth

        mock_result = MagicMock()
        mock_result.has_changes.return_value = True
        mock_result.summary.return_value = "Test summary"
        mock_result.conflicts = []
        mock_result.matched_contacts = []
        mock_result.to_create_in_account1 = []
        mock_result.to_create_in_account2 = []

        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_class.return_value = mock_engine

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["sync", "--dry-run"])
            assert result.exit_code == 0
            assert "Dry run complete" in result.output
            # Verify sync was called with dry_run=True
            mock_engine.sync.assert_called_once()
            call_kwargs = mock_engine.sync.call_args.kwargs
            assert call_kwargs["dry_run"] is True
            assert call_kwargs["full_sync"] is False
            assert "backup_enabled" in call_kwargs
            assert "backup_dir" in call_kwargs

    @patch("gcontact_sync.cli.ConfigLoader")
    @patch("gcontact_sync.sync.engine.SyncEngine")
    @patch("gcontact_sync.storage.db.SyncDatabase")
    @patch("gcontact_sync.api.people_api.PeopleAPI")
    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_sync_full_sync(
        self,
        mock_setup_logging,
        mock_auth_class,
        mock_api_class,
        mock_db_class,
        mock_engine_class,
        mock_config_loader,
    ):
        """Test sync with --full flag."""
        # Mock ConfigLoader to return empty config
        mock_loader = MagicMock()
        mock_loader.load_from_file.return_value = {}
        mock_config_loader.return_value = mock_loader

        mock_auth = MagicMock()
        mock_auth.get_credentials.return_value = MagicMock()
        mock_auth.get_account_email.return_value = "test@test.com"
        mock_auth_class.return_value = mock_auth

        mock_result = MagicMock()
        mock_result.has_changes.return_value = False
        mock_result.summary.return_value = "Test summary"
        mock_result.conflicts = []
        mock_result.matched_contacts = []
        mock_result.to_create_in_account1 = []
        mock_result.to_create_in_account2 = []

        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_class.return_value = mock_engine

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["sync", "--full"])
            assert result.exit_code == 0
            # Verify sync was called with full_sync=True
            mock_engine.sync.assert_called_once()
            call_kwargs = mock_engine.sync.call_args.kwargs
            assert call_kwargs["dry_run"] is False
            assert call_kwargs["full_sync"] is True
            assert "backup_enabled" in call_kwargs
            assert "backup_dir" in call_kwargs

    @patch("gcontact_sync.cli.ConfigLoader")
    @patch("gcontact_sync.sync.engine.SyncEngine")
    @patch("gcontact_sync.storage.db.SyncDatabase")
    @patch("gcontact_sync.api.people_api.PeopleAPI")
    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_sync_with_errors(
        self,
        mock_setup_logging,
        mock_auth_class,
        mock_api_class,
        mock_db_class,
        mock_engine_class,
        mock_config_loader,
    ):
        """Test sync shows warning when there are errors."""
        # Mock ConfigLoader to return empty config
        mock_loader = MagicMock()
        mock_loader.load_from_file.return_value = {}
        mock_config_loader.return_value = mock_loader

        mock_auth = MagicMock()
        mock_auth.get_credentials.return_value = MagicMock()
        mock_auth.get_account_email.return_value = "test@test.com"
        mock_auth_class.return_value = mock_auth

        mock_result = MagicMock()
        mock_result.has_changes.return_value = True
        mock_result.summary.return_value = "Test summary"
        mock_result.conflicts = []
        mock_result.matched_contacts = []
        mock_result.to_create_in_account1 = []
        mock_result.to_create_in_account2 = []
        mock_result.stats.created_in_account1 = 1
        mock_result.stats.created_in_account2 = 1
        mock_result.stats.updated_in_account1 = 0
        mock_result.stats.updated_in_account2 = 0
        mock_result.stats.deleted_in_account1 = 0
        mock_result.stats.deleted_in_account2 = 0
        mock_result.stats.errors = 2

        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_class.return_value = mock_engine

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["sync"])
            assert result.exit_code == 0
            assert "2 errors occurred" in result.output

    @patch("gcontact_sync.sync.engine.SyncEngine")
    @patch("gcontact_sync.storage.db.SyncDatabase")
    @patch("gcontact_sync.api.people_api.PeopleAPI")
    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_sync_exception(
        self,
        mock_setup_logging,
        mock_auth_class,
        mock_api_class,
        mock_db_class,
        mock_engine_class,
    ):
        """Test sync handles exceptions gracefully."""
        mock_auth = MagicMock()
        mock_auth.get_credentials.return_value = MagicMock()
        mock_auth.get_account_email.return_value = "test@test.com"
        mock_auth_class.return_value = mock_auth

        mock_engine = MagicMock()
        mock_engine.sync.side_effect = RuntimeError("Sync error")
        mock_engine_class.return_value = mock_engine

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["sync"])
            assert result.exit_code == 1
            assert "Sync failed" in result.output

    @patch("gcontact_sync.cli.ConfigLoader")
    @patch("gcontact_sync.sync.engine.SyncEngine")
    @patch("gcontact_sync.storage.db.SyncDatabase")
    @patch("gcontact_sync.api.people_api.PeopleAPI")
    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_sync_strategy_account1(
        self,
        mock_setup_logging,
        mock_auth_class,
        mock_api_class,
        mock_db_class,
        mock_engine_class,
        mock_config_loader,
    ):
        """Test sync with --strategy account1."""
        from gcontact_sync.sync.conflict import ConflictStrategy

        # Mock ConfigLoader to return empty config
        mock_loader = MagicMock()
        mock_loader.load_from_file.return_value = {}
        mock_config_loader.return_value = mock_loader

        mock_auth = MagicMock()
        mock_auth.get_credentials.return_value = MagicMock()
        mock_auth.get_account_email.return_value = "test@test.com"
        mock_auth_class.return_value = mock_auth

        mock_result = MagicMock()
        mock_result.has_changes.return_value = False
        mock_result.summary.return_value = "Test summary"
        mock_result.conflicts = []
        mock_result.matched_contacts = []
        mock_result.to_create_in_account1 = []
        mock_result.to_create_in_account2 = []

        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_class.return_value = mock_engine

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["sync", "--strategy", "account1"])
            assert result.exit_code == 0
            # Verify engine was created with correct strategy
            mock_engine_class.assert_called_once()
            call_kwargs = mock_engine_class.call_args.kwargs
            assert call_kwargs["conflict_strategy"] == ConflictStrategy.ACCOUNT1_WINS


class TestResetCommand:
    """Tests for the reset command."""

    def test_reset_help(self):
        """Test that reset command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["reset", "--help"])
        assert result.exit_code == 0
        assert "Reset sync state" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    def test_reset_no_database(self, mock_setup_logging):
        """Test reset when no database exists."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create a config directory within isolated filesystem (no sync.db)
            os.makedirs("config", exist_ok=True)
            result = runner.invoke(cli, ["--config-dir", "config", "reset", "--yes"])
            assert result.exit_code == 0
            assert "No sync database found" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    def test_reset_with_confirmation(self, mock_setup_logging):
        """Test reset with confirmation prompt."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create a database
            from gcontact_sync.storage.db import SyncDatabase

            db = SyncDatabase("sync.db")
            db.initialize()
            db.upsert_contact_mapping("test")

            # Confirm the reset
            result = runner.invoke(cli, ["reset"], input="y\n")
            assert result.exit_code == 0
            assert "Sync state has been reset" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    def test_reset_cancelled(self, mock_setup_logging):
        """Test reset when user cancels."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create a database
            from gcontact_sync.storage.db import SyncDatabase

            db = SyncDatabase("sync.db")
            db.initialize()

            # Cancel the reset
            result = runner.invoke(cli, ["reset"], input="n\n")
            assert result.exit_code == 1  # Aborted

    @patch("gcontact_sync.cli.setup_logging")
    def test_reset_with_yes_flag(self, mock_setup_logging):
        """Test reset with --yes flag skips confirmation."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create a database
            from gcontact_sync.storage.db import SyncDatabase

            db = SyncDatabase("sync.db")
            db.initialize()
            db.upsert_contact_mapping("test")

            result = runner.invoke(cli, ["reset", "--yes"])
            assert result.exit_code == 0
            assert "Sync state has been reset" in result.output


class TestClearAuthCommand:
    """Tests for the clear-auth command."""

    def test_clear_auth_help(self):
        """Test that clear-auth command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["clear-auth", "--help"])
        assert result.exit_code == 0
        assert "Clear stored authentication credentials" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_clear_auth_specific_account(self, mock_setup_logging, mock_auth_class):
        """Test clear-auth for specific account."""
        mock_auth = MagicMock()
        mock_auth.clear_credentials.return_value = True
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli, ["clear-auth", "--account", "account1", "--yes"]
            )
            assert result.exit_code == 0
            mock_auth.clear_credentials.assert_called_once_with("account1")
            assert "Cleared credentials for account1" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_clear_auth_both_accounts(self, mock_setup_logging, mock_auth_class):
        """Test clear-auth for both accounts."""
        mock_auth = MagicMock()
        mock_auth.clear_credentials.return_value = True
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["clear-auth", "--yes"])
            assert result.exit_code == 0
            assert mock_auth.clear_credentials.call_count == 2
            assert "Credentials cleared" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_clear_auth_no_credentials_found(self, mock_setup_logging, mock_auth_class):
        """Test clear-auth when no credentials exist."""
        mock_auth = MagicMock()
        mock_auth.clear_credentials.return_value = False
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli, ["clear-auth", "--account", "account1", "--yes"]
            )
            assert result.exit_code == 0
            assert "No credentials found for account1" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_clear_auth_with_confirmation(self, mock_setup_logging, mock_auth_class):
        """Test clear-auth with confirmation prompt."""
        mock_auth = MagicMock()
        mock_auth.clear_credentials.return_value = True
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli, ["clear-auth", "--account", "account1"], input="y\n"
            )
            assert result.exit_code == 0
            assert "Cleared credentials" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    def test_clear_auth_error(self, mock_setup_logging, mock_auth_class):
        """Test clear-auth handles errors gracefully."""
        mock_auth = MagicMock()
        mock_auth.clear_credentials.side_effect = RuntimeError("Error")
        mock_auth_class.return_value = mock_auth

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli, ["clear-auth", "--account", "account1", "--yes"]
            )
            assert result.exit_code == 1
            assert "Error:" in result.output


class TestHealthCommand:
    """Tests for the health command."""

    def test_health(self):
        """Test that health command returns healthy status."""
        runner = CliRunner()
        result = runner.invoke(cli, ["health"])
        assert result.exit_code == 0
        assert "healthy" in result.output

    def test_health_help(self):
        """Test that health command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["health", "--help"])
        assert result.exit_code == 0
        assert "health" in result.output.lower()


class TestRestoreCommand:
    """Tests for the restore command."""

    def test_restore_help(self):
        """Test that restore command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["restore", "--help"])
        assert result.exit_code == 0
        assert "Restore contacts from a backup file" in result.output

    @patch("gcontact_sync.backup.manager.BackupManager")
    @patch("gcontact_sync.cli.setup_logging")
    def test_restore_list_no_backups(self, mock_setup_logging, mock_backup_manager):
        """Test restore --list when no backups exist."""
        mock_bm = MagicMock()
        mock_bm.list_backups.return_value = []
        mock_backup_manager.return_value = mock_bm

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["restore", "--list"])
            assert result.exit_code == 0
            assert "No backups found" in result.output

    @patch("gcontact_sync.backup.manager.BackupManager")
    @patch("gcontact_sync.cli.setup_logging")
    def test_restore_list_with_backups(self, mock_setup_logging, mock_backup_manager):
        """Test restore --list displays available backups."""
        from datetime import datetime

        mock_bm = MagicMock()

        # Create mock backup paths
        backup1 = MagicMock()
        backup1.name = "backup_20240120_103000.json"
        backup1.stat.return_value.st_size = 10240
        backup1.stat.return_value.st_mtime = datetime(2024, 1, 20, 10, 30).timestamp()

        backup2 = MagicMock()
        backup2.name = "backup_20240121_120000.json"
        backup2.stat.return_value.st_size = 20480
        backup2.stat.return_value.st_mtime = datetime(2024, 1, 21, 12, 0).timestamp()

        mock_bm.list_backups.return_value = [backup1, backup2]
        mock_bm.load_backup.side_effect = [
            {"timestamp": "2024-01-20T10:30:00"},
            {"timestamp": "2024-01-21T12:00:00"},
        ]
        mock_backup_manager.return_value = mock_bm

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["restore", "--list"])
            assert result.exit_code == 0
            assert "Available backups" in result.output
            assert "backup_20240120_103000.json" in result.output
            assert "backup_20240121_120000.json" in result.output
            assert "Total: 2 backup(s)" in result.output

    @patch("gcontact_sync.backup.manager.BackupManager")
    @patch("gcontact_sync.cli.setup_logging")
    def test_restore_no_backup_file_shows_list(
        self, mock_setup_logging, mock_backup_manager
    ):
        """Test restore without --backup-file shows list of backups."""
        mock_bm = MagicMock()
        mock_bm.list_backups.return_value = []
        mock_backup_manager.return_value = mock_bm

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["restore"])
            assert result.exit_code == 0
            assert "No backups found" in result.output

    @patch("gcontact_sync.backup.manager.BackupManager")
    @patch("gcontact_sync.cli.setup_logging")
    def test_restore_dry_run(self, mock_setup_logging, mock_backup_manager):
        """Test restore with --dry-run flag."""
        from gcontact_sync.sync.contact import Contact
        from gcontact_sync.sync.group import ContactGroup

        mock_bm = MagicMock()
        # Use v2.0 format with accounts structure
        mock_bm.load_backup.return_value = {
            "version": "2.0",
            "timestamp": "2024-01-20T10:30:00",
            "accounts": {
                "account1": {
                    "email": "user1@example.com",
                    "contacts": [
                        {"display_name": "John Doe", "emails": ["john@example.com"]},
                        {"display_name": "Jane Smith", "emails": ["jane@example.com"]},
                    ],
                    "groups": [{"name": "Friends", "group_type": "USER_CONTACT_GROUP"}],
                },
                "account2": {
                    "email": "user2@example.com",
                    "contacts": [],
                    "groups": [],
                },
            },
        }
        # Mock get_contacts_for_restore and get_groups_for_restore
        mock_bm.get_contacts_for_restore.return_value = [
            Contact("", "", "John Doe", emails=["john@example.com"]),
            Contact("", "", "Jane Smith", emails=["jane@example.com"]),
        ]
        mock_bm.get_groups_for_restore.return_value = [
            ContactGroup("", "", "Friends", group_type="USER_CONTACT_GROUP"),
        ]
        mock_backup_manager.return_value = mock_bm

        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create a dummy backup file
            Path("backup.json").write_text("{}")

            result = runner.invoke(
                cli, ["restore", "--backup-file", "backup.json", "--dry-run"]
            )
            assert result.exit_code == 0
            assert "Dry run mode" in result.output
            # v2.0 format shows "  Contacts: X" (with indent)
            assert "Contacts: 2" in result.output
            assert "Groups: 1" in result.output
            assert "John Doe" in result.output
            assert "Dry run complete" in result.output

    @patch("gcontact_sync.api.people_api.PeopleAPI")
    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.backup.manager.BackupManager")
    @patch("gcontact_sync.cli.setup_logging")
    def test_restore_with_confirmation(
        self, mock_setup_logging, mock_backup_manager, mock_google_auth, mock_people_api
    ):
        """Test restore with confirmation prompt."""
        from gcontact_sync.sync.contact import Contact

        mock_bm = MagicMock()
        mock_bm.load_backup.return_value = {
            "version": "2.0",
            "timestamp": "2024-01-20T10:30:00",
            "accounts": {
                "account1": {
                    "email": "user1@example.com",
                    "contacts": [{"display_name": "John Doe"}],
                    "groups": [],
                },
                "account2": {
                    "email": "user2@example.com",
                    "contacts": [],
                    "groups": [],
                },
            },
        }
        mock_bm.get_contacts_for_restore.return_value = [
            Contact("", "", "John Doe"),
        ]
        mock_bm.get_groups_for_restore.return_value = []
        mock_backup_manager.return_value = mock_bm

        # Mock auth
        mock_auth_instance = MagicMock()
        mock_auth_instance.get_credentials.return_value = MagicMock()
        mock_auth_instance.get_account_email.return_value = "user1@example.com"
        mock_google_auth.return_value = mock_auth_instance

        # Mock API
        mock_api = MagicMock()
        mock_people_api.return_value = mock_api

        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create a dummy backup file
            Path("backup.json").write_text("{}")

            # Confirm the restore
            result = runner.invoke(
                cli, ["restore", "--backup-file", "backup.json"], input="y\n"
            )
            assert result.exit_code == 0
            assert "Restore complete!" in result.output

    @patch("gcontact_sync.api.people_api.PeopleAPI")
    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.backup.manager.BackupManager")
    @patch("gcontact_sync.cli.setup_logging")
    def test_restore_with_yes_flag(
        self, mock_setup_logging, mock_backup_manager, mock_google_auth, mock_people_api
    ):
        """Test restore with --yes flag skips confirmation."""
        from gcontact_sync.sync.contact import Contact

        mock_bm = MagicMock()
        mock_bm.load_backup.return_value = {
            "version": "2.0",
            "timestamp": "2024-01-20T10:30:00",
            "accounts": {
                "account1": {
                    "email": "user1@example.com",
                    "contacts": [{"display_name": "John Doe"}],
                    "groups": [],
                },
                "account2": {
                    "email": "user2@example.com",
                    "contacts": [],
                    "groups": [],
                },
            },
        }
        mock_bm.get_contacts_for_restore.return_value = [
            Contact("", "", "John Doe"),
        ]
        mock_bm.get_groups_for_restore.return_value = []
        mock_backup_manager.return_value = mock_bm

        # Mock auth
        mock_auth_instance = MagicMock()
        mock_auth_instance.get_credentials.return_value = MagicMock()
        mock_auth_instance.get_account_email.return_value = "user1@example.com"
        mock_google_auth.return_value = mock_auth_instance

        # Mock API
        mock_api = MagicMock()
        mock_people_api.return_value = mock_api

        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create a dummy backup file
            Path("backup.json").write_text("{}")

            result = runner.invoke(
                cli, ["restore", "--backup-file", "backup.json", "--yes"]
            )
            assert result.exit_code == 0
            assert "Restore complete!" in result.output

    @patch("gcontact_sync.backup.manager.BackupManager")
    @patch("gcontact_sync.cli.setup_logging")
    def test_restore_cancelled(self, mock_setup_logging, mock_backup_manager):
        """Test restore when user cancels."""
        mock_bm = MagicMock()
        mock_bm.load_backup.return_value = {
            "version": "1.0",
            "timestamp": "2024-01-20T10:30:00",
            "contacts": [{"display_name": "John Doe"}],
            "groups": [],
        }
        mock_backup_manager.return_value = mock_bm

        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create a dummy backup file
            Path("backup.json").write_text("{}")

            # Cancel the restore
            result = runner.invoke(
                cli, ["restore", "--backup-file", "backup.json"], input="n\n"
            )
            assert result.exit_code == 1  # Aborted

    @patch("gcontact_sync.backup.manager.BackupManager")
    @patch("gcontact_sync.cli.setup_logging")
    def test_restore_invalid_backup_file(self, mock_setup_logging, mock_backup_manager):
        """Test restore with invalid backup file."""
        mock_bm = MagicMock()
        mock_bm.load_backup.return_value = None
        mock_backup_manager.return_value = mock_bm

        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create a dummy backup file
            Path("invalid.json").write_text("{}")

            result = runner.invoke(
                cli, ["restore", "--backup-file", "invalid.json", "--yes"]
            )
            assert result.exit_code == 1
            assert "Error:" in result.output
            assert "Failed to load backup file" in result.output

    @patch("gcontact_sync.backup.manager.BackupManager")
    @patch("gcontact_sync.cli.setup_logging")
    def test_restore_specific_account(self, mock_setup_logging, mock_backup_manager):
        """Test restore to specific account."""
        mock_bm = MagicMock()
        mock_bm.load_backup.return_value = {
            "version": "1.0",
            "timestamp": "2024-01-20T10:30:00",
            "contacts": [{"display_name": "John Doe"}],
            "groups": [],
        }
        mock_backup_manager.return_value = mock_bm

        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create a dummy backup file
            Path("backup.json").write_text("{}")

            result = runner.invoke(
                cli,
                [
                    "restore",
                    "--backup-file",
                    "backup.json",
                    "--account",
                    "account1",
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0
            assert "account1" in result.output
            assert "Dry run complete" in result.output

    @patch("gcontact_sync.backup.manager.BackupManager")
    @patch("gcontact_sync.cli.setup_logging")
    def test_restore_error_handling(self, mock_setup_logging, mock_backup_manager):
        """Test restore handles errors gracefully."""
        mock_backup_manager.side_effect = RuntimeError("Backup manager error")

        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create a dummy backup file
            Path("backup.json").write_text("{}")

            result = runner.invoke(
                cli, ["restore", "--backup-file", "backup.json", "--yes"]
            )
            assert result.exit_code == 1
            assert "Error:" in result.output

    @patch("gcontact_sync.backup.manager.BackupManager")
    @patch("gcontact_sync.cli.setup_logging")
    def test_restore_custom_backup_dir_from_config(
        self, mock_setup_logging, mock_backup_manager
    ):
        """Test restore uses custom backup directory from config."""
        mock_bm = MagicMock()
        mock_bm.list_backups.return_value = []
        mock_backup_manager.return_value = mock_bm

        runner = CliRunner()
        with runner.isolated_filesystem():
            # The config would be loaded by CLI but we're testing that
            # BackupManager is called with correct directory
            result = runner.invoke(cli, ["restore", "--list"])
            assert result.exit_code == 0
            # Verify BackupManager was called
            mock_backup_manager.assert_called_once()


class TestConfigIntegration:
    """Tests for configuration file integration with CLI."""

    def test_cli_config_file_option_in_help(self):
        """Test that --config-file option appears in help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "--config-file" in result.output or "-f" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    def test_missing_config_file_handled_gracefully(self, mock_setup_logging):
        """Test that missing config file doesn't cause errors."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            # Run CLI with non-existent config file
            result = runner.invoke(cli, ["--config-file", "nonexistent.yaml", "--help"])
            assert result.exit_code == 0

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.cli.ConfigLoader")
    @patch("gcontact_sync.cli.GoogleAuth")
    def test_config_file_is_loaded(
        self, mock_auth, mock_config_loader, mock_setup_logging
    ):
        """Test that config file is loaded when present."""
        mock_loader = MagicMock()
        mock_loader.load_from_file.return_value = {"verbose": True}
        mock_loader.validate.return_value = None
        mock_config_loader.return_value = mock_loader

        # Mock auth to return not authenticated
        mock_auth_instance = MagicMock()
        mock_auth_instance.is_authenticated.return_value = False
        mock_auth.return_value = mock_auth_instance

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            # Verify config was loaded
            mock_loader.load_from_file.assert_called_once()

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.cli.ConfigLoader")
    @patch("gcontact_sync.cli.GoogleAuth")
    def test_invalid_config_file_shows_warning(
        self, mock_auth, mock_config_loader, mock_setup_logging
    ):
        """Test that invalid config file shows warning but doesn't crash."""
        from gcontact_sync.config.loader import ConfigError

        mock_loader = MagicMock()
        mock_loader.load_from_file.side_effect = ConfigError("Invalid YAML")
        mock_config_loader.return_value = mock_loader

        # Mock auth to return not authenticated
        mock_auth_instance = MagicMock()
        mock_auth_instance.is_authenticated.return_value = False
        mock_auth.return_value = mock_auth_instance

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            # Warning should be shown but command continues
            assert "Warning" in result.output or "Invalid YAML" in result.output

    @patch("gcontact_sync.cli.save_config_file")
    @patch("gcontact_sync.cli.setup_logging")
    def test_init_config_command_help(self, mock_setup_logging, mock_save):
        """Test that init-config command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["init-config", "--help"])
        assert result.exit_code == 0
        assert "init-config" in result.output or "Initialize" in result.output

    @patch("gcontact_sync.cli.save_config_file")
    @patch("gcontact_sync.cli.setup_logging")
    def test_init_config_creates_file(self, mock_setup_logging, mock_save):
        """Test that init-config command creates config file."""
        mock_save.return_value = (True, None)

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init-config"])
            assert result.exit_code == 0
            assert (
                "created" in result.output.lower() or "success" in result.output.lower()
            )
            mock_save.assert_called_once()

    @patch("gcontact_sync.cli.save_config_file")
    @patch("gcontact_sync.cli.setup_logging")
    def test_init_config_with_force_flag(self, mock_setup_logging, mock_save):
        """Test that init-config with --force overwrites existing file."""
        mock_save.return_value = (True, None)

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init-config", "--force"])
            assert result.exit_code == 0
            # Verify save_config_file was called with overwrite=True
            call_args = mock_save.call_args
            assert call_args.kwargs.get("overwrite") is True

    @patch("gcontact_sync.cli.save_config_file")
    @patch("gcontact_sync.cli.setup_logging")
    def test_init_config_error_handling(self, mock_setup_logging, mock_save):
        """Test that init-config handles errors gracefully."""
        mock_save.return_value = (False, "Permission denied")

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init-config"])
            assert result.exit_code == 1
            assert "Error" in result.output
            assert "Permission denied" in result.output

    @patch("gcontact_sync.sync.engine.SyncEngine")
    @patch("gcontact_sync.storage.db.SyncDatabase")
    @patch("gcontact_sync.api.people_api.PeopleAPI")
    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.ConfigLoader")
    @patch("gcontact_sync.cli.setup_logging")
    def test_sync_uses_config_values(
        self,
        mock_setup_logging,
        mock_config_loader,
        mock_auth_class,
        mock_api_class,
        mock_db_class,
        mock_engine_class,
    ):
        """Test that sync command uses values from config file."""
        # Setup config with dry_run enabled
        mock_loader = MagicMock()
        mock_loader.load_from_file.return_value = {"dry_run": True, "full": False}
        mock_loader.validate.return_value = None
        mock_config_loader.return_value = mock_loader

        # Setup auth
        mock_auth = MagicMock()
        mock_auth.get_credentials.return_value = MagicMock()
        mock_auth.get_account_email.return_value = "test@test.com"
        mock_auth_class.return_value = mock_auth

        # Setup sync engine
        mock_result = MagicMock()
        mock_result.has_changes.return_value = False
        mock_result.summary.return_value = "Test summary"
        mock_result.conflicts = []
        mock_result.matched_contacts = []
        mock_result.to_create_in_account1 = []
        mock_result.to_create_in_account2 = []
        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_class.return_value = mock_engine

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["sync"])
            assert result.exit_code == 0
            # Verify sync was called with dry_run=True from config
            mock_engine.sync.assert_called_once()
            call_kwargs = mock_engine.sync.call_args.kwargs
            assert call_kwargs.get("dry_run") is True

    @patch("gcontact_sync.sync.engine.SyncEngine")
    @patch("gcontact_sync.storage.db.SyncDatabase")
    @patch("gcontact_sync.api.people_api.PeopleAPI")
    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.ConfigLoader")
    @patch("gcontact_sync.cli.setup_logging")
    def test_cli_args_override_config_values(
        self,
        mock_setup_logging,
        mock_config_loader,
        mock_auth_class,
        mock_api_class,
        mock_db_class,
        mock_engine_class,
    ):
        """Test that CLI arguments override config file values."""
        # Setup config with full=True
        mock_loader = MagicMock()
        mock_loader.load_from_file.return_value = {"full": True, "dry_run": False}
        mock_loader.validate.return_value = None
        mock_config_loader.return_value = mock_loader

        # Setup auth
        mock_auth = MagicMock()
        mock_auth.get_credentials.return_value = MagicMock()
        mock_auth.get_account_email.return_value = "test@test.com"
        mock_auth_class.return_value = mock_auth

        # Setup sync engine
        mock_result = MagicMock()
        mock_result.has_changes.return_value = False
        mock_result.summary.return_value = "Test summary"
        mock_result.conflicts = []
        mock_result.matched_contacts = []
        mock_result.to_create_in_account1 = []
        mock_result.to_create_in_account2 = []
        mock_engine = MagicMock()
        mock_engine.sync.return_value = mock_result
        mock_engine_class.return_value = mock_engine

        runner = CliRunner()
        with runner.isolated_filesystem():
            # Run sync with --dry-run flag (should override config's dry_run=False)
            result = runner.invoke(cli, ["sync", "--dry-run"])
            assert result.exit_code == 0
            # Verify sync was called with dry_run=True from CLI, overriding config
            mock_engine.sync.assert_called_once()
            call_kwargs = mock_engine.sync.call_args.kwargs
            assert call_kwargs.get("dry_run") is True

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.cli.ConfigLoader")
    @patch("gcontact_sync.cli.GoogleAuth")
    def test_custom_config_file_path(
        self, mock_auth, mock_config_loader, mock_setup_logging
    ):
        """Test that custom config file path is used when specified."""
        mock_loader = MagicMock()
        mock_loader.load_from_file.return_value = {}
        mock_loader.validate.return_value = None
        mock_config_loader.return_value = mock_loader

        # Mock auth to return not authenticated
        mock_auth_instance = MagicMock()
        mock_auth_instance.is_authenticated.return_value = False
        mock_auth.return_value = mock_auth_instance

        runner = CliRunner()
        with runner.isolated_filesystem():
            # Create a custom config file
            custom_config = Path("custom.yaml")
            custom_config.write_text("verbose: true\n")

            result = runner.invoke(cli, ["--config-file", "custom.yaml", "status"])
            assert result.exit_code == 0
            # Verify loader was called with custom path
            mock_loader.load_from_file.assert_called_once()
            call_args = mock_loader.load_from_file.call_args
            assert call_args[0][0] == Path("custom.yaml")


class TestDaemonCommand:
    """Tests for the daemon command group."""

    def test_daemon_help(self):
        """Test that daemon command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["daemon", "--help"])
        assert result.exit_code == 0
        assert "Manage background synchronization daemon" in result.output

    def test_daemon_start_help(self):
        """Test that daemon start command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["daemon", "start", "--help"])
        assert result.exit_code == 0
        assert "Start the synchronization daemon" in result.output
        assert "--interval" in result.output
        assert "--foreground" in result.output
        assert "--no-initial-sync" in result.output

    def test_daemon_stop_help(self):
        """Test that daemon stop command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["daemon", "stop", "--help"])
        assert result.exit_code == 0
        assert "Stop the running synchronization daemon" in result.output

    def test_daemon_status_help(self):
        """Test that daemon status command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["daemon", "status", "--help"])
        assert result.exit_code == 0
        assert "Show the status of the synchronization daemon" in result.output

    def test_daemon_install_help(self):
        """Test that daemon install command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["daemon", "install", "--help"])
        assert result.exit_code == 0
        assert "Install gcontact-sync as a system service" in result.output
        assert "--interval" in result.output
        assert "--force" in result.output

    def test_daemon_uninstall_help(self):
        """Test that daemon uninstall command shows help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["daemon", "uninstall", "--help"])
        assert result.exit_code == 0
        assert "Uninstall the gcontact-sync system service" in result.output
        assert "--yes" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.DaemonScheduler")
    @patch("gcontact_sync.daemon.parse_interval")
    def test_daemon_start_invalid_interval(
        self, mock_parse_interval, mock_scheduler_class, mock_setup_logging
    ):
        """Test daemon start with invalid interval format."""
        mock_parse_interval.side_effect = ValueError(
            "Invalid interval format: 'invalid'. "
            "Use format like '30s', '5m', '1h', or '1d'."
        )

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "start", "--interval", "invalid"])
            assert result.exit_code == 1
            assert "Error:" in result.output
            assert "Invalid interval format" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.DaemonScheduler")
    @patch("gcontact_sync.daemon.parse_interval")
    def test_daemon_start_foreground_mode(
        self,
        mock_parse_interval,
        mock_scheduler_class,
        mock_setup_logging,
        mock_auth_class,
    ):
        """Test daemon start in foreground mode."""
        mock_parse_interval.return_value = 3600

        mock_auth = MagicMock()
        mock_auth.get_credentials.return_value = MagicMock()
        mock_auth.get_account_email.return_value = "test@test.com"
        mock_auth_class.return_value = mock_auth

        mock_scheduler = MagicMock()
        mock_scheduler_class.return_value = mock_scheduler

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "start", "--foreground"])
            assert result.exit_code == 0
            assert "Starting daemon" in result.output
            assert "foreground mode" in result.output
            mock_scheduler.run.assert_called_once()

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.DaemonScheduler")
    @patch("gcontact_sync.daemon.parse_interval")
    def test_daemon_start_with_custom_interval(
        self,
        mock_parse_interval,
        mock_scheduler_class,
        mock_setup_logging,
        mock_auth_class,
    ):
        """Test daemon start with custom interval."""
        mock_parse_interval.return_value = 1800  # 30 minutes

        mock_auth = MagicMock()
        mock_auth.get_credentials.return_value = MagicMock()
        mock_auth.get_account_email.return_value = "test@test.com"
        mock_auth_class.return_value = mock_auth

        mock_scheduler = MagicMock()
        mock_scheduler_class.return_value = mock_scheduler

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli, ["daemon", "start", "--interval", "30m", "--foreground"]
            )
            assert result.exit_code == 0
            assert "30m" in result.output
            mock_parse_interval.assert_called_with("30m")
            mock_scheduler_class.assert_called_once()
            # Verify interval was passed
            call_kwargs = mock_scheduler_class.call_args.kwargs
            assert call_kwargs["interval"] == 1800

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.DaemonScheduler")
    @patch("gcontact_sync.daemon.parse_interval")
    def test_daemon_start_no_initial_sync(
        self,
        mock_parse_interval,
        mock_scheduler_class,
        mock_setup_logging,
        mock_auth_class,
    ):
        """Test daemon start with --no-initial-sync flag."""
        mock_parse_interval.return_value = 3600

        mock_auth = MagicMock()
        mock_auth.get_credentials.return_value = MagicMock()
        mock_auth.get_account_email.return_value = "test@test.com"
        mock_auth_class.return_value = mock_auth

        mock_scheduler = MagicMock()
        mock_scheduler_class.return_value = mock_scheduler

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli, ["daemon", "start", "--foreground", "--no-initial-sync"]
            )
            assert result.exit_code == 0
            # Verify run_immediately was False when --no-initial-sync used
            mock_scheduler_class.assert_called_once()
            call_kwargs = mock_scheduler_class.call_args.kwargs
            assert call_kwargs["run_immediately"] is False

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.DaemonScheduler")
    @patch("gcontact_sync.daemon.parse_interval")
    def test_daemon_start_already_running(
        self,
        mock_parse_interval,
        mock_scheduler_class,
        mock_setup_logging,
        mock_auth_class,
    ):
        """Test daemon start when daemon is already running."""
        from gcontact_sync.daemon import DaemonAlreadyRunningError

        mock_parse_interval.return_value = 3600

        mock_auth = MagicMock()
        mock_auth.get_credentials.return_value = MagicMock()
        mock_auth.get_account_email.return_value = "test@test.com"
        mock_auth_class.return_value = mock_auth

        mock_scheduler = MagicMock()
        mock_scheduler.run.side_effect = DaemonAlreadyRunningError(
            "Daemon already running with PID 12345"
        )
        mock_scheduler_class.return_value = mock_scheduler

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "start", "--foreground"])
            assert result.exit_code == 1
            assert "Error:" in result.output
            assert "already running" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.DaemonScheduler")
    def test_daemon_stop_no_daemon_running(
        self, mock_scheduler_class, mock_setup_logging
    ):
        """Test daemon stop when no daemon is running."""
        mock_scheduler_class.get_running_pid.return_value = None

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "stop"])
            assert result.exit_code == 0
            assert "No daemon is currently running" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.DaemonScheduler")
    def test_daemon_stop_running_daemon(self, mock_scheduler_class, mock_setup_logging):
        """Test daemon stop with running daemon."""
        mock_scheduler_class.get_running_pid.return_value = 12345
        mock_scheduler_class.stop_running_daemon.return_value = True

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "stop"])
            assert result.exit_code == 0
            assert "Stopping daemon" in result.output
            assert "PID: 12345" in result.output
            assert "Stop signal sent successfully" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.DaemonScheduler")
    def test_daemon_stop_failed(self, mock_scheduler_class, mock_setup_logging):
        """Test daemon stop when stop signal fails."""
        mock_scheduler_class.get_running_pid.return_value = 12345
        mock_scheduler_class.stop_running_daemon.return_value = False

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "stop"])
            assert result.exit_code == 1
            assert "Failed to send stop signal" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.PIDFileManager")
    @patch("gcontact_sync.daemon.DaemonScheduler")
    def test_daemon_status_running(
        self, mock_scheduler_class, mock_pid_manager_class, mock_setup_logging
    ):
        """Test daemon status when daemon is running."""
        mock_scheduler_class.get_running_pid.return_value = 12345

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "status"])
            assert result.exit_code == 0
            assert "Daemon Status" in result.output
            assert "Running" in result.output
            assert "Process ID: 12345" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.PIDFileManager")
    @patch("gcontact_sync.daemon.DaemonScheduler")
    def test_daemon_status_stopped(
        self, mock_scheduler_class, mock_pid_manager_class, mock_setup_logging
    ):
        """Test daemon status when daemon is not running."""
        mock_scheduler_class.get_running_pid.return_value = None

        mock_pid_manager = MagicMock()
        mock_pid_manager.read.return_value = None
        mock_pid_manager_class.return_value = mock_pid_manager

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "status"])
            assert result.exit_code == 0
            assert "Daemon Status" in result.output
            assert "Stopped" in result.output
            assert "No daemon is currently running" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.PIDFileManager")
    @patch("gcontact_sync.daemon.DaemonScheduler")
    def test_daemon_status_stale_pid(
        self, mock_scheduler_class, mock_pid_manager_class, mock_setup_logging
    ):
        """Test daemon status with stale PID file."""
        mock_scheduler_class.get_running_pid.return_value = None

        mock_pid_manager = MagicMock()
        mock_pid_manager.read.return_value = 99999  # Stale PID
        mock_pid_manager_class.return_value = mock_pid_manager

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "status"])
            assert result.exit_code == 0
            assert "Stopped" in result.output
            assert "Stale PID file exists" in result.output
            assert "99999" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.get_platform")
    @patch("gcontact_sync.daemon.ServiceManager")
    @patch("gcontact_sync.daemon.parse_interval")
    def test_daemon_install_success(
        self,
        mock_parse_interval,
        mock_service_manager_class,
        mock_get_platform,
        mock_setup_logging,
    ):
        """Test daemon install on supported platform."""
        mock_parse_interval.return_value = 3600
        mock_get_platform.return_value = "macos"

        mock_manager = MagicMock()
        mock_manager.is_platform_supported.return_value = True
        mock_manager.install.return_value = (True, None)
        mock_manager.get_service_file_path.return_value = Path(
            "/Users/test/Library/LaunchAgents/com.gcontact-sync.plist"
        )
        mock_service_manager_class.return_value = mock_manager

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "install"])
            assert result.exit_code == 0
            assert "Installing gcontact-sync daemon" in result.output
            assert "installed successfully" in result.output
            mock_manager.install.assert_called_once()

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.get_platform")
    @patch("gcontact_sync.daemon.ServiceManager")
    def test_daemon_install_unsupported_platform(
        self, mock_service_manager_class, mock_get_platform, mock_setup_logging
    ):
        """Test daemon install on unsupported platform."""
        mock_get_platform.return_value = "windows"

        mock_manager = MagicMock()
        mock_manager.is_platform_supported.return_value = False
        mock_service_manager_class.return_value = mock_manager

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "install"])
            assert result.exit_code == 1
            assert "not supported" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.get_platform")
    @patch("gcontact_sync.daemon.ServiceManager")
    @patch("gcontact_sync.daemon.parse_interval")
    def test_daemon_install_with_force(
        self,
        mock_parse_interval,
        mock_service_manager_class,
        mock_get_platform,
        mock_setup_logging,
    ):
        """Test daemon install with --force flag."""
        mock_parse_interval.return_value = 3600
        mock_get_platform.return_value = "linux"

        mock_manager = MagicMock()
        mock_manager.is_platform_supported.return_value = True
        mock_manager.install.return_value = (True, None)
        mock_manager.get_service_file_path.return_value = Path(
            "/home/test/.config/systemd/user/gcontact-sync.service"
        )
        mock_service_manager_class.return_value = mock_manager

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "install", "--force"])
            assert result.exit_code == 0
            # Verify install was called with overwrite=True
            mock_manager.install.assert_called_once()
            call_kwargs = mock_manager.install.call_args.kwargs
            assert call_kwargs["overwrite"] is True

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.get_platform")
    @patch("gcontact_sync.daemon.ServiceManager")
    @patch("gcontact_sync.daemon.parse_interval")
    def test_daemon_install_failed(
        self,
        mock_parse_interval,
        mock_service_manager_class,
        mock_get_platform,
        mock_setup_logging,
    ):
        """Test daemon install failure."""
        mock_parse_interval.return_value = 3600
        mock_get_platform.return_value = "linux"

        mock_manager = MagicMock()
        mock_manager.is_platform_supported.return_value = True
        mock_manager.install.return_value = (False, "Permission denied")
        mock_service_manager_class.return_value = mock_manager

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "install"])
            assert result.exit_code == 1
            assert "Installation failed" in result.output
            assert "Permission denied" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.get_platform")
    @patch("gcontact_sync.daemon.ServiceManager")
    def test_daemon_uninstall_not_installed(
        self, mock_service_manager_class, mock_get_platform, mock_setup_logging
    ):
        """Test daemon uninstall when service is not installed."""
        mock_get_platform.return_value = "linux"

        mock_manager = MagicMock()
        mock_manager.is_platform_supported.return_value = True
        mock_manager.is_installed.return_value = False
        mock_service_manager_class.return_value = mock_manager

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "uninstall", "--yes"])
            assert result.exit_code == 0
            assert "No daemon service is currently installed" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.get_platform")
    @patch("gcontact_sync.daemon.ServiceManager")
    def test_daemon_uninstall_success(
        self, mock_service_manager_class, mock_get_platform, mock_setup_logging
    ):
        """Test daemon uninstall success."""
        mock_get_platform.return_value = "macos"

        mock_manager = MagicMock()
        mock_manager.is_platform_supported.return_value = True
        mock_manager.is_installed.return_value = True
        mock_manager.uninstall.return_value = (True, None)
        mock_manager.get_service_file_path.return_value = Path(
            "/Users/test/Library/LaunchAgents/com.gcontact-sync.plist"
        )
        mock_service_manager_class.return_value = mock_manager

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "uninstall", "--yes"])
            assert result.exit_code == 0
            assert "uninstalled successfully" in result.output
            mock_manager.uninstall.assert_called_once()

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.get_platform")
    @patch("gcontact_sync.daemon.ServiceManager")
    def test_daemon_uninstall_with_confirmation(
        self, mock_service_manager_class, mock_get_platform, mock_setup_logging
    ):
        """Test daemon uninstall with confirmation prompt."""
        mock_get_platform.return_value = "macos"

        mock_manager = MagicMock()
        mock_manager.is_platform_supported.return_value = True
        mock_manager.is_installed.return_value = True
        mock_manager.uninstall.return_value = (True, None)
        mock_manager.get_service_file_path.return_value = Path(
            "/Users/test/Library/LaunchAgents/com.gcontact-sync.plist"
        )
        mock_service_manager_class.return_value = mock_manager

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "uninstall"], input="y\n")
            assert result.exit_code == 0
            assert "uninstalled successfully" in result.output

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.get_platform")
    @patch("gcontact_sync.daemon.ServiceManager")
    def test_daemon_uninstall_cancelled(
        self, mock_service_manager_class, mock_get_platform, mock_setup_logging
    ):
        """Test daemon uninstall when user cancels."""
        mock_get_platform.return_value = "linux"

        mock_manager = MagicMock()
        mock_manager.is_platform_supported.return_value = True
        mock_manager.is_installed.return_value = True
        mock_manager.get_service_file_path.return_value = Path(
            "/home/test/.config/systemd/user/gcontact-sync.service"
        )
        mock_service_manager_class.return_value = mock_manager

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "uninstall"], input="n\n")
            assert result.exit_code == 1  # Aborted

    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.get_platform")
    @patch("gcontact_sync.daemon.ServiceManager")
    def test_daemon_uninstall_failed(
        self, mock_service_manager_class, mock_get_platform, mock_setup_logging
    ):
        """Test daemon uninstall failure."""
        mock_get_platform.return_value = "linux"

        mock_manager = MagicMock()
        mock_manager.is_platform_supported.return_value = True
        mock_manager.is_installed.return_value = True
        mock_manager.uninstall.return_value = (False, "Service is still running")
        mock_manager.get_service_file_path.return_value = Path(
            "/home/test/.config/systemd/user/gcontact-sync.service"
        )
        mock_service_manager_class.return_value = mock_manager

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "uninstall", "--yes"])
            assert result.exit_code == 1
            assert "Uninstallation failed" in result.output
            assert "Service is still running" in result.output

    @patch("gcontact_sync.cli.GoogleAuth")
    @patch("gcontact_sync.cli.setup_logging")
    @patch("gcontact_sync.daemon.DaemonScheduler")
    @patch("gcontact_sync.daemon.parse_interval")
    def test_daemon_start_unexpected_error(
        self,
        mock_parse_interval,
        mock_scheduler_class,
        mock_setup_logging,
        mock_auth_class,
    ):
        """Test daemon start handles unexpected errors."""
        mock_parse_interval.return_value = 3600

        mock_auth = MagicMock()
        mock_auth.get_credentials.return_value = MagicMock()
        mock_auth.get_account_email.return_value = "test@test.com"
        mock_auth_class.return_value = mock_auth

        mock_scheduler = MagicMock()
        mock_scheduler.run.side_effect = RuntimeError("Unexpected error occurred")
        mock_scheduler_class.return_value = mock_scheduler

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["daemon", "start", "--foreground"])
            assert result.exit_code == 1
            assert "Error" in result.output
