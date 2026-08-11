#!/usr/bin/env bash
# ============================================================
# compose-playwright-smoke.sh — one Playwright golden path (#118)
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${PLAYWRIGHT_SMOKE_PORT:-18082}"
BASE="http://127.0.0.1:${PORT}"
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
if [[ ! -d "$ROOT/e2e/node_modules" ]]; then
  echo "==> Installing e2e dependencies..."
  npm ci --prefix e2e
  npx --prefix e2e playwright install chromium
fi

TMP="$(mktemp -d)"
COMPOSE=(docker compose -f "$ROOT/docker-compose.yml" -f "$TMP/override.yml" --env-file "$TMP/.env")
cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

mkdir -p "$TMP/data" "$TMP/config" "$TMP/podcasts"

cat >"$TMP/.env" <<EOF
HOST_AUDIOBOOKS_DIR=$TMP/podcasts
OUTPUT_ROOT=/media/podcasts
AUTH_ENABLED=false
EXTENSION_API_ENABLED=false
RELEASE_SMOKE_FIXTURE=true
RELEASE_SMOKE_FIXTURE_DIR=/fixtures/release_smoke
RELEASE_SMOKE_FAIL_ONCE=false
ABS_SCAN_AFTER_SUCCESS=false
EOF

cat >"$TMP/override.yml" <<EOF
services:
  app:
    env_file: !override
      - $TMP/.env
    ports:
      - "127.0.0.1:${PORT}:8080"
    environment:
      RELEASE_SMOKE_FIXTURE: "true"
      RELEASE_SMOKE_FIXTURE_DIR: /fixtures/release_smoke
      RELEASE_SMOKE_FAIL_ONCE: "false"
    volumes:
      - $TMP/data:/data
      - type: bind
        source: $TMP/podcasts
        target: /media/podcasts
        bind:
          create_host_path: false
      - $TMP/config:/config
      - $FIXTURE_DIR:/fixtures/release_smoke:ro
  worker:
    env_file: !override
      - $TMP/.env
    environment:
      RELEASE_SMOKE_FIXTURE: "true"
      RELEASE_SMOKE_FIXTURE_DIR: /fixtures/release_smoke
      RELEASE_SMOKE_FAIL_ONCE: "false"
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

echo "==> Starting Compose for Playwright golden path..."
"${COMPOSE[@]}" up -d --build

echo "==> Waiting for /ready..."
for _ in $(seq 1 90); do
  if curl -fsS "$BASE/ready" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS "$BASE/ready" >/dev/null

echo "==> Running Playwright..."
export REELDOCK_BASE_URL="$BASE"
npm --prefix e2e test

echo "PASS: playwright golden path"
