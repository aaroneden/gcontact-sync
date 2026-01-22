# Docker Deployment Guide for GContact Sync

This guide provides comprehensive instructions for deploying and running GContact Sync in Docker containers. Docker deployment is ideal for production environments, servers without Python installed, or isolated development environments.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Detailed Setup](#detailed-setup)
  - [1. Clone and Prepare](#1-clone-and-prepare)
  - [2. Configure Environment](#2-configure-environment)
  - [3. Build the Image](#3-build-the-image)
  - [4. Configure OAuth Credentials](#4-configure-oauth-credentials)
  - [5. Authenticate Accounts](#5-authenticate-accounts)
- [Running Sync Operations](#running-sync-operations)
- [Scheduled Execution](#scheduled-execution)
- [Health Monitoring](#health-monitoring)
- [Troubleshooting](#troubleshooting)
- [Advanced Topics](#advanced-topics)

## Prerequisites

Before deploying GContact Sync with Docker, ensure you have:

### Required Software

- **Docker Engine 20.10+** - [Installation Guide](https://docs.docker.com/engine/install/)
  - Linux: Install via package manager or Docker's official repository
  - macOS: Install [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/)
  - Windows: Install [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/)
- **Docker Compose 2.0+** - [Installation Guide](https://docs.docker.com/compose/install/)
  - Included with Docker Desktop
  - Linux: Install separately via package manager

Verify your installation:
```bash
docker --version
# Expected: Docker version 20.10.x or higher

docker compose version
# Expected: Docker Compose version 2.x.x or higher
```

### Google Cloud Prerequisites

You need a Google Cloud Project with OAuth credentials configured:

1. **Google Cloud Project** with People API enabled
2. **OAuth 2.0 credentials** (Desktop application type)
3. **OAuth consent screen** configured with test users
4. Downloaded **credentials JSON file** from Google Cloud Console

See the [Google Cloud Setup](README.md#google-cloud-setup) section in the main README for detailed instructions.

### System Requirements

- **CPU**: 0.25-1.0 cores (minimal CPU usage)
- **Memory**: 128-512 MB RAM (depends on contact count)
- **Storage**: 100 MB for image + space for data volumes
- **Network**: Outbound HTTPS access to Google APIs

## Quick Start

For experienced users who want to get started immediately:

```bash
# Clone and navigate
git clone https://github.com/example/gcontact-sync.git
cd gcontact-sync

# Prepare directories and environment
mkdir -p config data credentials
cp .env.example .env

# Place your Google OAuth credentials
cp ~/Downloads/client_secret_*.json config/credentials.json

# Build and verify
docker compose build
docker compose run --rm gcontact-sync --help

# Authenticate both accounts
docker compose run --rm gcontact-sync auth --account account1
docker compose run --rm gcontact-sync auth --account account2

# Test with dry run
docker compose run --rm gcontact-sync sync --dry-run

# Execute sync
docker compose run --rm gcontact-sync sync
```

For detailed explanations, continue reading below.

## Detailed Setup

### 1. Clone and Prepare

Clone the repository and create the required directory structure:

```bash
# Clone the repository
git clone https://github.com/example/gcontact-sync.git
cd gcontact-sync

# Create directories for volume mounts
mkdir -p config data credentials

# Verify directory creation
ls -la config data credentials
```

**Directory purposes:**
- **`config/`** - OAuth credentials and token files
- **`data/`** - SQLite database for sync state
- **`credentials/`** - Additional credential storage (optional)

Set proper permissions (especially important on Linux):
```bash
# Option 1: Set ownership to your user (recommended)
sudo chown -R $(id -u):$(id -g) config data credentials

# Option 2: Make directories writable (less secure, but simpler)
chmod 755 config data credentials
```

### 2. Configure Environment

Create your environment configuration file:

```bash
# Copy the example file
cp .env.example .env

# Edit with your preferred editor
nano .env  # or vim, vi, code, etc.
```

**Basic configuration** (`.env` file):
```bash
# Optional: Override config directory (use container path)
GCONTACT_SYNC_CONFIG_DIR=/app/config

# Optional: Set logging level
GCONTACT_SYNC_LOG_LEVEL=INFO

# Optional: Enable debug mode
GCONTACT_SYNC_DEBUG=false

# Optional: Anthropic API key for LLM-assisted matching
# ANTHROPIC_API_KEY=sk-ant-your-key-here
```

**Configuration notes:**
- Most users can leave the defaults unchanged
- `GCONTACT_SYNC_CONFIG_DIR` should use container paths (`/app/config`)
- OAuth credentials are stored as files, NOT in environment variables
- LLM-assisted matching (Tier 3) requires an Anthropic API key

### 3. Build the Image

Build the Docker image using Docker Compose:

```bash
# Build the image
docker compose build

# Verify the build succeeded
docker images | grep gcontact-sync
```

**Expected output:**
```
gcontact-sync   latest   abc123def456   2 minutes ago   200MB
```

**Build options:**

For a clean rebuild (if you encounter issues):
```bash
# Clear build cache and rebuild
docker compose build --no-cache
```

For faster rebuilds during development:
```bash
# Build with BuildKit (faster, better caching)
DOCKER_BUILDKIT=1 docker compose build
```

### 4. Configure OAuth Credentials

#### Step 1: Obtain OAuth Credentials

If you haven't already, create OAuth credentials in Google Cloud Console:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select or create a project
3. Enable the **People API**
4. Configure **OAuth consent screen** with your account emails as test users
5. Create **OAuth 2.0 Client ID** (Desktop application type)
6. Download the credentials JSON file

Alternatively, use the automated setup script:
```bash
# Run setup script (requires gcloud CLI)
./scripts/setup_gcloud.sh
```

#### Step 2: Place Credentials in Config Directory

Copy the downloaded credentials file:

```bash
# Copy from Downloads (adjust path as needed)
cp ~/Downloads/client_secret_*.json config/credentials.json

# Verify the file
ls -lh config/credentials.json
```

**Important:** The file must be named `credentials.json` exactly.

#### Step 3: Verify Credentials Format

Ensure your credentials file has the correct structure:

```bash
# Check the file contains OAuth credentials
cat config/credentials.json | grep -q "client_id" && echo "✓ Valid credentials file" || echo "✗ Invalid format"
```

The file should contain fields like:
- `client_id`
- `client_secret`
- `redirect_uris`
- `auth_uri`
- `token_uri`

### 5. Authenticate Accounts

Authenticate both Google accounts to generate OAuth tokens:

#### Authenticate Account 1

```bash
docker compose run --rm gcontact-sync auth --account account1
```

**What happens:**
1. The command opens a browser window (or provides a URL)
2. You sign in with your first Google account
3. You authorize the application to access contacts
4. An OAuth token is saved to `config/token_account1.json`

**Troubleshooting authentication:**

If the browser doesn't open automatically:
```
1. Look for a URL in the terminal output
2. Copy the URL manually
3. Paste it into your browser
4. Complete the OAuth flow
```

For **headless servers** (no browser available):
1. Authenticate on a local machine first
2. Copy the token file to your server:
   ```bash
   scp config/token_account1.json user@server:/path/to/gcontact-sync/config/
   ```

#### Authenticate Account 2

```bash
docker compose run --rm gcontact-sync auth --account account2
```

Repeat the same process for your second Google account. This generates `config/token_account2.json`.

#### Verify Authentication

Check that both token files were created:

```bash
# List token files
ls -lh config/token_*.json

# Expected output:
# config/token_account1.json
# config/token_account2.json
```

Verify authentication status:
```bash
docker compose run --rm gcontact-sync status
```

**Expected output:**
```
✓ Account 1: Authenticated (email@example.com)
✓ Account 2: Authenticated (other@example.com)
✓ Database: Initialized
Ready to sync
```

## Running Sync Operations

### Basic Sync Commands

#### Preview Changes (Dry Run)

Always recommended before your first sync or after configuration changes:

```bash
docker compose run --rm gcontact-sync sync --dry-run
```

**Output shows:**
- Contacts that would be created in each account
- Contacts that would be updated
- Contacts that would be deleted
- No actual changes are made

#### Execute Sync

Once you're confident with the dry run results:

```bash
docker compose run --rm gcontact-sync sync
```

This performs the actual synchronization:
- Creates missing contacts in each account
- Updates contacts that changed
- Deletes contacts removed from one account
- Stores sync state in the database

#### Verbose Sync

For detailed logging during sync operations:

```bash
docker compose run --rm gcontact-sync sync --verbose
```

Shows additional information:
- Each contact being processed
- Matching decisions (deterministic, fuzzy, LLM)
- API calls and responses
- Change detection details

#### Force Full Sync

Ignore sync tokens and compare all contacts:

```bash
docker compose run --rm gcontact-sync sync --full
```

**When to use:**
- After manually modifying contacts in Google Contacts
- When troubleshooting sync issues
- Periodically (e.g., weekly) to ensure consistency

**Note:** Full syncs are slower but more thorough.

### Advanced Sync Options

#### Combine Multiple Options

```bash
# Verbose dry run with full sync
docker compose run --rm gcontact-sync sync --verbose --dry-run --full

# Full sync with debug output
docker compose run --rm gcontact-sync sync --full --debug
```

#### Override Conflict Resolution Strategy

```bash
# Always prefer Account 1 changes
docker compose run --rm gcontact-sync sync --strategy account1

# Always prefer Account 2 changes
docker compose run --rm gcontact-sync sync --strategy account2

# Use most recent changes (default)
docker compose run --rm gcontact-sync sync --strategy last_modified
```

#### Custom Configuration File

Use a custom config file location:

```bash
# Mount custom config and specify path
docker run --rm \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/my-custom-config.yaml:/app/my-config.yaml \
  gcontact-sync:latest \
  --config-file /app/my-config.yaml sync
```

### Checking Sync Status

View current authentication and sync state:

```bash
docker compose run --rm gcontact-sync status
```

**Output includes:**
- Authentication status for both accounts
- Database state
- Last sync timestamp
- Contact counts per account

### Viewing Logs

Docker Compose captures all output. View logs:

```bash
# View recent logs
docker compose logs

# Follow logs in real-time
docker compose logs -f

# View last 50 lines
docker compose logs --tail=50
```

## Scheduled Execution

GContact Sync doesn't include built-in scheduling. Use system tools to run syncs automatically.

### Using Cron (Linux/macOS)

#### Create a Wrapper Script

Create `sync-gcontact.sh`:

```bash
#!/bin/bash
# sync-gcontact.sh - Automated sync wrapper

cd /path/to/gcontact-sync || exit 1

# Run sync with logging
docker compose run --rm gcontact-sync sync >> logs/sync.log 2>&1

# Exit with docker's exit code
exit $?
```

Make it executable:
```bash
chmod +x sync-gcontact.sh
```

#### Configure Cron Job

Edit your crontab:
```bash
crontab -e
```

Add a schedule (examples):

```cron
# Sync every hour
0 * * * * /path/to/sync-gcontact.sh

# Sync every 6 hours
0 */6 * * * /path/to/sync-gcontact.sh

# Sync daily at 2 AM
0 2 * * * /path/to/sync-gcontact.sh

# Sync Monday-Friday at 9 AM
0 9 * * 1-5 /path/to/sync-gcontact.sh
```

#### Monitor Cron Execution

Check cron logs to verify execution:

```bash
# View cron logs (Ubuntu/Debian)
grep CRON /var/log/syslog

# View sync logs
tail -f logs/sync.log
```

### Using Systemd Timers (Linux)

Systemd timers provide more flexibility than cron.

#### Create Service File

Create `/etc/systemd/system/gcontact-sync.service`:

```ini
[Unit]
Description=GContact Sync Service
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
User=youruser
WorkingDirectory=/path/to/gcontact-sync
ExecStart=/usr/local/bin/docker compose run --rm gcontact-sync sync
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

#### Create Timer File

Create `/etc/systemd/system/gcontact-sync.timer`:

```ini
[Unit]
Description=Run GContact Sync every 6 hours
Requires=gcontact-sync.service

[Timer]
# Run every 6 hours
OnCalendar=*-*-* 00,06,12,18:00:00
# Run 5 minutes after boot if missed
OnBootSec=5min
# Allow up to 1 hour variance to reduce load spikes
RandomizedDelaySec=1h
# Persistent timer (runs missed executions)
Persistent=true

[Install]
WantedBy=timers.target
```

#### Enable and Start Timer

```bash
# Reload systemd configuration
sudo systemctl daemon-reload

# Enable timer to start at boot
sudo systemctl enable gcontact-sync.timer

# Start timer now
sudo systemctl start gcontact-sync.timer

# Check timer status
sudo systemctl status gcontact-sync.timer

# List all timers
systemctl list-timers --all
```

#### View Logs

```bash
# View service logs
journalctl -u gcontact-sync.service

# Follow logs in real-time
journalctl -u gcontact-sync.service -f

# View logs since last boot
journalctl -u gcontact-sync.service -b
```

### Using Docker Compose with Restart Policy

For continuous sync operations, modify `docker-compose.yml`:

```yaml
services:
  gcontact-sync:
    # ... other configuration ...
    restart: unless-stopped
    command: ["sync", "--verbose"]
    # Add delay between syncs
    entrypoint: >
      /bin/sh -c "
      while true; do
        gcontact-sync sync --verbose;
        echo 'Sync completed. Waiting 6 hours...';
        sleep 21600;
      done
      "
```

Then start the service:
```bash
docker compose up -d
```

**Note:** This approach keeps a container running continuously. Use systemd timers or cron for more efficient resource usage.

### Using Cloud Schedulers

#### AWS ECS Scheduled Tasks

Deploy as an ECS task with CloudWatch Events:

1. Create ECS task definition with gcontact-sync image
2. Configure task to mount EFS volumes for persistent data
3. Create CloudWatch Events rule to trigger task on schedule

#### Google Cloud Scheduler + Cloud Run

1. Deploy container to Cloud Run
2. Configure Cloud Scheduler to invoke Cloud Run URL
3. Pass sync command as parameter

#### Azure Container Instances

1. Deploy container to ACI
2. Use Azure Logic Apps or Functions for scheduling
3. Trigger container execution on schedule

## Health Monitoring

### Built-in Health Check

The Docker container includes a health check that runs automatically:

```bash
# View health status
docker compose ps

# Expected output shows health status:
# NAME              STATUS
# gcontact-sync     Up 2 minutes (healthy)
```

#### Health Check Details

- **Interval:** Every 30 seconds
- **Timeout:** 10 seconds
- **Start period:** 5 seconds (grace period)
- **Retries:** 3 attempts before marking unhealthy
- **Command:** `gcontact-sync health`

### Manual Health Check

Run the health command manually:

```bash
docker compose run --rm gcontact-sync health
```

**Healthy output:**
```
✓ Config directory accessible
✓ Database accessible
✓ Credentials file present
✓ Account 1 authenticated
✓ Account 2 authenticated
Health check passed
```

**Unhealthy output:**
```
✗ Account 1 not authenticated
✗ Account 2 not authenticated
Health check failed
```

Exit codes:
- `0` - Healthy
- `1` - Unhealthy

### Viewing Health Check Logs

Detailed health status from Docker:

```bash
# View full health status
docker inspect --format='{{json .State.Health}}' gcontact-sync | jq

# View last health check result
docker inspect --format='{{json .State.Health.Log}}' gcontact-sync | jq '.[0]'
```

### Integration with Monitoring Systems

#### Prometheus Monitoring

Create a simple exporter script:

```bash
#!/bin/bash
# gcontact-health-exporter.sh

while true; do
  if docker compose run --rm gcontact-sync health > /dev/null 2>&1; then
    echo "gcontact_sync_health 1" > /var/lib/node_exporter/textfile_collector/gcontact.prom
  else
    echo "gcontact_sync_health 0" > /var/lib/node_exporter/textfile_collector/gcontact.prom
  fi
  sleep 60
done
```

#### Healthchecks.io Integration

Ping healthchecks.io after successful syncs:

```bash
#!/bin/bash
# sync-with-monitoring.sh

cd /path/to/gcontact-sync || exit 1

# Run sync
if docker compose run --rm gcontact-sync sync; then
  # Success - ping healthchecks.io
  curl -fsS --retry 3 https://hc-ping.com/your-uuid-here
else
  # Failure - ping with /fail
  curl -fsS --retry 3 https://hc-ping.com/your-uuid-here/fail
fi
```

#### Uptime Kuma / Uptime Robot

Configure HTTP(S) monitoring:
- Create a simple web endpoint that runs health check
- Monitor the endpoint from Uptime Kuma/Robot
- Alert on failures

## Troubleshooting

### Common Issues and Solutions

#### 1. Permission Denied Errors

**Symptoms:**
```
Error: Permission denied: '/app/config/credentials.json'
Error: Cannot write to /app/data/sync.db
```

**Cause:** The container runs as user ID 1000, but host directories have different ownership.

**Solutions:**

Option A - Change ownership (recommended):
```bash
# Set ownership to UID 1000
sudo chown -R 1000:1000 config data credentials
```

Option B - Make directories world-writable (less secure):
```bash
chmod 777 config data credentials
```

Option C - Run container as your user (override docker-compose.yml):
```bash
docker compose run --rm --user $(id -u):$(id -g) gcontact-sync status
```

#### 2. OAuth Authentication Failures

**Symptoms:**
```
Error: invalid_grant
Error: Token has been expired or revoked
Error: Cannot open browser for authentication
```

**Solutions:**

For expired tokens:
```bash
# Delete token files and re-authenticate
rm config/token_*.json
docker compose run --rm gcontact-sync auth --account account1
docker compose run --rm gcontact-sync auth --account account2
```

For headless servers:
```bash
# Authenticate on local machine first
# Then copy token files to server
scp config/token_*.json user@server:/path/to/gcontact-sync/config/
```

For "cannot open browser" errors:
```bash
# Look for the authorization URL in the output
# Manually copy and paste it into a browser
# Complete the OAuth flow
# Paste the authorization code back into the terminal
```

#### 3. Container Exits Immediately

**Symptoms:**
```
Container starts but exits with code 0 or 1
No error messages shown
```

**Diagnosis:**

Check container logs:
```bash
docker compose logs gcontact-sync
```

Verify configuration:
```bash
docker compose config
```

Run with interactive shell:
```bash
docker compose run --rm --entrypoint /bin/bash gcontact-sync
# Then manually run commands inside container
```

**Common causes:**
- Missing volume mounts
- Incorrect environment variables
- Missing credentials file

#### 4. Database Locked Errors

**Symptoms:**
```
sqlite3.OperationalError: database is locked
Error: Cannot access database
```

**Cause:** Multiple container instances trying to access the same SQLite database.

**Solution:**

Stop all running containers:
```bash
# Stop all gcontact-sync containers
docker compose down

# Remove any orphaned containers
docker ps -a | grep gcontact-sync | awk '{print $1}' | xargs docker rm

# Remove stale lock files
rm -f data/*.db-journal data/*.db-wal

# Restart with clean state
docker compose run --rm gcontact-sync status
```

**Prevention:**
- Never run multiple sync operations simultaneously
- Use systemd timers instead of cron (better concurrency control)
- Add file locking in wrapper scripts

#### 5. Health Check Failures

**Symptoms:**
```
docker compose ps shows (unhealthy)
Container restarts frequently
```

**Diagnosis:**

Run health check manually:
```bash
docker compose run --rm gcontact-sync health
```

Check what's failing and address the specific issue.

**Temporary workaround:**

Disable health check (edit `docker-compose.yml`):
```yaml
# Comment out the healthcheck section
# healthcheck:
#   test: ["CMD", "gcontact-sync", "health"]
#   ...
```

#### 6. API Rate Limiting

**Symptoms:**
```
Error: 429 Too Many Requests
Error: Quota exceeded
```

**Cause:** Google People API rate limits exceeded.

**Solutions:**

Reduce sync frequency:
```bash
# Instead of hourly, sync every 6 hours
0 */6 * * * /path/to/sync-gcontact.sh
```

Use incremental syncs (not full):
```bash
# Let the system use sync tokens
docker compose run --rm gcontact-sync sync
# Don't use --full unless necessary
```

Add delays between operations:
```bash
#!/bin/bash
docker compose run --rm gcontact-sync sync
sleep 60  # Wait 1 minute
docker compose run --rm gcontact-sync sync --full
```

#### 7. Network Connectivity Issues

**Symptoms:**
```
Error: Cannot connect to googleapis.com
Error: Connection timeout
Error: SSL certificate verification failed
```

**Solutions:**

Verify Docker networking:
```bash
# Test connectivity from container
docker compose run --rm gcontact-sync /bin/bash -c "curl -I https://www.googleapis.com"
```

Check proxy settings (if behind corporate proxy):
```yaml
# In docker-compose.yml
environment:
  - HTTP_PROXY=http://proxy.example.com:8080
  - HTTPS_PROXY=http://proxy.example.com:8080
  - NO_PROXY=localhost,127.0.0.1
```

Update CA certificates:
```bash
# Rebuild image to get latest certificates
docker compose build --no-cache
```

#### 8. Build Failures

**Symptoms:**
```
Error: Failed to build image
Error: Cannot install dependencies
```

**Solutions:**

Clear Docker build cache:
```bash
# Remove build cache
docker builder prune -a

# Rebuild without cache
docker compose build --no-cache
```

Check for network issues during build:
```bash
# Build with verbose output
docker compose build --progress=plain
```

Verify pyproject.toml is valid:
```bash
# Check Python package definition
cat pyproject.toml
```

### Debugging Tips

#### View Container Processes

```bash
# List running processes in container
docker compose top
```

#### Interactive Shell Access

```bash
# Open shell in container
docker compose run --rm --entrypoint /bin/bash gcontact-sync

# Then explore the container:
ls -la /app/
env | grep GCONTACT
cat /app/config/credentials.json
```

#### Check Resource Usage

```bash
# Monitor resource usage
docker stats gcontact-sync

# View detailed container info
docker inspect gcontact-sync
```

#### Enable Debug Logging

```bash
# Run with debug output
docker compose run --rm \
  -e GCONTACT_SYNC_DEBUG=true \
  -e GCONTACT_SYNC_LOG_LEVEL=DEBUG \
  gcontact-sync sync --verbose
```

## Advanced Topics

### Production Deployment Best Practices

#### Security Hardening

1. **Use secrets management** for API keys:
   ```bash
   # Docker secrets (Swarm mode)
   echo "sk-ant-..." | docker secret create anthropic_api_key -
   ```

2. **Enable read-only root filesystem**:
   ```yaml
   # In docker-compose.yml
   read_only: true
   tmpfs:
     - /tmp
   ```

3. **Use non-root user** (already configured):
   ```yaml
   user: "1000:1000"
   ```

4. **Drop unnecessary capabilities**:
   ```yaml
   cap_drop:
     - ALL
   cap_add:
     - NET_BIND_SERVICE  # Only if needed
   ```

5. **Scan images for vulnerabilities**:
   ```bash
   # Using Trivy
   trivy image gcontact-sync:latest

   # Using Docker Scout
   docker scout cves gcontact-sync:latest
   ```

#### Resource Management

Configure resource limits for production:

```yaml
# In docker-compose.yml
deploy:
  resources:
    limits:
      cpus: '0.5'
      memory: 256M
    reservations:
      cpus: '0.1'
      memory: 64M
```

#### High Availability

For critical deployments:

1. **Use named volumes** instead of bind mounts:
   ```yaml
   volumes:
     config:
       driver: local
       driver_opts:
         type: nfs
         o: addr=nfs-server.local,rw
         device: ":/path/to/config"
   ```

2. **Implement backup strategy**:
   ```bash
   #!/bin/bash
   # backup-gcontact.sh
   DATE=$(date +%Y%m%d_%H%M%S)
   tar -czf "backup_${DATE}.tar.gz" config/ data/
   aws s3 cp "backup_${DATE}.tar.gz" s3://my-backups/gcontact-sync/
   ```

3. **Monitor sync success rate**:
   - Log all sync operations
   - Alert on consecutive failures
   - Track sync duration trends

### Using Named Volumes

Switch from bind mounts to Docker-managed volumes:

```yaml
# In docker-compose.yml
volumes:
  config:
  data:
  credentials:

services:
  gcontact-sync:
    volumes:
      - config:/app/config:rw
      - data:/app/data:rw
      - credentials:/app/credentials:rw
```

**Benefits:**
- Better performance on Windows/macOS
- Easier to backup and restore
- Portable across different hosts

**Managing named volumes:**
```bash
# List volumes
docker volume ls

# Backup volume
docker run --rm -v gcontact-sync_config:/data -v $(pwd):/backup ubuntu tar czf /backup/config-backup.tar.gz /data

# Restore volume
docker run --rm -v gcontact-sync_config:/data -v $(pwd):/backup ubuntu tar xzf /backup/config-backup.tar.gz -C /

# Remove volumes
docker volume rm gcontact-sync_config gcontact-sync_data
```

### Custom Build Options

#### Multi-Platform Builds

Build for different architectures (amd64, arm64):

```bash
# Enable BuildKit
export DOCKER_BUILDKIT=1

# Build for multiple platforms
docker buildx create --use
docker buildx build --platform linux/amd64,linux/arm64 -t gcontact-sync:latest .
```

#### Development vs Production Images

Create separate Dockerfiles:

**Dockerfile.dev:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY . .
RUN uv sync --dev
CMD ["uv", "run", "gcontact-sync", "--help"]
```

**Usage:**
```bash
# Development build
docker build -f Dockerfile.dev -t gcontact-sync:dev .

# Production build (use standard Dockerfile)
docker build -t gcontact-sync:prod .
```

### Integration with CI/CD

#### GitHub Actions Example

```yaml
# .github/workflows/docker.yml
name: Docker Build and Push

on:
  push:
    branches: [ main ]
    tags: [ 'v*' ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v2

      - name: Login to Docker Hub
        uses: docker/login-action@v2
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v4
        with:
          context: .
          push: true
          tags: |
            yourusername/gcontact-sync:latest
            yourusername/gcontact-sync:${{ github.ref_name }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

#### GitLab CI Example

```yaml
# .gitlab-ci.yml
docker-build:
  stage: build
  image: docker:latest
  services:
    - docker:dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
  only:
    - main
```

### Docker Swarm Deployment

Deploy to Docker Swarm for orchestration:

```yaml
# docker-stack.yml
version: '3.8'

services:
  gcontact-sync:
    image: gcontact-sync:latest
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
    volumes:
      - config:/app/config
      - data:/app/data
    secrets:
      - anthropic_api_key
    environment:
      - ANTHROPIC_API_KEY_FILE=/run/secrets/anthropic_api_key

volumes:
  config:
    driver: local
  data:
    driver: local

secrets:
  anthropic_api_key:
    external: true
```

Deploy the stack:
```bash
# Initialize Swarm (if not already)
docker swarm init

# Create secret
echo "sk-ant-..." | docker secret create anthropic_api_key -

# Deploy stack
docker stack deploy -c docker-stack.yml gcontact
```

### Kubernetes Deployment

Example Kubernetes manifests:

**deployment.yaml:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gcontact-sync
spec:
  replicas: 1
  selector:
    matchLabels:
      app: gcontact-sync
  template:
    metadata:
      labels:
        app: gcontact-sync
    spec:
      containers:
      - name: gcontact-sync
        image: gcontact-sync:latest
        command: ["sync", "--verbose"]
        volumeMounts:
        - name: config
          mountPath: /app/config
        - name: data
          mountPath: /app/data
        envFrom:
        - configMapRef:
            name: gcontact-sync-config
        resources:
          requests:
            memory: "64Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "500m"
      volumes:
      - name: config
        persistentVolumeClaim:
          claimName: gcontact-sync-config
      - name: data
        persistentVolumeClaim:
          claimName: gcontact-sync-data
```

**cronjob.yaml:**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: gcontact-sync
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: gcontact-sync
            image: gcontact-sync:latest
            args: ["sync"]
            volumeMounts:
            - name: config
              mountPath: /app/config
            - name: data
              mountPath: /app/data
          restartPolicy: OnFailure
          volumes:
          - name: config
            persistentVolumeClaim:
              claimName: gcontact-sync-config
          - name: data
            persistentVolumeClaim:
              claimName: gcontact-sync-data
```

## Additional Resources

### Official Documentation

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Google People API Reference](https://developers.google.com/people)

### Related Guides

- [Main README](README.md) - General usage and features
- [Google Cloud Setup](README.md#google-cloud-setup) - OAuth configuration
- [Configuration Guide](README.md#configuration) - Config file options

### Getting Help

If you encounter issues not covered in this guide:

1. Check the [troubleshooting section](#troubleshooting) above
2. Review container logs: `docker compose logs`
3. Run health check: `docker compose run --rm gcontact-sync health`
4. Open an issue on GitHub with:
   - Docker version (`docker --version`)
   - Docker Compose version (`docker compose version`)
   - Container logs
   - Steps to reproduce

### Contributing

Improvements to this Docker deployment guide are welcome! Please submit pull requests with:
- Corrections to existing content
- Additional troubleshooting scenarios
- Production deployment patterns
- Integration examples

---

**Note:** This guide assumes familiarity with Docker basics. For Docker fundamentals, see the [official Docker getting started guide](https://docs.docker.com/get-started/).
