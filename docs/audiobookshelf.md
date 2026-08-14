# Audiobookshelf Setup & Integration

`reeldock` is designed to run alongside [Audiobookshelf](https://www.audiobookshelf.org/) (ABS). It writes files to a directory that ABS monitors, can trigger a library scan when a job completes, and tracks when each audiobook appears in ABS (2.0.0).

## 1. Directory Alignment

Ensure your Audiobookshelf instance is pointed to the same physical storage folder that `reeldock` writes to.

* **Docker setup**: If both ABS and `reeldock` are run on the same Docker host, they should both mount the same host directory.
  * In `reeldock` `.env`:
    `HOST_PODCASTS_DIR=/mnt/podcasts`
  * In your Audiobookshelf Docker Compose config:
    ```yaml
    volumes:
      - /mnt/podcasts:/podcasts
    ```
  * In this example, you would configure your Audiobookshelf Library to monitor `/podcasts`.

---

## 2. Directory Structure Expectations

Audiobookshelf scans files based on directory groupings. By default, it expects a structure of **`LibraryRoot/PodcastTitle/Episode.m4b`**.

`reeldock` writes **`LibraryRoot/ChannelName/Title.m4b`** when you leave destination unset (no server default). Channel display name is preferred, then uploader. Pick **Library root** in the extension (or an explicit empty destination) to write at the media root instead.

`reeldock` automatically handles this:
1. When submitting a video, you choose or create a destination folder (e.g. `TechTalk`), or accept the channel folder default.
2. The background worker downloads the video, converts it, and writes it to `/media/podcasts/TechTalk/Video Title.m4b`.
3. In Audiobookshelf, `TechTalk` will appear as a Podcast or Audiobook series, and `Video Title.m4b` will appear as an episode/track.

---

## 3. Connect Audiobookshelf in Settings

Prefer configuring ABS from **Settings → Audiobookshelf** (no need to copy a library ID from the ABS URL):

1. Enter the Audiobookshelf base URL (reachable from the ReelDock container).
2. Paste an API token (Settings → Users → API Tokens in ABS). Leave the field blank on later saves to keep the stored token.
3. Click **Test Connection** — ReelDock lists libraries by name (audiobook/`book` libraries first).
4. Pick a library from the dropdown. If a previously saved library disappeared from the server, ReelDock warns you and does **not** silently switch.
5. Optionally enable **Default ABS scan after success**, then **Save**.

You can still set the same values via environment / `.env` if you prefer infrastructure config:

```env
ABS_SCAN_AFTER_SUCCESS=true
ABS_BASE_URL=http://audiobookshelf:13378
ABS_API_TOKEN=your-long-api-token-string
ABS_LIBRARY_ID=bc7f781a-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

After a successful import with scan enabled, Job Detail shows indexing status (`Waiting…` → `Added to Audiobookshelf`) and an Open in Audiobookshelf link when the item is matched by relative path.

---

## 4. Future channel subscriptions

Channel/playlist **subscriptions** (automatic polling of new uploads) are not implemented yet. When they ship, ReelDock will discover new videos with **yt-dlp** and dedupe against the existing **ImportedVideo** ledger — no YouTube Data API key will be required.
