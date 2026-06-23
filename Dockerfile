# ---- builder: installs all Python dependencies into an isolated venv ----
FROM python:3.12-slim-bookworm AS builder

ARG DEBIAN_FRONTEND=noninteractive

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libpq-dev \
        libgdal-dev \
        libgeos-dev \
        libproj-dev \
        libspatialite-dev \
    ; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    set -eux; \
    uv sync --frozen; \
    if command -v gdal-config >/dev/null 2>&1; then \
        GDAL_VERSION=$(gdal-config --version); \
        uv pip install --python /opt/venv/bin/python "GDAL==${GDAL_VERSION}" || true; \
    fi

# ---- runtime: lean image without build tools ----
FROM python:3.12-slim-bookworm AS runtime

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        libpq5 \
        gdal-bin \
        libgdal-dev \
        libgeos-dev \
        libproj-dev \
        libspatialite-dev \
        spatialite-bin \
    ; \
    rm -rf /var/lib/apt/lists/*; \
    pip install --upgrade pip; \
    groupadd --gid 1001 appgroup; \
    useradd --uid 1001 --gid appgroup --no-create-home --shell /bin/bash appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

COPY --chown=appuser:appgroup . .

RUN chmod +x ./docker-entrypoint.sh

USER appuser

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "backend_projects.asgi:application", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "9", "--log-config", "log_config.yaml", "--ws", "wsproto"]
