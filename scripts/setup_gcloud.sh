#!/usr/bin/env bash
#
# Google Cloud Setup Script for GContact Sync
#
# This script automates the setup of a Google Cloud project with the People API
# enabled and OAuth 2.0 credentials configured for desktop application use.
#
# Prerequisites:
#   - Google Cloud SDK (gcloud) installed: https://cloud.google.com/sdk/docs/install
#   - A Google account with permissions to create projects (or an existing project)
#
# Usage:
#   chmod +x scripts/setup_gcloud.sh
#   ./scripts/setup_gcloud.sh
#
# The script will:
#   1. Check for gcloud CLI installation
#   2. Authenticate with Google Cloud (if needed)
#   3. Create or select a project
#   4. Enable the People API
#   5. Configure the OAuth consent screen
#   6. Create OAuth 2.0 credentials
#   7. Download and save credentials to ~/.gcontact-sync/
#

set -e  # Exit on error

# Configuration
CONFIG_DIR="${GCONTACT_SYNC_CONFIG_DIR:-$HOME/.gcontact-sync}"
DEFAULT_PROJECT_ID="gcontact-sync-$(date +%s)"
APP_NAME="GContact Sync"

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

# Check if gcloud is installed
check_gcloud() {
    print_header "Checking Prerequisites"

    if ! command -v gcloud &> /dev/null; then
        print_error "Google Cloud SDK (gcloud) is not installed."
        echo ""
        echo "Please install it from: https://cloud.google.com/sdk/docs/install"
        echo ""
        echo "Installation options:"
        echo "  - macOS: brew install google-cloud-sdk"
        echo "  - Ubuntu/Debian: sudo apt-get install google-cloud-sdk"
        echo "  - Or download from the link above"
        exit 1
    fi

    print_success "Google Cloud SDK is installed"
    gcloud --version | head -1
}

# Authenticate with Google Cloud
authenticate() {
    print_header "Authenticating with Google Cloud"

    # Check if already authenticated
    if gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | grep -q "@"; then
        CURRENT_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | head -1)
        print_info "Currently authenticated as: $CURRENT_ACCOUNT"

        read -p "Use this account? (Y/n): " USE_CURRENT
        if [[ "${USE_CURRENT,,}" != "n" ]]; then
            print_success "Using existing authentication"
            return 0
        fi
    fi

    print_info "Opening browser for Google authentication..."
    gcloud auth login --no-launch-browser 2>/dev/null || gcloud auth login

    print_success "Authentication successful"
}

# Create or select a project
setup_project() {
    print_header "Setting Up Google Cloud Project"

    # List existing projects
    print_info "Fetching your existing projects..."
    PROJECTS=$(gcloud projects list --format="value(projectId)" 2>/dev/null || echo "")

    if [[ -n "$PROJECTS" ]]; then
        echo ""
        echo "Your existing projects:"
        echo "$PROJECTS" | head -10
        PROJECT_COUNT=$(echo "$PROJECTS" | wc -l | tr -d ' ')
        if [[ $PROJECT_COUNT -gt 10 ]]; then
            echo "... and $((PROJECT_COUNT - 10)) more"
        fi
        echo ""
    fi

    echo "Options:"
    echo "  1. Create a new project"
    echo "  2. Use an existing project"
    echo ""
    read -p "Choose option (1 or 2): " PROJECT_OPTION

    if [[ "$PROJECT_OPTION" == "1" ]]; then
        # Create new project
        read -p "Enter project ID (default: $DEFAULT_PROJECT_ID): " PROJECT_ID
        PROJECT_ID="${PROJECT_ID:-$DEFAULT_PROJECT_ID}"

        print_info "Creating project: $PROJECT_ID"
        if gcloud projects create "$PROJECT_ID" --name="$APP_NAME" 2>/dev/null; then
            print_success "Project created: $PROJECT_ID"
        else
            print_warning "Project creation failed. It may already exist or you don't have permissions."
            print_info "Trying to use existing project..."
        fi
    else
        # Use existing project
        read -p "Enter existing project ID: " PROJECT_ID
        if [[ -z "$PROJECT_ID" ]]; then
            print_error "Project ID is required"
            exit 1
        fi
    fi

    # Set the project as active
    print_info "Setting active project to: $PROJECT_ID"
    gcloud config set project "$PROJECT_ID"

    print_success "Project configured: $PROJECT_ID"
    export GCLOUD_PROJECT_ID="$PROJECT_ID"
}

# Enable required APIs
enable_apis() {
    print_header "Enabling Required APIs"

    print_info "Enabling People API..."
    if gcloud services enable people.googleapis.com 2>/dev/null; then
        print_success "People API enabled"
    else
        print_warning "Could not enable People API. It may already be enabled or there might be billing issues."
        print_info "Please ensure billing is enabled for your project."
    fi

    # Also enable the Google+ API for user info (optional)
    print_info "Enabling Cloud Resource Manager API (for project management)..."
    gcloud services enable cloudresourcemanager.googleapis.com 2>/dev/null || true
}

