"""
Command-line interface for gcontact_sync.

Provides CLI commands for authentication, synchronization, and status checking
of Google Contacts between two accounts.

Usage:
    # Show help
    gcontact-sync --help

    # Authenticate accounts
    gcontact-sync auth --account account1
    gcontact-sync auth --account account2

    # Check status
    gcontact-sync status

    # Run synchronization
    gcontact-sync sync
    gcontact-sync sync --dry-run
    gcontact-sync sync --full --verbose
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from gcontact_sync import __version__
from gcontact_sync.auth.google_auth import (
    ACCOUNT_1,
    ACCOUNT_2,
    AuthenticationError,
    GoogleAuth,
)
from gcontact_sync.cli.formatters import show_debug_info, show_detailed_changes
from gcontact_sync.config.generator import save_config_file
from gcontact_sync.config.loader import ConfigError, ConfigLoader
from gcontact_sync.config.sync_config import SyncConfigError
from gcontact_sync.config.sync_config import load_config as load_sync_config
from gcontact_sync.sync.conflict import ConflictStrategy
from gcontact_sync.utils import DEFAULT_CONFIG_DIR, resolve_config_dir
from gcontact_sync.utils.logging import get_logger, setup_logging

if TYPE_CHECKING:
    pass

# Valid account identifiers
VALID_ACCOUNTS = (ACCOUNT_1, ACCOUNT_2)

# Default configuration file
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"


def validate_account(
    ctx: click.Context, _param: click.Parameter, value: str | None
) -> str | None:
    """Validate account identifier for Click option."""
    if value is None:
        return value
    if value not in VALID_ACCOUNTS:
        raise click.BadParameter(
            f"Invalid account '{value}'. Must be one of: {', '.join(VALID_ACCOUNTS)}"
        )
    return value


def get_config_dir(config_dir: str | None) -> Path:
    """Get the configuration directory path."""
    return resolve_config_dir(config_dir)


def get_config_file(config_file: str | None) -> Path:
    """Get the configuration file path."""
    if config_file:
        return Path(config_file)
    return DEFAULT_CONFIG_FILE


@click.group()
@click.version_option(version=__version__, prog_name="gcontact-sync")
@click.option(
    "--verbose", "-v", is_flag=True, help="Enable verbose output with detailed logging."
)
@click.option(
    "--config-dir",
    "-c",
    type=click.Path(exists=False, file_okay=False, dir_okay=True),
    envvar="GCONTACT_SYNC_CONFIG_DIR",
    help="Configuration directory path (default: ~/.gcontact-sync).",
)
@click.option(
    "--config-file",
    "-f",
    type=click.Path(exists=False, file_okay=True, dir_okay=False),
    envvar="GCONTACT_SYNC_CONFIG_FILE",
    help="Configuration file path (default: ~/.gcontact-sync/config.yaml).",
)
@click.pass_context
def cli(
    ctx: click.Context,
    verbose: bool,
    config_dir: str | None,
    config_file: str | None,
) -> None:
    """
    Bidirectional Google Contacts Sync.

    Synchronizes contacts between two Google accounts, ensuring both accounts
    contain identical contact sets after each sync.

    For more information, visit: https://github.com/gcontact-sync
    """
    # Initialize context
    ctx.ensure_object(dict)

    # Resolve paths
    resolved_config_dir = get_config_dir(config_dir)
    resolved_config_file = get_config_file(config_file)

    ctx.obj["config_dir"] = resolved_config_dir
    ctx.obj["config_file"] = resolved_config_file

    # Load configuration file
    config = {}
    try:
        loader = ConfigLoader(config_dir=resolved_config_dir)
        config = loader.load_from_file(resolved_config_file)
        if config:
            # Validate loaded config
            loader.validate(config)
    except ConfigError as e:
        # Show error but don't fail - allow CLI to work without config file
        click.echo(
            click.style(f"Warning: Configuration error: {e}", fg="yellow"), err=True
        )
        config = {}

    # Store loaded config for commands to use
    ctx.obj["config"] = config

    # Merge verbose flag: CLI arg takes precedence over config file
    # If verbose was not set via CLI, use config value
    effective_verbose = verbose or config.get("verbose", False)
    ctx.obj["verbose"] = effective_verbose

    # Get log directory from config
    log_dir = None
    if config.get("log_dir"):
        log_dir = Path(config["log_dir"])

    # Setup logging with configured log directory
    setup_logging(verbose=effective_verbose, log_dir=log_dir, enable_file_logging=True)

    # Clean up old log files based on retention setting
    log_retention = config.get("log_retention_count", 10)
    if log_retention > 0:
        from gcontact_sync.utils.logging import cleanup_old_logs

        cleanup_old_logs(log_dir=log_dir, keep_count=log_retention)


# =============================================================================
# Auth Command
# =============================================================================


@cli.command("auth")
@click.option(
    "--account",
    "-a",
    required=True,
    type=click.Choice(VALID_ACCOUNTS, case_sensitive=False),
    help="Account to authenticate (account1 or account2).",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Force re-authentication even if already authenticated.",
)
@click.pass_context
def auth_command(ctx: click.Context, account: str, force: bool) -> None:
    """
    Authenticate a Google account.

    Opens a browser window to complete the OAuth flow and stores
    the credentials for future use.

    Examples:

        # Authenticate first account
        gcontact-sync auth --account account1

        # Force re-authentication
        gcontact-sync auth --account account1 --force
    """
    logger = get_logger(__name__)
    config_dir = ctx.obj["config_dir"]

    click.echo(f"Authenticating {account}...")

    try:
        auth = GoogleAuth(config_dir=config_dir)

        # Check if already authenticated
        if not force and auth.is_authenticated(account):
            click.echo(
                click.style(f"Account {account} is already authenticated.", fg="green")
            )
            click.echo("Use --force to re-authenticate.")
            return

        # Run authentication flow
        auth.authenticate(account, force_reauth=force)

        # Try to get email for display
        email = auth.get_account_email(account)
        if email:
            click.echo(
                click.style(
                    f"Successfully authenticated {account} ({email})!", fg="green"
                )
            )
        else:
            click.echo(
                click.style(f"Successfully authenticated {account}!", fg="green")
            )

        logger.info(f"Authentication completed for {account}")

    except FileNotFoundError as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        click.echo("\nTo get started:", err=True)
        click.echo("1. Go to https://console.cloud.google.com/", err=True)
        click.echo("2. Create a project and enable the People API", err=True)
        click.echo("3. Create OAuth 2.0 credentials (Desktop application)", err=True)
        click.echo(
            f"4. Download and save as: {config_dir / 'credentials.json'}", err=True
        )
        sys.exit(1)

    except AuthenticationError as e:
        logger.error(f"Authentication failed: {e}")
        click.echo(click.style(f"Authentication failed: {e}", fg="red"), err=True)
        sys.exit(1)

    except Exception as e:
        logger.exception(f"Unexpected error during authentication: {e}")
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)


# =============================================================================
# Status Command
# =============================================================================


@cli.command("status")
@click.pass_context
def status_command(ctx: click.Context) -> None:
    """
    Show authentication and sync status.

    Displays the current status of both Google accounts, including
    authentication state and last sync information.

    Example:

        gcontact-sync status
    """
    logger = get_logger(__name__)
    config_dir = ctx.obj["config_dir"]

    try:
        auth = GoogleAuth(config_dir=config_dir)
        auth_status = auth.get_auth_status()

        click.echo("=== Google Contacts Sync Status ===\n")

        # Config directory
        click.echo(f"Configuration directory: {auth_status['config_dir']}")
        creds_status = (
            "Found"
            if auth_status["credentials_exist"]
            else click.style("Not found", fg="red")
        )
        click.echo(f"OAuth credentials: {creds_status}")
        click.echo()

        # Account status
        needs_reauth_for_email = False
        for account_id in (ACCOUNT_1, ACCOUNT_2):
            account_status = auth_status.get(account_id, {})
            # Cast to dict since we know the structure
            if isinstance(account_status, dict):
                is_authenticated = account_status.get("authenticated", False)
                token_exists = account_status.get("token_exists", False)
            else:
                is_authenticated = False
                token_exists = False

            if is_authenticated:
                status_text = click.style("Authenticated", fg="green")
                email = auth.get_account_email(account_id)
                # Use email as the primary label when available
                if email:
                    account_label = email
                else:
                    account_label = account_id
                    needs_reauth_for_email = True
            else:
                account_label = account_id
                if token_exists:
                    status_text = click.style("Token expired or invalid", fg="yellow")
                else:
                    status_text = click.style("Not authenticated", fg="red")

            click.echo(f"{account_label}: {status_text}")

        if needs_reauth_for_email:
            click.echo(
                click.style(
                    "\nTip: Re-authenticate with --force to display email addresses.",
                    fg="cyan",
                )
            )

        click.echo()

        # Sync status (if database exists)
        db_path = config_dir / "sync.db"
        if db_path.exists():
            from gcontact_sync.storage.db import SyncDatabase

            db = SyncDatabase(str(db_path))
            db.initialize()

            click.echo("=== Sync Status ===\n")

            mapping_count = db.get_mapping_count()
            click.echo(f"Contact mappings: {mapping_count}")

            for account_id in (ACCOUNT_1, ACCOUNT_2):
                # Use email address for display if available
                account_label = auth.get_account_email(account_id) or account_id
                state = db.get_sync_state(account_id)
                if state:
                    last_sync = state.get("last_sync_at")
                    has_token = bool(state.get("sync_token"))
                    click.echo(
                        f"{account_label}: Last sync: {last_sync or 'Never'}, "
                        f"Sync token: {'Yes' if has_token else 'No'}"
                    )
                else:
                    click.echo(f"{account_label}: Never synced")
        else:
            click.echo("Sync database: Not initialized (no syncs performed yet)")

        click.echo()

        # Check if ready to sync
        auth1 = auth.is_authenticated(ACCOUNT_1)
        auth2 = auth.is_authenticated(ACCOUNT_2)

        if auth1 and auth2:
            click.echo(click.style("Ready to sync!", fg="green"))
            click.echo("Run 'gcontact-sync sync' to synchronize contacts.")
        elif not auth_status["credentials_exist"]:
            click.echo(
                click.style("Setup required: OAuth credentials not found.", fg="yellow")
            )
            click.echo("Please download credentials from Google Cloud Console")
            click.echo(f"and save to: {auth_status['credentials_path']}")
        else:
            missing = []
            if not auth1:
                missing.append(ACCOUNT_1)
            if not auth2:
                missing.append(ACCOUNT_2)
            click.echo(
                click.style(
                    f"Authentication required for: {', '.join(missing)}", fg="yellow"
                )
            )
            for acc in missing:
                click.echo(f"  Run: gcontact-sync auth --account {acc}")

    except Exception as e:
        logger.exception(f"Error getting status: {e}")
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)


# =============================================================================
# Init-Config Command
# =============================================================================


@cli.command("init-config")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Overwrite existing configuration file if it exists.",
)
@click.pass_context
def init_config_command(ctx: click.Context, force: bool) -> None:
    """
    Generate a default configuration file.

    Creates a configuration file with all available options documented
    and commented out. You can then uncomment and modify the options
    you want to use.

    Examples:

        # Create config file (fails if already exists)
        gcontact-sync init-config

        # Overwrite existing config file
        gcontact-sync init-config --force
    """
    logger = get_logger(__name__)
    config_file = ctx.obj["config_file"]

    click.echo(f"Creating configuration file: {config_file}")

    success, error = save_config_file(config_file, overwrite=force)

    if success:
        click.echo(click.style("Configuration file created successfully!", fg="green"))
        click.echo(f"\nLocation: {config_file}")
        click.echo("\nNext steps:")
        click.echo("1. Edit the file to uncomment and configure desired options")
        click.echo("2. Run 'gcontact-sync --help' to see available commands")
        logger.info(f"Created configuration file: {config_file}")
    else:
        click.echo(click.style(f"Error: {error}", fg="red"), err=True)
        logger.error(f"Failed to create configuration file: {error}")
        sys.exit(1)


# =============================================================================
# Sync Command
# =============================================================================


@cli.command("sync")
@click.option(
    "--dry-run", "-n", is_flag=True, help="Preview changes without applying them."
)
@click.option(
    "--full", "-f", is_flag=True, help="Force full sync (ignore sync tokens)."
)
@click.option(
    "--strategy",
    "-s",
    type=click.Choice(["last_modified", "account1", "account2"], case_sensitive=False),
    default="last_modified",
    help="Conflict resolution strategy (default: last_modified).",
)
@click.option(
    "--debug",
    "-d",
    is_flag=True,
    help="Show debug info: sample matches and unmatched contacts.",
)
@click.option(
    "--no-backup",
    is_flag=True,
    help="Skip automatic backup before sync (not recommended).",
)
@click.pass_context
def sync_command(
    ctx: click.Context,
    dry_run: bool,
    full: bool,
    strategy: str,
    debug: bool,
    no_backup: bool,
) -> None:
    """
    Synchronize contacts and groups between accounts.

    Performs bidirectional sync to ensure both Google accounts have
    identical contacts and contact groups (labels). A backup is created
    automatically before each sync unless --no-backup is used. Groups are
    synced first to ensure membership mappings work correctly. Contacts and
    groups only in one account are copied to the other. Conflicting
    edits are resolved using the configured strategy.

    Examples:

        # Preview changes without applying
        gcontact-sync sync --dry-run

        # Force full sync
        gcontact-sync sync --full

        # Use specific conflict strategy
        gcontact-sync sync --strategy account1

        # Show debug info with sample matches
        gcontact-sync sync --dry-run --debug

        # Skip automatic backup (not recommended)
        gcontact-sync sync --no-backup
    """
    logger = get_logger(__name__)
    config_dir = ctx.obj["config_dir"]
    verbose = ctx.obj["verbose"]

    # Get config from context
    config = ctx.obj.get("config", {})

    # Merge with config: CLI args take precedence
    # For boolean flags, if CLI is True, use it; otherwise check config
    effective_dry_run = dry_run or config.get("dry_run", False)
    effective_full = full or config.get("full", False)
    effective_debug = debug or config.get("debug", False)

    # Backup configuration
    # If --no-backup is specified, disable backup regardless of config
    # Otherwise, use config setting (default: True)
    if no_backup:
        effective_backup_enabled = False
    else:
        effective_backup_enabled = config.get("backup_enabled", True)

    # Get backup directory and retention count from config
    backup_dir_config = config.get("backup_dir")
    backup_dir = (
        Path(backup_dir_config).expanduser()
        if backup_dir_config
        else config_dir / "backups"
    )
    backup_retention_count = config.get("backup_retention_count", 10)

    # For strategy, use config default if CLI used default value
    effective_strategy = strategy
    if strategy == "last_modified" and "strategy" in config:
        config_strategy = config["strategy"]
        # Map config strategy names to CLI strategy names
        strategy_mapping = {
            "last_modified": "last_modified",
            "newest": "last_modified",  # Alias for last_modified
            "account1": "account1",
            "account2": "account2",
        }
        effective_strategy = strategy_mapping.get(config_strategy, strategy)

    # Map strategy string to enum
    strategy_map = {
        "last_modified": ConflictStrategy.LAST_MODIFIED_WINS,
        "account1": ConflictStrategy.ACCOUNT1_WINS,
        "account2": ConflictStrategy.ACCOUNT2_WINS,
    }
    conflict_strategy = strategy_map[effective_strategy]

    try:
        # Initialize authentication
        auth = GoogleAuth(config_dir=config_dir)

        # Check authentication for both accounts
        click.echo("Checking authentication...")

        creds1 = auth.get_credentials(ACCOUNT_1)
        creds2 = auth.get_credentials(ACCOUNT_2)

        if not creds1:
            click.echo(
                click.style(f"Error: {ACCOUNT_1} is not authenticated.", fg="red"),
                err=True,
            )
            click.echo(f"Run: gcontact-sync auth --account {ACCOUNT_1}", err=True)
            sys.exit(1)

        if not creds2:
            click.echo(
                click.style(f"Error: {ACCOUNT_2} is not authenticated.", fg="red"),
                err=True,
            )
            click.echo(f"Run: gcontact-sync auth --account {ACCOUNT_2}", err=True)
            sys.exit(1)

        # Get actual email addresses for better logging
        account1_email = auth.get_account_email(ACCOUNT_1) or ACCOUNT_1
        account2_email = auth.get_account_email(ACCOUNT_2) or ACCOUNT_2

        click.echo(click.style(f"  {account1_email}", fg="green"))
        click.echo(click.style(f"  {account2_email}", fg="green"))

        # Initialize components
        import os

        from gcontact_sync.api.people_api import PeopleAPI
        from gcontact_sync.storage.db import SyncDatabase
        from gcontact_sync.sync.engine import SyncEngine
        from gcontact_sync.sync.matcher import MatchConfig

        # Ensure database directory exists
        db_path = config_dir / "sync.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize API clients and database
        api1 = PeopleAPI(credentials=creds1)
        api2 = PeopleAPI(credentials=creds2)
        database = SyncDatabase(str(db_path))
        database.initialize()

        # Load sync configuration for tag-based filtering
        sync_config = None
        try:
            sync_config = load_sync_config(config_dir)
            if sync_config.has_any_filter():
                logger.info("Sync config loaded with group filtering enabled")
                if sync_config.account1.has_filter():
                    logger.debug(
                        f"Account1 filter groups: {sync_config.account1.sync_groups}"
                    )
                if sync_config.account2.has_filter():
                    logger.debug(
                        f"Account2 filter groups: {sync_config.account2.sync_groups}"
                    )
            else:
                logger.debug("Sync config loaded with no group filtering (sync all)")
        except SyncConfigError as e:
            # Log warning but continue without filtering (backwards compatible)
            logger.warning(f"Failed to load sync config, syncing all contacts: {e}")
            click.echo(
                click.style(f"Warning: Sync config error: {e}", fg="yellow"), err=True
            )

        # Build MatchConfig from config file settings
        # Resolve Anthropic API key with priority:
        # 1. anthropic_api_key in config (direct key - not recommended)
        # 2. anthropic_api_key_env in config (custom env var name)
        # 3. None (LLMMatcher will use default ANTHROPIC_API_KEY env var)
        anthropic_api_key = config.get("anthropic_api_key")
        if not anthropic_api_key:
            env_var_name = config.get("anthropic_api_key_env")
            if env_var_name:
                anthropic_api_key = os.environ.get(env_var_name)

        match_config = MatchConfig(
            name_similarity_threshold=config.get("name_similarity_threshold", 0.85),
            name_only_threshold=config.get("name_only_threshold", 0.95),
            uncertain_threshold=config.get("uncertain_threshold", 0.7),
            use_llm_matching=True,
            llm_batch_size=config.get("llm_batch_size", 20),
            use_organization_matching=config.get("use_organization_matching", True),
            anthropic_api_key=anthropic_api_key,
            llm_model=config.get("llm_model", "claude-haiku-4-5-20250514"),
            llm_max_tokens=config.get("llm_max_tokens", 500),
            llm_batch_max_tokens=config.get("llm_batch_max_tokens", 2000),
        )

        # Create sync engine with account emails for better logging
        duplicate_handling = config.get("duplicate_handling", "skip")
        engine = SyncEngine(
            api1=api1,
            api2=api2,
            database=database,
            conflict_strategy=conflict_strategy,
            account1_email=account1_email,
            account2_email=account2_email,
            match_config=match_config,
            duplicate_handling=duplicate_handling,
            config=sync_config,
        )

        # Store account emails in context for summary display
        ctx.obj["account1_email"] = account1_email
        ctx.obj["account2_email"] = account2_email

        # Show sync configuration
        if verbose:
            click.echo("\nSync configuration:")
            click.echo(f"  Database: {db_path}")
            click.echo(f"  Conflict strategy: {effective_strategy}")
            click.echo(f"  Full sync: {effective_full}")
            click.echo(f"  Dry run: {effective_dry_run}")

            # Show group filtering configuration
            if sync_config and sync_config.has_any_filter():
                click.echo("  Group filtering: Enabled")
                if sync_config.account1.has_filter():
                    groups1 = ", ".join(sync_config.account1.sync_groups)
                    click.echo(f"    {account1_email}: {groups1}")
                else:
                    click.echo(f"    {account1_email}: (all contacts)")
                if sync_config.account2.has_filter():
                    groups2 = ", ".join(sync_config.account2.sync_groups)
                    click.echo(f"    {account2_email}: {groups2}")
                else:
                    click.echo(f"    {account2_email}: (all contacts)")
            else:
                click.echo("  Group filtering: Disabled (sync all contacts)")
            click.echo()

        # Run sync
        mode = "Analyzing" if effective_dry_run else "Synchronizing"
        click.echo(f"\n{mode} contacts and groups...")

        result = engine.sync(
            dry_run=effective_dry_run,
            full_sync=effective_full,
            backup_enabled=effective_backup_enabled,
            backup_dir=backup_dir,
            backup_retention_count=backup_retention_count,
        )

        # Display results with actual email addresses
        click.echo("\n" + "=" * 50)
        click.echo(
            result.summary(account1_label=account1_email, account2_label=account2_email)
        )
        click.echo("=" * 50)

        if result.has_changes():
            if effective_dry_run:
                click.echo(
                    click.style(
                        "\nDry run complete. No changes were made.", fg="yellow"
                    )
                )
                click.echo("Run without --dry-run to apply these changes.")

                # Show detailed changes if verbose
                if verbose:
                    show_detailed_changes(result, account1_email, account2_email)
            else:
                click.echo(click.style("\nSync completed successfully!", fg="green"))
                stats = result.stats
                # Log summary including groups if any group operations occurred
                if stats.has_group_changes:
                    logger.info(
                        f"Sync completed: "
                        f"groups (created={stats.total_groups_created}, "
                        f"updated={stats.total_groups_updated}, "
                        f"deleted={stats.total_groups_deleted}), "
                        f"contacts (created={stats.total_contacts_created}, "
                        f"updated={stats.total_contacts_updated}, "
                        f"deleted={stats.total_contacts_deleted})"
                    )
                else:
                    logger.info(
                        f"Sync completed: "
                        f"created {stats.total_contacts_created}, "
                        f"updated {stats.total_contacts_updated}, "
                        f"deleted {stats.total_contacts_deleted}"
                    )

                if stats.errors > 0:
                    click.echo(
                        click.style(
                            f"\nWarning: {result.stats.errors} errors occurred.",
                            fg="yellow",
                        )
                    )
        else:
            click.echo(
                click.style(
                    "\nAccounts are already in sync. No changes needed.", fg="green"
                )
            )

        # Show conflict details if any
        if result.conflicts and verbose:
            click.echo("\n=== Conflicts Resolved ===")
            for conflict in result.conflicts:
                click.echo(f"  {conflict.winner.display_name}: {conflict.reason}")

        # Show debug information if requested
        if effective_debug:
            show_debug_info(result, account1_email, account2_email)

    except Exception as e:
        logger.exception(f"Sync failed: {e}")
        click.echo(click.style(f"\nSync failed: {e}", fg="red"), err=True)
        sys.exit(1)


# =============================================================================
# Reset Command
# =============================================================================


@cli.command("reset")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def reset_command(ctx: click.Context, yes: bool) -> None:
    """
    Reset sync state (forces full sync on next run).

    Clears all sync tokens and contact mappings from the database.
    This does NOT delete contacts from either account.

    Example:

        gcontact-sync reset
    """
    logger = get_logger(__name__)
    config_dir = ctx.obj["config_dir"]

    db_path = config_dir / "sync.db"

    if not db_path.exists():
        click.echo("No sync database found. Nothing to reset.")
        return

    if not yes:
        click.confirm(
            "This will clear all sync state and force a full sync on next run.\n"
            "Continue?",
            abort=True,
        )

    try:
        from gcontact_sync.storage.db import SyncDatabase

        db = SyncDatabase(str(db_path))
        db.initialize()
        db.clear_all_state()
        db.vacuum()

        click.echo(click.style("Sync state has been reset.", fg="green"))
        click.echo("Next sync will perform a full comparison of both accounts.")
        logger.info("Sync state reset completed")

    except Exception as e:
        logger.exception(f"Reset failed: {e}")
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)


# =============================================================================
# Clear-Auth Command
# =============================================================================


@cli.command("clear-auth")
@click.option(
    "--account",
    "-a",
    type=click.Choice(VALID_ACCOUNTS, case_sensitive=False),
    help="Account to clear (clears both if not specified).",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def clear_auth_command(ctx: click.Context, account: str | None, yes: bool) -> None:
    """
    Clear stored authentication credentials.

    Removes stored OAuth tokens for one or both accounts.
    You will need to re-authenticate before syncing again.

    Examples:

        # Clear specific account
        gcontact-sync clear-auth --account account1

        # Clear both accounts
        gcontact-sync clear-auth
    """
    logger = get_logger(__name__)
    config_dir = ctx.obj["config_dir"]

    if account:
        accounts_to_clear = [account]
        msg = f"Clear authentication for {account}?"
    else:
        accounts_to_clear = list(VALID_ACCOUNTS)
        msg = "Clear authentication for BOTH accounts?"

    if not yes:
        click.confirm(msg, abort=True)

    try:
        auth = GoogleAuth(config_dir=config_dir)

        for acc in accounts_to_clear:
            if auth.clear_credentials(acc):
                click.echo(f"Cleared credentials for {acc}")
                logger.info(f"Cleared credentials for {acc}")
            else:
                click.echo(f"No credentials found for {acc}")

        click.echo(click.style("\nCredentials cleared.", fg="green"))

    except Exception as e:
        logger.exception(f"Clear auth failed: {e}")
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)


# =============================================================================
# List-Groups Command
# =============================================================================


@cli.command("list-groups")
@click.option(
    "--account",
    "-a",
    required=True,
    type=click.Choice(VALID_ACCOUNTS, case_sensitive=False),
    help="Account to list groups from (account1 or account2).",
)
@click.option(
    "--all",
    "-A",
    "show_all",
    is_flag=True,
    help="Show all groups including system groups.",
)
@click.pass_context
def list_groups_command(ctx: click.Context, account: str, show_all: bool) -> None:
    """
    List contact groups for an account.

    Displays all user-created contact groups (labels) for the specified
    Google account. System groups (myContacts, starred) are hidden by default.

    Examples:

        # List groups for account1
        gcontact-sync list-groups --account account1

        # List all groups including system groups
        gcontact-sync list-groups --account account1 --all
    """
    logger = get_logger(__name__)
    config_dir = ctx.obj["config_dir"]
    verbose = ctx.obj["verbose"]

    try:
        # Initialize authentication
        auth = GoogleAuth(config_dir=config_dir)

        # Check authentication
        creds = auth.get_credentials(account)
        if not creds:
            click.echo(
                click.style(f"Error: {account} is not authenticated.", fg="red"),
                err=True,
            )
            click.echo(f"Run: gcontact-sync auth --account {account}", err=True)
            sys.exit(1)

        # Get account email for display
        account_email = auth.get_account_email(account) or account

        click.echo(f"Listing contact groups for {account_email}...")
        click.echo()

        # Initialize API and list groups
        from gcontact_sync.api.people_api import PeopleAPI
        from gcontact_sync.sync.group import ContactGroup

        api = PeopleAPI(credentials=creds)
        groups_data, _ = api.list_contact_groups()

        # Parse and filter groups
        groups = [ContactGroup.from_api_response(g) for g in groups_data]

        if not show_all:
            # Filter to user groups only
            groups = [g for g in groups if g.is_user_group()]

        if not groups:
            if show_all:
                click.echo("No contact groups found.")
            else:
                click.echo("No user contact groups found.")
                click.echo("Use --all to include system groups.")
            return

        # Display groups
        click.echo(f"{'Name':<40} {'Type':<20} {'Members':<10}")
        click.echo("-" * 70)

        for group in sorted(groups, key=lambda g: g.name.lower()):
            group_type = "User" if group.is_user_group() else "System"
            click.echo(f"{group.name:<40} {group_type:<20} {group.member_count:<10}")

        click.echo()
        click.echo(f"Total: {len(groups)} group(s)")

        if verbose:
            click.echo()
            click.echo("Resource names:")
            for group in sorted(groups, key=lambda g: g.name.lower()):
                click.echo(f"  {group.name}: {group.resource_name}")

    except Exception as e:
        logger.exception(f"Failed to list groups: {e}")
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)


# =============================================================================
# Create-Group Command
# =============================================================================


@cli.command("create-group")
@click.argument("name")
@click.option(
    "--account",
    "-a",
    type=click.Choice(VALID_ACCOUNTS, case_sensitive=False),
    help="Account to create group in (creates in both if not specified).",
)
@click.pass_context
def create_group_command(ctx: click.Context, name: str, account: str | None) -> None:
    """
    Create a new contact group.

    Creates a contact group with the specified NAME. By default, the group
    is created in both accounts. Use --account to create in only one account.

    Examples:

        # Create group in both accounts
        gcontact-sync create-group "Work"

        # Create group in specific account
        gcontact-sync create-group "Family" --account account1
    """
    logger = get_logger(__name__)
    config_dir = ctx.obj["config_dir"]

    # Determine which accounts to create in
    accounts_to_create = [account] if account else list(VALID_ACCOUNTS)

    try:
        # Initialize authentication
        auth = GoogleAuth(config_dir=config_dir)

        # Import API module
        from gcontact_sync.api.people_api import PeopleAPI, PeopleAPIError

        created_count = 0
        errors: list[str] = []

        for acc in accounts_to_create:
            # Check authentication
            creds = auth.get_credentials(acc)
            if not creds:
                errors.append(f"{acc}: Not authenticated")
                continue

            # Get account email for display
            account_email = auth.get_account_email(acc) or acc

            click.echo(f"Creating group '{name}' in {account_email}...")

            try:
                api = PeopleAPI(credentials=creds)
                result = api.create_contact_group(name)
                resource_name = result.get("resourceName", "unknown")
                click.echo(
                    click.style(
                        f"  Created: {resource_name}",
                        fg="green",
                    )
                )
                created_count += 1
                logger.info(f"Created group '{name}' in {acc}: {resource_name}")

            except PeopleAPIError as e:
                error_msg = str(e)
                if "already exists" in error_msg.lower():
                    click.echo(
                        click.style(
                            f"  Group '{name}' already exists in {account_email}",
                            fg="yellow",
                        )
                    )
                else:
                    errors.append(f"{account_email}: {error_msg}")
                    click.echo(click.style(f"  Error: {error_msg}", fg="red"))

        # Summary
        click.echo()
        if created_count > 0:
            msg = f"Successfully created group '{name}' in {created_count} account(s)."
            click.echo(click.style(msg, fg="green"))
        elif not errors:
            click.echo(
                click.style(
                    f"Group '{name}' already exists in all specified accounts.",
                    fg="yellow",
                )
            )

        if errors:
            for error in errors:
                click.echo(click.style(f"Error: {error}", fg="red"), err=True)
            sys.exit(1)

    except Exception as e:
        logger.exception(f"Failed to create group: {e}")
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)


# =============================================================================
# Delete-Group Command
# =============================================================================


@cli.command("delete-group")
@click.argument("name")
@click.option(
    "--account",
    "-a",
    type=click.Choice(VALID_ACCOUNTS, case_sensitive=False),
    help="Account to delete group from (deletes from both if not specified).",
)
@click.option(
    "--delete-contacts",
    is_flag=True,
    help="Also delete all contacts in the group (default: preserve contacts).",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def delete_group_command(
    ctx: click.Context,
    name: str,
    account: str | None,
    delete_contacts: bool,
    yes: bool,
) -> None:
    """
    Delete a contact group.

    Deletes the contact group with the specified NAME. By default, the group
    is deleted from both accounts. Use --account to delete from only one account.

    Contacts in the group are preserved by default (they remain in myContacts).
    Use --delete-contacts to also delete all contacts in the group.

    Examples:

        # Delete group from both accounts
        gcontact-sync delete-group "Old Group"

        # Delete group from specific account
        gcontact-sync delete-group "Work" --account account1

        # Delete group and its contacts
        gcontact-sync delete-group "Temp" --delete-contacts
    """
    logger = get_logger(__name__)
    config_dir = ctx.obj["config_dir"]

    # Determine which accounts to delete from
    accounts_to_delete = [account] if account else list(VALID_ACCOUNTS)

    # Confirmation prompt
    if not yes:
        warning_msg = f"Delete group '{name}'"
        if delete_contacts:
            warning_msg += " AND all contacts in it"
        if not account:
            warning_msg += " from BOTH accounts"
        else:
            warning_msg += f" from {account}"
        warning_msg += "?"

        click.confirm(warning_msg, abort=True)

    try:
        # Initialize authentication
        auth = GoogleAuth(config_dir=config_dir)

        # Import API module
        from gcontact_sync.api.people_api import PeopleAPI, PeopleAPIError
        from gcontact_sync.sync.group import ContactGroup

        deleted_count = 0
        not_found_count = 0
        errors: list[str] = []

        for acc in accounts_to_delete:
            # Check authentication
            creds = auth.get_credentials(acc)
            if not creds:
                errors.append(f"{acc}: Not authenticated")
                continue

            # Get account email for display
            account_email = auth.get_account_email(acc) or acc

            click.echo(f"Deleting group '{name}' from {account_email}...")

            try:
                api = PeopleAPI(credentials=creds)

                # First, find the group by name
                groups_data, _ = api.list_contact_groups()
                groups = [ContactGroup.from_api_response(g) for g in groups_data]

                # Find matching group (case-insensitive)
                target_group = None
                for group in groups:
                    if group.name.lower() == name.lower() and group.is_user_group():
                        target_group = group
                        break

                if not target_group:
                    click.echo(
                        click.style(
                            f"  Group '{name}' not found in {account_email}",
                            fg="yellow",
                        )
                    )
                    not_found_count += 1
                    continue

                # Delete the group
                api.delete_contact_group(
                    target_group.resource_name,
                    delete_contacts=delete_contacts,
                )
                click.echo(
                    click.style(
                        f"  Deleted: {target_group.resource_name}",
                        fg="green",
                    )
                )
                deleted_count += 1
                logger.info(
                    f"Deleted group '{name}' from {acc}: {target_group.resource_name}"
                )

            except PeopleAPIError as e:
                error_msg = str(e)
                errors.append(f"{account_email}: {error_msg}")
                click.echo(click.style(f"  Error: {error_msg}", fg="red"))

        # Summary
        click.echo()
        if deleted_count > 0:
            msg = f"Deleted group '{name}' from {deleted_count} account(s)."
            click.echo(click.style(msg, fg="green"))
        elif not_found_count == len(accounts_to_delete):
            click.echo(
                click.style(
                    f"Group '{name}' was not found in any specified account.",
                    fg="yellow",
                )
            )

        if errors:
            for error in errors:
                click.echo(click.style(f"Error: {error}", fg="red"), err=True)
            sys.exit(1)

    except Exception as e:
        logger.exception(f"Failed to delete group: {e}")
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)


# =============================================================================
# Health Command
# =============================================================================


@cli.command("health")
def health_command() -> None:
    """
    Check application health status.

    Returns a simple health status indicator. Useful for container
    health checks and monitoring.

    Example:

        gcontact-sync health
    """
    click.echo("healthy")


# =============================================================================
# Restore Command
# =============================================================================


@cli.command("restore")
@click.option(
    "--backup-file",
    "-b",
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    help="Path to specific backup file to restore from.",
)
@click.option(
    "--list",
    "-l",
    "list_backups_flag",
    is_flag=True,
    help="List available backup files.",
)
@click.option(
    "--account",
    "-a",
    type=click.Choice(VALID_ACCOUNTS, case_sensitive=False),
    help="Account to restore to (restores to both if not specified).",
)
@click.option(
    "--dry-run", "-n", is_flag=True, help="Preview restore without applying changes."
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def restore_command(
    ctx: click.Context,
    backup_file: str | None,
    list_backups_flag: bool,
    account: str | None,
    dry_run: bool,
    yes: bool,
) -> None:
    """
    Restore contacts from a backup file.

    Restores contacts and groups from a previously created backup.
    By default, restores to both accounts. Use --account to restore
    to a specific account only.

    Without --backup-file, lists available backups to choose from.

    Examples:

        # List available backups
        gcontact-sync restore --list

        # Restore from specific backup to both accounts
        gcontact-sync restore --backup-file backup_20240120_103000.json

        # Preview restore without applying
        gcontact-sync restore --backup-file backup.json --dry-run

        # Restore to specific account
        gcontact-sync restore --backup-file backup.json --account account1
    """
    logger = get_logger(__name__)
    config_dir = ctx.obj["config_dir"]
    config = ctx.obj.get("config", {})

    # Get backup directory from config or use default
    backup_dir_config = config.get("backup_dir")
    backup_dir = (
        Path(backup_dir_config).expanduser()
        if backup_dir_config
        else config_dir / "backups"
    )

    try:
        from gcontact_sync.backup.manager import BackupManager

        # Initialize backup manager
        bm = BackupManager(backup_dir)

        # If --list flag is set or no backup file specified, list backups
        if list_backups_flag or not backup_file:
            backups = bm.list_backups()

            if not backups:
                click.echo("No backups found.")
                click.echo(f"Backup directory: {backup_dir}")
                return

            click.echo(f"Available backups in {backup_dir}:\n")
            click.echo(f"{'Filename':<40} {'Date':<20} {'Size':<10}")
            click.echo("-" * 70)

            for backup_path in backups:
                # Extract timestamp from filename
                filename = backup_path.name
                size = backup_path.stat().st_size
                size_kb = size / 1024

                # Try to get timestamp from backup content
                backup_data = bm.load_backup(backup_path)
                if backup_data and "timestamp" in backup_data:
                    timestamp = backup_data["timestamp"]
                else:
                    # Fallback to file modification time
                    from datetime import datetime

                    mtime = backup_path.stat().st_mtime
                    timestamp = datetime.fromtimestamp(mtime).isoformat()

                click.echo(f"{filename:<40} {timestamp[:19]:<20} {size_kb:>8.1f} KB")

            click.echo(f"\nTotal: {len(backups)} backup(s)")
            click.echo("\nTo restore, use: gcontact-sync restore --backup-file <path>")
            return

        # Load the specified backup file
        backup_path = Path(backup_file)
        click.echo(f"Loading backup from {backup_path}...")

        backup_data = bm.load_backup(backup_path)
        if not backup_data:
            click.echo(
                click.style(
                    f"Error: Failed to load backup file: {backup_path}", fg="red"
                ),
                err=True,
            )
            sys.exit(1)

        # Display backup info
        timestamp = backup_data.get("timestamp", "Unknown")
        version = backup_data.get("version", "Unknown")

        click.echo(f"Backup version: {version}")
        click.echo(f"Backup timestamp: {timestamp}")

        # Determine which accounts to restore to
        accounts_to_restore = [account] if account else list(VALID_ACCOUNTS)

        # Get contact/group counts per account for v2.0 format
        if version == "2.0":
            accounts_data = backup_data.get("accounts", {})
            for acc_key in accounts_to_restore:
                acc_data = accounts_data.get(acc_key, {})
                acc_email = acc_data.get("email", acc_key)
                acc_contacts = acc_data.get("contacts", [])
                acc_groups = acc_data.get("groups", [])
                click.echo(f"\n{acc_email}:")
                click.echo(f"  Contacts: {len(acc_contacts)}")
                click.echo(f"  Groups: {len(acc_groups)}")
        else:
            # Legacy v1.0 format
            contacts = backup_data.get("contacts", [])
            groups = backup_data.get("groups", [])
            click.echo(f"Contacts: {len(contacts)}")
            click.echo(f"Groups: {len(groups)}")

        click.echo()

        # Calculate total contacts/groups for confirmation
        total_contacts = 0
        total_groups = 0
        if version == "2.0":
            for acc_key in accounts_to_restore:
                acc_data = backup_data.get("accounts", {}).get(acc_key, {})
                total_contacts += len(acc_data.get("contacts", []))
                total_groups += len(acc_data.get("groups", []))
        else:
            total_contacts = len(backup_data.get("contacts", []))
            total_groups = len(backup_data.get("groups", []))

        # Confirmation prompt
        if not yes and not dry_run:
            warning_msg = f"Restore {total_contacts} contacts and {total_groups} groups"
            if not account:
                warning_msg += " to BOTH accounts"
            else:
                warning_msg += f" to {account}"
            warning_msg += "?"

            click.confirm(warning_msg, abort=True)

        if dry_run:
            click.echo(
                click.style("\nDry run mode - no changes will be made.", fg="yellow")
            )
            click.echo(
                f"\nWould restore to account(s): {', '.join(accounts_to_restore)}"
            )

            # Show sample of contacts that would be restored for each account
            for acc_key in accounts_to_restore:
                contacts_list = bm.get_contacts_for_restore(backup_data, acc_key)
                if contacts_list:
                    click.echo(f"\nSample contacts for {acc_key} (first 5):")
                    for contact in contacts_list[:5]:
                        click.echo(f"  - {contact.display_name}")
                        if contact.emails:
                            click.echo(f"    Emails: {', '.join(contact.emails[:2])}")

            click.echo(
                click.style(
                    "\nDry run complete. Use without --dry-run to apply restore.",
                    fg="green",
                )
            )
            return

        # Perform actual restore
        click.echo("\nInitializing restore...")

        # Initialize authentication
        auth = GoogleAuth(config_dir=config_dir)

        from gcontact_sync.api.people_api import PeopleAPI

        # Map account keys to credentials
        account_apis: dict[str, PeopleAPI] = {}
        for acc_key in accounts_to_restore:
            creds = auth.get_credentials(acc_key)
            if not creds:
                click.echo(
                    click.style(f"Error: {acc_key} is not authenticated.", fg="red"),
                    err=True,
                )
                click.echo(f"Run: gcontact-sync auth --account {acc_key}", err=True)
                sys.exit(1)
            account_apis[acc_key] = PeopleAPI(credentials=creds)

        # Restore each account
        for acc_key in accounts_to_restore:
            api = account_apis[acc_key]
            acc_email = auth.get_account_email(acc_key) or acc_key

            click.echo(f"\nRestoring to {acc_email}...")

            # Get contacts and groups to restore
            contacts_to_restore = bm.get_contacts_for_restore(backup_data, acc_key)
            groups_to_restore = bm.get_groups_for_restore(backup_data, acc_key)

            # Restore groups first (contacts may reference them)
            groups_created = 0
            groups_failed = 0
            for group in groups_to_restore:
                # Skip system groups
                if group.group_type != "USER_CONTACT_GROUP":
                    continue
                try:
                    api.create_contact_group(group.name)
                    groups_created += 1
                    logger.debug(f"Restored group: {group.name}")
                except Exception as e:
                    # Group may already exist
                    if "already exists" in str(e):
                        logger.debug(f"Group already exists: {group.name}")
                    else:
                        groups_failed += 1
                        logger.warning(f"Failed to restore group {group.name}: {e}")

            click.echo(f"  Groups: {groups_created} created, {groups_failed} failed")

            # Restore contacts
            contacts_created = 0
            contacts_failed = 0
            for contact in contacts_to_restore:
                try:
                    # Create contact (resource_name will be assigned by Google)
                    api.create_contact(contact)
                    contacts_created += 1
                    logger.debug(f"Restored contact: {contact.display_name}")
                except Exception as e:
                    contacts_failed += 1
                    logger.warning(
                        f"Failed to restore contact {contact.display_name}: {e}"
                    )

            click.echo(
                f"  Contacts: {contacts_created} created, {contacts_failed} failed"
            )

        click.echo(click.style("\nRestore complete!", fg="green"))
        logger.info(f"Restore completed from {backup_path}")

    except Exception as e:
        logger.exception(f"Restore failed: {e}")
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)


# =============================================================================
# Daemon Command Group
# =============================================================================


@cli.group("daemon")
@click.pass_context
def daemon_group(ctx: click.Context) -> None:
    """
    Manage background synchronization daemon.

    The daemon runs in the background and automatically synchronizes
    contacts at a configurable interval.

    Examples:

        # Start daemon in foreground (for testing)
        gcontact-sync daemon start --foreground

        # Start daemon with custom interval
        gcontact-sync daemon start --interval 30m

        # Check daemon status
        gcontact-sync daemon status

        # Stop running daemon
        gcontact-sync daemon stop
    """
    # Daemon group passes context through to subcommands
    pass


@daemon_group.command("start")
@click.option(
    "--interval",
    "-i",
    default=None,
    help=(
        "Sync interval (e.g., '30s', '5m', '1h', '1d'). "
        "Defaults to config value or '1h'."
    ),
)
@click.option(
    "--foreground",
    "-f",
    is_flag=True,
    help="Run in foreground instead of daemonizing (useful for debugging).",
)
@click.option(
    "--no-initial-sync",
    is_flag=True,
    help="Skip the initial sync on daemon startup.",
)
@click.pass_context
def daemon_start_command(
    ctx: click.Context,
    interval: str | None,
    foreground: bool,
    no_initial_sync: bool,
) -> None:
    """
    Start the synchronization daemon.

    Runs the sync process continuously in the background (or foreground
    with --foreground flag) at the specified interval.

    The daemon will:
    - Perform an initial sync on startup (unless --no-initial-sync)
    - Continue syncing at the specified interval
    - Handle SIGTERM/SIGINT for graceful shutdown
    - Write a PID file for daemon management

    Examples:

        # Start daemon in foreground with verbose output
        gcontact-sync -v daemon start --foreground

        # Start with 30-minute sync interval
        gcontact-sync daemon start --interval 30m

        # Start without initial sync
        gcontact-sync daemon start --no-initial-sync

        # Start with 1 hour interval (default)
        gcontact-sync daemon start
    """
    logger = get_logger(__name__)
    config_dir = ctx.obj["config_dir"]
    config = ctx.obj.get("config", {})
    verbose = ctx.obj["verbose"]

    # Import daemon components
    from gcontact_sync.daemon import (
        DaemonAlreadyRunningError,
        DaemonError,
        DaemonScheduler,
        parse_interval,
    )

    # Resolve interval: CLI > config > default
    effective_interval_str = interval or config.get("daemon_interval", "1h")
    try:
        interval_seconds = parse_interval(effective_interval_str)
    except ValueError as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)

    # Get PID file from config or use default
    pid_file = None
    if config.get("daemon_pid_file"):
        pid_file = Path(config["daemon_pid_file"]).expanduser()

    click.echo(f"Starting daemon with {effective_interval_str} sync interval...")

    if foreground:
        click.echo("Running in foreground mode (Ctrl+C to stop)")
    else:
        click.echo("Running in background mode")

    if verbose:
        click.echo(f"  Config directory: {config_dir}")
        click.echo(f"  Interval: {interval_seconds} seconds")
        click.echo(f"  Initial sync: {'No' if no_initial_sync else 'Yes'}")

    try:
        # Create the scheduler
        scheduler = DaemonScheduler(
            interval=interval_seconds,
            pid_file=pid_file,
            run_immediately=not no_initial_sync,
        )

        # Set up sync callback using existing sync infrastructure
        def sync_callback() -> bool:
            """Execute a sync operation and return success status."""
            import os

            from gcontact_sync.api.people_api import PeopleAPI
            from gcontact_sync.storage.db import SyncDatabase
            from gcontact_sync.sync.conflict import ConflictStrategy
            from gcontact_sync.sync.engine import SyncEngine
            from gcontact_sync.sync.matcher import MatchConfig

            try:
                # Initialize authentication
                auth = GoogleAuth(config_dir=config_dir)

                # Check authentication for both accounts
                creds1 = auth.get_credentials(ACCOUNT_1)
                creds2 = auth.get_credentials(ACCOUNT_2)

                if not creds1 or not creds2:
                    logger.error("One or both accounts not authenticated")
                    return False

                # Get account emails for logging
                account1_email = auth.get_account_email(ACCOUNT_1) or ACCOUNT_1
                account2_email = auth.get_account_email(ACCOUNT_2) or ACCOUNT_2

                # Initialize components
                db_path = config_dir / "sync.db"
                db_path.parent.mkdir(parents=True, exist_ok=True)

                api1 = PeopleAPI(credentials=creds1)
                api2 = PeopleAPI(credentials=creds2)
                database = SyncDatabase(str(db_path))
                database.initialize()

                # Load sync configuration for tag-based filtering
                sync_config = None
                try:
                    sync_config = load_sync_config(config_dir)
                    if sync_config.has_any_filter():
                        logger.info("Sync config loaded with group filtering enabled")
                        if sync_config.account1.has_filter():
                            logger.debug(
                                f"Account1 filter groups: "
                                f"{sync_config.account1.sync_groups}"
                            )
                        if sync_config.account2.has_filter():
                            logger.debug(
                                f"Account2 filter groups: "
                                f"{sync_config.account2.sync_groups}"
                            )
                    else:
                        logger.debug(
                            "Sync config loaded with no group filtering (sync all)"
                        )
                except SyncConfigError as e:
                    # Log warning but continue without filtering (backwards compatible)
                    logger.warning(f"Could not load sync config: {e}")
                    logger.info("Continuing with no group filtering")

                # Build MatchConfig from config
                anthropic_api_key = config.get("anthropic_api_key")
                if not anthropic_api_key:
                    env_var_name = config.get("anthropic_api_key_env")
                    if env_var_name:
                        anthropic_api_key = os.environ.get(env_var_name)

                match_config = MatchConfig(
                    name_similarity_threshold=config.get(
                        "name_similarity_threshold", 0.85
                    ),
                    name_only_threshold=config.get("name_only_threshold", 0.95),
                    uncertain_threshold=config.get("uncertain_threshold", 0.7),
                    use_llm_matching=True,
                    llm_batch_size=config.get("llm_batch_size", 20),
                    use_organization_matching=config.get(
                        "use_organization_matching", True
                    ),
                    anthropic_api_key=anthropic_api_key,
                    llm_model=config.get("llm_model", "claude-haiku-4-5-20250514"),
                    llm_max_tokens=config.get("llm_max_tokens", 500),
                    llm_batch_max_tokens=config.get("llm_batch_max_tokens", 2000),
                )

                # Get conflict strategy from config
                strategy_str = config.get("strategy", "last_modified")
                strategy_map = {
                    "last_modified": ConflictStrategy.LAST_MODIFIED_WINS,
                    "newest": ConflictStrategy.LAST_MODIFIED_WINS,
                    "account1": ConflictStrategy.ACCOUNT1_WINS,
                    "account2": ConflictStrategy.ACCOUNT2_WINS,
                }
                conflict_strategy = strategy_map.get(
                    strategy_str, ConflictStrategy.LAST_MODIFIED_WINS
                )

                # Get backup settings from config
                backup_enabled = config.get("backup_enabled", True)
                backup_dir_config = config.get("backup_dir")
                backup_dir = (
                    Path(backup_dir_config).expanduser()
                    if backup_dir_config
                    else config_dir / "backups"
                )
                backup_retention_count = config.get("backup_retention_count", 10)

                # Create sync engine
                engine = SyncEngine(
                    api1=api1,
                    api2=api2,
                    database=database,
                    conflict_strategy=conflict_strategy,
                    account1_email=account1_email,
                    account2_email=account2_email,
                    match_config=match_config,
                    duplicate_handling=config.get("duplicate_handling", "skip"),
                    config=sync_config,
                )

                # Run sync
                result = engine.sync(
                    dry_run=False,
                    full_sync=False,
                    backup_enabled=backup_enabled,
                    backup_dir=backup_dir,
                    backup_retention_count=backup_retention_count,
                )

                created = (
                    result.stats.created_in_account1 + result.stats.created_in_account2
                )
                updated = (
                    result.stats.updated_in_account1 + result.stats.updated_in_account2
                )
                logger.info(
                    f"Sync completed: {created} created, "
                    f"{updated} updated, {result.stats.errors} errors"
                )

                return result.stats.errors == 0

            except Exception as e:
                logger.error(f"Sync failed: {e}")
                return False

        scheduler.set_sync_callback(sync_callback)

        # Run the scheduler (blocks until shutdown signal)
        logger.info(f"Daemon starting (interval={interval_seconds}s)")
        scheduler.run()

        click.echo(click.style("\nDaemon stopped gracefully.", fg="green"))

    except DaemonAlreadyRunningError as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        click.echo("Use 'gcontact-sync daemon stop' to stop the running daemon.")
        sys.exit(1)

    except DaemonError as e:
        logger.error(f"Daemon error: {e}")
        click.echo(click.style(f"Daemon error: {e}", fg="red"), err=True)
        sys.exit(1)

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)


@daemon_group.command("stop")
@click.pass_context
def daemon_stop_command(ctx: click.Context) -> None:
    """
    Stop the running synchronization daemon.

    Sends a SIGTERM signal to the daemon process to initiate
    graceful shutdown. The daemon will complete any in-progress
    sync before exiting.

    Examples:

        # Stop the running daemon
        gcontact-sync daemon stop
    """
    logger = get_logger(__name__)
    config = ctx.obj.get("config", {})

    from gcontact_sync.daemon import DEFAULT_PID_FILE, DaemonScheduler

    # Get PID file from config or use default
    pid_file = None
    if config.get("daemon_pid_file"):
        pid_file = Path(config["daemon_pid_file"]).expanduser()
    else:
        pid_file = DEFAULT_PID_FILE

    # Check if daemon is running
    pid = DaemonScheduler.get_running_pid(pid_file)

    if pid is None:
        click.echo("No daemon is currently running.")
        return

    click.echo(f"Stopping daemon (PID: {pid})...")

    # Send stop signal
    if DaemonScheduler.stop_running_daemon(pid_file):
        click.echo(click.style("Stop signal sent successfully.", fg="green"))
        click.echo("The daemon will shut down after completing any in-progress sync.")
        logger.info(f"Sent stop signal to daemon (PID: {pid})")
    else:
        click.echo(
            click.style("Failed to send stop signal to daemon.", fg="red"), err=True
        )
        sys.exit(1)


@daemon_group.command("status")
@click.pass_context
def daemon_status_command(ctx: click.Context) -> None:
    """
    Show the status of the synchronization daemon.

    Displays whether the daemon is running, its process ID,
    and the PID file location.

    Examples:

        # Check daemon status
        gcontact-sync daemon status
    """
    config = ctx.obj.get("config", {})
    verbose = ctx.obj.get("verbose", False)

    from gcontact_sync.daemon import DEFAULT_PID_FILE, DaemonScheduler, PIDFileManager

    # Get PID file from config or use default
    pid_file = None
    if config.get("daemon_pid_file"):
        pid_file = Path(config["daemon_pid_file"]).expanduser()
    else:
        pid_file = DEFAULT_PID_FILE

    click.echo("=== Daemon Status ===\n")

    # Check if daemon is running
    pid = DaemonScheduler.get_running_pid(pid_file)

    if pid is not None:
        click.echo(f"Status: {click.style('Running', fg='green')}")
        click.echo(f"Process ID: {pid}")
    else:
        # Check if there's a stale PID file
        pid_manager = PIDFileManager(pid_file)
        stale_pid = pid_manager.read()

        if stale_pid is not None:
            click.echo(f"Status: {click.style('Stopped', fg='yellow')}")
            click.echo(f"Stale PID file exists (PID: {stale_pid})")
            click.echo("The daemon process is no longer running.")
            click.echo("\nThe stale PID file will be cleaned up on next daemon start.")
        else:
            click.echo(f"Status: {click.style('Stopped', fg='yellow')}")
            click.echo("No daemon is currently running.")

    if verbose:
        click.echo(f"\nPID file: {pid_file}")

    click.echo()

    # Show next steps
    if pid is None:
        click.echo("To start the daemon, run:")
        click.echo("  gcontact-sync daemon start")
        click.echo("\nOr run in foreground for debugging:")
        click.echo("  gcontact-sync daemon start --foreground")
    else:
        click.echo("To stop the daemon, run:")
        click.echo("  gcontact-sync daemon stop")


@daemon_group.command("install")
@click.option(
    "--interval",
    "-i",
    default=None,
    help=(
        "Sync interval for the service (e.g., '30s', '5m', '1h', '1d'). "
        "Defaults to config value or '1h'."
    ),
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Overwrite existing service file if it exists.",
)
@click.pass_context
def daemon_install_command(
    ctx: click.Context,
    interval: str | None,
    force: bool,
) -> None:
    """
    Install gcontact-sync as a system service.

    Installs the daemon as a systemd user service (Linux) or launchd
    agent (macOS) for automatic background synchronization.

    The service will be configured to:
    - Start automatically on user login
    - Restart on failure
    - Run with the configured sync interval

    Examples:

        # Install with default settings
        gcontact-sync daemon install

        # Install with custom sync interval
        gcontact-sync daemon install --interval 30m

        # Overwrite existing installation
        gcontact-sync daemon install --force
    """
    logger = get_logger(__name__)
    config_dir = ctx.obj["config_dir"]
    config = ctx.obj.get("config", {})
    verbose = ctx.obj.get("verbose", False)

    from gcontact_sync.daemon import (
        ServiceManager,
        get_platform,
        parse_interval,
    )

    # Resolve interval: CLI > config > default
    effective_interval = interval or config.get("daemon_interval", "1h")

    # Validate interval format
    try:
        interval_seconds = parse_interval(effective_interval)
    except ValueError as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)

    # Create service manager
    service_manager = ServiceManager(config_dir=config_dir)

    # Check platform support
    platform = get_platform()
    if not service_manager.is_platform_supported():
        click.echo(
            click.style(
                f"Error: Platform '{platform}' is not supported "
                "for service installation.",
                fg="red",
            ),
            err=True,
        )
        click.echo(
            "Supported platforms: Linux (systemd), macOS (launchd)",
            err=True,
        )
        sys.exit(1)

    click.echo(f"Installing gcontact-sync daemon as a {platform} service...")
    click.echo(f"  Sync interval: {effective_interval} ({interval_seconds} seconds)")

    if verbose:
        click.echo(f"  Config directory: {config_dir}")
        service_path = service_manager.get_service_file_path()
        click.echo(f"  Service file: {service_path}")

    # Install the service
    success, error = service_manager.install(
        interval=effective_interval,
        overwrite=force,
    )

    if success:
        service_path = service_manager.get_service_file_path()
        click.echo(click.style("\nService installed successfully!", fg="green"))
        click.echo(f"\nService file: {service_path}")
        logger.info(f"Daemon service installed at {service_path}")

        # Show platform-specific instructions
        if platform == "linux":
            click.echo("\nTo enable and start the service:")
            click.echo("  systemctl --user enable gcontact-sync")
            click.echo("  systemctl --user start gcontact-sync")
            click.echo("\nTo check service status:")
            click.echo("  systemctl --user status gcontact-sync")
        elif platform == "macos":
            click.echo("\nTo load and start the service:")
            click.echo(f"  launchctl load {service_path}")
            click.echo("\nTo check if the service is running:")
            click.echo("  launchctl list | grep gcontact-sync")
            click.echo("\nThe service is configured to start automatically on login.")
    else:
        click.echo(click.style(f"\nInstallation failed: {error}", fg="red"), err=True)
        logger.error(f"Daemon service installation failed: {error}")
        sys.exit(1)


@daemon_group.command("uninstall")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt.",
)
@click.pass_context
def daemon_uninstall_command(ctx: click.Context, yes: bool) -> None:
    """
    Uninstall the gcontact-sync system service.

    Stops the running service (if any) and removes the service file
    from the system. This does not affect your configuration or
    contact data.

    Examples:

        # Uninstall with confirmation
        gcontact-sync daemon uninstall

        # Uninstall without confirmation
        gcontact-sync daemon uninstall --yes
    """
    logger = get_logger(__name__)
    config_dir = ctx.obj["config_dir"]
    verbose = ctx.obj.get("verbose", False)

    from gcontact_sync.daemon import ServiceManager, get_platform

    # Create service manager
    service_manager = ServiceManager(config_dir=config_dir)

    # Check platform support
    platform = get_platform()
    if not service_manager.is_platform_supported():
        click.echo(
            click.style(
                f"Error: Platform '{platform}' is not supported "
                "for service management.",
                fg="red",
            ),
            err=True,
        )
        sys.exit(1)

    # Check if service is installed
    if not service_manager.is_installed():
        click.echo("No daemon service is currently installed.")
        return

    service_path = service_manager.get_service_file_path()

    if verbose:
        click.echo(f"Service file: {service_path}")

    # Confirmation prompt
    if not yes:
        click.confirm(
            f"Uninstall gcontact-sync daemon service from {platform}?",
            abort=True,
        )

    click.echo("Uninstalling gcontact-sync daemon service...")

    # Uninstall the service
    success, error = service_manager.uninstall()

    if success:
        click.echo(click.style("\nService uninstalled successfully!", fg="green"))
        click.echo(f"Removed: {service_path}")
        logger.info(f"Daemon service uninstalled from {service_path}")
        click.echo("\nYour configuration and contact data are preserved.")
        click.echo("You can reinstall the service anytime with 'daemon install'.")
    else:
        click.echo(click.style(f"\nUninstallation failed: {error}", fg="red"), err=True)
        logger.error(f"Daemon service uninstallation failed: {error}")
        sys.exit(1)


# Module entry point (for python -m gcontact_sync.cli)
if __name__ == "__main__":
    cli()
