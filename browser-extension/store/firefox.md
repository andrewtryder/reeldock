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
to queue that video. Recent imports, cancel, and retry stay in the popup.
Your server converts it to an `.m4b` audiobook.

Requires **Firefox 140** or newer (built-in data-collection consent). Configure
the ReelDock origin and extension API token in Options. Localhost may use
HTTP; any other host must use HTTPS.

Desktop Firefox only for this initial store release. Keep
`browser_specific_settings.gecko_android` omitted — AMO treats that as
not Android-compatible, so you do not need to mark Android incompatible
in the listing unless AMO later asks. `web-ext lint` may warn that
data-collection consent on Android starts at 142 while desktop min is
140; that warning is expected and non-blocking.

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

Permanent gecko id: `@reeldock.andrewtryder`

AMO checks uniqueness on first signing and treats the id as stable after
listing. Do not change it after the first AMO submission.

## Reviewer setup

See [reviewer-notes.md](reviewer-notes.md).
