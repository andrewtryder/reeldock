# Troubleshooting Guide

This guide covers common issues and questions when running `reeldock`.

## 1. yt-dlp Extractor Errors

### Video Unavailable
```
ERROR: [youtube] CcYToxtmFHs: Video unavailable
```
* **Cause**: The video is private, age-restricted, region-blocked, or has been taken down.
* **Solution**: Ensure the video is publicly accessible. The application cannot bypass age gates or private video restrictions.

### Unable to Extract Uploader ID
```
ERROR: Unable to extract uploader id
```
* **Cause**: YouTube frequently updates their site layout, which can break older versions of `yt-dlp`.
* **Solution**: Update `yt-dlp` to the latest version. In Docker, run:
  ```bash
  docker compose pull
  docker compose up --build -d
  ```

---

## 2. ffmpeg Fallback Errors

### Tag Text Incompatible
```
Tag text incompatible with output codec id 'mp4a'...
```
* **Cause**: This happens when the download contains metadata streams that are not supported by the `.m4b` container format.
* **Solution**: No action is needed. The background worker automatically detects this failure and retries extraction using an audio-only command (omitting video/album art streams) to ensure the file is successfully created.

---

## 3. Permission Denied on NFS/SMB Shares

### Symptoms
Jobs fail during the final phase with a log message indicating `Permission denied` when trying to write to `/media/podcasts/...`

### Fix
1. Find the UID/GID of the user that owns the mounted share on your host:
   ```bash
   ls -lan /mnt/podcasts
   ```
2. Note the numeric owner ID (e.g. `1001`) and group ID (e.g. `1001`).
3. Add or uncomment the `PUID` and `PGID` settings in your `.env` file to match these values:
   ```env
   PUID=1001
   PGID=1001
   ```
4. Restart the Docker stack:
   ```bash
   docker compose down
   docker compose up -d
   ```

---

## 4. Files Not Appearing in Audiobookshelf

If downloads complete successfully in `reeldock` but do not show up in Audiobookshelf:
1. Verify directory alignment (see [Audiobookshelf Guide](audiobookshelf.md)).
2. Make sure the files are inside a subfolder of your Audiobookshelf library directory (e.g. `/media/podcasts/ChannelName/Title.m4b`). ABS requires files to be at least one level deep to detect them.
3. Trigger a manual library scan in the Audiobookshelf UI (**Settings** -> **Libraries** -> **Scan**).
4. Configure [API Integration](audiobookshelf.md) to trigger scans automatically.

---

## 5. Duplicate Video Rejection

### Symptoms
Queueing a URL fails immediately with a `409` response (or UI error) indicating the video has already been imported.

### Cause
The app keeps a database ledger (`imported_videos`) of successfully imported video IDs and rejects duplicate imports early. In-flight imports take a short-lived claim so two jobs cannot process the same video at once. Failed and cancelled jobs do not write ledger rows and release their claim.

`youtube-archive.txt` is **not** used for duplicate detection. ReelDock no longer passes `--download-archive` to yt-dlp. An ID that exists only in a leftover archive file does not block a new import.

File commit and the SQLite ledger are not one atomic transaction. If the database write fails after the `.m4b` is in the library, the job is not marked succeeded; retry uses the configured collision mode instead of blindly writing a second file.

### Fix
* **Option A: Enable Re-import for This Job**: In the web import form, check **Allow re-import (overwrite duplicate guard)**, or send `allow_reimport=true` to the API.
* **Option B: Remove the ledger row**: If you intentionally need a re-import, delete the video ID from `imported_videos` (or use allow-reimport). Do not edit `youtube-archive.txt` for this — it is unused.

---

## 6. Settings, pairing, and encrypted secrets

### Encrypted settings will not load
* **Cause**: UI secrets are encrypted with `/config/.reeldock-settings.key` (or `REELDOCK_SETTINGS_KEY`). A new key cannot decrypt an old database.
* **Solution**: Restore the original key file from backup. ReelDock will not mint a replacement key when ciphertext already exists.

### Pairing code rejected
* Codes expire after five minutes and can be used once. Generate a new code from Settings. Enable the browser extension API first.
* Store extensions need a browser-trusted HTTPS origin, not LAN HTTP (`http://192.168.x`, `http://10.x`).

### Web UI password change did nothing
* Blank password on Save means **keep**. Use Reset to clear a stored secret.

---

## 7. Missing Chapters or Thumbnails

### Missing Chapters
* YouTube chapters are extracted directly from the video creator's timestamp list in the video description. If a video does not have timestamps defined in its description, no chapters can be embedded. This is normal behavior.

### Missing Thumbnail / Cover Art
* If embedding the cover art fails due to formatting issues, `ffmpeg` falls back to writing an audio-only file.
* You can manually embed a cover image into the `.m4b` file afterwards using `ffmpeg` from a terminal:
  ```bash
  ffmpeg -i "Input.m4b" -i cover.jpg -map 0:a -map 1 -c copy -disposition:v:0 attached_pic "Output.m4b"
  ```
