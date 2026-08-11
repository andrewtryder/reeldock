#!/usr/bin/env bash
# ============================================================
# compose-release-smoke.sh — real worker + ffmpeg M4B gate (#118)
# ============================================================
# Builds the shipping Compose image, enables RELEASE_SMOKE_FIXTURE,
# and asserts a valid .m4b without live YouTube.
#
# Requires Docker + ffmpeg/ffprobe on the host for assertions.
# Skips cleanly when Docker is unavailable.
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SMOKE_URL="https://www.youtube.com/watch?v=reeldockSmoke01"
SMOKE_TITLE="ReelDock Release Smoke"
SMOKE_VIDEO_ID="reeldockSmoke01"
PORT="${RELEASE_SMOKE_PORT:-18081}"
BASE="http://127.0.0.1:${PORT}"

if ! command -v docker >/dev/null 2>&1; then
  echo "SKIP: docker not available"
  exit 0
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "SKIP: docker compose not available"
  exit 0
fi
if ! command -v ffprobe >/dev/null 2>&1; then
  echo "FAIL: ffprobe required on host for release-smoke assertions" >&2
  exit 1
fi

FIXTURE_DIR="$ROOT/tests/fixtures/release_smoke"
if [[ ! -f "$FIXTURE_DIR/source.m4a" ]]; then
  echo "FAIL: missing fixture $FIXTURE_DIR/source.m4a" >&2
  exit 1
fi

TMP="$(mktemp -d)"
COMPOSE=(docker compose -f "$ROOT/docker-compose.yml" -f "$TMP/override.yml" --env-file "$TMP/.env")
cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

mkdir -p "$TMP/data" "$TMP/config" "$TMP/podcasts" "$TMP/data/work" "$TMP/data/logs" "$TMP/data/config"

cat >"$TMP/.env" <<EOF
HOST_AUDIOBOOKS_DIR=$TMP/podcasts
OUTPUT_ROOT=/media/podcasts
AUTH_ENABLED=false
EXTENSION_API_ENABLED=false
RELEASE_SMOKE_FIXTURE=true
RELEASE_SMOKE_FIXTURE_DIR=/fixtures/release_smoke
RELEASE_SMOKE_FAIL_ONCE=false
ABS_SCAN_AFTER_SUCCESS=false
COLLISION_MODE=append_id
EOF

cat >"$TMP/override.yml" <<EOF
services:
  app:
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

echo "==> Building and starting Compose stack for release-smoke..."
"${COMPOSE[@]}" up -d --build

echo "==> Waiting for /ready..."
for _ in $(seq 1 90); do
  if curl -fsS "$BASE/ready" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS "$BASE/ready" >/dev/null

wait_job() {
  local job_id="$1"
  local want="$2"
  local i st
  for i in $(seq 1 120); do
    st="$(curl -fsS "$BASE/api/jobs/$job_id" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status",""))')"
    echo "    job $job_id status=$st"
    if [[ "$st" == "$want" ]]; then
      return 0
    fi
    if [[ "$st" == "failed" || "$st" == "cancelled" ]] && [[ "$want" != "failed" ]]; then
      echo "FAIL: job $job_id ended as $st (wanted $want)" >&2
      curl -fsS "$BASE/api/jobs/$job_id" || true
      "${COMPOSE[@]}" logs worker app 2>&1 | tail -80 || true
      return 1
    fi
    if [[ "$st" == "succeeded" && "$want" == "failed" ]]; then
      echo "FAIL: job $job_id succeeded but expected failure" >&2
      return 1
    fi
    sleep 2
  done
  echo "FAIL: timed out waiting for job $job_id -> $want (last=$st)" >&2
  return 1
}

assert_m4b() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "FAIL: missing output $path" >&2
    ls -la "$(dirname "$path")" >&2 || true
    return 1
  fi
  if find "$TMP/podcasts" -name '*.partial' | grep -q .; then
    echo "FAIL: leftover .partial files under $TMP/podcasts" >&2
    find "$TMP/podcasts" -name '*.partial' >&2
    return 1
  fi
  local duration
  duration="$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$path")"
  python3 - "$duration" <<'PY'
import sys
d = float(sys.argv[1])
if d < 1.0:
    raise SystemExit(f"duration too short: {d}")
print(f"    ffprobe duration={d:.3f}s OK")
PY
  local fmt
  fmt="$(ffprobe -v error -show_entries format=format_name -of default=noprint_wrappers=1:nokey=1 "$path")"
  echo "    ffprobe format=$fmt"
  case "$fmt" in
    *mp4*|*ipod*|*mov*) ;;
    *)
      echo "FAIL: unexpected container format '$fmt'" >&2
      return 1
      ;;
  esac
}

create_job() {
  local title="$1"
  local folder="${2:-}"
  local collision="${3:-append_id}"
  local loc
  loc="$(curl -fsS -D - -o /dev/null -X POST "$BASE/jobs/create" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode "url=$SMOKE_URL" \
    --data-urlencode "video_id=$SMOKE_VIDEO_ID" \
    --data-urlencode "source_title=$title" \
    --data-urlencode "output_title=$title" \
    --data-urlencode "uploader=ReelDock CI" \
    --data-urlencode "uploader_id=reeldock_ci" \
    --data-urlencode "duration=3" \
    --data-urlencode "destination_folder=$folder" \
    --data-urlencode "collision_mode=$collision" \
    --data-urlencode "embed_metadata=true" \
    --data-urlencode "embed_thumbnail=true" \
    --data-urlencode "embed_chapters=true" \
    --data-urlencode "allow_reimport=true" \
    | tr -d '\r' | awk -F': ' 'tolower($1)=="location"{print $2; exit}')"
  if [[ -z "$loc" ]]; then
    echo "FAIL: no Location header from /jobs/create" >&2
    return 1
  fi
  basename "$loc"
}

