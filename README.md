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

### Using Docker (Alternative)

GContact Sync provides Docker support for containerized deployments. This is ideal for running the application in isolated environments or on servers without Python installed.

#### Prerequisites

- Docker Engine 20.10+ ([Install Docker](https://docs.docker.com/engine/install/))
- Docker Compose 2.0+ ([Install Docker Compose](https://docs.docker.com/compose/install/))

#### Quick Start with Docker Compose

```bash
# Clone the repository
git clone https://github.com/example/gcontact-sync.git
cd gcontact-sync

# Create required directories for volume mounts
mkdir -p config data credentials

# Copy environment template
cp .env.example .env

# Build the Docker image
docker compose build

# Run commands using docker compose
docker compose run --rm gcontact-sync --help
```

#### Volume Mounts

The Docker container uses three volume mounts for persistent data:

| Host Path | Container Path | Purpose | Required |
|-----------|----------------|---------|----------|
| `./config` | `/app/config` | OAuth credentials and configuration files | Yes |
| `./data` | `/app/data` | SQLite database (sync.db) | Yes |
| `./credentials` | `/app/credentials` | Additional credential storage | Optional |

**Important**: Ensure these directories exist and have proper permissions before running the container:

```bash
mkdir -p config data credentials
chmod 755 config data credentials
```

#### Environment Variables for Docker

Create a `.env` file based on `.env.example` to configure the application:

```bash
# Copy the example file
cp .env.example .env

# Edit the file with your preferred settings
nano .env  # or use your preferred editor
```

Available environment variables:

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `GCONTACT_SYNC_CONFIG_DIR` | Config directory path inside container | `/app/config` | `/app/config` |
| `GCONTACT_SYNC_LOG_LEVEL` | Logging level | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `GCONTACT_SYNC_DEBUG` | Enable debug mode | `false` | `true`, `false` |
| `ANTHROPIC_API_KEY` | API key for LLM-assisted matching | None | `sk-ant-...` |

**Note**: OAuth credentials (`credentials.json`, `token_*.json`) should be placed in the `config/` directory, NOT in environment variables.

#### Docker Usage Examples

**Authenticate accounts:**
```bash
# Authenticate Account 1
docker compose run --rm gcontact-sync auth --account account1

# Authenticate Account 2
docker compose run --rm gcontact-sync auth --account account2
```

**Check status:**
```bash
docker compose run --rm gcontact-sync status
```

**Sync contacts (dry run):**
```bash
docker compose run --rm gcontact-sync sync --dry-run
```

**Execute sync:**
```bash
docker compose run --rm gcontact-sync sync
```

**Verbose sync with full refresh:**
```bash
docker compose run --rm gcontact-sync sync --full --verbose
```

**Initialize config file:**
```bash
docker compose run --rm gcontact-sync init-config
```

#### Building the Docker Image Manually

If you prefer to build without docker-compose:

```bash
# Build the image
docker build -t gcontact-sync:latest .

# Run with volume mounts
docker run --rm \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/credentials:/app/credentials \
  --env-file .env \
  gcontact-sync:latest --help
```

#### Health Checks

The Docker container includes a health check that runs every 30 seconds:

```bash
# Check container health status
docker compose ps

# View health check logs
docker inspect --format='{{json .State.Health}}' gcontact-sync | jq
```

The health check uses the `gcontact-sync health` command to verify the application is functioning correctly.

#### Docker Compose Configuration Customization

The `docker-compose.yml` file can be customized for your deployment:

**Enable resource limits** (uncomment in docker-compose.yml):
```yaml
deploy:
  resources:
    limits:
      cpus: '1.0'
      memory: 512M
    reservations:
      cpus: '0.25'
      memory: 128M
```

**Use named volumes instead of bind mounts** (uncomment in docker-compose.yml):
```yaml
volumes:
  config:
  data:
  credentials:
```

Then update the volume mounts in the service definition:
```yaml
volumes:
  - config:/app/config:rw
  - data:/app/data:rw
  - credentials:/app/credentials:rw
```

#### Troubleshooting Docker Deployment

**Problem**: Permission denied errors when accessing mounted volumes

**Solution**: Ensure the host directories have the correct permissions. The container runs as user ID 1000:

```bash
# Set correct ownership (Linux/macOS)
sudo chown -R 1000:1000 config data credentials

# Or make directories world-writable (less secure)
chmod 777 config data credentials
```

**Problem**: OAuth authentication fails in Docker

**Solution**: Make sure `credentials.json` is in the `config/` directory and the container can access it:

```bash
# Check if file exists and is readable
ls -la config/credentials.json

# Copy credentials if missing
cp ~/Downloads/client_secret_*.json config/credentials.json
```

**Problem**: Container exits immediately or shows "No such file or directory"

**Solution**: Verify the volume mounts and environment variables:

```bash
# Check docker compose configuration
docker compose config

# View container logs
docker compose logs gcontact-sync

# Run with interactive shell for debugging
docker compose run --rm --entrypoint /bin/bash gcontact-sync
```

**Problem**: Database locked errors

**Solution**: Ensure only one container instance is accessing the database:

```bash
# Stop all running containers
docker compose down

# Remove any stale lock files
rm -f data/.sync.db-*

# Restart with clean state
docker compose run --rm gcontact-sync status
```

**Problem**: Health check failures

**Solution**: The health check command requires the application to be properly configured:

```bash
# Disable health check temporarily (docker-compose.yml)
# Comment out the healthcheck section

# Or check what's failing
docker compose run --rm gcontact-sync health
```

**Problem**: Cannot access Google OAuth consent screen during authentication

**Solution**: OAuth authentication requires a browser. For headless servers:

1. Authenticate on a local machine first
2. Copy the token files to your server:
   ```bash
   # On local machine after auth
   scp config/token_*.json user@server:/path/to/gcontact-sync/config/
   ```
3. Or use SSH port forwarding to access the OAuth flow

**Problem**: Building fails with dependency errors

**Solution**: Clear Docker build cache and rebuild:

```bash
# Remove existing images and build cache
docker compose down --rmi all
docker builder prune -a

# Rebuild from scratch
docker compose build --no-cache
```

**Problem**: Sync is slow or times out in Docker

**Solution**: Increase resource limits and timeout settings:

```bash
# Run with increased verbosity to identify bottlenecks
docker compose run --rm gcontact-sync sync --verbose

# Check container resource usage
docker stats gcontact-sync
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
