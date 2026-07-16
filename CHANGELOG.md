# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **iCloud Duplicate Contact Removal**: New utility to detect and remove duplicate contacts from the macOS/iCloud address book
  - Located at `scripts/remove_icloud_duplicates.py`
  - Uses macOS Contacts framework (via pyobjc) to access local contacts
  - Automatically merges unique data (emails, phones, addresses, birthday) from duplicates into the kept contact before deletion
  - Supports `--dry-run`, `--verbose`, `--yes`, and `--no-merge` flags
  - Processes groups individually to handle CoreData errors gracefully

### Fixed

- **Update Ping-Pong on Contacts with Duplicate Field Entries**: Fixed an endless update loop for contacts whose copies differ only in duplicate email/phone entries (Google merge artifacts, provider-injected profile emails)
  - `content_hash` now deduplicates emails, phones, and organizations before hashing - duplicate multiplicity is not a content difference
  - Updates for pairs matched by key now persist BOTH resource names into the mapping (previously a hash-only row was written that Phase 0 could never pair, so every run re-resolved the conflict and flipped an update)
  - The full-sync dead-mapping cleanup no longer removes hash-only mapping rows (no recorded resource names)
- **Duplicate Contacts No Longer Created During Sync**: Resolved a persistent bug where the sync engine would repeatedly create duplicate contacts (e.g., Michael Hruska, Aaron Eden, abackos) on every sync run
  - **Root cause**: When multiple copies of the same contact existed within one account, the sync engine would silently drop all but one during indexing — but the dropped copies weren't marked as "already handled," causing the other account's matching contact to appear unmatched and trigger a new copy
  - Same-account duplicates are now tracked during indexing and excluded from the create pipeline
  - Added pre-create guard that checks if a contact with the same name, email, or phone already exists in the target account before creating
  - Added batch deduplication to prevent same-batch duplicate creates
  - Verified: scheduled sync now runs with 0 new contacts created ([PR #12](https://github.com/aaroneden/gcontact-sync/pull/12))

---

## [Previous Unreleased]

### Added

- **Target Groups Feature**: Configure how synced contacts are assigned to groups in destination accounts
  - `target_group`: Assign all incoming synced contacts to a specific group (e.g., "Brain Bridge" or "Personal")
  - `preserve_source_groups`: Control whether source group memberships are mapped to destination (default: false)
  - `group_sync_mode`: Control group creation/deletion behavior with three modes:
    - `"all"`: Create all groups from source in destination
    - `"used"`: Only create groups that have synced contacts
    - `"none"`: Don't create or manage groups at all (recommended for most users)
  - Per-account configuration allows different sync strategies for each direction
  - Example: Sync "Personal" contacts from account1 → "Brain Bridge" group on account2

- **Duplicate Contact Removal Script**: New utility to identify and remove duplicate contacts
  - Located at `scripts/remove_duplicates.py`
  - Detects duplicates by matching name + emails + phone numbers
  - Supports dry-run mode to preview changes before deletion
  - Rate-limiting with configurable delays to avoid Google API throttling
  - Process individual accounts or both at once
  - Keeps the oldest contact (by modification time) when removing duplicates

- **Docker Support**: Run gcontact-sync in a container for simplified deployment and isolation
  - Multi-stage Dockerfile optimized for Python 3.12-slim with minimal image size
  - docker-compose.yml for easy deployment with persistent volumes for config and data
  - Health check command (`gcontact-sync health`) for Docker health monitoring
  - Daemon mode works seamlessly in Docker with `--foreground` flag
  - Default 24-hour sync interval configurable via `SYNC_INTERVAL` environment variable
  - Setup script (`scripts/setup_docker.sh`) for quick Docker deployment
  - GitHub Actions workflow for automated multi-platform image builds (amd64/arm64)
  - Published to GitHub Container Registry: `ghcr.io/aeden2019/gcontact-sync`
  - Comprehensive Docker documentation in `docs/DOCKER.md`

- **Built-in Scheduler/Daemon Mode**: Run gcontact-sync as a background service with automatic periodic synchronization
  - Start daemon with configurable intervals: `gcontact-sync daemon start --interval 24h`
  - Support for interval formats: seconds (30s), minutes (5m), hours (1h), days (1d)
  - Graceful shutdown with SIGTERM/SIGINT signal handling
  - PID file management to prevent multiple daemon instances
  - Check daemon status: `gcontact-sync daemon status`
  - Stop running daemon: `gcontact-sync daemon stop`

- **Cross-Platform Service Installation**: Install gcontact-sync as a system service for automatic startup
  - **macOS**: launchd user agent (`~/Library/LaunchAgents/com.gcontact-sync.plist`)
  - **Linux**: systemd user service (`~/.config/systemd/user/gcontact-sync.service`)
  - **Windows**: Task Scheduler task with repetition trigger
  - Install with: `gcontact-sync daemon install --interval 24h`
  - Uninstall with: `gcontact-sync daemon uninstall`
  - Services auto-restart on failure and start automatically on login/boot

- **Contact Photo Synchronization**: Photos are now synchronized between Google accounts
  - Photos are automatically downloaded from source contacts and uploaded to destination contacts
  - Photo changes are detected during sync analysis and included in dry-run reports
  - Support for photo removal when source contact no longer has a photo
  - Photos are processed and optimized (resized to max 1MB, converted to JPEG format)
  - Retry logic with exponential backoff for reliable photo downloads

- **Contact Group Synchronization**: Contact groups (labels) are now synchronized between accounts
  - Groups are matched by name across accounts
  - New groups are created automatically in the destination account
  - Group membership is preserved when contacts are synced
  - System groups (like "myContacts") are excluded from synchronization

### Fixed

- **Incremental Sync Duplicate Creation Loop**: Fixed the root cause of recurring duplicate contacts that ping-ponged between accounts on every daemon run
  - A mapped contact absent from an incremental fetch was treated as deleted, so its surviving partner was re-created in the other account each run
  - Phase 0 matching now verifies a missing partner with a direct `people.get` before deciding: still exists → pair stays matched; genuinely gone (404) → the stale mapping is removed; transient error → the pair is safely skipped for that run
  - Contact creations are never decided from an incremental delta anymore: if an incremental analysis queues creates, the engine re-analyzes with full account state first (deletions detected from the delta are preserved)
  - The daemon now honors the `full` setting from `config.yaml` instead of always forcing incremental sync
  - Mapping updates that re-point an existing pair to different contacts now log a warning for visibility
- **Daemon Now Loads Sync Configuration**: Fixed critical bug where the daemon scheduler was not loading `sync_config.json`
  - Previously, daemon syncs ignored group filtering settings, causing contacts from all groups to sync
  - This could result in mass duplicate contact creation when group filtering was expected
  - Daemon now properly loads and applies `sync_groups`, `target_group`, `group_sync_mode`, and `preserve_source_groups` settings

### Changed

- Contact content hash now includes photo URL for accurate change detection
- Sync summary output now shows photo sync statistics (photos synced, deleted, failed)
- Dry-run mode now displays pending photo changes without applying them

### Technical Details

- Added `photo_url`, `photo_data`, and `photo_etag` fields to Contact model
- Added `memberships` field to Contact model for group tracking
- New `gcontact_sync/sync/photo.py` module with `download_photo()` and `process_photo()` functions
- New `gcontact_sync/sync/group.py` module for contact group handling
- Added `upload_photo()` and `delete_photo()` methods to PeopleAPI
- Added comprehensive test coverage for photo and group synchronization (737 tests total)
