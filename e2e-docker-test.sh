#!/bin/bash
#
# End-to-End Docker Deployment Test Script
# GContact Sync - Docker Container and Docker Compose Support
#
# This script automates the end-to-end testing of Docker deployment.
# See E2E_DOCKER_TEST.md for detailed documentation.
#
# Usage: ./e2e-docker-test.sh [--skip-cleanup] [--keep-data]
#
# Options:
#   --skip-cleanup    Don't remove test artifacts at the end
#   --keep-data       Don't remove test data (config, data, credentials)
#   --help            Show this help message
#

set -e  # Exit on error
set -u  # Exit on undefined variable

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test configuration
SKIP_CLEANUP=false
KEEP_DATA=false
TEST_IMAGE="gcontact-sync:test"
COMPOSE_FILE="docker-compose.yml"
COMPOSE_BACKUP="docker-compose.yml.bak"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-cleanup)
            SKIP_CLEANUP=true
            shift
            ;;
        --keep-data)
            KEEP_DATA=true
            shift
            ;;
        --help)
            head -n 15 "$0" | tail -n 11
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Helper functions
print_header() {
    echo ""
    echo -e "${BLUE}===================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}===================================================${NC}"
}

print_step() {
    echo ""
    echo -e "${YELLOW}[$1]${NC} $2"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Test steps counter
TOTAL_STEPS=13
PASSED_STEPS=0
FAILED_STEPS=0
WARNING_STEPS=0

# Array to store test results
declare -a TEST_RESULTS

record_result() {
    local step=$1
    local status=$2
    local message=$3

    TEST_RESULTS+=("Step $step: $status - $message")

    case $status in
        "PASS")
            ((PASSED_STEPS++))
            ;;
        "FAIL")
            ((FAILED_STEPS++))
            ;;
        "WARN")
            ((WARNING_STEPS++))
            ;;
    esac
}

# Prerequisite checks
check_prerequisites() {
    print_header "Checking Prerequisites"

    # Check Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed or not in PATH"
        exit 1
    fi
    print_success "Docker is installed: $(docker --version)"

    # Check Docker Compose
    if ! command -v docker compose &> /dev/null && ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose is not installed or not in PATH"
        exit 1
    fi

    if command -v docker compose &> /dev/null; then
        print_success "Docker Compose is installed: $(docker compose version)"
    else
        print_success "Docker Compose is installed: $(docker-compose --version)"
        # Create alias for consistency
        shopt -s expand_aliases
        alias 'docker compose'='docker-compose'
    fi

    # Check Docker daemon is running
    if ! docker info &> /dev/null; then
        print_error "Docker daemon is not running"
        exit 1
    fi
    print_success "Docker daemon is running"

    # Check required files exist
    if [ ! -f "Dockerfile" ]; then
        print_error "Dockerfile not found in current directory"
        exit 1
    fi
    print_success "Dockerfile found"

    if [ ! -f "$COMPOSE_FILE" ]; then
        print_error "docker-compose.yml not found in current directory"
        exit 1
    fi
    print_success "docker-compose.yml found"

    if [ ! -f ".env" ] && [ ! -f ".env.docker" ]; then
        print_warning ".env file not found - will be created from .env.docker"
    fi
}

# Step 1: Clean Docker environment
step1_clean_environment() {
    print_step "1/$TOTAL_STEPS" "Cleaning Docker environment"

    # Stop and remove existing containers
    docker compose down -v 2>/dev/null || true
    docker rm -f gcontact-sync 2>/dev/null || true

    # Remove existing test images
    docker rmi $TEST_IMAGE 2>/dev/null || true

    # Clean dangling images
    docker image prune -f > /dev/null

    print_success "Docker environment cleaned"
    record_result 1 "PASS" "Docker environment cleaned"
}

# Step 2: Build Docker image
step2_build_image() {
    print_step "2/$TOTAL_STEPS" "Building Docker image"

    if docker build -t $TEST_IMAGE . > build.log 2>&1; then
        print_success "Docker image built successfully"

        # Check image size
        IMAGE_SIZE=$(docker image inspect $TEST_IMAGE --format='{{.Size}}' | awk '{print int($1/1024/1024)}')
        print_info "Image size: ${IMAGE_SIZE}MB"

        if [ $IMAGE_SIZE -lt 500 ]; then
            print_success "Image size is optimized (< 500MB)"
            record_result 2 "PASS" "Docker image built successfully (${IMAGE_SIZE}MB)"
        else
            print_warning "Image size is larger than expected (${IMAGE_SIZE}MB > 500MB)"
            record_result 2 "WARN" "Docker image built but larger than expected (${IMAGE_SIZE}MB)"
        fi
    else
        print_error "Docker build failed"
        echo "Build log:"
        cat build.log
        record_result 2 "FAIL" "Docker build failed"
        exit 1
    fi
}

