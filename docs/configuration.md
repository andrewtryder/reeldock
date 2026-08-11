# Configuration Reference

`reeldock` supports flexible configuration using environment variables, a YAML configuration file, and the Web UI.

## Configuration Precedence

When the application loads its settings, it resolves them in the following order of precedence (highest priority first):

1. **Environment Variables**: Defined in your `.env` file, Docker, or host shell environment. These **lock** the corresponding field in the Web UI.
2. **YAML Config File**: Configuration loaded from `/config/config.yaml`. These also **lock** their fields when present.
3. **Database Overrides**: Settings saved via the Web UI to the `app_settings` table.
4. **Application Defaults**: Built-in defaults.

If a setting is provided via environment or YAML, the Web UI shows it as read-only with a badge indicating the source.

---

## Web UI Editable Settings

The Settings page is driven by a configuration registry. The following settings can be edited in the UI when not locked by environment or YAML:

| Setting | Env Variable | Description |
| :--- | :--- | :--- |
| Output root | `OUTPUT_ROOT` | Base folder for finished audiobooks |
| Default destination folder | `DEFAULT_DESTINATION_FOLDER` | Default subdirectory under output root |
| Cookies file | `COOKIES_FILE` | Absolute path to a Netscape cookies file for yt-dlp |
| Collision mode | `COLLISION_MODE` | `skip`, `overwrite`, `append_id`, or `append_counter` |
| Allowed domains | `ALLOWED_DOMAINS` | Comma-separated permitted hostnames |
| yt-dlp extra args | `YTDLP_EXTRA_ARGS` | Space-separated extra yt-dlp arguments |
| ffmpeg extra args | `FFMPEG_EXTRA_ARGS` | Space-separated extra ffmpeg arguments |
| Filename template | `FILENAME_TEMPLATE` | Output filename template |
| Job timeout | `JOB_TIMEOUT_SECONDS` | Maximum job runtime in seconds |
| Retry count | `RETRY_MAX` | Maximum retry attempts |
| Retry intervals | `RETRY_INTERVAL_SECONDS` | Comma-separated wait times between retries |
| Cleanup temp on success | `CLEANUP_TEMP_ON_SUCCESS` | Remove temp files after success |
| Cleanup temp on failure | `CLEANUP_TEMP_ON_FAILURE` | Remove temp files after failure |
| Dry run | `DRY_RUN` | Simulate imports without downloading |
| Allow playlist URLs | `ALLOW_PLAYLISTS` | Accept playlist URLs and enumerate videos for batch selection in the UI. |
| Allow channel URLs | `ALLOW_CHANNELS` | Accept channel URLs and enumerate videos for batch selection in the UI. |
| Max playlist entries | `MAX_PLAYLIST_ENTRIES` | Maximum videos enumerated or queued from one playlist/channel. |
| Skip SponsorBlock sponsors | `SPONSORBLOCK_REMOVE` | Remove sponsor segments during download (`--sponsorblock-remove sponsor`). |
| Normalize loudness | `LOUDNESS_NORMALIZE` | Apply ffmpeg loudnorm (EBU R128) during conversion. |
| Loudness target | `LOUDNESS_TARGET_LUFS` | Integrated loudness target (typically `-16`). |
| Loudness bitrate | `LOUDNESS_AUDIO_BITRATE` | AAC bitrate used when loudness re-encodes. |
| ABS scan after success | `ABS_SCAN_AFTER_SUCCESS` | Trigger Audiobookshelf scan after import |

**Not editable in UI (secrets / infrastructure):** `AUTH_PASSWORD`, `ABS_API_TOKEN`, `EXTENSION_API_TOKEN`, `REDIS_URL`, `DATABASE_URL`, and binary paths.

---

## Environment Variables Reference

