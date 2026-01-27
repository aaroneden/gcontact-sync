#!/usr/bin/env python3
"""
Import contacts from a CSV file into a Google account.

Usage:
    python scripts/import_contacts.py ~/Downloads/all_contacts_c360.csv
    python scripts/import_contacts.py ~/Downloads/all_contacts_c360.csv --dry-run
    python scripts/import_contacts.py ~/Downloads/all_contacts_c360.csv --group "C360"
"""

import argparse
import csv
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from gcontact_sync.api.people_api import PeopleAPI
from gcontact_sync.auth.google_auth import GoogleAuth
from gcontact_sync.sync.contact import Contact
from gcontact_sync.utils import DEFAULT_CONFIG_DIR

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def parse_display_name(raw_name: str) -> tuple[str | None, str | None, str]:
    """
    Parse the display name, handling data quality issues.

    Some names have multiple emails concatenated like:
    "email1, email2, Actual Name"

    Returns:
        Tuple of (given_name, family_name, display_name)
    """
    if not raw_name:
        return None, None, ""

    # Remove extra whitespace and quotes
    raw_name = raw_name.strip().strip('"').strip()

    # Check if the name contains email addresses (data quality issue)
    # Split by comma and filter out email-like entries
    parts = [p.strip().strip('"').strip() for p in raw_name.split(",")]

    # Filter out parts that look like email addresses
    name_parts = [part for part in parts if "@" not in part and part]

    # Reconstruct display name from non-email parts (empty if only emails)
    display_name = ", ".join(name_parts) if name_parts else ""

    # If display_name is still an email address, use empty string
    if "@" in display_name:
        display_name = ""

    # Try to split into given/family name
    name_words = display_name.split()
    if len(name_words) >= 2:
        given_name = name_words[0]
        family_name = " ".join(name_words[1:])
    elif len(name_words) == 1:
        given_name = name_words[0]
        family_name = None
    else:
        given_name = None
        family_name = None

    return given_name, family_name, display_name


def load_csv_contacts(csv_path: str) -> list[dict]:
    """Load contacts from CSV file."""
    contacts = []

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = row.get("email", "").strip().lower()
            raw_name = row.get("display_name", "").strip()

            if not email:
                continue

            given_name, family_name, display_name = parse_display_name(raw_name)

            contacts.append(
                {
                    "email": email,
                    "display_name": display_name,
                    "given_name": given_name,
                    "family_name": family_name,
                    "sources": row.get("sources", ""),
                    "source_count": row.get("source_count", ""),
                }
            )

    return contacts


def find_or_create_group(api: PeopleAPI, group_name: str, dry_run: bool) -> str | None:
    """Find existing group by name or create it. Returns resource name."""
    groups, _ = api.list_contact_groups()

    # Look for existing group with this name
    for group in groups:
        if group.get("name", "").lower() == group_name.lower():
            logger.info(f"Found existing group: {group_name}")
            return group.get("resourceName")

    # Group doesn't exist, create it
    if dry_run:
        logger.info(f"Would create new group: {group_name}")
        return None

    logger.info(f"Creating new group: {group_name}")
    new_group = api.create_contact_group(group_name)
    return new_group.get("resourceName")


