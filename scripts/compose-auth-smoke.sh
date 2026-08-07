#!/usr/bin/env bash
# Smoke-test that Compose injects AUTH_* from .env into the app container.
# Requires Docker. Skips cleanly when Docker is unavailable.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "SKIP: docker not available"
  exit 0
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "SKIP: docker compose not available"
  exit 0
fi

TMP="$(mktemp -d)"
trap 'docker compose -f "$ROOT/docker-compose.yml" -f "$TMP/override.yml" --env-file "$TMP/.env" down -v --remove-orphans >/dev/null 2>&1 || true; rm -rf "$TMP"' EXIT

mkdir -p "$TMP/data" "$TMP/config" "$TMP/podcasts"

cat >"$TMP/.env" <<EOF
HOST_PODCASTS_DIR=$TMP/podcasts
CONTAINER_PODCASTS_DIR=/media/podcasts
OUTPUT_ROOT=/media/podcasts
AUTH_ENABLED=true
AUTH_USERNAME=smokeadmin
AUTH_PASSWORD=smokesecret
EXTENSION_API_ENABLED=false
EOF

cat >"$TMP/override.yml" <<EOF
services:
  app:
    ports:
      - "127.0.0.1:18080:8080"
    volumes:
      - $TMP/data:/data
      - type: bind
        source: $TMP/podcasts
        target: /media/podcasts
        bind:
          create_host_path: false
      - $TMP/config:/config
  worker:
    volumes:
      - $TMP/data:/data
      - type: bind
        source: $TMP/podcasts
        target: /media/podcasts
        bind:
          create_host_path: false
      - $TMP/config:/config
EOF

echo "Building and starting Compose stack for auth smoke test..."
docker compose -f "$ROOT/docker-compose.yml" -f "$TMP/override.yml" --env-file "$TMP/.env" up -d --build

echo "Waiting for /ready..."
for _ in $(seq 1 60); do
  if curl -fs "http://127.0.0.1:18080/ready" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

code="$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:18080/" || true)"
if [[ "$code" != "401" ]]; then
  echo "FAIL: expected unauthenticated / to return 401, got $code"
  docker compose -f "$ROOT/docker-compose.yml" -f "$TMP/override.yml" --env-file "$TMP/.env" logs app || true
  exit 1
fi

auth_code="$(curl -s -o /dev/null -w "%{http_code}" -u smokeadmin:smokesecret "http://127.0.0.1:18080/" || true)"
if [[ "$auth_code" != "200" ]]; then
  echo "FAIL: expected authenticated / to return 200, got $auth_code"
  exit 1
fi

echo "PASS: Compose auth wiring enforces Basic Auth"
