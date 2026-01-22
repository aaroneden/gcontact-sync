# Docker Compose Verification Guide

This document provides comprehensive verification steps for the docker-compose.yml configuration for gcontact-sync.

## Overview

The docker-compose.yml file orchestrates the deployment of the gcontact-sync CLI application with:
- Proper volume mounts for persistent data
- Health check configuration
- Security best practices
- Environment variable support

## Prerequisites

Before testing, ensure you have:
- Docker Engine 20.10 or later installed
- Docker Compose v2 or later
- At least 512MB of available memory
- Write permissions in the project directory

## Verification Steps

### Step 1: Validate Configuration Syntax

```bash
# Verify docker-compose.yml syntax
docker compose config --quiet && echo 'COMPOSE_VALID'
```

Expected: `COMPOSE_VALID` (no errors)

### Step 2: Build the Image

```bash
# Build the Docker image
docker compose build
```

Expected: Build completes successfully with no errors

### Step 3: Start Container in Detached Mode

```bash
# Start the container
docker compose up -d
```

Expected:
- Container starts successfully
- No error messages
- Container name: `gcontact-sync`

### Step 4: Wait for Health Check

```bash
# Wait 5 seconds for health check to initialize
sleep 5

# Check container status
docker compose ps
```

Expected output should show:
- Container is running
- Status includes `healthy` or `Up` with health status
- No restart count

### Step 5: Verify Health Check Passes

```bash
# Check if container is healthy
docker compose ps | grep -q 'healthy' && echo 'HEALTH_OK'
```

Expected: `HEALTH_OK`

### Step 6: Inspect Container Logs

```bash
# View container logs
docker compose logs
```

Expected:
- No error messages
- Help output displayed (from default command: `--help`)
- Clean startup sequence

### Step 7: Verify Volume Mounts

```bash
# Check mounted volumes
docker compose exec gcontact-sync ls -la /app/config /app/data /app/credentials
```

Expected:
- All three directories exist
- Owned by gcontact user (UID 1000)
- Writable permissions

### Step 8: Test Health Command Inside Container

```bash
# Run health check command manually
docker compose exec gcontact-sync gcontact-sync health
```

Expected output: `healthy` (exit code 0)

### Step 9: Stop and Clean Up

```bash
# Stop and remove container
docker compose down
```

Expected:
- Container stops gracefully
- Network removed
- No errors

### Step 10: Complete Verification Command

Run all steps in one command:

```bash
docker compose up -d && \
sleep 5 && \
docker compose ps | grep -q 'healthy' && \
docker compose down && \
echo 'COMPOSE_OK'
```

Expected: `COMPOSE_OK`

## Configuration Verification Checklist

- [x] **docker-compose.yml exists** - File is present
- [x] **YAML syntax is valid** - Parses without errors
- [x] **Dockerfile exists** - Referenced in build context
- [x] **.env file exists** - Environment configuration present
- [x] **Volume directories exist** - config/, data/, credentials/ created
- [x] **Health check configured** - Uses `gcontact-sync health` command
- [x] **Restart policy set** - `unless-stopped` for auto-restart
- [x] **Security options** - Non-root user (1000:1000), no-new-privileges
- [x] **Resource limits available** - Commented out but ready to enable
- [x] **Labels present** - Metadata for container identification

## Expected Container Behavior

### On Startup
1. Container builds from Dockerfile
2. Runs as non-root user (gcontact:1000)
3. Mounts volumes for config, data, credentials
4. Executes default command (`--help`)
5. Health check runs every 30 seconds
6. Becomes "healthy" within 5 seconds

### Health Check Details
- **Command**: `gcontact-sync health`
- **Interval**: 30 seconds
- **Timeout**: 10 seconds
- **Start Period**: 5 seconds
- **Retries**: 3 attempts before marking unhealthy