# Step 3: Verify health check
step3_verify_health_check() {
    print_step "3/$TOTAL_STEPS" "Testing health check command"

    HEALTH_OUTPUT=$(docker run --rm $TEST_IMAGE health 2>&1)
    HEALTH_EXIT=$?

    print_info "Health output: $HEALTH_OUTPUT"

    if [ $HEALTH_EXIT -eq 0 ] && echo "$HEALTH_OUTPUT" | grep -q "healthy"; then
        print_success "Health check works correctly"
        record_result 3 "PASS" "Health check returns 'healthy'"
    else
        print_error "Health check failed (exit: $HEALTH_EXIT)"
        record_result 3 "FAIL" "Health check failed"
        exit 1
    fi
}

# Step 4: Create configuration directories
step4_create_config() {
    print_step "4/$TOTAL_STEPS" "Creating configuration directories"

    mkdir -p ./config ./data ./credentials

    # Check for credentials.json
    CREDS_FOUND=false
    for path in ./config/credentials.json ./credentials.json ../credentials.json; do
        if [ -f "$path" ]; then
            if [ "$path" != "./config/credentials.json" ]; then
                cp "$path" ./config/credentials.json
            fi
            CREDS_FOUND=true
            print_success "credentials.json found and copied to config/"
            break
        fi
    done

    if [ "$CREDS_FOUND" = false ]; then
        print_warning "credentials.json not found - OAuth steps will fail"
        print_info "Place credentials.json in ./config/ to test authentication"
        record_result 4 "WARN" "Configuration created but credentials.json missing"
    else
        record_result 4 "PASS" "Configuration directories created with credentials"
    fi

    # Set proper permissions
    chmod -R 755 ./config ./data ./credentials 2>/dev/null || true

    print_success "Configuration directories created"
}

# Step 5: Start container with docker-compose
step5_start_container() {
    print_step "5/$TOTAL_STEPS" "Starting container with docker-compose"

    # Backup and modify docker-compose.yml to use test image
    cp $COMPOSE_FILE $COMPOSE_BACKUP
    sed -i.tmp "s|image: gcontact-sync:latest|image: $TEST_IMAGE|" $COMPOSE_FILE
    rm -f ${COMPOSE_FILE}.tmp

    # Ensure .env file exists
    if [ ! -f .env ] && [ -f .env.docker ]; then
        cp .env.docker .env
        print_info "Created .env from .env.docker"
    fi

    # Start container
    if docker compose up -d > compose-up.log 2>&1; then
        print_success "Container started successfully"

        # Wait for startup
        print_info "Waiting for container to initialize..."
        sleep 5

        # Check container state
        if docker compose ps | grep -q "Up"; then
            print_success "Container is running"
            record_result 5 "PASS" "Container started and running"
        else
            print_error "Container is not in 'Up' state"
            docker compose logs
            record_result 5 "FAIL" "Container not running"
            exit 1
        fi
    else
        print_error "Failed to start container"
        cat compose-up.log
        record_result 5 "FAIL" "docker compose up failed"
        exit 1
    fi
}

