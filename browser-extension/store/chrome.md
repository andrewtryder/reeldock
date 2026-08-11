# Chrome Web Store listing (draft)

Do not claim the extension is already published. Copy these fields into the
Chrome Developer Dashboard when submitting.

**Privacy policy URL** (after this file is on `main`):

`https://github.com/andrewtryder/reeldock/blob/main/browser-extension/PRIVACY.md`

**Support URL:** `https://github.com/andrewtryder/reeldock/issues`

**Homepage:** `https://github.com/andrewtryder/reeldock`

## Name

ReelDock

## Short summary

Queue the YouTube video you are watching into your own ReelDock server.

## Detailed description

ReelDock is a browser helper for people who already run a self-hosted ReelDock
instance. Open a YouTube watch or Shorts page, click the extension, and queue
that video for conversion to an `.m4b` audiobook on your server.

The extension talks only to the ReelDock URL you configure (localhost or
HTTPS). It does not use a ReelDock cloud account. You must enable the
extension API on your server and paste the matching API token into Options.

Job status and progress appear in the popup while your server processes the
import. You can also open the job page on your ReelDock instance.

This extension is not affiliated with YouTube or Google.

## Single-purpose statement

Queue the current YouTube video into the user’s self-hosted ReelDock server.

## Remote code

**No.** All JavaScript the extension executes is packaged with the extension.
Communicating with the user’s ReelDock server for JSON/WebSocket job data is
not remote code.

## Permission justifications

| Permission | Why |
|------------|-----|
| `activeTab` | Read the active tab URL after the user opens the popup, so we can queue that YouTube video. |
| `storage` | Save the server URL, API token, and import defaults on the device. |
| `contextMenus` | “Send to ReelDock” on YouTube pages and links. |
| `notifications` | Confirm queue success or show a failure after a context-menu or popup queue. |
| Host: `http(s)://localhost/*`, `127.0.0.1`, `[::1]` | Default local ReelDock API, WebSocket, and job page. |
| Optional host: `https://*/*` | Requested only for the **specific** HTTPS origin the user saves in Options (not granted eagerly). |

YouTube host permissions are **not** declared. The extension does not inject
scripts into YouTube and does not fetch YouTube as a host.

## Data handling (dashboard)

Match the live Chrome Developer Dashboard categories to:

- browsing / current-page URL information (the YouTube URL the user queues)
- authentication information (the ReelDock extension API token)

Do not invent extra data-use categories. There is no analytics, advertising,
or developer-operated collection.

## Reviewer setup

See [reviewer-notes.md](reviewer-notes.md). Reviewers need a local ReelDock
server and a test token; there is no SaaS login.