def add_contacts_to_group(
    api: PeopleAPI, group_resource: str, contact_resources: list[str]
) -> int:
    """Add contacts to a group. Returns number added."""
    if not contact_resources:
        return 0

    # API allows up to 1000 contacts per call, batch if needed
    batch_size = 1000
    total_added = 0

    for i in range(0, len(contact_resources), batch_size):
        batch = contact_resources[i : i + batch_size]
        try:
            api.modify_group_members(
                group_resource, add_resource_names=batch, remove_resource_names=None
            )
            total_added += len(batch)
        except Exception as e:
            logger.error(f"Error adding contacts to group: {e}")

    return total_added


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import contacts from CSV into Google Contacts"
    )
    parser.add_argument("csv_file", help="Path to the CSV file")
    parser.add_argument(
        "--account",
        choices=["account1", "account2"],
        default="account1",
        help="Which account to import into (default: account1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--group",
        help="Add all imported contacts to this group (creates if doesn't exist)",
    )
    parser.add_argument(
        "--config-dir",
        default=str(DEFAULT_CONFIG_DIR),
        help=f"Config directory (default: {DEFAULT_CONFIG_DIR})",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show verbose output"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load CSV contacts
    logger.info(f"Loading contacts from {args.csv_file}...")
    csv_contacts = load_csv_contacts(args.csv_file)
    logger.info(f"Loaded {len(csv_contacts)} contacts from CSV")

    # Authenticate to the target account
    config_dir = Path(args.config_dir)
    auth = GoogleAuth(config_dir=config_dir)
    credentials = auth.get_credentials(args.account)

    if not credentials:
        logger.error(
            f"Not authenticated for {args.account}. "
            f"Run: gcontact-sync auth --account {args.account}"
        )
        sys.exit(1)

    account_email = auth.get_account_email(args.account) or args.account
    logger.info(f"Importing to account: {account_email}")

    # Get existing contacts
    api = PeopleAPI(credentials)
    logger.info("Fetching existing contacts...")
    existing_contacts, _ = api.list_contacts(request_sync_token=False)
    logger.info(f"Found {len(existing_contacts)} existing contacts")

    # Build lookup by email (lowercase)
    existing_by_email: dict[str, Contact] = {}
    for contact in existing_contacts:
        for email in contact.emails:
            existing_by_email[email.lower()] = contact

    # Analyze what needs to be done
    to_create = []
    to_update = []
    already_exists = []

    for csv_contact in csv_contacts:
        email = csv_contact["email"]

        if email in existing_by_email:
            existing = existing_by_email[email]

            # Check if name needs updating
            # Only update if the existing contact has no name or a placeholder
            needs_update = False
            has_name = csv_contact["display_name"]
            missing_display = not existing.display_name
            is_placeholder = existing.display_name == email
            missing_given = not existing.given_name and csv_contact["given_name"]

            if has_name and (missing_display or is_placeholder or missing_given):
                needs_update = True

            if needs_update:
                to_update.append((existing, csv_contact))
            else:
                already_exists.append((existing, csv_contact))
        else:
            to_create.append(csv_contact)

    # Show summary
    logger.info("")
    logger.info("=== Import Summary ===")
    logger.info(f"Already exists (no changes): {len(already_exists)}")
    logger.info(f"To update (name missing): {len(to_update)}")
    logger.info(f"To create (new contacts): {len(to_create)}")
    if args.group:
        total_for_group = len(to_create) + len(to_update) + len(already_exists)
        logger.info(f"Will add to group '{args.group}': {total_for_group}")

    if args.dry_run:
        logger.info("")
        logger.info("=== DRY RUN - No changes made ===")

        if args.group:
            find_or_create_group(api, args.group, dry_run=True)

        if to_update and args.verbose:
            logger.info("")
            logger.info("Contacts to update:")
            for existing, csv_contact in to_update[:20]:
                old_name = existing.display_name
                new_name = csv_contact["display_name"]
                logger.info(f"  {csv_contact['email']}: '{old_name}' -> '{new_name}'")
            if len(to_update) > 20:
                logger.info(f"  ... and {len(to_update) - 20} more")

        if to_create and args.verbose:
            logger.info("")
            logger.info("Contacts to create:")
            for csv_contact in to_create[:20]:
                logger.info(f"  {csv_contact['email']}: {csv_contact['display_name']}")
            if len(to_create) > 20:
                logger.info(f"  ... and {len(to_create) - 20} more")

        return

    # Find or create the group if specified
    group_resource = None
    if args.group:
        group_resource = find_or_create_group(api, args.group, dry_run=False)

    # Execute changes
    created_count = 0
    updated_count = 0
    error_count = 0
    created_resources: list[str] = []

    # Create new contacts
    if to_create:
        logger.info("")
        logger.info(f"Creating {len(to_create)} new contacts...")

        contacts_to_create = []
        for csv_contact in to_create:
            contact = Contact(
                resource_name="",  # Will be assigned by API
                etag="",  # Will be assigned by API
                display_name=csv_contact["display_name"] or csv_contact["email"],
                given_name=csv_contact["given_name"],
                family_name=csv_contact["family_name"],
                emails=[csv_contact["email"]],
            )
            contacts_to_create.append(contact)

        # Batch create
        try:
            created = api.batch_create_contacts(contacts_to_create)
            created_count = len(created)
            created_resources = [c.resource_name for c in created]
            logger.info(f"Created {created_count} contacts")
        except Exception as e:
            logger.error(f"Error during batch create: {e}")
            error_count += len(to_create)

    # Update existing contacts
    if to_update:
        logger.info("")
        logger.info(f"Updating {len(to_update)} contacts...")

        updates = []
        for existing, csv_contact in to_update:
            updated = Contact(
                resource_name=existing.resource_name,
                etag=existing.etag,
                display_name=csv_contact["display_name"],
                given_name=csv_contact["given_name"],
                family_name=csv_contact["family_name"],
                emails=existing.emails,  # Keep existing emails
                phones=existing.phones,
                organizations=existing.organizations,
                notes=existing.notes,
            )
            updates.append((existing.resource_name, updated))

        # Batch update
        try:
            updated_contacts = api.batch_update_contacts(updates)
            updated_count = len(updated_contacts)
            logger.info(f"Updated {updated_count} contacts")
        except Exception as e:
            logger.error(f"Error during batch update: {e}")
            error_count += len(to_update)

    # Add contacts to group if specified
    if group_resource:
        logger.info("")
        logger.info(f"Adding contacts to group '{args.group}'...")

        # Collect all resource names to add
        all_resources = created_resources.copy()
        # Add updated contacts
        all_resources.extend([existing.resource_name for existing, _ in to_update])
        # Add already existing contacts
        all_resources.extend([existing.resource_name for existing, _ in already_exists])

        added_count = add_contacts_to_group(api, group_resource, all_resources)
        logger.info(f"Added {added_count} contacts to group '{args.group}'")

    # Final summary
    logger.info("")
    logger.info("=== Import Complete ===")
    logger.info(f"Created: {created_count}")
    logger.info(f"Updated: {updated_count}")
    logger.info(f"Already existed: {len(already_exists)}")
    if error_count:
        logger.info(f"Errors: {error_count}")


if __name__ == "__main__":
    main()
