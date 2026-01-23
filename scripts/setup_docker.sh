#!/usr/bin/env bash
#
# Docker Setup Script for GContact Sync
#
# This script automates the setup of a Docker deployment environment for gcontact-sync.
# It creates the required directory structure, sets permissions, and helps configure
# the environment for containerized operation.
#
# Prerequisites:
#   - Docker installed: https://docs.docker.com/get-docker/
#   - Docker Compose (included with Docker Desktop, or install separately)
#   - credentials.json from Google Cloud Console (see scripts/setup_gcloud.sh)
#
# Usage:
#   chmod +x scripts/setup_docker.sh
#   ./scripts/setup_docker.sh
#
# The script will:
#   1. Check for Docker and Docker Compose installation
#   2. Create deployment directory structure
#   3. Set proper permissions for directories
#   4. Create .env file from template
#   5. Help locate and copy credentials.json
#   6. Optionally build the Docker image
#   7. Provide next steps for authentication
#

set -e  # Exit on error

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEFAULT_DEPLOY_DIR="$HOME/gcontact-sync-docker"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print functions
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo ""
    echo -e "${BLUE}=====================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}=====================================${NC}"
    echo ""
}

# Check if Docker is installed
check_docker() {
    print_header "Checking Prerequisites"

    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed."
        echo ""
        echo "Please install Docker from: https://docs.docker.com/get-docker/"
        echo ""
        echo "Installation options:"
        echo "  - macOS: Install Docker Desktop from https://docs.docker.com/desktop/mac/install/"
        echo "  - Linux: Follow instructions at https://docs.docker.com/engine/install/"
        echo "  - Windows: Install Docker Desktop from https://docs.docker.com/desktop/windows/install/"
        exit 1
    fi

    print_success "Docker is installed"
    docker --version

    # Check if Docker daemon is running
    if ! docker info &> /dev/null; then
        print_error "Docker daemon is not running."
        echo ""
        echo "Please start Docker Desktop or the Docker service."
        exit 1
    fi

    print_success "Docker daemon is running"

    # Check for Docker Compose (v2 is bundled with Docker, v1 is standalone)
    if docker compose version &> /dev/null; then
        print_success "Docker Compose is available (Docker Compose V2)"
        docker compose version
    elif command -v docker-compose &> /dev/null; then
        print_success "Docker Compose is available (standalone)"
        docker-compose --version
    else
        print_error "Docker Compose is not installed."
        echo ""
        echo "Docker Compose should be included with Docker Desktop."
        echo "If using Linux without Docker Desktop, install with:"
        echo "  sudo apt-get install docker-compose-plugin"
        exit 1
    fi
}

# Choose or create deployment directory
setup_deploy_directory() {
    print_header "Setting Up Deployment Directory"

    echo "Choose where to set up your Docker deployment:"
    echo ""
    echo "  1. Use default location: $DEFAULT_DEPLOY_DIR"
    echo "  2. Use current directory: $(pwd)"
    echo "  3. Specify a custom path"
    echo ""
    read -p "Choose option (1, 2, or 3): " DIR_OPTION

    case "$DIR_OPTION" in
        1)
            DEPLOY_DIR="$DEFAULT_DEPLOY_DIR"
            ;;
        2)
            DEPLOY_DIR="$(pwd)"
            ;;
        3)
            read -p "Enter deployment directory path: " DEPLOY_DIR
            ;;
        *)
            DEPLOY_DIR="$DEFAULT_DEPLOY_DIR"
            ;;
    esac

    # Expand ~ if present
    DEPLOY_DIR="${DEPLOY_DIR/#\~/$HOME}"

    print_info "Deployment directory: $DEPLOY_DIR"

    # Create deployment directory if it doesn't exist
    if [[ ! -d "$DEPLOY_DIR" ]]; then
        print_info "Creating deployment directory..."
        mkdir -p "$DEPLOY_DIR"
    fi

    cd "$DEPLOY_DIR"
    print_success "Working in: $DEPLOY_DIR"
}

