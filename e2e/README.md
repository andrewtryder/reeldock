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

YouTube watch pages for `reeldockSmoke*` are fulfilled locally via
`page.route`. The unpacked Chrome extension is loaded with
`--disable-extensions-except` / `--load-extension` on a persistent
Chromium context.

Headless MV3 extension load is unreliable on Playwright’s pinned Chromium,
so the compose script runs **headed** Chromium. In CI (no `DISPLAY`) it
wraps that in `xvfb-run`. No user Chrome profile is used.

### What is not covered in the browser

Optional-host permission prompts (non-loopback HTTPS, custom CA / dialogs)
are **skipped** here. Origin-permission rules are covered by
`browser-extension` JS unit tests (`isLocalServerUrl`, HTTPS-required).

Firefox has no second Playwright suite. Keep `npm --prefix browser-extension run lint`,
`web-ext`, package checks, and the shared JS tests.

## Manual matrix

If a desktop browser is available, walk A–G from the Extension 2.0 brief
(localhost options, Basic+token coexistence, queue, reopen, notifications,
bad token, cancel, retry). Optional-host HTTPS remains manual.