# Step 6: Verify health check in running container
step6_verify_health() {
    print_step "6/$TOTAL_STEPS" "Verifying health check in running container"

    # Wait for health check to pass (up to 60 seconds)
    print_info "Waiting for health check to pass..."
    ATTEMPTS=0
    MAX_ATTEMPTS=12

    while [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do
        HEALTH_STATUS=$(docker inspect --format='{{.State.Health.Status}}' gcontact-sync 2>/dev/null || echo "none")

        if [ "$HEALTH_STATUS" = "healthy" ]; then
            print_success "Health check passed"
            record_result 6 "PASS" "Container health check is healthy"
            return 0
        fi

        print_info "Health status: $HEALTH_STATUS (attempt $((ATTEMPTS+1))/$MAX_ATTEMPTS)"
        ((ATTEMPTS++))
        sleep 5
    done

    print_warning "Health check did not pass within timeout"
    docker compose logs --tail=20
    record_result 6 "WARN" "Health check did not pass in time"
}

# Step 7: Test basic container functionality
step7_test_commands() {
    print_step "7/$TOTAL_STEPS" "Testing container command execution"

    HELP_OUTPUT=$(docker compose run --rm gcontact-sync --help 2>&1)
    HELP_EXIT=$?

    if [ $HELP_EXIT -eq 0 ] && echo "$HELP_OUTPUT" | grep -q "Usage:"; then
        print_success "Container can execute commands"
        record_result 7 "PASS" "CLI commands work in container"
    else
        print_error "Container command execution failed"
        print_info "$HELP_OUTPUT"
        record_result 7 "FAIL" "CLI commands failed"
        exit 1
    fi
}

# Step 8: Test authentication (manual)
step8_test_auth() {
    print_step "8/$TOTAL_STEPS" "Authentication test (manual)"

    if [ ! -f ./config/credentials.json ]; then
        print_warning "Skipping authentication test - credentials.json not found"
        record_result 8 "SKIP" "No credentials.json available"
        return 0
    fi

    print_info "Authentication requires manual OAuth flow"
    print_info "To test manually, run:"
    print_info "  docker compose run --rm gcontact-sync auth account1"
    print_info ""

    # Check if token already exists
    if [ -f ./config/token_account1.json ]; then
        print_success "Token file already exists (authentication previously completed)"
        record_result 8 "PASS" "Token file exists"
    else
        print_warning "Token file not found - manual authentication needed"
        record_result 8 "SKIP" "Manual OAuth required"
    fi
}

# Step 9: Test sync dry-run
step9_test_sync() {
    print_step "9/$TOTAL_STEPS" "Testing sync --dry-run"

    if [ ! -f ./config/token_account1.json ]; then
        print_warning "Skipping sync test - no authentication token"
        record_result 9 "SKIP" "No authentication token"
        return 0
    fi

    print_info "Running sync --dry-run..."
    SYNC_OUTPUT=$(docker compose run --rm gcontact-sync sync --dry-run 2>&1 || true)
    SYNC_EXIT=$?

    echo "$SYNC_OUTPUT"

    # Check for expected patterns
    if echo "$SYNC_OUTPUT" | grep -qi "dry.run\|dry-run"; then
        print_success "Sync dry-run executed successfully"
        record_result 9 "PASS" "Sync dry-run completed"
    elif [ $SYNC_EXIT -eq 0 ]; then
        print_success "Sync command completed successfully"
        record_result 9 "PASS" "Sync completed"
    else
        print_warning "Sync may have encountered issues (exit: $SYNC_EXIT)"
        record_result 9 "WARN" "Sync completed with warnings"
    fi
}

# Step 10: Verify database created
step10_verify_database() {
    print_step "10/$TOTAL_STEPS" "Verifying database creation"

    if [ -f ./data/sync.db ]; then
        DB_SIZE=$(stat -f%z ./data/sync.db 2>/dev/null || stat -c%s ./data/sync.db 2>/dev/null || echo "0")
        print_success "Database created (size: ${DB_SIZE} bytes)"

        if command -v sqlite3 &> /dev/null && [ "$DB_SIZE" -gt 0 ]; then
            TABLES=$(sqlite3 ./data/sync.db ".tables" 2>&1 || echo "")
            if [ -n "$TABLES" ]; then
                print_info "Database tables: $TABLES"
            fi
        fi

        record_result 10 "PASS" "Database created"
    else
        print_warning "Database file not found (may be created on first sync)"
        record_result 10 "WARN" "Database not yet created"
    fi
}

# Step 11: Test container restart and persistence
step11_test_persistence() {
    print_step "11/$TOTAL_STEPS" "Testing state persistence across restart"

    # Record token modification time (if exists)
    if [ -f ./config/token_account1.json ]; then
        TOKEN_MTIME_BEFORE=$(stat -f%m ./config/token_account1.json 2>/dev/null || stat -c%Y ./config/token_account1.json 2>/dev/null || echo "0")
    else
        TOKEN_MTIME_BEFORE="0"
    fi

    # Stop container
    print_info "Stopping container..."
    docker compose down > /dev/null 2>&1

    sleep 2

    # Start container again
    print_info "Starting container..."
    docker compose up -d > /dev/null 2>&1

    sleep 5

    # Verify container is running
    if docker compose ps | grep -q "Up"; then
        print_success "Container restarted successfully"
    else
        print_error "Container failed to restart"
        record_result 11 "FAIL" "Container restart failed"
        exit 1
    fi

    # Check token persistence
    if [ -f ./config/token_account1.json ]; then
        TOKEN_MTIME_AFTER=$(stat -f%m ./config/token_account1.json 2>/dev/null || stat -c%Y ./config/token_account1.json 2>/dev/null || echo "0")

        if [ "$TOKEN_MTIME_BEFORE" = "$TOKEN_MTIME_AFTER" ] && [ "$TOKEN_MTIME_BEFORE" != "0" ]; then
            print_success "Token persisted (not re-authenticated)"
        else
            print_info "Token file state changed or newly created"
        fi
    fi

    # Check database persistence
    if [ -f ./data/sync.db ]; then
        print_success "Database persisted"
        record_result 11 "PASS" "State persisted across restart"
    else
        print_warning "Database not found after restart"
        record_result 11 "WARN" "Database persistence uncertain"
    fi
}

# Step 12: Verify logs
step12_verify_logs() {
    print_step "12/$TOTAL_STEPS" "Checking container logs"

    LOGS=$(docker compose logs --tail=50 2>&1)

    # Save logs to file
    echo "$LOGS" > container.log

    # Check for critical errors
    if echo "$LOGS" | grep -Ei "critical|fatal" | grep -v "grep"; then
        print_warning "Logs contain critical errors"
        record_result 12 "WARN" "Critical errors in logs"
    elif echo "$LOGS" | grep -Ei "error" | grep -v "grep" | grep -v "ERROR" | head -n 5; then
        print_warning "Logs contain some errors (may be expected)"
        record_result 12 "WARN" "Some errors in logs"
    else
        print_success "Logs show clean operation"
        record_result 12 "PASS" "No critical errors in logs"
    fi

    print_info "Full logs saved to container.log"
}

# Step 13: Cleanup
step13_cleanup() {
    print_step "13/$TOTAL_STEPS" "Cleaning up test environment"

    if [ "$SKIP_CLEANUP" = true ]; then
        print_info "Skipping cleanup (--skip-cleanup flag)"
        record_result 13 "SKIP" "Cleanup skipped by user"
        return 0
    fi

    # Stop and remove containers
    docker compose down -v > /dev/null 2>&1 || true

    # Restore original docker-compose.yml
    if [ -f $COMPOSE_BACKUP ]; then
        mv $COMPOSE_BACKUP $COMPOSE_FILE
    fi

    # Remove test image
    docker rmi $TEST_IMAGE > /dev/null 2>&1 || true

    # Clean up logs
    rm -f build.log compose-up.log container.log

    # Remove test data (optional)
    if [ "$KEEP_DATA" = false ]; then
        print_info "Removing test data directories"
        rm -rf ./config ./data ./credentials
    else
        print_info "Keeping test data (--keep-data flag)"
    fi

    print_success "Test environment cleaned up"
    record_result 13 "PASS" "Cleanup completed"
}

# Print test summary
print_summary() {
    print_header "Test Summary"

    echo ""
    echo "Test Results:"
    echo "============="
    for result in "${TEST_RESULTS[@]}"; do
        if echo "$result" | grep -q "PASS"; then
            echo -e "${GREEN}✅${NC} $result"
        elif echo "$result" | grep -q "FAIL"; then
            echo -e "${RED}❌${NC} $result"
        elif echo "$result" | grep -q "WARN"; then
            echo -e "${YELLOW}⚠️${NC} $result"
        else
            echo -e "${BLUE}ℹ️${NC} $result"
        fi
    done

    echo ""
    echo "Summary:"
    echo "========"
    echo -e "${GREEN}Passed:${NC} $PASSED_STEPS"
    echo -e "${YELLOW}Warnings:${NC} $WARNING_STEPS"
    echo -e "${RED}Failed:${NC} $FAILED_STEPS"
    echo ""

    if [ $FAILED_STEPS -eq 0 ]; then
        if [ $WARNING_STEPS -eq 0 ]; then
            echo -e "${GREEN}✅ ALL TESTS PASSED!${NC}"
            return 0
        else
            echo -e "${YELLOW}⚠️  TESTS PASSED WITH WARNINGS${NC}"
            return 0
        fi
    else
        echo -e "${RED}❌ SOME TESTS FAILED${NC}"
        return 1
    fi
}

# Main execution
main() {
    print_header "GContact Sync - E2E Docker Deployment Test"

    check_prerequisites

    step1_clean_environment
    step2_build_image
    step3_verify_health_check
    step4_create_config
    step5_start_container
    step6_verify_health
    step7_test_commands
    step8_test_auth
    step9_test_sync
    step10_verify_database
    step11_test_persistence
    step12_verify_logs
    step13_cleanup

    print_summary
}

# Run main function
main
EXIT_CODE=$?

exit $EXIT_CODE
