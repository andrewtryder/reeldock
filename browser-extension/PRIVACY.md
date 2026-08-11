# ReelDock browser extension privacy policy

This policy describes the **browser extension** only. It applies to the
unpacked and packaged Chrome / Firefox builds shipped from this repository.

The extension is not published to a hosted ReelDock cloud. You configure it to
talk to **your own** ReelDock server.

## Data stored locally

The extension stores the following in browser extension local storage
(`chrome.storage.local` / Firefox equivalent) until you change it, clear site
or extension data, or remove the extension:

- ReelDock server URL (normalized origin)
- extension API authentication token
- default destination folder
- import defaults (embed metadata / thumbnail / chapters, allow re-import)
- Audiobookshelf scan toggle

These values stay on the device. They are not encrypted beyond whatever the
browser already applies to extension storage.

## Data transmitted

When you queue or import a video (popup **Queue video** or the YouTube context
menu), the extension sends **only to the ReelDock server URL you configured**:

- the selected / current YouTube video URL
- the import options you chose (destination, embed flags, re-import, ABS scan)
- the extension API authentication token (`Authorization: Bearer …` on HTTP;
  the same token as a WebSocket query parameter for job status)

The extension then receives job status and progress from that same configured
server.

The extension does **not** send this data to the ReelDock developer, to a
developer-operated relay, or to any analytics, advertising, or data-broker
service. There are no advertisements and no telemetry in the extension.

ReelDock does not operate a hosted cloud relay for the extension.

## Your server

You are responsible for the privacy and security of the ReelDock instance you
point the extension at. Non-loopback servers must use HTTPS so the token is
not sent over plaintext HTTP.

## Chrome Limited Use

ReelDock's use of information received from Chrome APIs adheres to the Chrome
Web Store User Data Policy, including the Limited Use requirements.

## Contact

Questions and issues: [github.com/andrewtryder/reeldock](https://github.com/andrewtryder/reeldock/issues).
