# Browser extension for reeldock

An unpacked WebExtension (Manifest V3) that lets you queue the YouTube video open in
your browser into a local `reeldock` instance. Works with Chrome and Firefox
development builds. Nothing is published to a browser store.

## Privacy

Configuration (server URL, API token, embed defaults) is stored only in
`chrome.storage.local` / Firefox local extension storage on your device. The
extension does not upload settings to any third party. The API token is sent
only to the ReelDock base URL you configure.

## Features

- **Popup** on YouTube video pages with a one-click "Queue video" button.
- **Context menu** "Send to reeldock" on YouTube pages and links.
- **Options page** to configure the server URL, API token, default destination
  folder, embed flags, the "trigger Audiobookshelf scan" toggle, and a default
  "allow re-import" toggle.
- **Localhost by default**; for a LAN hostname/IP, the options page requests
  optional host permission when you save.

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
npm run build        # builds both Chrome and Firefox into dist/
```

**Chrome**

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select `browser-extension/dist/chrome/`

**Firefox**

1. Open `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on**
3. Select `browser-extension/dist/firefox/manifest.json`

> Temporary add-ons in Firefox are removed on restart. For a persistent
> install, use `web-ext sign` with a Mozilla developer account.

## 3. Configure the extension

Click the extension icon → Options (or the gear icon on the popup) and set:

- **Server URL**: e.g. `http://127.0.0.1:8080` or `http://192.168.1.50:8080`
- **API token**: must match `EXTENSION_API_TOKEN`
- **Default destination folder**: subfolder under `OUTPUT_ROOT` (optional)
- **Embed metadata / thumbnail / chapters**: passed through to the job
- **Trigger Audiobookshelf scan after success**: passed through to the job
- **Allow re-import by default**: sends `allow_reimport=true` for extension
  queue requests unless overridden in the popup

Use **Test connection** to verify the server is reachable and the token is
accepted. Non-localhost URLs prompt for optional host permission once.

## Endpoints used by the extension

| Method | Path                      | Purpose                                  |
|--------|---------------------------|------------------------------------------|
| GET    | `/api/extension/status`   | Health / capability check (options page) |
| POST   | `/api/extension/queue`    | Queue a video; returns `job_id` + `job_url` |

Both endpoints return `404` when `EXTENSION_API_ENABLED=false`, and `401` when
the token is missing/wrong. See [docs/configuration.md](../docs/configuration.md).

## Security notes

- Treat the extension API token like any other secret. It lives in local extension
  storage and is sent as `Authorization: Bearer …` or `X-REELDOCK-Token`.
- Default host permissions cover YouTube plus `localhost` / `127.0.0.1`. Other
  origins use optional host permissions requested when you save a non-localhost
  server URL.
- The backend re-validates the YouTube URL with `yt-dlp` server-side.
- WebSocket job updates use the same token via `?token=` (custom headers are
  unreliable for WebSockets from extensions).

## Development

```bash
npm run lint          # syntax-check JS + verify manifest entry points exist
npm run build:chrome  # build only Chrome
npm run build:firefox # build only Firefox
```

## Known limitations

- The extension queues **single** YouTube video URLs (`/watch?v=…`, `/shorts/…`,
  `youtu.be/<id>`). Playlist/channel batch selection is available in the web UI
  when `ALLOW_PLAYLISTS` / `ALLOW_CHANNELS` are enabled.
- Job progress is not surfaced in the extension; open the returned `job_url`
  in the web UI to track it.
