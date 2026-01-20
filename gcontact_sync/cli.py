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
from typing import TYPE_CHECKING, Optional

import click

from gcontact_sync import __version__
from gcontact_sync.auth.google_auth import (
    ACCOUNT_1,
    ACCOUNT_2,
    AuthenticationError,
    GoogleAuth,
)
from gcontact_sync.sync.conflict import ConflictStrategy
from gcontact_sync.utils.logging import get_logger, setup_logging

if TYPE_CHECKING:
    from gcontact_sync.sync.conflict import ConflictResult
    from gcontact_sync.sync.contact import Contact
    from gcontact_sync.sync.engine import SyncResult

# Valid account identifiers
VALID_ACCOUNTS = (ACCOUNT_1, ACCOUNT_2)

# Default configuration directory
DEFAULT_CONFIG_DIR = Path.home() / ".gcontact-sync"


def validate_account(
    ctx: click.Context, param: click.Parameter, value: Optional[str]
) -> Optional[str]:
    """Validate account identifier for Click option."""
    if value is None:
        return value
    if value not in VALID_ACCOUNTS:
        raise click.BadParameter(
            f"Invalid account '{value}'. Must be one of: {', '.join(VALID_ACCOUNTS)}"
        )
    return value


def get_config_dir(config_dir: Optional[str]) -> Path:
    """Get the configuration directory path."""
    if config_dir:
        return Path(config_dir)
    return DEFAULT_CONFIG_DIR


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
@click.pass_context
def cli(ctx: click.Context, verbose: bool, config_dir: Optional[str]) -> None:
    """
    Bidirectional Google Contacts Sync.

    Synchronizes contacts between two Google accounts, ensuring both accounts
    contain identical contact sets after each sync.

    For more information, visit: https://github.com/gcontact-sync
    """
    # Initialize context
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["config_dir"] = get_config_dir(config_dir)

    # Setup logging
    setup_logging(verbose=verbose, enable_file_logging=True)


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
@click.pass_context
def sync_command(
    ctx: click.Context, dry_run: bool, full: bool, strategy: str, debug: bool
) -> None:
    """
    Synchronize contacts and groups between accounts.

    Performs bidirectional sync to ensure both Google accounts have
    identical contacts and contact groups (labels). Groups are synced
    first to ensure membership mappings work correctly. Contacts and
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
    """
    logger = get_logger(__name__)
    config_dir = ctx.obj["config_dir"]
    verbose = ctx.obj["verbose"]

    # Map strategy string to enum
    strategy_map = {
        "last_modified": ConflictStrategy.LAST_MODIFIED_WINS,
        "account1": ConflictStrategy.ACCOUNT1_WINS,
        "account2": ConflictStrategy.ACCOUNT2_WINS,
    }
    conflict_strategy = strategy_map[strategy]

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
        from gcontact_sync.api.people_api import PeopleAPI
        from gcontact_sync.storage.db import SyncDatabase
        from gcontact_sync.sync.engine import SyncEngine

        # Ensure database directory exists
        db_path = config_dir / "sync.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize API clients and database
        api1 = PeopleAPI(credentials=creds1)
        api2 = PeopleAPI(credentials=creds2)
        database = SyncDatabase(str(db_path))
        database.initialize()

        # Create sync engine with account emails for better logging
        engine = SyncEngine(
            api1=api1,
            api2=api2,
            database=database,
            conflict_strategy=conflict_strategy,
            account1_email=account1_email,
            account2_email=account2_email,
        )

        # Store account emails in context for summary display
        ctx.obj["account1_email"] = account1_email
        ctx.obj["account2_email"] = account2_email

        # Show sync configuration
        if verbose:
            click.echo("\nSync configuration:")
            click.echo(f"  Database: {db_path}")
            click.echo(f"  Conflict strategy: {strategy}")
            click.echo(f"  Full sync: {full}")
            click.echo(f"  Dry run: {dry_run}")
            click.echo()

        # Run sync
        mode = "Analyzing" if dry_run else "Synchronizing"
        click.echo(f"\n{mode} contacts and groups...")

        result = engine.sync(dry_run=dry_run, full_sync=full)

        # Display results with actual email addresses
        click.echo("\n" + "=" * 50)
        click.echo(
            result.summary(account1_label=account1_email, account2_label=account2_email)
        )
        click.echo("=" * 50)

        if result.has_changes():
            if dry_run:
                click.echo(
                    click.style(
                        "\nDry run complete. No changes were made.", fg="yellow"
                    )
                )
                click.echo("Run without --dry-run to apply these changes.")

                # Show detailed changes if verbose
                if verbose:
                    _show_detailed_changes(result, account1_email, account2_email)
            else:
                click.echo(click.style("\nSync completed successfully!", fg="green"))
                # Contact stats
                created = (
                    result.stats.created_in_account1 + result.stats.created_in_account2
                )
                updated = (
                    result.stats.updated_in_account1 + result.stats.updated_in_account2
                )
                deleted = (
                    result.stats.deleted_in_account1 + result.stats.deleted_in_account2
                )
                # Group stats
                groups_created = (
                    result.stats.groups_created_in_account1
                    + result.stats.groups_created_in_account2
                )
                groups_updated = (
                    result.stats.groups_updated_in_account1
                    + result.stats.groups_updated_in_account2
                )
                groups_deleted = (
                    result.stats.groups_deleted_in_account1
                    + result.stats.groups_deleted_in_account2
                )
                # Log summary including groups if any group operations occurred
                if groups_created or groups_updated or groups_deleted:
                    logger.info(
                        f"Sync completed: groups (created={groups_created}, "
                        f"updated={groups_updated}, deleted={groups_deleted}), "
                        f"contacts (created={created}, updated={updated}, "
                        f"deleted={deleted})"
                    )
                else:
                    logger.info(
                        f"Sync completed: created {created}, "
                        f"updated {updated}, deleted {deleted}"
                    )

                if result.stats.errors > 0:
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
        if debug:
            _show_debug_info(result, account1_email, account2_email)

    except Exception as e:
        logger.exception(f"Sync failed: {e}")
        click.echo(click.style(f"\nSync failed: {e}", fg="red"), err=True)
        sys.exit(1)


