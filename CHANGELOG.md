# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
