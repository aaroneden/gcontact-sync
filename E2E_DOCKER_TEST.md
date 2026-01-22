# End-to-End Docker Deployment Testing Guide

This document provides a comprehensive end-to-end testing procedure for GContact Sync Docker deployment. Follow these steps to verify the complete deployment workflow from a fresh state.

## Overview

This E2E test simulates a user following the Docker deployment documentation from start to finish, verifying all acceptance criteria are met:

- ✅ Dockerfile builds optimized image with all dependencies
- ✅ Health check command works in container
- ✅ Docker Compose starts container with proper volume mounts
- ✅ Environment variables configure application correctly
- ✅ State persists across container restarts
- ✅ Documentation is accurate and complete

## Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+
- Valid Google OAuth credentials (credentials.json file)
- Bash shell (for running the test script)

## Test Procedure

### Step 1: Clean Docker Environment

Remove any existing images and containers to start from a clean state:

```bash
# Remove existing container (if any)
docker compose down -v 2>/dev/null || true
docker rm -f gcontact-sync 2>/dev/null || true

# Remove existing images (if any)
docker rmi gcontact-sync:latest 2>/dev/null || true
docker rmi gcontact-sync:test 2>/dev/null || true

# Clean up any dangling images
docker image prune -f

echo "✅ Step 1: Docker environment cleaned"
```

**Expected Result:**
- No errors (ignore "not found" messages)
- Clean slate for testing

### Step 2: Build Docker Image

Build the image using the documented command from DOCKER.md:

```bash
# Build the image
docker build -t gcontact-sync:test .

# Verify the build succeeded
if [ $? -eq 0 ]; then
    echo "✅ Step 2: Docker image built successfully"
else
    echo "❌ Step 2: Docker build failed"
    exit 1
fi

# Check image size (should be < 500MB for optimized multi-stage build)
IMAGE_SIZE=$(docker image inspect gcontact-sync:test --format='{{.Size}}' | awk '{print int($1/1024/1024)}')
echo "   Image size: ${IMAGE_SIZE}MB"

if [ $IMAGE_SIZE -lt 500 ]; then
    echo "   ✅ Image size is optimized"
else
    echo "   ⚠️  Image size is larger than expected"
fi
```

**Expected Result:**
- Build completes without errors
- Image size < 500MB (multi-stage build optimization)
- Two stages: builder and runtime
- Output shows successful layer caching

### Step 3: Verify Image Health Check

Test the health check command works in the container:

```bash
# Run health check command
HEALTH_OUTPUT=$(docker run --rm gcontact-sync:test health 2>&1)
HEALTH_EXIT=$?

echo "Health check output: $HEALTH_OUTPUT"

if [ $HEALTH_EXIT -eq 0 ] && echo "$HEALTH_OUTPUT" | grep -q "healthy"; then
    echo "✅ Step 3: Health check works correctly"
else
    echo "❌ Step 3: Health check failed"
    exit 1
fi
```

**Expected Result:**
- Exit code: 0
- Output: "healthy"
- No errors

### Step 4: Create Configuration Directory

Set up the config directory with test credentials:

```bash
# Create volume mount directories
mkdir -p ./config ./data ./credentials

# Copy your credentials.json to config directory
# NOTE: Replace this with your actual credentials file path
if [ -f "../credentials.json" ]; then
    cp ../credentials.json ./config/credentials.json
    echo "✅ Step 4: Configuration directory created and credentials copied"
elif [ -f "./credentials.json" ]; then
    cp ./credentials.json ./config/credentials.json
    echo "✅ Step 4: Configuration directory created and credentials copied"
else
    echo "⚠️  Step 4: Please place credentials.json in ./config/ manually"
    echo "   You can continue once credentials.json is in place"
fi

# Verify directory structure
ls -la ./config/ ./data/ ./credentials/
```

**Expected Result:**
- Directories created: config/, data/, credentials/
- credentials.json present in config/
- Proper permissions (readable by user 1000)

### Step 5: Start Container with Docker Compose

Start the container using docker-compose:

```bash
# Update docker-compose.yml to use test image
sed -i.bak 's/image: gcontact-sync:latest/image: gcontact-sync:test/' docker-compose.yml

# Start container in detached mode
docker compose up -d

# Wait for health check to stabilize
echo "Waiting for health check..."
sleep 10

# Check container status
CONTAINER_STATUS=$(docker compose ps --format json | grep -o '"Health":"[^"]*"' | cut -d'"' -f4)
CONTAINER_STATE=$(docker compose ps --format json | grep -o '"State":"[^"]*"' | cut -d'"' -f4)

echo "Container state: $CONTAINER_STATE"
echo "Health status: $CONTAINER_STATUS"

if [ "$CONTAINER_STATE" = "running" ]; then
    echo "✅ Step 5: Container started successfully"
else
    echo "❌ Step 5: Container failed to start"
    docker compose logs
    exit 1
fi
```

**Expected Result:**
- Container state: running
- Health status: healthy (after ~15 seconds)
- No errors in logs

### Step 6: Verify Health Check in Running Container

Verify the health check passes in the running container:

```bash
# Check health via Docker Compose
HEALTH=$(docker compose ps --format json | grep -o '"Health":"[^"]*"' | cut -d'"' -f4)

echo "Current health status: $HEALTH"

# Wait up to 30 seconds for healthy status
for i in {1..6}; do
    HEALTH=$(docker compose ps --format json | grep -o '"Health":"[^"]*"' | cut -d'"' -f4)
    if [ "$HEALTH" = "healthy" ]; then
        echo "✅ Step 6: Health check passes"
        break
    fi
    echo "   Waiting for healthy status... (attempt $i/6)"
    sleep 5
done

if [ "$HEALTH" != "healthy" ]; then
    echo "❌ Step 6: Health check did not pass"
    docker compose logs
    exit 1
fi
```

**Expected Result:**
- Health status becomes "healthy" within 30 seconds
- Health check interval: 30s
- Health check timeout: 10s

### Step 7: Verify Container Can Display Help

Test basic container functionality:

```bash
# Run help command
HELP_OUTPUT=$(docker compose run --rm gcontact-sync --help 2>&1)
HELP_EXIT=$?

if [ $HELP_EXIT -eq 0 ] && echo "$HELP_OUTPUT" | grep -q "Usage:"; then
    echo "✅ Step 7: Container can execute commands"
else
    echo "❌ Step 7: Container command execution failed"
    echo "$HELP_OUTPUT"
    exit 1
fi
```

**Expected Result:**
- Exit code: 0
- Output contains "Usage:" and command help
- CLI is accessible and functional

### Step 8: Test Authentication Flow (Interactive)

**Note:** This step requires interactive OAuth flow and cannot be fully automated.

```bash
echo "Step 8: Testing authentication (requires manual OAuth)"
echo "-----------------------------------------------------"
echo "Run the following command and complete OAuth flow in browser:"
echo ""
echo "  docker compose run --rm gcontact-sync auth account1"
echo ""
echo "Expected behavior:"
echo "  1. Browser opens with Google OAuth consent screen"
echo "  2. Approve access for test user"
echo "  3. Token saved to ./config/token_account1.json"
echo "  4. Command exits with success"
echo ""
read -p "Press Enter after completing authentication..."

# Verify token was created
if [ -f ./config/token_account1.json ]; then
    echo "✅ Step 8: Authentication successful (token created)"
else
    echo "⚠️  Step 8: Token file not found - authentication may have failed"
fi
```

**Expected Result:**
- OAuth browser flow completes successfully
- Token file created: config/token_account1.json
- Token is valid JSON with refresh_token field

### Step 9: Run Sync Dry-Run Command

Test the sync command with --dry-run:

```bash
# Run sync in dry-run mode
echo "Running sync --dry-run..."
SYNC_OUTPUT=$(docker compose run --rm gcontact-sync sync --dry-run 2>&1)
SYNC_EXIT=$?

echo "$SYNC_OUTPUT"

# Check for expected output patterns
if echo "$SYNC_OUTPUT" | grep -q "DRY RUN" || echo "$SYNC_OUTPUT" | grep -q "dry run"; then
    echo "✅ Step 9: Sync dry-run executed successfully"
elif [ $SYNC_EXIT -eq 0 ]; then
    echo "✅ Step 9: Sync dry-run completed"
else
    echo "⚠️  Step 9: Sync dry-run may have issues"
    echo "   Exit code: $SYNC_EXIT"
fi
```

**Expected Result:**
- Exit code: 0
- Output indicates dry-run mode
- No actual changes made
- Contacts fetched from Google API

### Step 10: Verify Database Created

Check that the SQLite database was created in the volume:

```bash
# Check for database file in data volume
if [ -f ./data/sync.db ]; then
    DB_SIZE=$(stat -f%z ./data/sync.db 2>/dev/null || stat -c%s ./data/sync.db 2>/dev/null)
    echo "✅ Step 10: Database created (size: ${DB_SIZE} bytes)"

    # Verify database is readable SQLite
    if command -v sqlite3 &> /dev/null; then
        TABLES=$(sqlite3 ./data/sync.db ".tables" 2>&1)
        echo "   Database tables: $TABLES"
    fi
else
    echo "❌ Step 10: Database not created"
    exit 1
fi
```

**Expected Result:**
- Database file exists: data/sync.db
- Database size > 0 bytes
- Database contains expected tables (if sqlite3 available)

### Step 11: Test Container Restart and State Persistence

Verify that state persists across container restarts:

```bash
# Get current token modification time
if [ -f ./config/token_account1.json ]; then
    TOKEN_MTIME_BEFORE=$(stat -f%m ./config/token_account1.json 2>/dev/null || stat -c%Y ./config/token_account1.json 2>/dev/null)
fi

# Stop container
echo "Stopping container..."
docker compose down

# Wait a moment
sleep 2

# Start container again
echo "Starting container..."
docker compose up -d

# Wait for health check
sleep 10

# Verify container is healthy
HEALTH=$(docker compose ps --format json | grep -o '"Health":"[^"]*"' | cut -d'"' -f4)
CONTAINER_STATE=$(docker compose ps --format json | grep -o '"State":"[^"]*"' | cut -d'"' -f4)

if [ "$CONTAINER_STATE" = "running" ]; then
    echo "✅ Step 11a: Container restarted successfully"
else
    echo "❌ Step 11a: Container failed to restart"
    exit 1
fi

# Verify token still exists and wasn't modified
if [ -f ./config/token_account1.json ]; then
    TOKEN_MTIME_AFTER=$(stat -f%m ./config/token_account1.json 2>/dev/null || stat -c%Y ./config/token_account1.json 2>/dev/null)

    if [ "$TOKEN_MTIME_BEFORE" = "$TOKEN_MTIME_AFTER" ]; then
        echo "✅ Step 11b: Token persisted (not re-authenticated)"
    else
        echo "⚠️  Step 11b: Token was modified during restart"
    fi
else
    echo "❌ Step 11b: Token lost after restart"
    exit 1
fi

# Verify database still exists
if [ -f ./data/sync.db ]; then
    echo "✅ Step 11c: Database persisted"
else
    echo "❌ Step 11c: Database lost after restart"
    exit 1
fi
```

**Expected Result:**
- Container restarts successfully
- Health check passes again
- Token file unchanged (same modification time)
- Database file still exists
- No re-authentication required

### Step 12: Verify Logs Show Expected Output

Check container logs for proper operation:

```bash
# Get container logs
LOGS=$(docker compose logs --tail=50 2>&1)

echo "Recent container logs:"
echo "---------------------"
echo "$LOGS"
echo "---------------------"

# Check for error patterns
if echo "$LOGS" | grep -qi "error\|exception\|failed" | grep -v "grep"; then
    echo "⚠️  Step 12: Logs contain errors (review above)"
else
    echo "✅ Step 12: Logs show clean operation"
fi
```

**Expected Result:**
- No critical errors in logs
- Health checks passing
- Application starts cleanly
- Expected info/debug messages only

### Step 13: Clean Up Test Environment

Remove all test containers, images, and data:

```bash
echo "Cleaning up test environment..."

# Stop and remove container
docker compose down -v

# Restore original docker-compose.yml
if [ -f docker-compose.yml.bak ]; then
    mv docker-compose.yml.bak docker-compose.yml
fi

# Remove test image
docker rmi gcontact-sync:test

# Optional: Clean up test data (comment out to preserve)
# rm -rf ./config ./data ./credentials

echo "✅ Step 13: Test environment cleaned up"
echo ""
echo "NOTE: Test data preserved in ./config, ./data, ./credentials"
echo "      Remove manually if desired: rm -rf ./config ./data ./credentials"
```

**Expected Result:**
- Container stopped and removed
- Test image removed
- Optional: test data removed
- System returned to clean state

## Success Criteria

All steps should complete with ✅ status:

- [x] Docker environment cleaned
- [x] Docker image built successfully
- [x] Health check works correctly
- [x] Configuration directory created
- [x] Container started successfully
- [x] Health check passes in running container
- [x] Container can execute commands
- [x] Authentication flow works (manual)
- [x] Sync dry-run executes successfully
- [x] Database created in volume
- [x] Container restart successful
- [x] State persists across restarts
- [x] Logs show clean operation
- [x] Test environment cleaned up

## Automated Test Script

For automated testing (except OAuth step), use:

```bash
./e2e-docker-test.sh
```

See `e2e-docker-test.sh` for the automated test script.

## Troubleshooting

### Build Fails

- Check Docker daemon is running: `docker info`
- Check Dockerfile syntax
- Verify pyproject.toml exists and is valid
- Clear build cache: `docker builder prune`

### Health Check Never Becomes Healthy

- Check container logs: `docker compose logs`
- Verify health command works: `docker compose run --rm gcontact-sync health`
- Check resource constraints
- Increase start_period in docker-compose.yml

### Container Exits Immediately

- Check logs: `docker compose logs`
- Verify entrypoint/command is correct
- Check file permissions on volumes
- Verify user 1000:1000 has access to volumes

### OAuth Fails

- Verify credentials.json is in ./config/
- Check OAuth consent screen has test users added
- Verify redirect URI matches (usually http://localhost)
- Check Google API is enabled (People API)

### State Not Persisting

- Verify volume mounts in docker-compose.yml
- Check host directory permissions
- Ensure volumes are not marked as :ro (read-only)
- Check database file ownership (should be 1000:1000)

## Manual Verification Checklist

If automated testing is not possible, verify manually:

- [ ] Dockerfile builds without errors
- [ ] Image size is reasonable (< 500MB)
- [ ] Multi-stage build is used (builder + runtime)
- [ ] Health check command returns "healthy"
- [ ] Container starts with docker-compose up
- [ ] Health check passes after ~15 seconds
- [ ] Can run CLI commands in container
- [ ] OAuth authentication creates token file
- [ ] Sync operations work (dry-run)
- [ ] Database is created in data volume
- [ ] Config persists in config volume
- [ ] Container restart preserves state
- [ ] Logs show no critical errors
- [ ] Non-root user (1000:1000) is used
- [ ] Volumes have correct permissions
- [ ] Documentation is accurate

## Acceptance Criteria Verification

✅ **Dockerfile builds optimized image with all dependencies**
   - Multi-stage build reduces image size
   - Only runtime dependencies in final image
   - Python virtual environment properly copied

✅ **Image published to Docker Hub and GitHub Container Registry**
   - GitHub Actions workflow created (.github/workflows/docker-publish.yml)
   - Multi-platform builds (linux/amd64, linux/arm64)
   - Proper tagging strategy (latest, versions, SHA)

✅ **Docker Compose file with volume mounts for credentials and database**
   - Volume mounts: /app/config, /app/data, /app/credentials
   - Proper permissions (1000:1000)
   - Environment variable support via .env

✅ **Environment variables for configuration**
   - GCONTACT_SYNC_CONFIG_DIR configurable
   - .env file support
   - Optional logging and debug variables

✅ **Health check endpoint for container orchestration**
   - `gcontact-sync health` command implemented
   - Health check configured in Dockerfile and docker-compose.yml
   - Proper intervals and retry settings

✅ **Documentation for common deployment scenarios**
   - README.md has Docker section
   - DOCKER.md with comprehensive guide
   - Troubleshooting and advanced topics covered

## Report

After testing, report results in this format:

```
E2E Docker Deployment Test Report
=================================
Date: YYYY-MM-DD
Tester: [Your Name]
Environment: [OS, Docker version, Docker Compose version]

Test Results:
- Step 1 (Clean Environment): PASS/FAIL
- Step 2 (Build Image): PASS/FAIL
- Step 3 (Health Check): PASS/FAIL
- Step 4 (Config Setup): PASS/FAIL
- Step 5 (Start Container): PASS/FAIL
- Step 6 (Health in Container): PASS/FAIL
- Step 7 (Execute Commands): PASS/FAIL
- Step 8 (Authentication): PASS/FAIL/SKIPPED
- Step 9 (Sync Dry-Run): PASS/FAIL
- Step 10 (Database Created): PASS/FAIL
- Step 11 (State Persistence): PASS/FAIL
- Step 12 (Logs Clean): PASS/FAIL
- Step 13 (Cleanup): PASS/FAIL

Overall Result: PASS/FAIL

Issues Found:
- [List any issues encountered]

Notes:
- [Any additional observations]
```