def _show_detailed_changes(
    result: "SyncResult",
    account1_label: str = ACCOUNT_1,
    account2_label: str = ACCOUNT_2,
) -> None:
    """
    Display detailed change information for dry-run mode.

    Args:
        result: The SyncResult containing changes to display
        account1_label: Label for account 1 (email or 'account1')
        account2_label: Label for account 2 (email or 'account2')
    """
    click.echo("\n=== Detailed Changes ===")

    # Show group changes first (since groups sync before contacts)
    if result.has_group_changes():
        click.echo("\n--- Group Changes ---")

        if result.groups_to_create_in_account1:
            click.echo(f"\nGroups to create in {account1_label}:")
            for group in result.groups_to_create_in_account1[:10]:
                click.echo(f"  + {group.name}")
            if len(result.groups_to_create_in_account1) > 10:
                remaining = len(result.groups_to_create_in_account1) - 10
                click.echo(f"  ... and {remaining} more")

        if result.groups_to_create_in_account2:
            click.echo(f"\nGroups to create in {account2_label}:")
            for group in result.groups_to_create_in_account2[:10]:
                click.echo(f"  + {group.name}")
            if len(result.groups_to_create_in_account2) > 10:
                remaining = len(result.groups_to_create_in_account2) - 10
                click.echo(f"  ... and {remaining} more")

        if result.groups_to_update_in_account1:
            click.echo(f"\nGroups to update in {account1_label}:")
            for _resource_name, group in result.groups_to_update_in_account1[:10]:
                click.echo(f"  ~ {group.name}")
            if len(result.groups_to_update_in_account1) > 10:
                remaining = len(result.groups_to_update_in_account1) - 10
                click.echo(f"  ... and {remaining} more")

        if result.groups_to_update_in_account2:
            click.echo(f"\nGroups to update in {account2_label}:")
            for _resource_name, group in result.groups_to_update_in_account2[:10]:
                click.echo(f"  ~ {group.name}")
            if len(result.groups_to_update_in_account2) > 10:
                remaining = len(result.groups_to_update_in_account2) - 10
                click.echo(f"  ... and {remaining} more")

        if result.groups_to_delete_in_account1:
            click.echo(f"\nGroups to delete in {account1_label}:")
            for resource_name in result.groups_to_delete_in_account1[:10]:
                click.echo(f"  - {resource_name}")
            if len(result.groups_to_delete_in_account1) > 10:
                remaining = len(result.groups_to_delete_in_account1) - 10
                click.echo(f"  ... and {remaining} more")

        if result.groups_to_delete_in_account2:
            click.echo(f"\nGroups to delete in {account2_label}:")
            for resource_name in result.groups_to_delete_in_account2[:10]:
                click.echo(f"  - {resource_name}")
            if len(result.groups_to_delete_in_account2) > 10:
                remaining = len(result.groups_to_delete_in_account2) - 10
                click.echo(f"  ... and {remaining} more")

    # Show contact changes
    if result.has_contact_changes():
        click.echo("\n--- Contact Changes ---")

    if result.to_create_in_account1:
        click.echo(f"\nTo create in {account1_label}:")
        for contact in result.to_create_in_account1[:10]:  # Limit display
            click.echo(f"  + {contact.display_name}")
        if len(result.to_create_in_account1) > 10:
            click.echo(f"  ... and {len(result.to_create_in_account1) - 10} more")

    if result.to_create_in_account2:
        click.echo(f"\nTo create in {account2_label}:")
        for contact in result.to_create_in_account2[:10]:
            click.echo(f"  + {contact.display_name}")
        if len(result.to_create_in_account2) > 10:
            click.echo(f"  ... and {len(result.to_create_in_account2) - 10} more")

    if result.to_update_in_account1:
        click.echo(f"\nTo update in {account1_label}:")
        for _resource_name, contact in result.to_update_in_account1[:10]:
            click.echo(f"  ~ {contact.display_name}")
        if len(result.to_update_in_account1) > 10:
            click.echo(f"  ... and {len(result.to_update_in_account1) - 10} more")

    if result.to_update_in_account2:
        click.echo(f"\nTo update in {account2_label}:")
        for _resource_name, contact in result.to_update_in_account2[:10]:
            click.echo(f"  ~ {contact.display_name}")
        if len(result.to_update_in_account2) > 10:
            click.echo(f"  ... and {len(result.to_update_in_account2) - 10} more")

    if result.to_delete_in_account1:
        click.echo(f"\nTo delete in {account1_label}:")
        for resource_name in result.to_delete_in_account1[:10]:
            click.echo(f"  - {resource_name}")
        if len(result.to_delete_in_account1) > 10:
            click.echo(f"  ... and {len(result.to_delete_in_account1) - 10} more")

    if result.to_delete_in_account2:
        click.echo(f"\nTo delete in {account2_label}:")
        for resource_name in result.to_delete_in_account2[:10]:
            click.echo(f"  - {resource_name}")
        if len(result.to_delete_in_account2) > 10:
            click.echo(f"  ... and {len(result.to_delete_in_account2) - 10} more")


