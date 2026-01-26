"""CLI output formatting functions.

This module contains functions for displaying sync results, debug information,
and detailed change summaries to the command line.
"""

from typing import TYPE_CHECKING

import click

from gcontact_sync.auth.google_auth import ACCOUNT_1, ACCOUNT_2

if TYPE_CHECKING:
    from gcontact_sync.sync.conflict import ConflictResult
    from gcontact_sync.sync.contact import Contact
    from gcontact_sync.sync.engine import SyncResult


def show_detailed_changes(
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


def show_debug_info(
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
            group_sample = random.sample(matched_groups, group_sample_size)  # nosec B311
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
    # Handle case where matched_contacts might be a MagicMock in tests
    if not isinstance(matched, list):
        matched = list(matched) if hasattr(matched, "__iter__") else []
    click.echo(f"\n{click.style('Matched Contacts:', fg='green')} {len(matched)} pairs")

    if matched:
        sample_size = min(5, len(matched))
        sample = random.sample(list(matched), sample_size)  # nosec B311
        click.echo(f"\nRandom sample of {sample_size} matched pairs:")
        for contact1, contact2 in sample:
            click.echo(f"\n  {click.style('Match:', fg='cyan')}")
            click.echo(f"    {account1_label}:")
            click.echo(f"      Name: {contact1.display_name}")
            if contact1.emails:
                click.echo(f"      Emails: {', '.join(contact1.emails[:2])}")
            if contact1.phones:
                click.echo(f"      Phones: {', '.join(contact1.phones[:2])}")
            if contact1.memberships:
                # Show group names (strip contactGroups/ prefix for readability)
                groups1 = [
                    m.replace("contactGroups/", "") for m in contact1.memberships
                ]
                click.echo(f"      Groups: {', '.join(groups1[:3])}")
            click.echo(f"    {account2_label}:")
            click.echo(f"      Name: {contact2.display_name}")
            if contact2.emails:
                click.echo(f"      Emails: {', '.join(contact2.emails[:2])}")
            if contact2.phones:
                click.echo(f"      Phones: {', '.join(contact2.phones[:2])}")
            if contact2.memberships:
                groups2 = [
                    m.replace("contactGroups/", "") for m in contact2.memberships
                ]
                click.echo(f"      Groups: {', '.join(groups2[:3])}")

    # Show unmatched contacts (to be created)
    # Handle case where these might be MagicMock in tests
    unmatched_in_1 = result.to_create_in_account2  # Contacts only in account 1
    unmatched_in_2 = result.to_create_in_account1  # Contacts only in account 2
    if not isinstance(unmatched_in_1, list):
        unmatched_in_1 = (
            list(unmatched_in_1) if hasattr(unmatched_in_1, "__iter__") else []
        )
    if not isinstance(unmatched_in_2, list):
        unmatched_in_2 = (
            list(unmatched_in_2) if hasattr(unmatched_in_2, "__iter__") else []
        )

    click.echo(
        f"\n{click.style('Unmatched Contacts:', fg='yellow')} "
        f"{len(unmatched_in_1)} only in {account1_label}, "
        f"{len(unmatched_in_2)} only in {account2_label}"
    )

    if unmatched_in_1:
        unmatched_sample_size_1 = min(5, len(unmatched_in_1))
        unmatched_sample_1: list[Contact] = random.sample(  # nosec B311
            list(unmatched_in_1), unmatched_sample_size_1
        )
        click.echo(
            f"\nSample of {unmatched_sample_size_1} contacts only in {account1_label}:"
        )
        for contact in unmatched_sample_1:
            print_contact_debug(contact)

    if unmatched_in_2:
        unmatched_sample_size_2 = min(5, len(unmatched_in_2))
        unmatched_sample_2: list[Contact] = random.sample(  # nosec B311
            list(unmatched_in_2), unmatched_sample_size_2
        )
        click.echo(
            f"\nSample of {unmatched_sample_size_2} contacts only in {account2_label}:"
        )
        for contact in unmatched_sample_2:
            print_contact_debug(contact)

    # Show conflicts sample
    conflicts = result.conflicts
    if not isinstance(conflicts, list):
        conflicts = list(conflicts) if hasattr(conflicts, "__iter__") else []
    if conflicts:
        click.echo(f"\n{click.style('Conflicts:', fg='magenta')} {len(conflicts)}")
        conflict_sample_size = min(3, len(conflicts))
        conflict_sample: list[ConflictResult] = random.sample(  # nosec B311
            list(conflicts), conflict_sample_size
        )
        click.echo(f"\nSample of {conflict_sample_size} conflicts:")
        for conflict in conflict_sample:
            click.echo(f"\n  Contact: {conflict.winner.display_name}")
            click.echo(f"  Resolution: {conflict.reason}")


def print_contact_debug(contact: "Contact") -> None:
    """Print a single contact's debug info."""
    click.echo(f"  - {contact.display_name}")
    if contact.emails:
        click.echo(f"      Emails: {', '.join(contact.emails[:2])}")
    if contact.phones:
        click.echo(f"      Phones: {', '.join(contact.phones[:2])}")
    if contact.organizations:
        click.echo(f"      Org: {contact.organizations[0]}")