# Create directory structure
create_directories() {
    print_header "Creating Directory Structure"

    # Create required directories
    for dir in config data credentials; do
        if [[ ! -d "$dir" ]]; then
            print_info "Creating $dir/ directory..."
            mkdir -p "$dir"
        else
            print_info "$dir/ directory already exists"
        fi
    done

    # Set permissions (ensure current user owns them, not root)
    print_info "Setting directory permissions..."
    chmod 755 config data credentials

    print_success "Directory structure created:"
    echo "  $DEPLOY_DIR/"
    echo "  ├── config/     (for credentials.json and tokens)"
    echo "  ├── data/       (for sync.db database)"
    echo "  └── credentials/ (additional credential storage)"
}

# Copy Docker files from project
copy_docker_files() {
    print_header "Setting Up Docker Files"

    # Copy docker-compose.yml if not present or user wants to update
    if [[ -f "docker-compose.yml" ]]; then
        print_info "docker-compose.yml already exists"
        read -p "Overwrite with latest version? (y/N): " OVERWRITE
        if [[ "$(echo "$OVERWRITE" | tr '[:upper:]' '[:lower:]')" == "y" ]]; then
            cp "$PROJECT_ROOT/docker-compose.yml" ./docker-compose.yml
            print_success "docker-compose.yml updated"
        fi
    else
        cp "$PROJECT_ROOT/docker-compose.yml" ./docker-compose.yml
        print_success "docker-compose.yml copied"
    fi

    # Create .env file from template
    if [[ -f ".env" ]]; then
        print_info ".env file already exists"
        read -p "Overwrite with default values? (y/N): " OVERWRITE_ENV
        if [[ "$(echo "$OVERWRITE_ENV" | tr '[:upper:]' '[:lower:]')" == "y" ]]; then
            cp "$PROJECT_ROOT/.env.docker" ./.env
            print_success ".env file updated"
        fi
    else
        cp "$PROJECT_ROOT/.env.docker" ./.env
        print_success ".env file created from template"
    fi

    print_info "Docker files configured"
}

# Help user locate and copy credentials
setup_credentials() {
    print_header "Setting Up Google Credentials"

    # Check if credentials already exist
    if [[ -f "config/credentials.json" ]]; then
        print_success "credentials.json already exists in config/"
        read -p "Replace with a different credentials file? (y/N): " REPLACE_CREDS
        if [[ "$(echo "$REPLACE_CREDS" | tr '[:upper:]' '[:lower:]')" != "y" ]]; then
            return 0
        fi
    fi

    echo ""
    echo "To authenticate with Google, you need a credentials.json file from"
    echo "the Google Cloud Console. If you haven't created one yet, run:"
    echo ""
    echo "  $PROJECT_ROOT/scripts/setup_gcloud.sh"
    echo ""
    echo "Or follow the manual steps in the README."
    echo ""

    # Check common locations
    CREDS_FOUND=""

    # Check default gcontact-sync config directory
    if [[ -f "$HOME/.gcontact-sync/credentials.json" ]]; then
        CREDS_FOUND="$HOME/.gcontact-sync/credentials.json"
        print_info "Found credentials at: $CREDS_FOUND"
    fi

    # Check Downloads folder for recent client_secret files
    if [[ -z "$CREDS_FOUND" && -d "$HOME/Downloads" ]]; then
        RECENT_CREDS=$(find "$HOME/Downloads" -name "client_secret*.json" -mmin -60 2>/dev/null | head -1)
        if [[ -n "$RECENT_CREDS" ]]; then
            CREDS_FOUND="$RECENT_CREDS"
            print_info "Found recently downloaded credentials: $CREDS_FOUND"
        fi
    fi

    if [[ -n "$CREDS_FOUND" ]]; then
        read -p "Use this file? (Y/n): " USE_FOUND
        if [[ "$(echo "$USE_FOUND" | tr '[:upper:]' '[:lower:]')" != "n" ]]; then
            cp "$CREDS_FOUND" config/credentials.json
            chmod 600 config/credentials.json
            print_success "Credentials copied to config/credentials.json"
            return 0
        fi
    fi

    # Ask for manual path
    echo ""
    read -p "Enter path to your credentials.json file (or press Enter to skip): " CREDS_PATH

    if [[ -n "$CREDS_PATH" ]]; then
        CREDS_PATH="${CREDS_PATH/#\~/$HOME}"
        if [[ -f "$CREDS_PATH" ]]; then
            cp "$CREDS_PATH" config/credentials.json
            chmod 600 config/credentials.json
            print_success "Credentials copied to config/credentials.json"
        else
            print_error "File not found: $CREDS_PATH"
            print_warning "You will need to copy credentials.json to config/ manually"
        fi
    else
        print_warning "Skipping credentials setup"
        print_info "Remember to copy credentials.json to: $DEPLOY_DIR/config/"
    fi
}

