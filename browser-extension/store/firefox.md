# Firefox AMO listing (draft)

Do not claim the extension is already listed. Copy these fields into AMO when
submitting.

**Privacy policy URL** (after this file is on `main`):

`https://github.com/andrewtryder/reeldock/blob/main/browser-extension/PRIVACY.md`

**Support:** `https://github.com/andrewtryder/reeldock/issues`

## Name

ReelDock

## Summary

Queue the YouTube video you are watching into your own ReelDock server.

## Description

ReelDock is a helper for a self-hosted ReelDock instance. On a YouTube watch
or Shorts page, use the toolbar popup or the “Send to ReelDock” context menu
to queue that video. Your server converts it to an `.m4b` audiobook.

Requires **Firefox 140** or newer (built-in data-collection consent). Configure
the ReelDock origin and extension API token in Options. Localhost may use
HTTP; any other host must use HTTPS.

Do not enable Firefox for Android on the AMO listing. The extension is
desktop-only; `gecko_android` is omitted on purpose.

The extension communicates only with the ReelDock server you configure. There
is no Mozilla- or developer-operated cloud relay.

Submitted JavaScript is the same readable source as in this repository (copied
into the package, not minified or transpiled). A separate generated-source
package should not be necessary.

## AMO data collection

Manifest `browser_specific_settings.gecko.data_collection_permissions.required`:

| Type | Why |
|------|-----|
| `browsingActivity` | The current or selected YouTube URL is sent to the user’s ReelDock server when they queue a video. |
| `authenticationInfo` | The extension API token is sent to that same server so the queue/status APIs can authorize the request. |

Do **not** declare `required: ["none"]`. No other Mozilla taxonomy types apply
to current behavior (no bookmarks, location, health, search, website content
scraping, or technical telemetry).

## Firefox ID

The packaged gecko id is `reeldock@local`. **Change this before the first AMO
submission if you want a different permanent ID** — AMO treats the id as
stable after listing.

## Reviewer setup

See [reviewer-notes.md](reviewer-notes.md).
