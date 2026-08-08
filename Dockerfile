# ============================================================
# reeldock — Dockerfile
# ============================================================
# Python 3.12-slim base with yt-dlp, ffmpeg, and app deps.
# Supports PUID/PGID for volume permissions via entrypoint.sh
#
# Supply-chain pins (bump intentionally via Dependabot/manual PR):
#   - python base image digest
#   - uv image digest
#   - yt-dlp release tag + SHA256
# ============================================================

FROM python:3.14.0-slim@sha256:0aecac02dc3d4c5dbb024b753af084cafe41f5416e02193f1ce345d671ec966e AS base

LABEL org.opencontainers.image.title="reeldock"
LABEL org.opencontainers.image.description="YouTube to Audiobookshelf importer"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    atomicparsley \
    curl \
    wget \
    ca-certificates \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Install pinned yt-dlp binary with checksum verification
ARG YTDLP_VERSION=2026.07.04
ARG YTDLP_SHA256=495be29ff4d9d4e9be7eabdfef225221e5d5282e77f2f505abc6dca80349f3fd
RUN curl -sL "https://github.com/yt-dlp/yt-dlp/releases/download/${YTDLP_VERSION}/yt-dlp" \
    -o /usr/local/bin/yt-dlp \
    && echo "${YTDLP_SHA256}  /usr/local/bin/yt-dlp" | sha256sum -c - \
    && chmod a+rx /usr/local/bin/yt-dlp

# ── Python dependencies ─────────────────────────────────────
FROM base AS deps

COPY --from=ghcr.io/astral-sh/uv:0.8.22@sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1 \
    /uv /usr/local/bin/uv

WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# ── Final image ─────────────────────────────────────────────
FROM base AS final

WORKDIR /app

# Copy installed Python environment from deps stage
COPY --from=deps /build/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application code and Alembic migration assets
COPY app/ app/
COPY worker/ worker/
COPY alembic/ alembic/
COPY alembic.ini pyproject.toml ./

# Register package metadata so importlib.metadata.version() works at runtime
COPY --from=ghcr.io/astral-sh/uv:0.8.22@sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1 \
    /uv /usr/local/bin/uv
RUN uv pip install --python /app/.venv/bin/python --no-deps .

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create directories (permissions set at runtime via PUID/PGID)
RUN mkdir -p /data /data/work /data/logs /data/config /media/podcasts /config

# Default environment
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8080
ENV REDIS_URL=redis://redis:6379/0
ENV DATABASE_URL=sqlite+aiosqlite:////data/app.db
ENV WORK_DIR=/data/work
ENV ARCHIVE_FILE=/data/config/youtube-archive.txt
ENV OUTPUT_ROOT=/media/podcasts
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -fs http://localhost:8080/ready || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["app"]
