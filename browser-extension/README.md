# Browser extension for ReelDock

A Manifest V3 extension that queues the YouTube video open in your browser
into **your** ReelDock server. It works in Chrome and in Firefox 140+.

Nothing is published to the Chrome Web Store or Firefox AMO yet. Use an
unpacked build or the GitHub release zips for sideload / review.

Privacy policy: [PRIVACY.md](PRIVACY.md). Store listing drafts:
[store/chrome.md](store/chrome.md), [store/firefox.md](store/firefox.md).

## Features

- **Popup** on YouTube watch / Shorts pages: destination, quality, embed /
  SponsorBlock, and **Create Audiobook**. The form stays visible after queueing.
- **Recent imports** (last 5 of 10 stored) with View / Cancel / Retry. The
  background service worker owns API calls, WebSockets, and the ledger so
  closing the popup does not lose progress.
- **Notifications**: context-menu queue confirmation, then one success or
  failure notification. Click a notification to open the job. Popup queue does
  not fire a “Queued” toast.
- **Context menu** “Send to ReelDock” uses your saved defaults.
- **Options** for pairing (origin + one-use code), destination, quality, SponsorBlock,
  embed flags, optional Audiobookshelf scan, and **Open ReelDock after queueing**
  (off by default). Advanced/legacy paste-token remains for existing installs.
  Pairing is the 2.0.0 onboarding path.

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

## 1. Enable the extension API and pair a browser

In ReelDock **Settings → Browser Extension**, enable the API (or set
`EXTENSION_API_ENABLED=true`), set the advertised HTTPS origin if needed, and
click **Generate pairing code**. In Options, paste the origin and `RDK-XXXX-XXXX`
code. The code is one-use and is not stored.

Legacy shared token (optional, not created in the UI):

```ini
EXTENSION_API_ENABLED=true
EXTENSION_API_TOKEN=generate-with-openssl-rand-hex-32
```

Store-installed browsers need a browser-trusted HTTPS origin they can reach.
Loopback HTTP is for unpacked local testing only.

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

- **ReelDock origin** + **pairing code** from Settings (recommended)
- **Advanced / legacy token** only if you still use `EXTENSION_API_TOKEN`
- **Default destination**: server default (channel folder), library root, or a folder from your ReelDock library
- **Default quality**: Standard / High / Best
- **Embed metadata / thumbnail / chapters** and optional SponsorBlock
- **Trigger Audiobookshelf scan after success**: shown only when ABS is configured
- **Open ReelDock after queueing**: off by default
- **Allow re-import by default**: secondary; sends `allow_reimport=true` unless
  overridden in the popup

Use **Test connection** to verify the server is reachable and the token is
accepted. Non-localhost HTTPS URLs prompt for optional host permission once.

## Endpoints used by the extension

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/extension/status` | Health / `api_version` / `supports` |
| GET | `/api/extension/destinations` | Library folders (no host paths) |
| POST | `/api/extension/queue` | Queue a video (`quality`, SponsorBlock, embeds) |
| GET | `/api/extension/jobs/{id}` | Slim job status for the recent-jobs ledger |
| POST | `/api/extension/jobs/{id}/cancel` | Cancel queued / running jobs |
| POST | `/api/extension/jobs/{id}/retry` | Retry failed / cancelled jobs |
| WS | `/api/ws/jobs/{job_id}` | Progress while the background worker is alive |

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
