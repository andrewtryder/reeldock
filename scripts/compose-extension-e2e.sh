#!/usr/bin/env bash
# ============================================================
# compose-extension-e2e.sh — unpacked Chrome extension vs Compose
# ============================================================
# Builds browser-extension/dist/chrome, starts a Compose stack with
# AUTH_ENABLED + EXTENSION_API_ENABLED (host .env is not inherited),
# and runs Playwright against mocked YouTube smoke URLs.
#
# Headless MV3 extension load is unreliable on Playwright's pinned
# Chromium. This script runs headed Chromium under xvfb-run when no
# DISPLAY is set (CI). Locally it uses your display if present.
#
# Optional-host permission browser E2E is skipped (dialogs/certs).
# Origin-permission coverage lives in browser-extension JS unit tests.
# Firefox has no second E2E suite (lint / web-ext / shared JS tests).
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${EXTENSION_E2E_PORT:-18083}"
BASE="http://127.0.0.1:${PORT}"
TOKEN="${REELDOCK_EXTENSION_TOKEN:-e2e-extension-token}"
AUTH_USER="${REELDOCK_AUTH_USERNAME:-admin}"
AUTH_PASS="${REELDOCK_AUTH_PASSWORD:-secret}"
FIXTURE_DIR="$ROOT/tests/fixtures/release_smoke"

if ! command -v docker >/dev/null 2>&1; then
  echo "SKIP: docker not available"
  exit 0
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "SKIP: docker compose not available"
  exit 0
fi
if [[ ! -f "$FIXTURE_DIR/source.m4a" ]]; then
  echo "FAIL: missing fixture $FIXTURE_DIR/source.m4a" >&2
  exit 1
fi

echo "==> Building unpacked Chrome extension..."
if [[ ! -d "$ROOT/browser-extension/node_modules" ]]; then
  npm ci --prefix browser-extension
fi
npm --prefix browser-extension run build:chrome

if [[ ! -d "$ROOT/e2e/node_modules" ]]; then
  echo "==> Installing e2e dependencies..."
  npm ci --prefix e2e
  npx --prefix e2e playwright install chromium
fi

TMP="$(mktemp -d)"
COMPOSE=(docker compose -f "$ROOT/docker-compose.yml" -f "$TMP/override.yml" --env-file "$TMP/.env")
cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  if [[ -d "$TMP" ]]; then
    docker run --rm -v "$TMP:/tmp/smoke" alpine:3.22 \
      chown -R "$(id -u):$(id -g)" /tmp/smoke >/dev/null 2>&1 || true
    rm -rf "$TMP" 2>/dev/null || true
  fi
}
trap cleanup EXIT

mkdir -p "$TMP/data" "$TMP/config" "$TMP/podcasts/Theology"
SMOKE_PUID="$(id -u)"
SMOKE_PGID="$(id -g)"

cat >"$TMP/.env" <<EOF
HOST_AUDIOBOOKS_DIR=$TMP/podcasts
OUTPUT_ROOT=/media/podcasts
PUID=$SMOKE_PUID
PGID=$SMOKE_PGID
AUTH_ENABLED=true
AUTH_USERNAME=$AUTH_USER
AUTH_PASSWORD=$AUTH_PASS
EXTENSION_API_ENABLED=true
EXTENSION_API_TOKEN=$TOKEN
RELEASE_SMOKE_FIXTURE=true
RELEASE_SMOKE_FIXTURE_DIR=/fixtures/release_smoke
RELEASE_SMOKE_FAIL_ONCE=false
ABS_SCAN_AFTER_SUCCESS=false
DEFAULT_DESTINATION_FOLDER=Theology
EOF

cat >"$TMP/override.yml" <<EOF
services:
  app:
    env_file: !override
      - $TMP/.env
    ports:
      - "127.0.0.1:${PORT}:8080"
    environment:
      PUID: "$SMOKE_PUID"
      PGID: "$SMOKE_PGID"
      AUTH_ENABLED: "true"
      AUTH_USERNAME: "$AUTH_USER"
      AUTH_PASSWORD: "$AUTH_PASS"
      EXTENSION_API_ENABLED: "true"
      EXTENSION_API_TOKEN: "$TOKEN"
      RELEASE_SMOKE_FIXTURE: "true"
      RELEASE_SMOKE_FIXTURE_DIR: /fixtures/release_smoke
      RELEASE_SMOKE_FAIL_ONCE: "false"
      DEFAULT_DESTINATION_FOLDER: Theology
    volumes:
      - $TMP/data:/data
      - type: bind
        source: $TMP/podcasts
        target: /media/podcasts
        bind:
          create_host_path: false
      - $TMP/config:/config
      - $FIXTURE_DIR:/fixtures/release_smoke:ro
    healthcheck:
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 20s
  worker:
    env_file: !override
      - $TMP/.env
    environment:
      PUID: "$SMOKE_PUID"
      PGID: "$SMOKE_PGID"
      AUTH_ENABLED: "true"
      AUTH_USERNAME: "$AUTH_USER"
      AUTH_PASSWORD: "$AUTH_PASS"
      EXTENSION_API_ENABLED: "true"
      EXTENSION_API_TOKEN: "$TOKEN"
      RELEASE_SMOKE_FIXTURE: "true"
      RELEASE_SMOKE_FIXTURE_DIR: /fixtures/release_smoke
      RELEASE_SMOKE_FAIL_ONCE: "false"
      DEFAULT_DESTINATION_FOLDER: Theology
    volumes:
      - $TMP/data:/data
      - type: bind
        source: $TMP/podcasts
        target: /media/podcasts
        bind:
          create_host_path: false
      - $TMP/config:/config
      - $FIXTURE_DIR:/fixtures/release_smoke:ro
EOF

echo "==> Starting Compose for extension E2E..."
"${COMPOSE[@]}" up -d --build

echo "==> Waiting for /ready..."
for _ in $(seq 1 90); do
  if curl -fsS "$BASE/ready" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS "$BASE/ready" >/dev/null

echo "==> Waiting for RQ worker..."
for _ in $(seq 1 30); do
  if docker logs reeldock-worker 2>/dev/null | grep -q "Listening on reeldock"; then
    break
  fi
  sleep 1
done

echo "==> Running Playwright extension suite..."
export REELDOCK_BASE_URL="$BASE"
export REELDOCK_EXTENSION_TOKEN="$TOKEN"
export REELDOCK_AUTH_USERNAME="$AUTH_USER"
export REELDOCK_AUTH_PASSWORD="$AUTH_PASS"
export EXTENSION_DIST="$ROOT/browser-extension/dist/chrome"
export EXTENSION_E2E_HEADED="${EXTENSION_E2E_HEADED:-1}"
export REELDOCK_LIBRARY_DIR="$TMP/podcasts"

run_pw() {
  npm --prefix e2e run test:extension
}

if [[ -z "${DISPLAY:-}" ]] && command -v xvfb-run >/dev/null 2>&1; then
  echo "==> No DISPLAY; headed Chromium under xvfb-run (MV3 extension load)"
  xvfb-run -a bash -lc 'npm --prefix e2e run test:extension'
else
  run_pw
fi

echo "PASS: extension e2e"
