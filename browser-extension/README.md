# Browser extension for ReelDock

A Manifest V3 extension that queues the YouTube video open in your browser
into **your** ReelDock server. It works in Chrome and in Firefox 140+.

Nothing is published to the Chrome Web Store or Firefox AMO yet. Use an
unpacked build or the GitHub release zips for sideload / review.

Privacy policy: [PRIVACY.md](PRIVACY.md). Store listing drafts:
[store/chrome.md](store/chrome.md), [store/firefox.md](store/firefox.md).

## Features

- **Popup** on YouTube watch / Shorts pages with **Queue video**.
- **Job status** in the popup (progress, Finalize / Done) via a WebSocket to
  your ReelDock server. The job page on the server may also open.
- **Context menu** “Send to ReelDock” on YouTube pages and links.
- **Options** for server URL, API token, destination folder, embed flags,
  Audiobookshelf scan, and allow re-import.

## Server URL rules

- `http://localhost`, `http://127.0.0.1`, and `http://[::1]` (any port) are
  allowed.
- Any other host must be `https://…`. LAN HTTP is rejected; it is not upgraded
  to HTTPS.
- The extension stores the normalized origin only (no path, query, fragment,
  or embedded credentials).

Localhost / loopback origins are covered by required host permissions.
A non-loopback HTTPS origin is requested **only when you save** that specific
server in Options (`https://your-host/*`), not as a blanket grant.

## 1. Enable the extension API on the backend

Set these in the backend `.env` (see `.env.example`):

```ini
EXTENSION_API_ENABLED=true
EXTENSION_API_TOKEN=generate-with-openssl-rand-hex-32
```

`EXTENSION_API_TOKEN` is **required** when the API is enabled (the app refuses
to start without it). Recreate containers after changing `.env`:

```bash
docker compose up -d --force-recreate
```

Verify with:

```bash
curl -H "Authorization: Bearer $EXTENSION_API_TOKEN" \
  http://127.0.0.1:8080/api/extension/status
```

## 2. Build and load the extension

Requires Node.js 18+.

```bash
cd browser-extension
npm ci
npm run build        # builds both Chrome and Firefox into dist/
```

**Chrome**

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select `browser-extension/dist/chrome/`

**Firefox 140+**

1. Open `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on**
3. Select `browser-extension/dist/firefox/manifest.json`

Temporary add-ons in Firefox are removed on restart. Store listing is not
available yet.

## 3. Configure the extension

Click the extension icon → Options (or the gear icon on the popup) and set:

- **Server URL**: e.g. `http://127.0.0.1:8080` or `https://reeldock.example.com`
- **API token**: must match `EXTENSION_API_TOKEN`
- **Default destination folder**: subfolder under `OUTPUT_ROOT` (optional)
- **Embed metadata / thumbnail / chapters**: passed through to the job
- **Trigger Audiobookshelf scan after success**: passed through to the job
- **Allow re-import by default**: sends `allow_reimport=true` for extension
  queue requests unless overridden in the popup

Use **Test connection** to verify the server is reachable and the token is
accepted. Non-localhost HTTPS URLs prompt for optional host permission once.

## Endpoints used by the extension

| Method | Path                      | Purpose                                  |
|--------|---------------------------|------------------------------------------|
| GET    | `/api/extension/status`   | Health / capability check (options page) |
| POST   | `/api/extension/queue`    | Queue a video; returns `job_id` + `job_url` |
| WS     | `/api/ws/jobs/{job_id}`   | Job progress while the popup is open     |

HTTP endpoints return `404` when `EXTENSION_API_ENABLED=false`, and `401` when
the token is missing/wrong. See [docs/configuration.md](../docs/configuration.md).

## Security notes

- Treat the extension API token like any other secret. It lives in local
  extension storage and is sent as `Authorization: Bearer …` to your configured
  origin. Job WebSockets use the same token as `?token=` (custom headers are
  unreliable for WebSockets from extensions).
- Required host permissions cover loopback ReelDock only. Other origins use
  optional host permission for the saved HTTPS origin.
- The backend re-validates the YouTube URL with `yt-dlp` server-side.

## Development

```bash
npm run lint          # syntax, store-readiness, and URL tests
npm run test          # server URL validation tests
npm run lint:firefox  # web-ext lint on the Firefox build
npm run build:chrome  # build only Chrome
npm run build:firefox # build only Firefox
npm run package       # zip artifacts (not uploaded to any store)
```

## Known limitations

- The extension queues **single** YouTube video URLs (`/watch?v=…`, `/shorts/…`,
  `youtu.be/<id>`). Playlist/channel batch selection is available in the web UI
  when `ALLOW_PLAYLISTS` / `ALLOW_CHANNELS` are enabled.
- Firefox Android is not supported.
