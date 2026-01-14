# GContact Sync

A Python-based bidirectional synchronization system that keeps Google Contacts synchronized between two separate Google accounts.

## Features

- **Bidirectional Sync**: Automatically synchronize contacts between two Google accounts
- **Conflict Resolution**: Last-modified-wins strategy for handling conflicting changes
- **Dry Run Mode**: Preview changes before applying them
- **State Tracking**: SQLite-based state management for efficient incremental syncs
- **CLI Interface**: Simple command-line interface for all operations

## Requirements

- Python 3.8 or higher
- Google Cloud Project with People API enabled
- OAuth 2.0 credentials (Desktop application type)

## Installation

### From Source

```bash
# Clone the repository
git clone https://github.com/example/gcontact-sync.git
cd gcontact-sync

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Or install in development mode
pip install -e ".[dev]"
```

### Using pip

```bash
pip install gcontact-sync
```

## Google Cloud Setup

Before using GContact Sync, you need to set up a Google Cloud Project:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the **People API**:
   - Navigate to "APIs & Services" > "Library"
   - Search for "People API"
   - Click "Enable"
4. Create OAuth 2.0 credentials:
   - Navigate to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Select "Desktop application" as the application type
   - Download the credentials JSON file
5. Place the credentials file:
   ```bash
   mkdir -p ~/.gcontact-sync
   cp ~/Downloads/client_secret_*.json ~/.gcontact-sync/credentials.json
   ```

## Configuration

GContact Sync stores all configuration in `~/.gcontact-sync/` by default:

| File | Purpose |
|------|---------|
| `credentials.json` | OAuth client credentials from Google Cloud Console |
| `token_account1.json` | OAuth tokens for Account 1 (generated after auth) |
| `token_account2.json` | OAuth tokens for Account 2 (generated after auth) |
| `sync.db` | SQLite database for state tracking |

### Environment Variables (Optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `GCONTACT_SYNC_CONFIG_DIR` | Override config directory location | `~/.gcontact-sync/` |
| `GCONTACT_SYNC_LOG_LEVEL` | Set logging level | `INFO` |
| `GCONTACT_SYNC_DEBUG` | Enable debug mode | `false` |

## Usage

### Authenticate Accounts

Before syncing, authenticate both Google accounts:

```bash
# Authenticate first account
gcontact-sync auth --account account1

# Authenticate second account
gcontact-sync auth --account account2
```

Each command will open a browser window for OAuth authorization.

### Check Status

View authentication and sync status:

```bash
gcontact-sync status
```

### Sync Contacts

#### Preview Changes (Dry Run)

Always recommended before the first sync:

```bash
gcontact-sync sync --dry-run
```

#### Execute Sync

```bash
gcontact-sync sync
```

#### Force Full Sync

Ignore sync tokens and perform a complete comparison:

```bash
gcontact-sync sync --full
```

#### Verbose Output

For detailed logging:

```bash
gcontact-sync sync --verbose
```

### Command Reference

```bash
# Show all available commands
gcontact-sync --help

# Show help for a specific command
gcontact-sync sync --help
gcontact-sync auth --help
gcontact-sync status --help
```

## How It Works

### Sync Algorithm

1. **Fetch Contacts**: Retrieve all contacts from both accounts using the Google People API
2. **Build Index**: Create matching keys based on normalized name + primary email
3. **Compare**: Identify contacts that exist in only one account or both
4. **Resolve Conflicts**: For contacts in both accounts with different data, the last-modified version wins
5. **Execute Changes**: Create missing contacts and update outdated ones
6. **Track State**: Store sync tokens and mappings in SQLite for efficient future syncs

### Matching Strategy

Contacts are matched between accounts using a normalized key combining:
- Display name (lowercased, whitespace normalized)
- Primary email address (if available)

This ensures the same person isn't duplicated even if they have slightly different resource names in each account.

### Conflict Resolution

When the same contact has been modified in both accounts since the last sync:
- The **last-modified-wins** strategy is applied
- The contact with the most recent modification timestamp is considered authoritative
- The other account's contact is updated to match

## Development

### Setup Development Environment

```bash
# Install with development dependencies
pip install -e ".[dev]"
```

### Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=gcontact_sync

# Run specific test file
pytest tests/test_sync.py -v
```

### Code Quality

```bash
# Format code
black gcontact_sync tests
isort gcontact_sync tests

# Lint
flake8 gcontact_sync tests

# Type check
mypy gcontact_sync
```

## Project Structure

```
gcontact-sync/
├── gcontact_sync/
│   ├── __init__.py           # Package initialization
│   ├── __main__.py           # CLI entry point
│   ├── cli.py                # CLI commands (Click)
│   ├── auth/
│   │   └── google_auth.py    # OAuth2 authentication
│   ├── api/
│   │   └── people_api.py     # Google People API wrapper
│   ├── sync/
│   │   ├── engine.py         # Core sync logic
│   │   ├── contact.py        # Contact data model
│   │   └── conflict.py       # Conflict resolution
│   ├── storage/
│   │   └── db.py             # SQLite state management
│   └── utils/
│       └── logging.py        # Logging configuration
├── tests/                    # Unit and integration tests
├── requirements.txt          # Production dependencies
├── requirements-dev.txt      # Development dependencies
└── pyproject.toml           # Project configuration
```

## Security Considerations

- **Never commit credentials**: OAuth tokens and credentials should never be committed to version control
- **Secure storage**: All sensitive data is stored in the user's home directory, not the project
- **Minimal scopes**: The application only requests the `contacts` scope needed for sync operations

## Limitations

- **No photo sync**: Contact photos are not synchronized
- **No group sync**: Contact groups/labels are not synchronized
- **No automated scheduling**: Use external tools like cron for scheduled syncs

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request
