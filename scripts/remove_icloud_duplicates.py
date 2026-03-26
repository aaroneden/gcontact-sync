#!/usr/bin/env python3
"""
iCloud Duplicate Contact Detection and Removal Script

Uses the macOS Contacts framework (via pyobjc) to find and remove
duplicate contacts in the local/iCloud address book.

Duplicates are identified by signature: normalized (name + emails + phones).
For each duplicate group, the richest contact is kept and any unique data
from the duplicates is merged into it before deletion.

Usage:
    python scripts/remove_icloud_duplicates.py [--dry-run] [--verbose]
"""

import argparse
import re
from collections import defaultdict

from Contacts import (
    CNContactBirthdayKey,
    CNContactDatesKey,
    CNContactDepartmentNameKey,
    CNContactEmailAddressesKey,
    CNContactFamilyNameKey,
    CNContactFetchRequest,
    CNContactGivenNameKey,
    CNContactIdentifierKey,
    CNContactInstantMessageAddressesKey,
    CNContactJobTitleKey,
    CNContactMiddleNameKey,
    CNContactOrganizationNameKey,
    CNContactPhoneNumbersKey,
    CNContactPostalAddressesKey,
    CNContactSocialProfilesKey,
    CNContactStore,
    CNContactUrlAddressesKey,
    # CNContactNoteKey excluded — requires special
    # entitlement on modern macOS
    CNSaveRequest,
)


def normalize_string(s: str | None) -> str:
    """Normalize a string for comparison."""
    if not s:
        return ""
    return s.lower().strip()


def normalize_phone(phone: str) -> str:
    """Normalize phone number to digits only."""
    return re.sub(r"\D", "", phone)


# Properties that hold CNLabeledValue arrays
LABELED_VALUE_KEYS = [
    "emailAddresses",
    "phoneNumbers",
    "postalAddresses",
    "urlAddresses",
    "instantMessageAddresses",
    "socialProfiles",
    "dates",
]

# Properties that hold simple string values
SIMPLE_STRING_KEYS = [
    "jobTitle",
    "departmentName",
]


def get_labeled_value_id(lv) -> str:
    """Get a normalized identifier for a labeled value."""
    label = lv.label() or ""
    value = lv.value()
    if hasattr(value, "stringValue"):
        value = value.stringValue()
    return f"{label}:{value}".lower().strip()


class ICloudContact:
    """Wrapper around a CNContact for easier access."""

    def __init__(self, cn_contact):
        self.cn_contact = cn_contact
        self.identifier = cn_contact.identifier()
        self.given_name = self._safe(cn_contact, "givenName")
        self.family_name = self._safe(cn_contact, "familyName")
        self.middle_name = self._safe(cn_contact, "middleName")
        self.organization = self._safe(
            cn_contact, "organizationName"
        )
        self.job_title = self._safe(cn_contact, "jobTitle")
        self.department = self._safe(
            cn_contact, "departmentName"
        )


        self.emails = self._safe_labeled_strings(
            cn_contact, "emailAddresses"
        )
        self.phones = self._safe_labeled_phones(
            cn_contact, "phoneNumbers"
        )
        self.urls = self._safe_labeled_strings(
            cn_contact, "urlAddresses"
        )

        self.has_addresses = self._safe_has(
            cn_contact, "postalAddresses"
        )
        self.has_dates = self._safe_has(
            cn_contact, "dates"
        )
        self.has_social = self._safe_has(
            cn_contact, "socialProfiles"
        )
        self.has_im = self._safe_has(
            cn_contact, "instantMessageAddresses"
        )
        self.has_birthday = self._safe_has(
            cn_contact, "birthday"
        )

    @staticmethod
    def _safe(cn_contact, prop: str) -> str:
        try:
            return getattr(cn_contact, prop)() or ""
        except Exception:
            return ""

    @staticmethod
    def _safe_has(cn_contact, prop: str) -> bool:
        try:
            return bool(getattr(cn_contact, prop)())
        except Exception:
            return False

    @staticmethod
    def _safe_labeled_strings(
        cn_contact, prop: str,
    ) -> list[str]:
        try:
            result = []
            for lv in getattr(cn_contact, prop)() or []:
                val = lv.value()
                if val:
                    result.append(str(val))
            return result
        except Exception:
            return []

    @staticmethod
    def _safe_labeled_phones(
        cn_contact, prop: str,
    ) -> list[str]:
        try:
            result = []
            for lv in getattr(cn_contact, prop)() or []:
                val = lv.value()
                if val:
                    result.append(str(val.stringValue()))
            return result
        except Exception:
            return []

    @property
    def display_name(self) -> str:
        parts = [
            self.given_name,
            self.middle_name,
            self.family_name,
        ]
        name = " ".join(p for p in parts if p).strip()
        return name or self.organization or "(no name)"

    @property
    def data_richness(self) -> int:
        """Score how much data this contact has."""
        score = 0
        if self.given_name:
            score += 1
        if self.family_name:
            score += 1
        if self.middle_name:
            score += 1
        if self.organization:
            score += 1
        if self.job_title:
            score += 1
        if self.department:
            score += 1
        score += len(self.emails)
        score += len(self.phones)
        score += len(self.urls)
        if self.has_addresses:
            score += 2
        if self.has_dates:
            score += 1
        if self.has_social:
            score += 1
        if self.has_im:
            score += 1
        if self.has_birthday:
            score += 1
        return score

    def display_info(self) -> str:
        email = self.emails[0] if self.emails else ""
        if email:
            return (
                f"{self.display_name} <{email}> "
                f"({self.identifier})"
            )
        return f"{self.display_name} ({self.identifier})"

    def extra_fields_summary(self) -> str:
        """Summarize non-name/email/phone data."""
        parts = []
        if self.job_title:
            parts.append(f"title={self.job_title}")
        if self.department:
            parts.append(f"dept={self.department}")
        if self.urls:
            parts.append(f"urls={self.urls}")
        if self.has_addresses:
            parts.append("has_addresses")
        if self.has_dates:
            parts.append("has_dates")
        if self.has_social:
            parts.append("has_social")
        if self.has_im:
            parts.append("has_im")
        if self.has_birthday:
            parts.append("has_birthday")
        return ", ".join(parts) if parts else "(no extra data)"


