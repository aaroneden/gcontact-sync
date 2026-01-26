#!/usr/bin/env python3
"""
Duplicate Contact Detection and Removal Script

This script identifies and removes duplicate contacts that were created
by synchronization errors. It works by:

1. Fetching all contacts from both accounts
2. Grouping contacts by "signature" (normalized name + emails + phones)
3. Identifying groups with multiple contacts (duplicates)
4. For each duplicate group, keeping the oldest contact and removing the rest
5. Optionally removing the duplicates after confirmation

Usage:
    python scripts/remove_duplicates.py [--dry-run] [--account ACCOUNT] [--verbose]
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from gcontact_sync.api.people_api import PeopleAPI
from gcontact_sync.auth.google_auth import GoogleAuth
from gcontact_sync.sync.contact import Contact


def normalize_string(s: str | None) -> str:
    """Normalize a string for comparison."""
    if not s:
        return ""
    return s.lower().strip()


def normalize_phone(phone: str) -> str:
    """Normalize phone number to digits only."""
    import re

    return re.sub(r"\D", "", phone)


def get_contact_signature(contact: Contact) -> tuple:
    """
    Create a signature tuple for a contact to identify duplicates.
    Uses: normalized display name + unique sorted emails + unique sorted phones
    """
    # Get display name
    display_name = normalize_string(contact.display_name)

    # Get unique emails (deduplicated and sorted)
    email_set = {normalize_string(e) for e in contact.emails if e}
    email_list = sorted(email_set)

    # Get unique phones (digits only, deduplicated and sorted)
    phone_set = {normalize_phone(p) for p in contact.phones if p}
    phone_list = sorted(phone_set)

    return (display_name, tuple(email_list), tuple(phone_list))


def get_contact_display_info(contact: Contact) -> str:
    """Get a human-readable display string for a contact."""
    display_name = contact.display_name or "Unknown"
    email = contact.emails[0] if contact.emails else ""
    resource_name = contact.resource_name

    if email:
        return f"{display_name} <{email}> ({resource_name})"
    return f"{display_name} ({resource_name})"


def find_duplicates(contacts: list[Contact]) -> dict[tuple, list[Contact]]:
    """
    Find duplicate contacts by grouping them by signature.
    Returns dict mapping signature -> list of contacts with that signature.
    Only includes signatures with more than one contact.
    """
    by_signature: dict[tuple, list[Contact]] = defaultdict(list)

    for contact in contacts:
        sig = get_contact_signature(contact)
        # Skip contacts with empty signatures (no name, email, or phone)
        if not sig[0] and not sig[1] and not sig[2]:
            continue
        by_signature[sig].append(contact)

    # Only return groups with duplicates
    return {
        sig: contacts for sig, contacts in by_signature.items() if len(contacts) > 1
    }


def pick_contact_to_keep(contacts: list[Contact]) -> tuple[Contact, list[Contact]]:
    """
    From a list of duplicate contacts, pick one to keep and return rest for removal.
    Strategy: Keep the oldest contact (by last_modified), remove newer ones.
    """

    # Sort by last_modified (oldest first, None values go last)
    def get_modified_time(c: Contact) -> tuple:
        if c.last_modified:
            return (0, c.last_modified)
        # If no last_modified, sort by resource name (lower IDs are older)
        return (1, c.resource_name)

    sorted_contacts = sorted(contacts, key=get_modified_time)
    return sorted_contacts[0], sorted_contacts[1:]


def fetch_all_contacts(api: PeopleAPI, verbose: bool = False) -> list[Contact]:
    """Fetch all contacts using the API."""
    if verbose:
        print("  Fetching contacts...")
    contacts, _ = api.list_contacts()
    if verbose:
        print(f"  Found {len(contacts)} contacts")
    return contacts


def delete_contacts(
    api: PeopleAPI,
    contacts_to_delete: list[Contact],
    dry_run: bool = False,
    delay: float = 0.5,
) -> int:
    """Delete the specified contacts. Returns count of deleted contacts."""
    import time

    deleted = 0
    total = len(contacts_to_delete)
    for i, contact in enumerate(contacts_to_delete, 1):
        resource_name = contact.resource_name
        if not resource_name:
            continue

        if dry_run:
            print(f"  [DRY RUN] Would delete: {get_contact_display_info(contact)}")
        else:
            try:
                api.delete_contact(resource_name)
                print(f"  [{i}/{total}] Deleted: {get_contact_display_info(contact)}")
                deleted += 1
                # Add delay between deletions to avoid rate limiting
                if i < total:
                    time.sleep(delay)
            except Exception as e:
                print(f"  [{i}/{total}] ERROR deleting {resource_name}: {e}")
                # If we hit an error, wait longer before trying next one
                time.sleep(delay * 2)

    return deleted


def process_account(
    account_name: str,
    api: PeopleAPI,
    dry_run: bool = False,
    verbose: bool = False,
    auto_confirm: bool = False,
) -> tuple[int, int]:
    """
    Process an account to find and optionally remove duplicates.
    Returns (duplicates_found, duplicates_removed).
    """
    print(f"\n{'=' * 60}")
    print(f"Processing {account_name}")
    print(f"{'=' * 60}")

    # Fetch contacts
    contacts = fetch_all_contacts(api, verbose)

    # Find duplicates
    duplicates = find_duplicates(contacts)

    if not duplicates:
        print(f"No duplicates found in {account_name}")
        return 0, 0

    # Analyze duplicates
    total_duplicate_contacts = sum(len(c) for c in duplicates.values())
    total_to_remove = sum(len(c) - 1 for c in duplicates.values())

    print(
        f"\nFound {len(duplicates)} duplicate groups "
        f"({total_duplicate_contacts} total contacts)"
    )
    print(f"Will keep {len(duplicates)} contacts, remove {total_to_remove}\n")

    # Collect all contacts to remove
    all_to_remove: list[Contact] = []
    for sig, dup_contacts in duplicates.items():
        keep, remove = pick_contact_to_keep(dup_contacts)

        if verbose:
            name = sig[0] or "(no name)"
            emails = ", ".join(sig[1]) if sig[1] else "(no email)"
            print(f"\n  Duplicate group: {name} - {emails}")
            print(f"    Keeping: {get_contact_display_info(keep)}")
            for r in remove:
                print(f"    Remove:  {get_contact_display_info(r)}")

        all_to_remove.extend(remove)

    # Confirm deletion
    if not dry_run and not auto_confirm:
        print(
            f"\nReady to delete {len(all_to_remove)} duplicate contacts "
            f"from {account_name}"
        )
        response = input("Proceed? [y/N]: ").strip().lower()
        if response != "y":
            print("Aborted.")
            return len(all_to_remove), 0

    # Delete
    deleted = delete_contacts(api, all_to_remove, dry_run=dry_run)

    if dry_run:
        print(
            f"\n[DRY RUN] Would have removed {len(all_to_remove)} duplicates "
            f"from {account_name}"
        )
    else:
        print(f"\nRemoved {deleted} duplicates from {account_name}")

    return len(all_to_remove), deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect and remove duplicate contacts")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--account",
        choices=["account1", "account2", "both"],
        default="both",
        help="Which account to process (default: both)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed information about duplicates",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path.home() / ".gcontact-sync",
        help="Config directory (default: ~/.gcontact-sync)",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Duplicate Contact Detection and Removal")
    print("=" * 60)

    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]\n")

    # Initialize authentication
    auth = GoogleAuth(config_dir=args.config_dir)

    total_found = 0
    total_removed = 0

    # Process account1
    if args.account in ("account1", "both"):
        creds1 = auth.get_credentials("account1")
        if creds1:
            api1 = PeopleAPI(credentials=creds1)
            email1 = auth.get_account_email("account1") or "account1"
            found, removed = process_account(
                f"Account 1 ({email1})",
                api1,
                dry_run=args.dry_run,
                verbose=args.verbose,
                auto_confirm=args.yes,
            )
            total_found += found
            total_removed += removed
        else:
            print("Account 1 not authenticated")

    # Process account2
    if args.account in ("account2", "both"):
        creds2 = auth.get_credentials("account2")
        if creds2:
            api2 = PeopleAPI(credentials=creds2)
            email2 = auth.get_account_email("account2") or "account2"
            found, removed = process_account(
                f"Account 2 ({email2})",
                api2,
                dry_run=args.dry_run,
                verbose=args.verbose,
                auto_confirm=args.yes,
            )
            total_found += found
            total_removed += removed
        else:
            print("Account 2 not authenticated")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if args.dry_run:
        print(f"Total duplicates found: {total_found}")
        print(f"Would remove: {total_found}")
    else:
        print(f"Total duplicates found: {total_found}")
        print(f"Total removed: {total_removed}")


if __name__ == "__main__":
    main()