### Volume Mounts
- `/app/config` ← `./config` (credentials, tokens, config files)
- `/app/data` ← `./data` (sync.db SQLite database)
- `/app/credentials` ← `./credentials` (additional credential storage)

### Environment Variables
From `.env` file:
- `GCONTACT_SYNC_CONFIG_DIR=/app/config`
- Optional: `GCONTACT_SYNC_LOG_LEVEL`, `GCONTACT_SYNC_DEBUG`

## Troubleshooting

### Container Fails to Start

**Check logs:**
```bash
docker compose logs gcontact-sync
```

**Common issues:**
- Missing .env file → Create from .env.docker
- Permission issues → Ensure directories are writable
- Port conflicts → Check if ports are already in use

### Health Check Failing

**Test health command manually:**
```bash
docker compose exec gcontact-sync gcontact-sync health
```

**If command fails:**
- Check if gcontact-sync is in PATH
- Verify virtual environment activation
- Review Dockerfile ENTRYPOINT and CMD

### Volume Mount Issues

**Verify mounts:**
```bash
docker compose exec gcontact-sync mount | grep /app
```

**Check permissions:**
```bash
docker compose exec gcontact-sync ls -la /app/config /app/data /app/credentials
```

**Fix permissions:**
```bash
# On host machine
chmod -R 755 config data credentials
chown -R 1000:1000 config data credentials
```

### Container Immediately Exits

**Check exit code:**
```bash
docker compose ps -a
```

**Review logs for errors:**
```bash
docker compose logs --tail=50
```

**Common causes:**
- Missing dependencies in Dockerfile
- Incorrect ENTRYPOINT or CMD
- Application crash on startup

## Production Deployment Checklist

Before deploying to production:

- [ ] Set proper resource limits (uncomment in docker-compose.yml)
- [ ] Configure log rotation
- [ ] Set up monitoring for health checks
- [ ] Enable read-only root filesystem if possible
- [ ] Review and restrict volume mount permissions
- [ ] Set environment variables in .env (not in docker-compose.yml)
- [ ] Test restart behavior (stop/start multiple times)
- [ ] Verify data persistence across restarts
- [ ] Document backup procedures for volumes
- [ ] Test recovery from container failure

## Manual Testing in Docker-Enabled Environment

When Docker is available, run these tests:

### Basic Test Suite
```bash
# 1. Clean environment
docker compose down -v
rm -rf config/* data/* credentials/*

# 2. Build fresh
docker compose build --no-cache

# 3. Start and verify
docker compose up -d
sleep 10
docker compose ps
docker compose logs

# 4. Test health
docker compose exec gcontact-sync gcontact-sync health

# 5. Test CLI commands
docker compose exec gcontact-sync gcontact-sync --help
docker compose exec gcontact-sync gcontact-sync --version

# 6. Clean up
docker compose down
```

### Integration Test
```bash
# Test complete workflow (requires credentials.json)
docker compose run --rm gcontact-sync auth account1
docker compose run --rm gcontact-sync auth account2
docker compose run --rm gcontact-sync sync --dry-run
docker compose run --rm gcontact-sync sync
```

## Verification Status

**Configuration Status**: ✅ All files present and valid
**Syntax Validation**: ✅ YAML parses correctly
**Docker Availability**: ❌ Docker not available in current environment
**Manual Testing Required**: Yes - in Docker-enabled environment

## Notes

- Docker commands are not available in the current development environment
- Configuration has been validated for syntax and structure
- All required files and directories are in place
- Manual testing with Docker is required to fully verify container behavior
- Configuration follows Docker and docker-compose best practices
- Health check implementation verified in CLI code and unit tests

## Next Steps

To complete verification in a Docker-enabled environment:

1. Install Docker Engine and Docker Compose
2. Run the verification command from Step 10 above
3. Verify all checks pass
4. Test with actual Google OAuth credentials
5. Confirm data persists across container restarts

---

*Generated as part of subtask-3-3 implementation*
*Last updated: 2026-01-22*