def get_signature(contact: ICloudContact) -> tuple:
    """Create a signature for duplicate detection."""
    display_name = normalize_string(contact.display_name)
    email_set = {
        normalize_string(e) for e in contact.emails if e
    }
    phone_set = {
        normalize_phone(p) for p in contact.phones if p
    }
    return (
        display_name,
        tuple(sorted(email_set)),
        tuple(sorted(phone_set)),
    )


ALL_FETCH_KEYS = [
    CNContactIdentifierKey,
    CNContactGivenNameKey,
    CNContactFamilyNameKey,
    CNContactMiddleNameKey,
    CNContactOrganizationNameKey,
    CNContactJobTitleKey,
    CNContactDepartmentNameKey,
    CNContactEmailAddressesKey,
    CNContactPhoneNumbersKey,
    CNContactPostalAddressesKey,
    CNContactUrlAddressesKey,
    CNContactInstantMessageAddressesKey,
    CNContactSocialProfilesKey,
    CNContactDatesKey,
    CNContactBirthdayKey,
]


def fetch_all_contacts(
    store: CNContactStore, verbose: bool = False,
) -> list[ICloudContact]:
    """Fetch all contacts from the macOS Contacts store."""
    request = CNContactFetchRequest.alloc().initWithKeysToFetch_(
        ALL_FETCH_KEYS
    )
    contacts = []

    def handler(cn_contact, stop):
        # Copy the contact so it survives enumeration
        copy = cn_contact.copy()
        contacts.append(ICloudContact(copy))

    error = None
    success, error = (
        store.enumerateContactsWithFetchRequest_error_usingBlock_(
            request, error, handler
        )
    )
    if not success:
        print(f"ERROR: Failed to fetch contacts: {error}")
        return []

    if verbose:
        print(
            f"  Fetched {len(contacts)} contacts "
            "from Contacts.app"
        )
    return contacts


def find_duplicates(
    contacts: list[ICloudContact],
) -> dict[tuple, list[ICloudContact]]:
    """Find duplicate contacts by grouping by signature."""
    by_sig: dict[tuple, list[ICloudContact]] = defaultdict(
        list
    )
    for contact in contacts:
        sig = get_signature(contact)
        if not sig[0] and not sig[1] and not sig[2]:
            continue
        by_sig[sig].append(contact)
    return {
        s: g for s, g in by_sig.items() if len(g) > 1
    }


def pick_contact_to_keep(
    contacts: list[ICloudContact],
) -> tuple[ICloudContact, list[ICloudContact]]:
    """Pick the richest contact to keep."""
    sorted_contacts = sorted(
        contacts, key=lambda c: c.data_richness, reverse=True
    )
    return sorted_contacts[0], sorted_contacts[1:]