# Optionally build or pull Docker image
setup_docker_image() {
    print_header "Setting Up Docker Image"

    echo "How would you like to get the Docker image?"
    echo ""
    echo "  1. Pull pre-built image from GitHub Container Registry (Recommended)"
    echo "  2. Build locally from source"
    echo "  3. Skip for now"
    echo ""
    read -p "Choose option (1, 2, or 3): " IMAGE_OPTION

    case "$IMAGE_OPTION" in
        1)
            print_info "Pulling image from GitHub Container Registry..."
            if docker pull ghcr.io/aeden2019/gcontact-sync:latest; then
                print_success "Image pulled successfully"
                # Update docker-compose.yml to use the pre-built image
                print_info "Updating docker-compose.yml to use pre-built image..."
                if [[ "$(uname)" == "Darwin" ]]; then
                    # macOS sed requires different syntax
                    sed -i '' 's|image: gcontact-sync:latest|image: ghcr.io/aeden2019/gcontact-sync:latest|g' docker-compose.yml
                else
                    sed -i 's|image: gcontact-sync:latest|image: ghcr.io/aeden2019/gcontact-sync:latest|g' docker-compose.yml
                fi
                print_success "docker-compose.yml updated to use pre-built image"
            else
                print_error "Failed to pull image. You may need to build locally instead."
            fi
            ;;
        2)
            print_info "Building Docker image locally..."
            print_info "This may take a few minutes..."
            if docker compose build; then
                print_success "Docker image built successfully"
            else
                print_error "Docker build failed. Check the output above for errors."
                exit 1
            fi
            ;;
        3)
            print_info "Skipping image setup"
            print_info "You can build later with: docker compose build"
            ;;
        *)
            print_info "Skipping image setup"
            ;;
    esac
}

# Print final instructions
print_final_instructions() {
    print_header "Setup Complete!"

    echo "Your Docker deployment environment is ready."
    echo ""
    echo "Deployment directory: $DEPLOY_DIR"
    echo ""
    echo "Directory structure:"
    echo "  config/       - Store credentials.json and tokens here"
    echo "  data/         - SQLite database will be stored here"
    echo "  credentials/  - Additional credential storage"
    echo ""

    # Check if credentials exist
    if [[ ! -f "config/credentials.json" ]]; then
        echo -e "${YELLOW}Important:${NC} You still need to copy credentials.json to config/"
        echo ""
    fi

    echo "Next steps:"
    echo ""
    echo "1. Ensure credentials.json is in the config/ directory"
    echo ""
    echo "2. Authenticate your first Google account:"
    echo "   docker compose run --rm gcontact-sync auth account1"
    echo ""
    echo "3. Authenticate your second Google account:"
    echo "   docker compose run --rm gcontact-sync auth account2"
    echo ""
    echo "4. Check status:"
    echo "   docker compose run --rm gcontact-sync status"
    echo ""
    echo "5. Preview sync changes:"
    echo "   docker compose run --rm gcontact-sync sync --dry-run"
    echo ""
    echo "6. Run the sync:"
    echo "   docker compose run --rm gcontact-sync sync"
    echo ""
    echo "For daemon mode (continuous sync):"
    echo "   docker compose run --rm gcontact-sync daemon --interval 3600"
    echo ""
    print_success "Happy syncing!"
}

# Main execution
main() {
    echo ""
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║         GContact Sync - Docker Setup Script                   ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo ""

    check_docker
    setup_deploy_directory
    create_directories
    copy_docker_files
    setup_credentials
    setup_docker_image
    print_final_instructions
}

# Run main function
main "$@"
