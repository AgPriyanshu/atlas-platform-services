# Use the official Python image as the base (slim)
FROM python:3.12-slim

# Avoid prompts during package installs
ARG DEBIAN_FRONTEND=noninteractive

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies (build deps are removed afterwards to keep the image small)
# - --no-install-recommends reduces installed packages
# - all install, builds, and cleanup happen in a single RUN to avoid extra layers
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        ca-certificates \
        libpq-dev \
        gdal-bin \
        libgdal-dev \
        libgeos-dev \
        libproj-dev \
        libspatialite-dev \
        spatialite-bin \
    ; \
    rm -rf /var/lib/apt/lists/*;

# Copy only requirements first to leverage Docker cache
COPY requirements.txt ./

# Upgrade pip, install python deps (no cache), install GDAL python wheel matching system GDAL
# then purge build tools to reduce final image size
RUN set -eux; \
    pip install --upgrade pip setuptools wheel --no-cache-dir; \
    pip install --no-cache-dir -r requirements.txt; \
    if command -v gdal-config >/dev/null 2>&1; then \
        GDAL_VERSION=$(gdal-config --version); \
        pip install --no-cache-dir "GDAL==${GDAL_VERSION}" || true; \
    fi; \
    # remove build deps (they are no longer needed after wheels are built/installed)
    apt-get purge -y --auto-remove build-essential gcc || true; \
    rm -rf /root/.cache/pip

# Copy the rest of the project files
COPY . .

# Ensure the entrypoint script is executable
RUN [ -f ./docker-entrypoint.sh ] && chmod +x ./docker-entrypoint.sh || true

# Expose port 8000
EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD uvicorn backend_projects.asgi:application --host 0.0.0.0 --port 8000 --workers 9 --log-config log_config.yaml --ws wsproto