# Configure OAuth consent screen
configure_oauth_consent() {
    print_header "Configuring OAuth Consent Screen"

    print_warning "OAuth consent screen configuration requires manual steps."
    echo ""
    echo "The gcloud CLI has limited support for OAuth consent screen configuration."
    echo "Please complete the following steps manually:"
    echo ""
    echo "1. Go to: https://console.cloud.google.com/apis/credentials/consent?project=$GCLOUD_PROJECT_ID"
    echo ""
    echo "2. Select 'External' user type (unless you have a Google Workspace org)"
    echo ""
    echo "3. Fill in the required fields:"
    echo "   - App name: $APP_NAME"
    echo "   - User support email: (your email)"
    echo "   - Developer contact: (your email)"
    echo ""
    echo "4. Add the scope: https://www.googleapis.com/auth/contacts"
    echo ""
    echo "5. Add your two Google account emails as test users"
    echo "   (Required for external apps in testing mode)"
    echo ""
    echo "6. Complete and save the configuration"
    echo ""

    read -p "Press Enter when you've completed the OAuth consent screen setup..."
    print_success "OAuth consent screen configured (manual)"
}

# Create OAuth credentials
create_credentials() {
    print_header "Creating OAuth 2.0 Credentials"

    # Check if we can create credentials via CLI
    print_info "Attempting to create OAuth credentials..."

    # Unfortunately, gcloud doesn't fully support creating OAuth client IDs
    # We need to guide the user through manual creation

    print_warning "OAuth credential creation requires manual steps in the Google Cloud Console."
    echo ""
    echo "Please follow these steps:"
    echo ""
    echo "1. Go to: https://console.cloud.google.com/apis/credentials?project=$GCLOUD_PROJECT_ID"
    echo ""
    echo "2. Click '+ CREATE CREDENTIALS' at the top"
    echo ""
    echo "3. Select 'OAuth client ID'"
    echo ""
    echo "4. Choose application type: 'Desktop app'"
    echo ""
    echo "5. Name it: '$APP_NAME Desktop Client'"
    echo ""
    echo "6. Click 'CREATE'"
    echo ""
    echo "7. Click 'DOWNLOAD JSON' on the confirmation dialog"
    echo ""
    echo "8. Note where the file is downloaded (usually ~/Downloads/)"
    echo ""

    read -p "Press Enter when you've downloaded the credentials JSON file..."

    # Try to find and copy the credentials file
    print_header "Locating and Installing Credentials"

    # Look for recently downloaded client secret files
    DOWNLOADS_DIR="$HOME/Downloads"
    if [[ -d "$DOWNLOADS_DIR" ]]; then
        RECENT_CREDS=$(find "$DOWNLOADS_DIR" -name "client_secret*.json" -mmin -30 2>/dev/null | head -1)

        if [[ -n "$RECENT_CREDS" ]]; then
            print_info "Found credentials file: $RECENT_CREDS"
            read -p "Use this file? (Y/n): " USE_FOUND

            if [[ "${USE_FOUND,,}" != "n" ]]; then
                CREDS_FILE="$RECENT_CREDS"
            fi
        fi
    fi

    # If not found, ask for path
    if [[ -z "$CREDS_FILE" ]]; then
        read -p "Enter the path to your downloaded credentials JSON file: " CREDS_FILE
    fi

    if [[ ! -f "$CREDS_FILE" ]]; then
        print_error "Credentials file not found: $CREDS_FILE"
        exit 1
    fi

    # Create config directory
    print_info "Creating config directory: $CONFIG_DIR"
    mkdir -p "$CONFIG_DIR"
    chmod 700 "$CONFIG_DIR"

    # Copy credentials
    print_info "Installing credentials..."
    cp "$CREDS_FILE" "$CONFIG_DIR/credentials.json"
    chmod 600 "$CONFIG_DIR/credentials.json"

    print_success "Credentials installed to: $CONFIG_DIR/credentials.json"
}

# Print final instructions
print_final_instructions() {
    print_header "Setup Complete!"

    echo "Your Google Cloud project is configured and ready to use."
    echo ""
    echo "Configuration:"
    echo "  - Project ID: $GCLOUD_PROJECT_ID"
    echo "  - Config directory: $CONFIG_DIR"
    echo "  - Credentials: $CONFIG_DIR/credentials.json"
    echo ""
    echo "Next steps:"
    echo ""
    echo "1. Authenticate your first Google account:"
    echo "   uv run gcontact-sync auth --account account1"
    echo ""
    echo "2. Authenticate your second Google account:"
    echo "   uv run gcontact-sync auth --account account2"
    echo ""
    echo "3. Check status:"
    echo "   uv run gcontact-sync status"
    echo ""
    echo "4. Preview sync changes:"
    echo "   uv run gcontact-sync sync --dry-run"
    echo ""
    echo "5. Run the sync:"
    echo "   uv run gcontact-sync sync"
    echo ""
    print_success "Happy syncing!"
}

# Main execution
main() {
    echo ""
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║           GContact Sync - Google Cloud Setup Script          ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo ""

    check_gcloud
    authenticate
    setup_project
    enable_apis
    configure_oauth_consent
    create_credentials
    print_final_instructions
}

# Run main function
main "$@"
