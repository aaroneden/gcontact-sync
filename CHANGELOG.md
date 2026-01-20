# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