| Variable | Default | Description |
| :--- | :--- | :--- |
| **Application & Auth** | | |
| `APP_HOST` | `0.0.0.0` | Bind address for the web server. |
| `APP_PORT` | `8080` | Bind port for the web server. |
| `AUTH_ENABLED` | `false` | Enable HTTP Basic Authentication. Set to `true` if exposing to the LAN/WAN. |
| `AUTH_USERNAME` | — | Username for Basic Authentication. |
| `AUTH_PASSWORD` | — | Password for Basic Authentication. |
| `EXTENSION_API_ENABLED` | `false` | Enable `/api/extension/*` for the browser extension. |
| `EXTENSION_API_TOKEN` | — | Required when extension API is enabled; app refuses to start if missing. |
| **Infrastructure** | | |
| `REDIS_URL` | `redis://redis:6379/0` | Connection string for Redis queue. |
| `DATABASE_URL` | `sqlite+aiosqlite:////data/app.db` | SQLAlchemy connection string for SQLite database. |
| **Paths & Volumes** | | |
| `HOST_AUDIOBOOKS_DIR` | `/mnt/podcasts` | Host path for audiobook media (Docker Compose). Legacy alias: `HOST_PODCASTS_DIR`. |
| `OUTPUT_ROOT` | `/media/podcasts` | Container path where finished audiobooks are written; Compose also uses this as the bind-mount target. Legacy mount-target alias: `CONTAINER_PODCASTS_DIR`. |
| `WORK_DIR` | `/data/work` | Workspace for downloading and processing audio. |
| `ARCHIVE_FILE` | `/data/config/youtube-archive.txt` | `yt-dlp` archive file used as a secondary duplicate guard at download time. |
| `COOKIES_FILE` | — | Absolute path to a Netscape cookies file passed to yt-dlp via `--cookies`. |
| **Download & Processing** | | |
| `ALLOW_PLAYLISTS` | `false` | Accept playlist URLs and enumerate entries for batch import in the UI. |
| `ALLOW_CHANNELS` | `false` | Accept channel URLs and enumerate entries for batch import in the UI. |
| `MAX_PLAYLIST_ENTRIES` | `100` | Maximum videos enumerated or queued from one playlist/channel submission. |
| `SPONSORBLOCK_REMOVE` | `false` | When true, yt-dlp removes sponsor segments (`--sponsorblock-remove sponsor`). |
| `LOUDNESS_NORMALIZE` | `false` | Apply ffmpeg loudnorm during conversion (re-encodes audio). |
| `LOUDNESS_TARGET_LUFS` | `-16` | Loudnorm integrated loudness target. |
| `LOUDNESS_AUDIO_BITRATE` | `192k` | AAC bitrate when loudness normalization re-encodes. |
| `DEFAULT_DESTINATION_FOLDER` | — | Default selected subdirectory under `OUTPUT_ROOT`. |
| `YTDLP_BIN` | `yt-dlp` | Command path to `yt-dlp`. |
| `FFMPEG_BIN` | `ffmpeg` | Command path to `ffmpeg`. |
| `FFPROBE_BIN` | `ffprobe` | Command path to `ffprobe`. |
| `YTDLP_AUDIO_QUALITY` | — | Quality arg for `yt-dlp` audio extraction (user-facing quality control). |
| `YTDLP_EXTRA_ARGS` | — | Space-separated extra arguments passed to `yt-dlp`. |
| `FFMPEG_EXTRA_ARGS` | — | Extra arguments passed to `ffmpeg`. |
| `FILENAME_TEMPLATE` | `{title}.m4b` | Output filename template (final extension is always `.m4b`). |
| `ALLOWED_DOMAINS` | YouTube hostnames | Comma-separated permitted import domains. |
| **Job Management** | | |
| `JOB_TIMEOUT_SECONDS` | `10800` | Job timeout duration in seconds (3 hours). |
| `RETRY_MAX` | `3` | Maximum download retry attempts. |
| `RETRY_INTERVAL_SECONDS` | `60,300,900` | Intervals between retries. |
| `CLEANUP_TEMP_ON_SUCCESS` | `true` | Clean up temporary files in `WORK_DIR` on job success. |
| `CLEANUP_TEMP_ON_FAILURE` | `false` | Clean up temporary files on job failure (useful for debugging). |
| `COLLISION_MODE` | `append_id` | Strategy when output file exists (`skip` \| `overwrite` \| `append_id` \| `append_counter`). |
| **Audiobookshelf Integration** | | |
| `ABS_BASE_URL` | — | Audiobookshelf server URL (e.g. `http://audiobookshelf:13378`). |
| `ABS_API_TOKEN` | — | Audiobookshelf API token. |
| `ABS_LIBRARY_ID` | — | Audiobookshelf Library ID to trigger a scan for. |
| `ABS_SCAN_AFTER_SUCCESS` | `false` | Enable automatic library scan requests after job success. |
| **Development** | | |
| `DRY_RUN` | `false` | If `true`, simulate commands instead of downloading or converting. |

---

## YAML Configuration Example

You can configure settings via a configuration file located at `/config/config.yaml`.

```yaml
app:
  host: "0.0.0.0"
  port: 8080
  auth_enabled: false

paths:
  work_dir: "/data/work"
  archive_file: "/data/config/youtube-archive.txt"
  output_root: "/media/podcasts"

download:
  allow_playlists: false
  allow_channels: false
  filename_template: "{title}.m4b"
  cookies_file: "/data/config/cookies.txt"
  allowed_domains:
    - youtube.com
    - youtu.be

jobs:
  timeout_seconds: 10800
  retry_max: 3
  retry_intervals_seconds: [60, 300, 900]

audiobookshelf:
  base_url: "http://audiobookshelf:13378"
  api_token: "your-token"
  library_id: "your-library-id"
  scan_after_success: true
```