def merge_labeled_values(
    keeper_cn, donor_cn, property_name: str,
) -> list:
    """
    Merge labeled values from donor into keeper.
    Returns new labeled values to add (those not already
    present in keeper).
    """
    keeper_vals = getattr(keeper_cn, property_name)() or []
    donor_vals = getattr(donor_cn, property_name)() or []

    if not donor_vals:
        return []

    existing_ids = {
        get_labeled_value_id(lv) for lv in keeper_vals
    }
    new_vals = []
    for lv in donor_vals:
        lv_id = get_labeled_value_id(lv)
        if lv_id not in existing_ids:
            new_vals.append(lv)
            existing_ids.add(lv_id)
    return new_vals


def refetch_contact(store, identifier):
    """Re-fetch a contact by ID with all keys."""
    error = None
    cn, error = (
        store
        .unifiedContactWithIdentifier_keysToFetch_error_(
            identifier, ALL_FETCH_KEYS, error
        )
    )
    return cn


def merge_contacts(
    store: CNContactStore,
    keeper: ICloudContact,
    duplicates: list[ICloudContact],
    verbose: bool = False,
) -> bool:
    """
    Merge unique data from duplicates into the keeper.
    Returns True if the keeper was modified.
    """
    # Re-fetch keeper with all keys so we can mutate
    keeper_cn = refetch_contact(store, keeper.identifier)
    if not keeper_cn:
        if verbose:
            print("      WARN: could not re-fetch keeper")
        return False
    mutable = keeper_cn.mutableCopy()
    modified = False

    for donor in duplicates:
        # Re-fetch donor with all keys too
        donor_cn = refetch_contact(
            store, donor.identifier
        )
        if not donor_cn:
            continue

        # Merge simple string fields (fill blanks)
        for key in SIMPLE_STRING_KEYS:
            keeper_val = getattr(mutable, key)() or ""
            donor_val = getattr(donor_cn, key)() or ""
            if donor_val and not keeper_val:
                setter = f"set{key[0].upper()}{key[1:]}_"
                getattr(mutable, setter)(donor_val)
                modified = True
                if verbose:
                    print(
                        f"      Merged {key}: "
                        f"'{donor_val}'"
                    )

        # Merge labeled value arrays
        for prop in LABELED_VALUE_KEYS:
            new_vals = merge_labeled_values(
                mutable, donor_cn, prop
            )
            if new_vals:
                current = list(
                    getattr(mutable, prop)() or []
                )
                current.extend(new_vals)
                setter = (
                    f"set{prop[0].upper()}{prop[1:]}_"
                )
                getattr(mutable, setter)(current)
                modified = True
                if verbose:
                    print(
                        f"      Merged {len(new_vals)} "
                        f"new {prop}"
                    )

        # Merge birthday
        if not mutable.birthday() and donor_cn.birthday():
            mutable.setBirthday_(donor_cn.birthday())
            modified = True
            if verbose:
                print("      Merged birthday")

    if modified:
        keeper.cn_contact = mutable
    return modified


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Detect and remove duplicate "
            "iCloud/local contacts"
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show duplicates without deleting",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed duplicate info",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Delete dupes without merging data",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("iCloud Duplicate Contact Detection & Removal")
    print("=" * 60)

    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]\n")

    store = CNContactStore.alloc().init()

    print("\nFetching contacts from Contacts.app...")
    contacts = fetch_all_contacts(store, verbose=args.verbose)
    if not contacts:
        print("No contacts found or access denied.")
        print(
            "Make sure Contacts access is allowed in "
            "System Settings > Privacy & Security "
            "> Contacts"
        )
        return

    print(f"Found {len(contacts)} total contacts")

    duplicates = find_duplicates(contacts)
    if not duplicates:
        print("\nNo duplicates found!")
        return

    total_contacts = sum(
        len(g) for g in duplicates.values()
    )
    total_to_remove = sum(
        len(g) - 1 for g in duplicates.values()
    )

    print(
        f"\nFound {len(duplicates)} duplicate groups "
        f"({total_contacts} total contacts)"
    )
    print(
        f"Will keep {len(duplicates)} contacts, "
        f"remove {total_to_remove}\n"
    )

    all_to_remove: list[ICloudContact] = []
    keepers_to_update: list[ICloudContact] = []

    for sig, group in sorted(
        duplicates.items(), key=lambda x: x[0][0]
    ):
        keep, remove = pick_contact_to_keep(group)

        if args.verbose:
            name = sig[0] or "(no name)"
            emails = (
                ", ".join(sig[1])
                if sig[1]
                else "(no email)"
            )
            print(f"  Duplicate group: {name} - {emails}")
            info = keep.display_info()
            rich = keep.data_richness
            print(f"    Keeping:  {info} (richness={rich})")
            extras = keep.extra_fields_summary()
            print(f"      Extra:  {extras}")
            for r in remove:
                r_info = r.display_info()
                r_rich = r.data_richness
                print(
                    f"    Remove:   {r_info} "
                    f"(richness={r_rich})"
                )
                r_extras = r.extra_fields_summary()
                if r_extras != "(no extra data)":
                    print(
                        f"      Extra:  {r_extras} "
                        f"-> will merge"
                    )

        # Merge unique data from dupes into keeper
        was_modified = merge_contacts(
            store, keep, remove, verbose=args.verbose
        )
        if was_modified:
            keepers_to_update.append(keep)

        if args.verbose:
            print()

        all_to_remove.extend(remove)

    # Confirm
    if not args.dry_run and not args.yes:
        msg = (
            f"Merge & delete {len(all_to_remove)} "
            f"duplicate contacts"
        )
        if keepers_to_update:
            msg += (
                f" ({len(keepers_to_update)} keepers "
                f"will be updated with merged data)"
            )
        prompt = f"{msg}? [y/N]: "
        response = input(prompt).strip().lower()
        if response != "y":
            print("Aborted.")
            return

    if args.dry_run:
        print(
            f"[DRY RUN] Would remove "
            f"{len(all_to_remove)} duplicate contacts"
        )
        if keepers_to_update:
            print(
                f"[DRY RUN] Would update "
                f"{len(keepers_to_update)} keepers "
                f"with merged data"
            )
        return

    # Execute one group at a time to avoid CoreData faults
    print(
        f"\nProcessing {len(all_to_remove)} duplicates "
        f"across {len(duplicates)} groups..."
    )
    total_deleted = 0
    total_updated = 0
    errors = 0

    # Re-collect per-group data for individual saves
    for sig, group in sorted(
        duplicates.items(), key=lambda x: x[0][0]
    ):
        keep, remove = pick_contact_to_keep(group)
        name = sig[0] or "(no name)"

        # Fresh store for each group to avoid stale refs
        grp_store = CNContactStore.alloc().init()
        save_req = CNSaveRequest.alloc().init()

        # Re-fetch and merge keeper
        keeper_cn = refetch_contact(
            grp_store, keep.identifier
        )
        if not keeper_cn:
            print(f"  SKIP {name}: can't re-fetch keeper")
            errors += 1
            continue

        mutable_keeper = keeper_cn.mutableCopy()
        keeper_modified = False
        no_merge = args.no_merge

        for donor in remove:
            donor_cn = refetch_contact(
                grp_store, donor.identifier
            )
            if not donor_cn:
                continue

            if not no_merge:
                # Merge simple string fields
                for key in SIMPLE_STRING_KEYS:
                    try:
                        kv = getattr(
                            mutable_keeper, key
                        )()
                        dv = getattr(donor_cn, key)()
                        if dv and not kv:
                            s = (
                                f"set{key[0].upper()}"
                                f"{key[1:]}_"
                            )
                            getattr(
                                mutable_keeper, s
                            )(dv)
                            keeper_modified = True
                    except Exception:
                        pass

                # Merge labeled value arrays
                for prop in LABELED_VALUE_KEYS:
                    try:
                        new = merge_labeled_values(
                            mutable_keeper,
                            donor_cn,
                            prop,
                        )
                        if new:
                            cur = list(
                                getattr(
                                    mutable_keeper,
                                    prop,
                                )() or []
                            )
                            cur.extend(new)
                            s = (
                                f"set{prop[0].upper()}"
                                f"{prop[1:]}_"
                            )
                            getattr(
                                mutable_keeper, s
                            )(cur)
                            keeper_modified = True
                    except Exception:
                        pass

                # Merge birthday
                try:
                    if (
                        not mutable_keeper.birthday()
                        and donor_cn.birthday()
                    ):
                        mutable_keeper.setBirthday_(
                            donor_cn.birthday()
                        )
                        keeper_modified = True
                except Exception:
                    pass

            # Delete the donor
            donor_mut = donor_cn.mutableCopy()
            save_req.deleteContact_(donor_mut)

        if keeper_modified:
            save_req.updateContact_(mutable_keeper)

        error = None
        ok, error = grp_store.executeSaveRequest_error_(
            save_req, error
        )
        if ok:
            total_deleted += len(remove)
            if keeper_modified:
                total_updated += 1
            print(f"  OK: {name} ({len(remove)} removed)")
        else:
            errors += 1
            print(f"  FAIL: {name}: {error}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Duplicate groups found: {len(duplicates)}")
    print(f"Contacts deleted: {total_deleted}")
    if total_updated:
        print(f"Contacts updated (merged): {total_updated}")
    if errors:
        print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
