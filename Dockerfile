# Multi-stage Dockerfile for gcontact-sync CLI application
# Stage 1: Builder - Install dependencies and build the package
FROM python:3.12-slim AS builder

# Set working directory
WORKDIR /build

# Install system dependencies needed for building Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml first to leverage Docker layer caching
COPY pyproject.toml ./

# Create virtual environment
RUN python -m venv /opt/venv

# Activate virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install build tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install dependencies from pyproject.toml
# This installs only production dependencies (not dev dependencies)
RUN pip install --no-cache-dir -e .

# Copy the entire application source
COPY gcontact_sync ./gcontact_sync

# Install the package in the virtual environment
RUN pip install --no-cache-dir .

# Stage 2: Runtime - Create minimal production image
FROM python:3.12-slim AS runtime

# Set working directory
WORKDIR /app

# Install runtime dependencies only (if any system packages are needed)
# Currently none needed, but keeping structure for future use
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash gcontact && \
    chown -R gcontact:gcontact /app

# Create necessary directories with proper permissions
RUN mkdir -p /app/config /app/data /app/credentials && \
    chown -R gcontact:gcontact /app/config /app/data /app/credentials

# Switch to non-root user
USER gcontact

# Set volumes for persistent data
VOLUME ["/app/config", "/app/data", "/app/credentials"]

# Health check using dedicated health command
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD gcontact-sync health || exit 1

# Default command - show help
ENTRYPOINT ["gcontact-sync"]
CMD ["--help"]
