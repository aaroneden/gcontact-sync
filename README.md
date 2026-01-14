# GContact Sync

A Python-based bidirectional synchronization system that keeps Google Contacts synchronized between two separate Google accounts.

## Features

- **Bidirectional Sync**: Automatically synchronize contacts between two Google accounts
- **Conflict Resolution**: Last-modified-wins strategy for handling conflicting changes
- **Dry Run Mode**: Preview changes before applying them
- **State Tracking**: SQLite-based state management for efficient incremental syncs
- **CLI Interface**: Simple command-line interface for all operations
- **Robust Matching**: Multi-field contact matching using names, emails, and phone numbers to prevent duplicates

## Requirements

- Python 3.8 or higher
- [UV](https://docs.astral.sh/uv/) package manager (recommended) or pip
- Google Cloud Project with People API enabled
- OAuth 2.0 credentials (Desktop application type)

## Installation

### Using UV (Recommended)

```bash
# Clone the repository
git clone https://github.com/example/gcontact-sync.git
cd gcontact-sync

# Install dependencies with UV
uv sync

# Or install in development mode with dev dependencies
uv sync --dev
```

### Using pip (Alternative)

```bash
# Clone the repository
git clone https://github.com/example/gcontact-sync.git
cd gcontact-sync

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install the package
pip install -e ".[dev]"
```

## Google Cloud Setup

Before using GContact Sync, you need to set up a Google Cloud Project.

### Automated Setup (Recommended)

We provide a setup script that automates most of the Google Cloud configuration:

```bash
# Make the script executable
chmod +x scripts/setup_gcloud.sh

# Run the setup script
./scripts/setup_gcloud.sh
```

The script will:
1. Check for gcloud CLI installation
2. Authenticate you with Google Cloud (if needed)
3. Create or select a project
4. Enable the People API
5. Configure the OAuth consent screen
6. Create OAuth credentials
7. Download and save the credentials file

### Manual Setup

If you prefer manual setup or the script doesn't work for your environment:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the **People API**:
   - Navigate to "APIs & Services" > "Library"
   - Search for "People API"
   - Click "Enable"
4. Configure OAuth Consent Screen:
   - Navigate to "APIs & Services" > "OAuth consent screen"
   - Select "External" user type
   - Fill in required fields (app name, user support email, developer contact)
   - Add scope: `https://www.googleapis.com/auth/contacts`
   - Add test users (your two Google account emails)
5. Create OAuth 2.0 credentials:
   - Navigate to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Select "Desktop application" as the application type
   - Download the credentials JSON file
6. Place the credentials file:
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
# With UV
uv run gcontact-sync auth --account account1
uv run gcontact-sync auth --account account2

# Or if installed globally
gcontact-sync auth --account account1
gcontact-sync auth --account account2
```

Each command will open a browser window for OAuth authorization.

### Check Status

View authentication and sync status:

```bash
uv run gcontact-sync status
```

### Sync Contacts

#### Preview Changes (Dry Run)

Always recommended before the first sync:

```bash
uv run gcontact-sync sync --dry-run
```

#### Execute Sync

```bash
uv run gcontact-sync sync
```

#### Force Full Sync

Ignore sync tokens and perform a complete comparison:

```bash
uv run gcontact-sync sync --full
```

#### Verbose Output

For detailed logging:

```bash
uv run gcontact-sync sync --verbose
```

### Command Reference

```bash
# Show all available commands
uv run gcontact-sync --help

# Show help for a specific command
uv run gcontact-sync sync --help
uv run gcontact-sync auth --help
uv run gcontact-sync status --help
```

## How It Works

### Sync Algorithm

1. **Fetch Contacts**: Retrieve all contacts from both accounts using the Google People API
2. **Build Index**: Create matching keys based on normalized contact data
3. **Compare**: Identify contacts that exist in only one account or both
4. **Resolve Conflicts**: For contacts in both accounts with different data, the last-modified version wins
5. **Execute Changes**: Create missing contacts and update outdated ones
6. **Track State**: Store sync tokens and mappings in SQLite for efficient future syncs

### Matching Strategy

Contacts are matched between accounts using a robust multi-field fingerprint to prevent duplicates:

1. **Primary matching**: Normalized display name
2. **Email matching**: All email addresses (normalized, sorted) - regardless of type (work/home/other)
3. **Phone matching**: All phone numbers (normalized to digits only, sorted)

This ensures:
- The same person isn't duplicated even with different resource names
- Contacts with emails in different fields (work vs. home) are still matched
- Multiple phone numbers are considered in matching

### Conflict Resolution

When the same contact has been modified in both accounts since the last sync:
- The **last-modified-wins** strategy is applied by default
- The contact with the most recent modification timestamp is considered authoritative
- The other account's contact is updated to match
- Alternative strategies available: `--strategy account1` or `--strategy account2`

## Development

### Setup Development Environment

```bash
# Install with development dependencies
uv sync --dev
```

### Run Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=gcontact_sync

# Run specific test file
uv run pytest tests/test_sync.py -v
```

### Code Quality

```bash
# Format code
uv run black gcontact_sync tests
uv run isort gcontact_sync tests

# Lint
uv run flake8 gcontact_sync tests

# Type check
uv run mypy gcontact_sync
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
├── scripts/
│   └── setup_gcloud.sh       # Google Cloud setup script
├── tests/                    # Unit and integration tests
└── pyproject.toml           # Project configuration (UV/pip compatible)
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
