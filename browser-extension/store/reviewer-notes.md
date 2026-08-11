# Store reviewer notes

ReelDock does not operate a hosted SaaS for this extension. Reviewers do not
need developer-cloud credentials.

## Minimal reproducible flow

1. Run ReelDock locally (Docker Compose from the GitHub repository is enough).
2. In the server `.env`, set `EXTENSION_API_ENABLED=true` and
   `EXTENSION_API_TOKEN` to a test value you generate (do not use a production
   secret). Recreate the app container.
3. Confirm `GET http://127.0.0.1:8080/api/extension/status` with
   `Authorization: Bearer <token>` returns JSON.
4. Load the unpacked extension (`dist/chrome` or `dist/firefox`) or the
   submitted zip.
5. Open Options. Set server URL to `http://127.0.0.1:8080` and paste the same
   token. Save, then Test connection.
6. Open a public YouTube watch page (any video the reviewer is allowed to
   view).
7. Click the extension → **Queue video**, or use the page context menu
   **Send to ReelDock**.
8. The popup should show the current video title, Create Audiobook, and a
   Recent list. Progress continues if you close and reopen the popup. A job
   page opens only if **Open ReelDock after queueing** is enabled.

Non-loopback HTTP URLs must be rejected. An HTTPS LAN or hostname should
prompt for host permission for **that origin only** when saving Options.