# ── Happy path ──────────────────────────────────────────────────────────────
echo "==> Happy path"
JOB="$(create_job "$SMOKE_TITLE" "")"
echo "    created job $JOB"
wait_job "$JOB" succeeded
assert_m4b "$TMP/podcasts/${SMOKE_TITLE}.m4b"
echo "PASS: happy path"

# ── Collision: skip ─────────────────────────────────────────────────────────
echo "==> Collision skip"
FOLDER="SmokeSkip"
mkdir -p "$TMP/podcasts/$FOLDER"
printf 'seed' >"$TMP/podcasts/$FOLDER/Collision Skip.m4b"
JOB="$(create_job "Collision Skip" "$FOLDER" "skip")"
wait_job "$JOB" succeeded
# Seed must remain tiny (skip did not overwrite with real audio)
SIZE="$(wc -c <"$TMP/podcasts/$FOLDER/Collision Skip.m4b" | tr -d ' ')"
if [[ "$SIZE" -gt 100 ]]; then
  echo "FAIL: skip collision replaced seed file (size=$SIZE)" >&2
  exit 1
fi
echo "PASS: collision skip"

# ── Collision: overwrite ────────────────────────────────────────────────────
echo "==> Collision overwrite"
FOLDER="SmokeOverwrite"
mkdir -p "$TMP/podcasts/$FOLDER"
printf 'seed-overwrite' >"$TMP/podcasts/$FOLDER/Collision Overwrite.m4b"
JOB="$(create_job "Collision Overwrite" "$FOLDER" "overwrite")"
wait_job "$JOB" succeeded
assert_m4b "$TMP/podcasts/$FOLDER/Collision Overwrite.m4b"
echo "PASS: collision overwrite"

# ── Collision: append_id ────────────────────────────────────────────────────
echo "==> Collision append_id"
FOLDER="SmokeAppend"
mkdir -p "$TMP/podcasts/$FOLDER"
printf 'seed-append' >"$TMP/podcasts/$FOLDER/Collision Append.m4b"
JOB="$(create_job "Collision Append" "$FOLDER" "append_id")"
wait_job "$JOB" succeeded
assert_m4b "$TMP/podcasts/$FOLDER/Collision Append [${SMOKE_VIDEO_ID}].m4b"
echo "PASS: collision append_id"

# ── Retry after intentional first-attempt failure ───────────────────────────
echo "==> Retry after fail-once"
"${COMPOSE[@]}" stop worker >/dev/null
# Flip fail-once on for worker only via env file + recreate
cat >"$TMP/.env" <<EOF
HOST_AUDIOBOOKS_DIR=$TMP/podcasts
OUTPUT_ROOT=/media/podcasts
AUTH_ENABLED=false
EXTENSION_API_ENABLED=false
RELEASE_SMOKE_FIXTURE=true
RELEASE_SMOKE_FIXTURE_DIR=/fixtures/release_smoke
RELEASE_SMOKE_FAIL_ONCE=true
ABS_SCAN_AFTER_SUCCESS=false
COLLISION_MODE=append_id
EOF
cat >"$TMP/override.yml" <<EOF
services:
  app:
    ports:
      - "127.0.0.1:${PORT}:8080"
    environment:
      RELEASE_SMOKE_FIXTURE: "true"
      RELEASE_SMOKE_FIXTURE_DIR: /fixtures/release_smoke
      RELEASE_SMOKE_FAIL_ONCE: "true"
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
    environment:
      RELEASE_SMOKE_FIXTURE: "true"
      RELEASE_SMOKE_FIXTURE_DIR: /fixtures/release_smoke
      RELEASE_SMOKE_FAIL_ONCE: "true"
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
"${COMPOSE[@]}" up -d --force-recreate app worker >/dev/null
for _ in $(seq 1 60); do
  curl -fsS "$BASE/ready" >/dev/null 2>&1 && break
  sleep 2
done

JOB="$(create_job "Retry Smoke" "SmokeRetry" "overwrite")"
wait_job "$JOB" failed

# Turn off fail-once and retry
cat >"$TMP/.env" <<EOF
HOST_AUDIOBOOKS_DIR=$TMP/podcasts
OUTPUT_ROOT=/media/podcasts
AUTH_ENABLED=false
EXTENSION_API_ENABLED=false
RELEASE_SMOKE_FIXTURE=true
RELEASE_SMOKE_FIXTURE_DIR=/fixtures/release_smoke
RELEASE_SMOKE_FAIL_ONCE=false
ABS_SCAN_AFTER_SUCCESS=false
COLLISION_MODE=append_id
EOF
cat >"$TMP/override.yml" <<EOF
services:
  app:
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
"${COMPOSE[@]}" up -d --force-recreate app worker >/dev/null
for _ in $(seq 1 60); do
  curl -fsS "$BASE/ready" >/dev/null 2>&1 && break
  sleep 2
done

curl -fsS -X POST "$BASE/api/jobs/$JOB/retry" >/dev/null
wait_job "$JOB" succeeded
assert_m4b "$TMP/podcasts/SmokeRetry/Retry Smoke.m4b"
echo "PASS: retry after fail-once"

echo "PASS: compose release-smoke"
