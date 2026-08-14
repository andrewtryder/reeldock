#!/usr/bin/env python3
"""Minimal fake Audiobookshelf HTTP API for Compose e2e tests."""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

LIBRARY_ID = os.environ.get("FAKE_ABS_LIBRARY_ID", "lib-e2e-books")
LIBRARY_NAME = os.environ.get("FAKE_ABS_LIBRARY_NAME", "E2E Audiobooks")
TOKEN = os.environ.get("FAKE_ABS_TOKEN", "fake-abs-token")
MEDIA_ROOT = Path(os.environ.get("FAKE_ABS_MEDIA_ROOT", "/media/podcasts"))
HOST = os.environ.get("FAKE_ABS_HOST", "0.0.0.0")  # noqa: S104
PORT = int(os.environ.get("FAKE_ABS_PORT", "13378"))

_lock = threading.Lock()
_scan_count = 0
_items_visible = False


def _auth_ok(handler: BaseHTTPRequestHandler) -> bool:
    header = handler.headers.get("Authorization", "")
    return header == f"Bearer {TOKEN}"


def _json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _walk_items() -> list[dict]:
    if not MEDIA_ROOT.exists():
        return []
    results: list[dict] = []
    for path in sorted(MEDIA_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".m4b", ".m4a", ".mp3"}:
            continue
        rel = path.relative_to(MEDIA_ROOT).as_posix()
        item_id = "li-" + rel.replace("/", "-").replace(" ", "_")
        results.append(
            {
                "id": item_id,
                "libraryId": LIBRARY_ID,
                "path": str(path),
                "relPath": rel,
                "isFile": True,
                "mediaType": "book",
                "media": {"metadata": {"title": path.stem}},
            }
        )
    return results


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/health":
            _json(self, 200, {"ok": True})
            return
        if path == "/_test/scan-count":
            with _lock:
                count = _scan_count
                visible = _items_visible
            _json(self, 200, {"scan_count": count, "items_visible": visible})
            return

        if not _auth_ok(self):
            _json(self, 401, {"error": "Unauthorized"})
            return

        if path == "/api/libraries":
            _json(
                self,
                200,
                {
                    "libraries": [
                        {
                            "id": LIBRARY_ID,
                            "name": LIBRARY_NAME,
                            "mediaType": "book",
                        }
                    ]
                },
            )
            return

        if path == f"/api/libraries/{LIBRARY_ID}":
            _json(
                self,
                200,
                {"id": LIBRARY_ID, "name": LIBRARY_NAME, "mediaType": "book"},
            )
            return

        if path == f"/api/libraries/{LIBRARY_ID}/items":
            with _lock:
                visible = _items_visible
            results = _walk_items() if visible else []
            _json(self, 200, {"results": results, "total": len(results)})
            return

        if path.startswith("/api/libraries/") and path.endswith("/search"):
            _json(self, 200, {"book": []})
            return

        if path.startswith("/api/libraries/"):
            _json(self, 404, {"error": "Library not found"})
            return

        _json(self, 404, {"error": "Not found"})

    def do_POST(self) -> None:
        global _scan_count, _items_visible
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

        if not _auth_ok(self):
            _json(self, 401, {"error": "Unauthorized"})
            return

        if path == f"/api/libraries/{LIBRARY_ID}/scan":
            with _lock:
                _scan_count += 1
                _items_visible = True
            _json(self, 200, {"success": True})
            return

        if path == "/_test/reset":
            with _lock:
                _scan_count = 0
                _items_visible = False
            _json(self, 200, {"ok": True})
            return

        _json(self, 404, {"error": "Not found"})


def main() -> None:
    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"fake-abs listening on {HOST}:{PORT} media={MEDIA_ROOT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        traceback.print_exc()
        raise
