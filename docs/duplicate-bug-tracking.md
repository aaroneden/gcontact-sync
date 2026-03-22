# Duplicate Contact Bug - Tracking Doc

**Date:** 2026-03-22
**Status:** Fix 4 complete, Fixes 1 & 2 pending

## Problem

The sync engine creates 1-2 duplicate contacts on nearly every run, resulting in 84 total duplicates across both accounts.

## Root Cause

A self-reinforcing duplicate loop:
1. `_build_contact_index` keeps only the "best" copy per matching key, silently dropping same-account duplicates
2. Dropped copies never enter the index, so they can't be matched in Phase 0/1
3. These "ghost" copies get re-created in the other account every sync
4. The newly created copy becomes yet another unmatched ghost next run

## Key Contacts to Monitor

These were the worst offenders. After cleanup, each should have exactly 1 copy per account:

| Contact | Acct 1 Copies Removed | Acct 2 Copies Removed | Notes |
|---|---|---|---|
| abackos@abmgmtllc.com | 6 | 1 | Worst offender (7 copies in acct 1) |
| Aaron Eden | 8 | 5 | User's own contact card, many emails |
| Michael Hruska | 5 | 4 | Two different email keys caused separate mappings |
| Aaron Hutchinson | 4 | 2 | |
| Bryan Bechtoldt | 3 | 1 | |
| Abraham Williams | 3 | 1 | |
| Biren Saini | 3 | 1 | |
| Ryan Flannagan | 3 | 1 | |
| Fred Hippo | 3 | 1 | |
| Matthew Gravatt | 3 | 2 | |
| Wiz Bathea | 2 | 1 | |
| Alex Rodriguez | 2 | 1 | |
| Tripp Shannon | 2 | 1 | |
| Alec Mitchell | 2 | 1 | |
| Adam Small | 2 | 1 | |
| Abi Adeoti | 3 | 1 | |
| David Borlo | 1 | 1 | |
| Miguel Ibarra | 1 | 0 | |
| Angela Wilson | 0 | 1 | No email - name-only match |
| Britney Sharp | 0 | 1 | |

## Fix Plan

### Fix 4: Data Cleanup (DONE)
- Ran `scripts/remove_duplicates.py` - removed 84 duplicates (56 from acct 1, 28 from acct 2)
- Ran `gcontact-sync reset` to clear stale sync state/mappings
- Daemon stopped to prevent further duplicates

### Fix 1: Pre-create duplicate guard in Phase 3 (PENDING)
In `_handle_unmatched_contact`, before adding to `to_create_in_account*`, check if the contact's matching_key or any shared identifiers already exist in the target account's contact list. If the target account already has this contact (matched or not), skip creation.

**File:** `gcontact_sync/sync/engine.py` - `_handle_unmatched_contact` (~line 1678)

### Fix 2: Post-create mapping guard (PENDING)
After creating contacts in `_execute_creates`, scan the target account for pre-existing contacts sharing identifiers with the newly created contact. Log warnings about these to prevent re-creation on next run.

**File:** `gcontact_sync/sync/engine.py` - `_execute_creates` (~line 3481)

## Verification Plan

1. Run `gcontact-sync sync --dry-run --verbose` - should show 0 creates
2. Run a real sync - should show 0 creates (only matched pairs)
3. Run a second sync immediately - should show 0 creates
4. Re-enable daemon and check logs after next scheduled run
5. Run `scripts/remove_duplicates.py --dry-run` after a few days - should find 0 duplicates
