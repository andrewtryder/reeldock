# ReelDock end-to-end tests

Playwright suites against a Compose stack. They never hit live YouTube.

## Golden path (web UI)

`./scripts/compose-playwright-smoke.sh` starts Compose with
`AUTH_ENABLED=false` and `EXTENSION_API_ENABLED=false`, then runs
`npm --prefix e2e test` (`--project=chromium`).

## Browser extension

`./scripts/compose-extension-e2e.sh` builds `browser-extension/dist/chrome`,
starts Compose with **both** Basic Auth and the extension API enabled (host
`.env` is not inherited), and runs `--project=extension`.

YouTube watch pages for `rdSmoke*` are fulfilled locally via `page.route`.
The unpacked Chrome extension is loaded with `--disable-extensions-except` /
`--load-extension` on a persistent Chromium context.

Automated scenarios queue through the service worker (`action: "queue"`).
Opening `popup.html` as a tab does **not** activate `activeTab`, and
`chrome.action.openPopup()` is not reliable on Playwright’s pinned Chromium,
so this suite does **not** cover the real toolbar icon path.

Headless MV3 extension load is unreliable on Playwright’s pinned Chromium,
so the compose script runs **headed** Chromium. In CI (no `DISPLAY`) it
wraps that in `xvfb-run`. No user Chrome profile is used.

### What is not covered in the browser

Optional-host permission prompts (non-loopback HTTPS, custom CA / dialogs)
are **skipped** here. Origin-permission rules are covered by
`browser-extension` JS unit tests (`isLocalServerUrl`, HTTPS-required).

Firefox has no second Playwright suite. Keep `npm --prefix browser-extension run lint`,
`web-ext`, package checks, and the shared JS tests.

## Mandatory manual smoke (toolbar / activeTab)

E2E does not replace clicking the toolbar icon. Before merge, on a desktop
browser with the unpacked extension loaded:

1. Chrome: load `browser-extension/dist/chrome` unpacked.
2. Open a real YouTube watch page.
3. Click the **toolbar icon** (not a `popup.html` tab).
4. Confirm the current video title is detected and Create Audiobook queues.
5. Repeat in Firefox with `browser-extension/dist/firefox`.

## Manual matrix

If a desktop browser is available, walk A–G from the Extension 2.0 brief
(localhost options, Basic+token coexistence, queue, reopen, notifications,
bad token, cancel, retry). Optional-host HTTPS remains manual.
