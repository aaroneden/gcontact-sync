# Installing GContact Sync on Synology NAS

This guide covers deploying GContact Sync on Synology NAS devices using Container Manager (Docker). Synology NAS provides an excellent platform for running scheduled contact synchronization in a home or office environment.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Installation Methods](#installation-methods)
  - [Method 1: Container Manager GUI (Recommended)](#method-1-container-manager-gui-recommended)
  - [Method 2: Portainer](#method-2-portainer)
  - [Method 3: SSH Command Line](#method-3-ssh-command-line)
- [Authentication Setup](#authentication-setup)
- [Running Sync Operations](#running-sync-operations)
- [Scheduled Execution](#scheduled-execution)
- [Monitoring and Logs](#monitoring-and-logs)
- [Troubleshooting](#troubleshooting)
- [Advanced Configuration](#advanced-configuration)

## Prerequisites

### Compatible Synology Models

**Container Manager requires an x86-based Synology NAS.** ARM-based models are not compatible.

**Compatible models include:**
- Plus series: DS224+, DS423+, DS723+, DS920+, DS1520+, DS1621+, DS1821+, etc.
- XS/XS+ series: DS1621xs+, DS3622xs+, etc.
- Enterprise series: RS1221+, RS2421+, etc.

**Note:** Avoid the "j" series (e.g., DS220j) and value models without "+" suffix as they typically use ARM processors.

To check your NAS compatibility:
1. Go to **Control Panel** > **Info Center**
2. Look for CPU information - it should be Intel or AMD (x86_64)

### Software Requirements

- **DSM 7.2 or later** (recommended) - Container Manager
- **DSM 6.0 - 7.1** - Docker package (similar steps, slightly different UI)
- **At least 1GB RAM available** for Docker operations
- **Storage space**: ~300MB for the container image + space for sync data

### Google Cloud Prerequisites

Before installing, you need:
1. A Google Cloud Project with People API enabled
2. OAuth 2.0 credentials (Desktop application type)
3. Downloaded `credentials.json` file

See the [main DOCKER.md](DOCKER.md#google-cloud-prerequisites) guide for detailed Google Cloud setup instructions.

## Quick Start

For experienced users:

```bash
# SSH into your Synology NAS
ssh admin@your-nas-ip

# Create directory structure
sudo mkdir -p /volume1/docker/gcontact-sync/{config,data,credentials}
sudo chown -R 1000:1000 /volume1/docker/gcontact-sync

# Create docker-compose.yml
cat > /volume1/docker/gcontact-sync/docker-compose.yml << 'EOF'
services:
  gcontact-sync:
    image: aeden2019/gcontact-sync:latest
    container_name: gcontact-sync
    restart: unless-stopped
    volumes:
      - /volume1/docker/gcontact-sync/config:/app/config:rw
      - /volume1/docker/gcontact-sync/data:/app/data:rw
      - /volume1/docker/gcontact-sync/credentials:/app/credentials:rw
    environment:
      - GCONTACT_SYNC_CONFIG_DIR=/app/config
      - SYNC_INTERVAL=24h
    user: "1000:1000"
    command: ["daemon", "start", "--foreground", "--interval", "24h"]
EOF

# Upload credentials.json to config folder via File Station
# Then authenticate (see Authentication Setup section)
```

## Installation Methods

Choose the installation method that best fits your comfort level and needs:

| Method | Best For | Difficulty |
|--------|----------|------------|
| Container Manager GUI | Most users, DSM 7.2+ | Easy |
| Portainer | Users who manage multiple containers | Medium |
| SSH Command Line | Advanced users, automation | Advanced |

All methods require the same prerequisites and produce identical results.

---

### Method 1: Container Manager GUI (Recommended)

This is the native Synology approach using the built-in Container Manager application.

#### Step 1.1: Install Container Manager

1. Open **Package Center** on your Synology DSM
2. Search for **"Container Manager"** (DSM 7.2+) or **"Docker"** (older DSM versions)
3. Click **Install**
4. Wait for installation to complete
5. Open **Container Manager** from the main menu

#### Step 1.2: Create Directory Structure

**Using File Station (GUI):**

1. Open **File Station**
2. Navigate to a shared folder (e.g., `docker` or create one)
3. Create folder structure:
   ```
   /docker/gcontact-sync/
   ├── config/
   ├── data/
   └── credentials/
   ```
4. Right-click `gcontact-sync` folder → **Properties** → **Permission**
5. Ensure the folder has read/write permissions

**Alternatively, using SSH:**

Enable SSH in **Control Panel** > **Terminal & SNMP** > **Enable SSH service**

```bash
# Connect via SSH
ssh your-username@your-nas-ip

# Create directories (adjust volume1 if using a different volume)
sudo mkdir -p /volume1/docker/gcontact-sync/{config,data,credentials}

# Set ownership to UID 1000 (container user)
sudo chown -R 1000:1000 /volume1/docker/gcontact-sync

# Verify
ls -la /volume1/docker/gcontact-sync
```

#### Step 1.3: Upload Configuration Files

**Upload credentials.json:**

1. Open **File Station**
2. Navigate to `/docker/gcontact-sync/config/`
3. Click **Upload** → **Upload - Overwrite**
4. Select your `credentials.json` file from Google Cloud Console
5. Verify the file appears as `credentials.json`

**Create .env file (Optional):**

Create a file named `.env` in `/docker/gcontact-sync/` with:

```bash
# Sync interval (default: 24h)
SYNC_INTERVAL=24h

# Logging level (DEBUG, INFO, WARNING, ERROR)
GCONTACT_SYNC_LOG_LEVEL=INFO
```

#### Step 1.4: Create Project in Container Manager

1. Open **Container Manager**
2. Go to **Project** tab
3. Click **Create**
4. Configure the project:
   - **Project name**: `gcontact-sync`
   - **Path**: `/volume1/docker/gcontact-sync`
   - **Source**: Select "Create docker-compose.yml"

#### Step 1.5: Enter Docker Compose Configuration

Paste the following `docker-compose.yml` content:

```yaml
services:
  gcontact-sync:
    image: aeden2019/gcontact-sync:latest
    container_name: gcontact-sync
    restart: unless-stopped

    volumes:
      # Configuration - stores credentials and tokens
      - /volume1/docker/gcontact-sync/config:/app/config:rw
      # Data - stores SQLite database
      - /volume1/docker/gcontact-sync/data:/app/data:rw
      # Additional credentials storage
      - /volume1/docker/gcontact-sync/credentials:/app/credentials:rw

    environment:
      - GCONTACT_SYNC_CONFIG_DIR=/app/config
      - SYNC_INTERVAL=24h
      - GCONTACT_SYNC_LOG_LEVEL=INFO

    # Run as non-root user
    user: "1000:1000"

    # Health check
    healthcheck:
      test: ["CMD", "gcontact-sync", "health"]
      interval: 60s
      timeout: 10s
      start_period: 10s
      retries: 3

    # Run daemon mode for continuous sync
    command: ["daemon", "start", "--foreground", "--interval", "24h"]
```

**Important notes for Synology:**
- Use absolute paths starting with `/volume1/` (or your volume number)
- The `restart: unless-stopped` ensures the container starts after NAS reboot
- Adjust `SYNC_INTERVAL` as needed (e.g., `6h`, `12h`, `24h`)

#### Step 1.6: Build and Start

1. Click **Next** to review settings
2. Click **Done** to create the project
3. The container will be pulled and started automatically

You can now proceed to [Authentication Setup](#authentication-setup).

---

### Method 2: Portainer

Portainer provides a powerful web-based Docker management interface. This is ideal if you manage multiple Docker containers or prefer a more visual approach than Container Manager.

#### Step 2.1: Install Portainer on Synology

If you don't already have Portainer installed:

**Option A: Install via Container Manager**

1. Open **Container Manager**
2. Go to **Registry** tab
3. Search for `portainer/portainer-ce`
4. Download the `latest` tag
5. Go to **Image** tab and select the downloaded image
6. Click **Run** and configure:
   - **Container name**: `portainer`
   - **Port Settings**: Map local port `9000` to container port `9000` (HTTP), optionally `9443` to `9443` (HTTPS)
   - **Volume Settings**:
     - `/var/run/docker.sock` → `/var/run/docker.sock` (read-only is fine)
     - `/volume1/docker/portainer` → `/data`
   - **Restart Policy**: `unless-stopped`
7. Click **Next** and **Done**

**Option B: Install via SSH**

```bash
# SSH into your NAS
ssh your-username@your-nas-ip

# Create data directory
sudo mkdir -p /volume1/docker/portainer

# Run Portainer
sudo docker run -d \
  --name=portainer \
  --restart=unless-stopped \
  -p 9000:9000 \
  -p 9443:9443 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /volume1/docker/portainer:/data \
  portainer/portainer-ce:latest
```

**Option C: Install via Task Scheduler (30-second install)**

1. Open **Control Panel** > **Task Scheduler**
2. Click **Create** > **Scheduled Task** > **User-defined script**
3. **General** tab:
   - Task name: `Install Portainer`
   - User: `root`
   - Uncheck "Enabled" (run once only)
4. **Schedule** tab: Set to any date
5. **Task Settings** > **Run command**:
   ```bash
   docker run -d --name=portainer \
     --restart=unless-stopped \
     -p 9000:9000 -p 9443:9443 \
     -v /var/run/docker.sock:/var/run/docker.sock \
     -v /volume1/docker/portainer:/data \
     portainer/portainer-ce:latest
   ```
6. Click **OK**, then right-click the task and select **Run**

#### Step 2.2: Access Portainer

1. Open your browser and navigate to:
   - HTTP: `http://your-nas-ip:9000`
   - HTTPS: `https://your-nas-ip:9443`
2. On first access, create an admin account
3. Select **"Get Started"** to connect to the local Docker environment

#### Step 2.3: Create Directory Structure

Before deploying, create the required directories. You can do this via SSH or File Station:

```bash
# Via SSH
sudo mkdir -p /volume1/docker/gcontact-sync/{config,data,credentials}
sudo chown -R 1000:1000 /volume1/docker/gcontact-sync
```

Upload your `credentials.json` to `/volume1/docker/gcontact-sync/config/` via File Station.

#### Step 2.4: Deploy GContact Sync Stack

1. In Portainer, go to **Stacks** in the left sidebar
2. Click **+ Add stack**
3. Configure:
   - **Name**: `gcontact-sync`
   - **Build method**: Select **Web editor**
4. Paste the following docker-compose content:

```yaml
services:
  gcontact-sync:
    image: aeden2019/gcontact-sync:latest
    container_name: gcontact-sync
    restart: unless-stopped

    volumes:
      - /volume1/docker/gcontact-sync/config:/app/config:rw
      - /volume1/docker/gcontact-sync/data:/app/data:rw
      - /volume1/docker/gcontact-sync/credentials:/app/credentials:rw

    environment:
      - GCONTACT_SYNC_CONFIG_DIR=/app/config
      - SYNC_INTERVAL=24h
      - GCONTACT_SYNC_LOG_LEVEL=INFO

    user: "1000:1000"

    healthcheck:
      test: ["CMD", "gcontact-sync", "health"]
      interval: 60s
      timeout: 10s
      start_period: 10s
      retries: 3

    command: ["daemon", "start", "--foreground", "--interval", "24h"]
```

5. Scroll down and click **Deploy the stack**

#### Step 2.5: Manage via Portainer

Once deployed, you can use Portainer to:

- **View logs**: Click on the container → **Logs**
- **Execute commands**: Click on the container → **Console** → **Connect**
- **Restart/Stop**: Use the container action buttons
- **Update image**: **Recreate** with "Pull latest image" checked

**Running sync commands via Portainer Console:**

1. Go to **Containers** → click `gcontact-sync`
2. Click **Console** tab
3. Select `/bin/bash` and click **Connect**
4. Run commands like:
   ```bash
   gcontact-sync status
   gcontact-sync sync --dry-run
   ```

You can now proceed to [Authentication Setup](#authentication-setup).

---

### Method 3: SSH Command Line

For advanced users who prefer command-line deployment or need to automate the setup.

#### Step 3.1: Enable SSH Access

1. Go to **Control Panel** > **Terminal & SNMP**
2. Check **Enable SSH service**
3. Set a port (default: 22)
4. Click **Apply**

#### Step 3.2: Connect and Create Directories

```bash
# SSH into your NAS
ssh your-username@your-nas-ip

# Create directory structure
sudo mkdir -p /volume1/docker/gcontact-sync/{config,data,credentials}

# Set ownership for container user
sudo chown -R 1000:1000 /volume1/docker/gcontact-sync

# Navigate to project directory
cd /volume1/docker/gcontact-sync
```

#### Step 3.3: Upload Credentials

Upload `credentials.json` via SCP:

```bash
# From your local machine (not the NAS)
scp /path/to/credentials.json your-username@your-nas-ip:/volume1/docker/gcontact-sync/config/
```

Or use File Station to upload the file.

#### Step 3.4: Create Docker Compose File

```bash
# On the NAS via SSH
cd /volume1/docker/gcontact-sync

# Create docker-compose.yml
cat > docker-compose.yml << 'EOF'
services:
  gcontact-sync:
    image: aeden2019/gcontact-sync:latest
    container_name: gcontact-sync
    restart: unless-stopped
    volumes:
      - /volume1/docker/gcontact-sync/config:/app/config:rw
      - /volume1/docker/gcontact-sync/data:/app/data:rw
      - /volume1/docker/gcontact-sync/credentials:/app/credentials:rw
    environment:
      - GCONTACT_SYNC_CONFIG_DIR=/app/config
      - SYNC_INTERVAL=24h
      - GCONTACT_SYNC_LOG_LEVEL=INFO
    user: "1000:1000"
    healthcheck:
      test: ["CMD", "gcontact-sync", "health"]
      interval: 60s
      timeout: 10s
      start_period: 10s
      retries: 3
    command: ["daemon", "start", "--foreground", "--interval", "24h"]
EOF
```

#### Step 3.5: Deploy the Container

```bash
# Pull the image
sudo docker pull aeden2019/gcontact-sync:latest

# Start the container in detached mode
sudo docker compose up -d

# Check status
sudo docker compose ps

# View logs
sudo docker compose logs -f
```

You can now proceed to [Authentication Setup](#authentication-setup).

## Authentication Setup

Before the sync daemon can run, you must authenticate both Google accounts. This requires a one-time browser-based OAuth flow.

### Method 1: Authenticate on Local Machine, Transfer Tokens

**Recommended for headless NAS setups:**

1. On your local computer with a browser, clone the repository or use Docker:
   ```bash
   # Using Docker on local machine
   docker pull aeden2019/gcontact-sync:latest
   mkdir -p ~/gcontact-temp/config
   cp /path/to/credentials.json ~/gcontact-temp/config/

   # Authenticate account 1
   docker run --rm -it \
     -v ~/gcontact-temp/config:/app/config \
     aeden2019/gcontact-sync:latest \
     auth --account account1

   # Authenticate account 2
   docker run --rm -it \
     -v ~/gcontact-temp/config:/app/config \
     aeden2019/gcontact-sync:latest \
     auth --account account2
   ```

2. Copy token files to your Synology NAS:
   ```bash
   # Using scp
   scp ~/gcontact-temp/config/token_*.json \
     your-username@your-nas-ip:/volume1/docker/gcontact-sync/config/
   ```

   Or use **File Station** to upload `token_account1.json` and `token_account2.json` to the config folder.

### Method 2: SSH with X11 Forwarding

If your NAS and network support it:

```bash
# Connect with X11 forwarding
ssh -X your-username@your-nas-ip

# Run auth command
cd /volume1/docker/gcontact-sync
sudo docker compose run --rm gcontact-sync auth --account account1
sudo docker compose run --rm gcontact-sync auth --account account2
```

### Method 3: Manual URL Copy

1. Run the auth command via SSH:
   ```bash
   sudo docker compose run --rm gcontact-sync auth --account account1
   ```

2. Copy the authorization URL that appears in the terminal

3. Open the URL in a browser on any device

4. Complete the Google sign-in and authorization

5. Copy the authorization code back to the terminal

### Verify Authentication

After authenticating both accounts, verify the setup:

```bash
# Check status
sudo docker compose run --rm gcontact-sync status

# Expected output:
# ✓ Account 1: Authenticated (email1@gmail.com)
# ✓ Account 2: Authenticated (email2@gmail.com)
# ✓ Database: Initialized
# Ready to sync
```

## Running Sync Operations

### One-Time Sync Commands

Run these via SSH or Container Manager's terminal:

```bash
cd /volume1/docker/gcontact-sync

# Preview changes (dry run)
sudo docker compose run --rm gcontact-sync sync --dry-run

# Execute sync
sudo docker compose run --rm gcontact-sync sync

# Full sync (ignore sync tokens)
sudo docker compose run --rm gcontact-sync sync --full

# Verbose output
sudo docker compose run --rm gcontact-sync sync --verbose
```

### Daemon Mode (Continuous)

The default docker-compose.yml runs in daemon mode, syncing at the specified interval:

```bash
# Start daemon (runs in background)
sudo docker compose up -d

# View logs
sudo docker compose logs -f

# Stop daemon
sudo docker compose down
```

## Scheduled Execution

### Option 1: Docker Restart Policy (Recommended)

The `restart: unless-stopped` policy in docker-compose.yml ensures:
- Container starts automatically after NAS reboot
- Container restarts if it crashes
- Daemon mode handles the sync schedule internally

This is the **recommended approach** for Synology.

### Option 2: Task Scheduler (One-Shot Syncs)

Use Synology's Task Scheduler for alternative scheduling:

1. Open **Control Panel** > **Task Scheduler**
2. Click **Create** > **Scheduled Task** > **User-defined script**
3. Configure:
   - **Task**: GContact Sync
   - **User**: root
   - **Schedule**: Set your preferred schedule
   - **Task Settings** > **Run command**:
     ```bash
     /usr/local/bin/docker compose -f /volume1/docker/gcontact-sync/docker-compose.yml run --rm gcontact-sync sync
     ```

4. Enable "Send run details by email" for notifications

**Note:** If using Task Scheduler, modify docker-compose.yml to remove the daemon command:

```yaml
# For Task Scheduler approach, use this command instead:
command: ["--help"]  # Container exits immediately, Task Scheduler runs sync
```

### Option 3: Cron via SSH

Edit crontab directly:

```bash
# SSH into NAS
ssh your-username@your-nas-ip

# Edit crontab (as root)
sudo crontab -e

# Add sync schedule (example: every 6 hours)
0 */6 * * * /usr/local/bin/docker compose -f /volume1/docker/gcontact-sync/docker-compose.yml run --rm gcontact-sync sync >> /volume1/docker/gcontact-sync/logs/sync.log 2>&1
```

## Monitoring and Logs

### View Container Status

**Via Container Manager GUI:**
1. Open **Container Manager**
2. Go to **Container** tab
3. Find `gcontact-sync` container
4. View status: Running, Health, Uptime

**Via SSH:**
```bash
# Container status
sudo docker compose -f /volume1/docker/gcontact-sync/docker-compose.yml ps

# Resource usage
sudo docker stats gcontact-sync --no-stream
```

### View Logs

**Via Container Manager GUI:**
1. Click on the `gcontact-sync` container
2. Go to **Log** tab
3. View real-time logs

**Via SSH:**
```bash
cd /volume1/docker/gcontact-sync

# View all logs
sudo docker compose logs

# Follow logs in real-time
sudo docker compose logs -f

# View last 100 lines
sudo docker compose logs --tail=100
```

### Health Check Status

```bash
# Check health manually
sudo docker compose run --rm gcontact-sync health

# View Docker health status
sudo docker inspect gcontact-sync --format='{{.State.Health.Status}}'
```

## Troubleshooting

### Container Won't Start

**Check logs for errors:**
```bash
sudo docker compose logs gcontact-sync
```

**Common issues:**

1. **Permission denied errors:**
   ```bash
   # Fix ownership
   sudo chown -R 1000:1000 /volume1/docker/gcontact-sync
   ```

2. **Volume path incorrect:**
   - Ensure paths use `/volume1/` (or correct volume number)
   - Verify directories exist

3. **Image not found:**
   ```bash
   # Pull image manually
   sudo docker pull aeden2019/gcontact-sync:latest
   ```

### Authentication Errors

**Token expired:**
```bash
# Remove old tokens
rm /volume1/docker/gcontact-sync/config/token_*.json

# Re-authenticate (see Authentication Setup section)
```

**Invalid credentials:**
- Verify `credentials.json` is in the config folder
- Check the file is valid JSON and contains OAuth credentials

### Container Marked Unhealthy

```bash
# Check health output
sudo docker compose run --rm gcontact-sync health

# Common fixes:
# 1. Re-authenticate accounts
# 2. Check credentials.json exists
# 3. Verify network connectivity
```

### Database Locked

```bash
# Stop all containers
sudo docker compose down

# Remove lock files
rm -f /volume1/docker/gcontact-sync/data/*.db-journal
rm -f /volume1/docker/gcontact-sync/data/*.db-wal

# Restart
sudo docker compose up -d
```

### Network Connectivity Issues

```bash
# Test from container
sudo docker compose run --rm gcontact-sync /bin/bash -c "curl -I https://www.googleapis.com"
```

If DNS issues occur, add to docker-compose.yml:
```yaml
services:
  gcontact-sync:
    dns:
      - 8.8.8.8
      - 8.8.4.4
```

## Advanced Configuration

### Using Specific Image Tags

For production stability, pin to a specific version:

```yaml
services:
  gcontact-sync:
    image: aeden2019/gcontact-sync:v1.2.3  # Specific version
    # or
    image: aeden2019/gcontact-sync:v1.2    # Latest patch of v1.2
```

### Custom Sync Intervals

Modify the `SYNC_INTERVAL` environment variable:

```yaml
environment:
  - SYNC_INTERVAL=6h   # Every 6 hours
  # Options: 30m, 1h, 6h, 12h, 24h, 1d
```

### Resource Limits

Add resource constraints for busy NAS systems:

```yaml
services:
  gcontact-sync:
    # ... other config ...
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
        reservations:
          cpus: '0.1'
          memory: 64M
```

### Backup Configuration

Create a backup script:

```bash
#!/bin/bash
# /volume1/docker/gcontact-sync/backup.sh

BACKUP_DIR="/volume1/backups/gcontact-sync"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Backup config and data
tar -czf "$BACKUP_DIR/gcontact-sync_$DATE.tar.gz" \
  /volume1/docker/gcontact-sync/config \
  /volume1/docker/gcontact-sync/data

# Keep only last 7 backups
ls -t "$BACKUP_DIR"/*.tar.gz | tail -n +8 | xargs -r rm

echo "Backup completed: gcontact-sync_$DATE.tar.gz"
```

Schedule via Task Scheduler to run weekly.

### Multiple Sync Configurations

To run multiple independent sync pairs, create separate project folders:

```
/volume1/docker/
├── gcontact-sync-personal/
│   ├── config/
│   ├── data/
│   └── docker-compose.yml
└── gcontact-sync-work/
    ├── config/
    ├── data/
    └── docker-compose.yml
```

Each with its own credentials and configuration.

### Alternative: Using Dockge

[Dockge](https://github.com/louislam/dockge) is a lightweight alternative to Portainer, focused specifically on managing docker-compose stacks.

**Quick install via SSH:**

```bash
# Create directories
sudo mkdir -p /volume1/docker/dockge/{data,stacks}

# Run Dockge
sudo docker run -d \
  --name=dockge \
  --restart=unless-stopped \
  -p 5001:5001 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /volume1/docker/dockge/data:/app/data \
  -v /volume1/docker/dockge/stacks:/opt/stacks \
  -e DOCKGE_STACKS_DIR=/opt/stacks \
  louislam/dockge:latest
```

Access at `http://your-nas-ip:5001` and create your gcontact-sync stack there.

## Additional Resources

- [Main Docker Guide](DOCKER.md) - Comprehensive Docker documentation
- [README](../README.md) - General usage and features
- [Synology Container Manager Documentation](https://kb.synology.com/en-global/DSM/help/ContainerManager/docker_project)
- [Marius Hosting Synology Guides](https://mariushosting.com/synology-best-docker-containers-to-manage-containers/)
- [Portainer Documentation](https://docs.portainer.io/)
- [Dockge GitHub](https://github.com/louislam/dockge)

## Getting Help

If you encounter issues:

1. Check the [Troubleshooting](#troubleshooting) section
2. Review container logs: `sudo docker compose logs`
3. Run health check: `sudo docker compose run --rm gcontact-sync health`
4. Open an issue on GitHub with:
   - Synology model and DSM version
   - Container Manager/Docker version
   - Container logs
   - Steps to reproduce