def _show_debug_info(
    result: "SyncResult",
    account1_label: str = ACCOUNT_1,
    account2_label: str = ACCOUNT_2,
) -> None:
    """
    Display debug information showing sample matches and unmatched contacts.

    Args:
        result: The SyncResult containing match data
        account1_label: Label for account 1 (email or 'account1')
        account2_label: Label for account 2 (email or 'account2')
    """
    import random

    click.echo("\n" + "=" * 50)
    click.echo(click.style("DEBUG INFO", fg="cyan", bold=True))
    click.echo("=" * 50)

    # Show group debug info first (since groups sync before contacts)
    matched_groups = result.matched_groups
    if matched_groups or result.has_group_changes():
        click.echo(
            f"\n{click.style('Matched Groups:', fg='green')} "
            f"{len(matched_groups)} pairs"
        )

        if matched_groups:
            group_sample_size = min(5, len(matched_groups))
            group_sample = random.sample(matched_groups, group_sample_size)
            click.echo(f"\nRandom sample of {group_sample_size} matched group pairs:")
            for group1, group2 in group_sample:
                click.echo(f"\n  {click.style('Group Match:', fg='cyan')}")
                click.echo(f"    {account1_label}: {group1.name}")
                click.echo(f"    {account2_label}: {group2.name}")

        # Show unmatched groups
        groups_in_1_only = result.groups_to_create_in_account2
        groups_in_2_only = result.groups_to_create_in_account1

        click.echo(
            f"\n{click.style('Unmatched Groups:', fg='yellow')} "
            f"{len(groups_in_1_only)} only in {account1_label}, "
            f"{len(groups_in_2_only)} only in {account2_label}"
        )

        if groups_in_1_only:
            click.echo(f"\nGroups only in {account1_label}:")
            for group in groups_in_1_only[:5]:
                click.echo(f"  - {group.name}")
            if len(groups_in_1_only) > 5:
                click.echo(f"  ... and {len(groups_in_1_only) - 5} more")

        if groups_in_2_only:
            click.echo(f"\nGroups only in {account2_label}:")
            for group in groups_in_2_only[:5]:
                click.echo(f"  - {group.name}")
            if len(groups_in_2_only) > 5:
                click.echo(f"  ... and {len(groups_in_2_only) - 5} more")

    # Show matched contacts sample
    matched = result.matched_contacts
    click.echo(f"\n{click.style('Matched Contacts:', fg='green')} {len(matched)} pairs")

    if matched:
        sample_size = min(5, len(matched))
        sample = random.sample(matched, sample_size)
        click.echo(f"\nRandom sample of {sample_size} matched pairs:")
        for contact1, contact2 in sample:
            click.echo(f"\n  {click.style('Match:', fg='cyan')}")
            click.echo(f"    {account1_label}:")
            click.echo(f"      Name: {contact1.display_name}")
            if contact1.emails:
                click.echo(f"      Emails: {', '.join(contact1.emails[:2])}")
            if contact1.phones:
                click.echo(f"      Phones: {', '.join(contact1.phones[:2])}")
            click.echo(f"    {account2_label}:")
            click.echo(f"      Name: {contact2.display_name}")
            if contact2.emails:
                click.echo(f"      Emails: {', '.join(contact2.emails[:2])}")
            if contact2.phones:
                click.echo(f"      Phones: {', '.join(contact2.phones[:2])}")

    # Show unmatched contacts (to be created)
    unmatched_in_1 = result.to_create_in_account2  # Contacts only in account 1
    unmatched_in_2 = result.to_create_in_account1  # Contacts only in account 2

    click.echo(
        f"\n{click.style('Unmatched Contacts:', fg='yellow')} "
        f"{len(unmatched_in_1)} only in {account1_label}, "
        f"{len(unmatched_in_2)} only in {account2_label}"
    )

    if unmatched_in_1:
        unmatched_sample_size_1 = min(5, len(unmatched_in_1))
        unmatched_sample_1: list[Contact] = random.sample(
            unmatched_in_1, unmatched_sample_size_1
        )
        click.echo(
            f"\nSample of {unmatched_sample_size_1} contacts only in {account1_label}:"
        )
        for contact in unmatched_sample_1:
            _print_contact_debug(contact)

    if unmatched_in_2:
        unmatched_sample_size_2 = min(5, len(unmatched_in_2))
        unmatched_sample_2: list[Contact] = random.sample(
            unmatched_in_2, unmatched_sample_size_2
        )
        click.echo(
            f"\nSample of {unmatched_sample_size_2} contacts only in {account2_label}:"
        )
        for contact in unmatched_sample_2:
            _print_contact_debug(contact)

    # Show conflicts sample
    if result.conflicts:
        click.echo(
            f"\n{click.style('Conflicts:', fg='magenta')} {len(result.conflicts)}"
        )
        conflict_sample_size = min(3, len(result.conflicts))
        conflict_sample: list[ConflictResult] = random.sample(
            result.conflicts, conflict_sample_size
        )
        click.echo(f"\nSample of {conflict_sample_size} conflicts:")
        for conflict in conflict_sample:
            click.echo(f"\n  Contact: {conflict.winner.display_name}")
            click.echo(f"  Resolution: {conflict.reason}")


def _print_contact_debug(contact: "Contact") -> None:
    """Print a single contact's debug info."""
    click.echo(f"  - {contact.display_name}")
    if contact.emails:
        click.echo(f"      Emails: {', '.join(contact.emails[:2])}")
    if contact.phones:
        click.echo(f"      Phones: {', '.join(contact.phones[:2])}")
    if contact.organizations:
        click.echo(f"      Org: {contact.organizations[0]}")


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
def clear_auth_command(ctx: click.Context, account: Optional[str], yes: bool) -> None:
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
def create_group_command(ctx: click.Context, name: str, account: Optional[str]) -> None:
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
    account: Optional[str],
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


# Module entry point (for python -m gcontact_sync.cli)
if __name__ == "__main__":
    cli()
