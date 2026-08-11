# Release-smoke fixtures

Deterministic media for Compose release-smoke (#118). No live YouTube.

| File | Purpose |
|------|---------|
| `source.m4a` | ~3s AAC sine tone (yt-dlp download stand-in) |
| `cover.jpg` | Tiny JPEG for artwork embedding |

Regenerate (requires ffmpeg):

```bash
ffmpeg -y -f lavfi -i "sine=frequency=440:duration=3" -c:a aac -b:a 128k \
  tests/fixtures/release_smoke/source.m4a
ffmpeg -y -f lavfi -i "color=c=0xE8A33D:s=64x64:d=1" -frames:v 1 -update 1 \
  tests/fixtures/release_smoke/cover.jpg
```

Reserved smoke URL (valid allowlist host; metadata/download come from the fixture shim when
`RELEASE_SMOKE_FIXTURE=1`):

`https://www.youtube.com/watch?v=reeldockSmoke01`
