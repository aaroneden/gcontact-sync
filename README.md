# GContact Sync

A Python-based bidirectional synchronization system that keeps Google Contacts synchronized between two separate Google accounts.

## Features

- **Bidirectional Sync**: Automatically synchronize contacts between two Google accounts
- **Multi-Tier Matching**: Deterministic, fuzzy, and optional LLM-assisted matching to identify contacts across accounts
- **Change Detection**: Content hashing detects modifications and propagates updates automatically
- **Deletion Sync**: Deleted contacts are automatically removed from the other account
- **Conflict Resolution**: Last-modified-wins strategy (or configurable account preference) for conflicting changes
- **Dry Run Mode**: Preview changes before applying them
- **State Tracking**: SQLite-based state management for efficient incremental syncs
- **CLI Interface**: Simple command-line interface for all operations

## Requirements

- Python 3.9 or higher
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
| `config.yaml` | Optional configuration file for sync preferences (see below) |

### Configuration File (Optional)

You can create a `config.yaml` file to store sync preferences and avoid passing CLI arguments repeatedly.

#### Creating a Config File

Generate a default configuration file with all available options:

```bash
uv run gcontact-sync init-config
```

This creates `~/.gcontact-sync/config.yaml` with documented defaults. You can also view the example at [`config/config.example.yaml`](config/config.example.yaml).

#### Available Options

The config file supports these options:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `verbose` | boolean | `false` | Enable verbose output with detailed logging |
| `debug` | boolean | `false` | Show debug information including sample matches |
| `dry_run` | boolean | `false` | Preview changes without applying them |
| `full` | boolean | `false` | Force full sync by ignoring sync tokens |
| `strategy` | string | `last_modified` | Conflict resolution strategy (see below) |
| `similarity_threshold` | float | `0.8` | Threshold for fuzzy matching (0.0 to 1.0) |
| `batch_size` | integer | `100` | Number of contacts to process per batch |

**Conflict Resolution Strategies:**
- `last_modified` (recommended): Use the most recently modified version
- `newest`: Alias for `last_modified`
- `account1`: Always prefer changes from Account 1
- `account2`: Always prefer changes from Account 2
- `manual`: Prompt for each conflict (not yet implemented)

#### Example Configuration

```yaml
# Conservative mode - preview all changes
verbose: true
dry_run: true
strategy: last_modified

# Production mode - automatic sync
# verbose: false
# dry_run: false
# strategy: last_modified
```

#### Using the Config File

Once created, the config file is automatically loaded. CLI arguments always override config values:

```bash
# Use config file defaults
uv run gcontact-sync sync

# Override specific options from CLI
uv run gcontact-sync sync --verbose --dry-run

# Use custom config file location
uv run gcontact-sync --config-file /path/to/config.yaml sync
```

### Environment Variables (Optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `GCONTACT_SYNC_CONFIG_DIR` | Override config directory location | `~/.gcontact-sync/` |
| `GCONTACT_SYNC_LOG_LEVEL` | Set logging level | `INFO` |
| `GCONTACT_SYNC_DEBUG` | Enable debug mode | `false` |
| `ANTHROPIC_API_KEY` | API key for LLM-assisted matching (Tier 3) | None (LLM matching disabled) |

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
3. **Match Contacts**: Use multi-tier matching to identify the same contact across accounts
4. **Detect Changes**: Compare content hashes to determine what changed since last sync
5. **Resolve Conflicts**: For contacts modified in both accounts, apply conflict resolution strategy
6. **Execute Changes**: Create, update, or delete contacts as needed
7. **Track State**: Store sync tokens, mappings, and content hashes in SQLite

### Multi-Tier Matching System

Contacts are matched between accounts using a sophisticated multi-tier approach:

#### Tier 1: Deterministic Matching (High Confidence)
- **Exact email match**: Any shared email address (normalized, case-insensitive)
- **Exact phone match**: Any shared phone number (digits only, normalized)
- **Exact name match**: Identical display names (normalized, case-insensitive)

#### Tier 2: Fuzzy Matching (Medium Confidence)
- **Similar name + shared email**: ≥85% name similarity (Jaro-Winkler) plus shared email
- **Similar name + shared phone**: ≥85% name similarity plus shared phone
- **Exact name, no identifiers**: ≥95% name match when neither contact has emails/phones

#### Tier 3: LLM-Assisted Matching (Optional)
For uncertain cases (70-85% name similarity, no shared identifiers):
- Uses Claude API to analyze contact pairs
- Considers name variations, nicknames, email domain patterns, organization context
- Requires `ANTHROPIC_API_KEY` environment variable
- Can be disabled via configuration

This ensures:
- The same person isn't duplicated even with different resource names
- Contacts with emails in different fields (work vs. home) are still matched
- Name variations like "Bob Smith" and "Robert Smith" can be matched
- Edge cases are handled intelligently with LLM assistance

### Change Detection

The system uses **content hashing** to efficiently detect changes:

- Each contact generates a SHA-256 hash of its syncable content (name, emails, phones, organizations, notes)
- The hash from the last successful sync is stored in the database
- On each sync, current hashes are compared against the stored hash

This three-way comparison determines the appropriate action:

| Account 1 | Account 2 | Action |
|-----------|-----------|--------|
| Changed | Unchanged | Update Account 2 with Account 1's data |
| Unchanged | Changed | Update Account 1 with Account 2's data |
| Changed | Changed | Apply conflict resolution strategy |
| Unchanged | Unchanged | No action needed |

### Deletion Propagation

When you delete a contact in one account, the sync system automatically deletes it in the other:

1. Google's People API marks deleted contacts with a `deleted` flag when using sync tokens
2. The sync engine detects deleted contacts and looks up their mapping
3. The corresponding contact in the other account is queued for deletion
4. The database mapping is removed after successful deletion

**Note**: Deletions only propagate for contacts that were previously synced (have a mapping in the database).

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
uv run ruff format gcontact_sync tests

# Lint (check only)
uv run ruff check gcontact_sync tests

# Lint and auto-fix
uv run ruff check --fix gcontact_sync tests

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
│   │   ├── conflict.py       # Conflict resolution strategies
│   │   ├── matcher.py        # Multi-tier contact matching
│   │   └── llm_matcher.py    # LLM-assisted matching (Tier 3)
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
