"""Audiobookshelf API client."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

_SLASH_RE = re.compile(r"/+")


@dataclass
class ScanResult:
    success: bool
    skipped: bool = False
    error: str | None = None


def normalize_rel_path(path: str) -> str:
    """Normalize a library-relative path for comparison (never host absolute)."""
    text = path.replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    text = text.lstrip("/")
    text = _SLASH_RE.sub("/", text)
    return text


def item_open_url(base_url: str, item_id: str) -> str:
    """Build the Audiobookshelf web UI URL for a library item."""
    base = base_url.rstrip("/")
    return f"{base}/#/item/{item_id}"


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _item_rel_paths(item: dict[str, Any]) -> list[str]:
    """Collect matchable relative paths for a library item."""
    paths: list[str] = []
    item_rel_raw = item.get("relPath")
    item_rel = normalize_rel_path(str(item_rel_raw)) if item_rel_raw else ""
    if item_rel:
        paths.append(item_rel)

    media = item.get("media")
    if not isinstance(media, dict):
        return paths

    audio_files = media.get("audioFiles")
    if not isinstance(audio_files, list):
        return paths

    for audio in audio_files:
        if not isinstance(audio, dict):
            continue
        meta = audio.get("metadata")
        if not isinstance(meta, dict):
            continue
        file_rel_raw = meta.get("relPath")
        if not file_rel_raw:
            continue
        file_rel = normalize_rel_path(str(file_rel_raw))
        if not file_rel:
            continue
        # Folder items expose file relPaths relative to the item folder.
        if item_rel and not item.get("isFile"):
            paths.append(normalize_rel_path(f"{item_rel}/{file_rel}"))
        else:
            paths.append(file_rel)
    return paths


def _item_title(item: dict[str, Any]) -> str | None:
    media = item.get("media")
    if not isinstance(media, dict):
        return None
    metadata = media.get("metadata")
    if not isinstance(metadata, dict):
        return None
    title = metadata.get("title")
    return str(title) if title else None


def _flatten_search_items(payload: object) -> list[dict[str, Any]]:
    """Extract libraryItem objects from ABS search response shapes."""
    items: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return items

    for value in payload.values():
        if not isinstance(value, list):
            continue
        for entry in value:
            if not isinstance(entry, dict):
                continue
            library_item = entry.get("libraryItem")
            if isinstance(library_item, dict):
                items.append(library_item)
            elif entry.get("id") and entry.get("relPath") is not None:
                items.append(entry)
    return items


class AudiobookshelfClient:
    """
    Audiobookshelf API client for library scan, listing, and item matching.

    API token is never logged.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def _configured(self) -> bool:
        return self.settings.abs_configured

    def trigger_scan(self, library_id: str | None = None) -> ScanResult:
        """
        POST to Audiobookshelf to trigger a library scan.

        If ABS is not configured, returns ScanResult(success=False, skipped=True).
        Does not raise on API error — returns ScanResult(success=False, error=...).
        """
        if not self._configured:
            logger.info("Audiobookshelf not configured, skipping scan")
            return ScanResult(success=False, skipped=True)

        lid = library_id or self.settings.abs_library_id
        if not lid:
            return ScanResult(
                success=False,
                skipped=True,
                error="No library ID configured",
            )

        base_url = (self.settings.abs_base_url or "").rstrip("/")
        url = f"{base_url}/api/libraries/{lid}/scan"

        headers = _auth_headers(self.settings.abs_api_token or "")
        logger.debug("Triggering ABS scan for library %s at %s", lid, base_url)

        try:
            response = httpx.post(url, headers=headers, timeout=30)
            response.raise_for_status()
            logger.info("ABS scan triggered successfully for library %s", lid)
            return ScanResult(success=True)
        except httpx.HTTPStatusError as exc:
            msg = f"ABS API returned {exc.response.status_code}"
            logger.error("ABS scan failed: %s", msg)
            return ScanResult(success=False, error=msg)
        except httpx.RequestError as exc:
            msg = f"ABS connection error: {type(exc).__name__}"
            logger.error("ABS scan failed: %s", msg)
            return ScanResult(success=False, error=msg)

    def list_libraries(
        self,
        *,
        base_url: str | None = None,
        api_token: str | None = None,
    ) -> tuple[list[dict[str, str]], str | None]:
        """Return (libraries, error) from GET /api/libraries. Never logs the token."""
        url_base = (base_url or self.settings.abs_base_url or "").rstrip("/")
        token = api_token if api_token is not None else self.settings.abs_api_token
        if not url_base or not token:
            return [], "Audiobookshelf URL and API token are required"

        headers = _auth_headers(token)
        try:
            response = httpx.get(f"{url_base}/api/libraries", headers=headers, timeout=8)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                return [], f"Authentication failed (HTTP {status_code})"
            return [], f"ABS API returned HTTP {status_code}"
        except httpx.RequestError as exc:
            return [], f"ABS connection error: {type(exc).__name__}"
        except Exception:
            return [], "Could not parse Audiobookshelf response"

        raw_libs = payload.get("libraries") if isinstance(payload, dict) else payload
        libraries: list[dict[str, str]] = []
        if isinstance(raw_libs, list):
            for item in raw_libs:
                if not isinstance(item, dict):
                    continue
                lib_id = str(item.get("id") or "")
                name = str(item.get("name") or lib_id)
                media_type = str(item.get("mediaType") or "")
                if lib_id:
                    libraries.append({"id": lib_id, "name": name, "mediaType": media_type})
        return libraries, None

    def check_connectivity(self, library_id: str | None = None) -> ScanResult:
        """
        Verify ABS URL and API token with a read-only library GET.

        Does not trigger a library scan.
        """
        if not self._configured:
            return ScanResult(success=False, skipped=True)

        lid = library_id or self.settings.abs_library_id
        if not lid:
            return ScanResult(
                success=False,
                skipped=True,
                error="No library ID configured",
            )

        base_url = (self.settings.abs_base_url or "").rstrip("/")
        url = f"{base_url}/api/libraries/{lid}"
        headers = _auth_headers(self.settings.abs_api_token or "")
        logger.debug("Checking ABS connectivity for library %s at %s", lid, base_url)

        try:
            response = httpx.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            return ScanResult(success=True)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                msg = f"Authentication failed (HTTP {status_code})"
            else:
                msg = f"ABS API returned HTTP {status_code}"
            logger.error("ABS connectivity check failed: %s", msg)
            return ScanResult(success=False, error=msg)
        except httpx.RequestError as exc:
            msg = f"ABS connection error: {type(exc).__name__}"
            logger.error("ABS connectivity check failed: %s", msg)
            return ScanResult(success=False, error=msg)

    def get_library_items(self, library_id: str) -> tuple[list[dict[str, Any]], str | None]:
        """GET /api/libraries/{id}/items — returns (items, error)."""
        if not self.settings.abs_base_url or not self.settings.abs_api_token:
            return [], "Audiobookshelf URL and API token are required"
        if not library_id:
            return [], "No library ID configured"

        base_url = self.settings.abs_base_url.rstrip("/")
        url = f"{base_url}/api/libraries/{library_id}/items"
        headers = _auth_headers(self.settings.abs_api_token)
        try:
            response = httpx.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                return [], f"Authentication failed (HTTP {status_code})"
            if status_code == 404:
                return [], "Library not found"
            return [], f"ABS API returned HTTP {status_code}"
        except httpx.RequestError as exc:
            return [], f"ABS connection error: {type(exc).__name__}"
        except Exception:
            return [], "Could not parse Audiobookshelf response"

        raw = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            return [], "Could not parse Audiobookshelf response"
        return [item for item in raw if isinstance(item, dict)], None

    def search_library(self, library_id: str, q: str) -> tuple[list[dict[str, Any]], str | None]:
        """GET /api/libraries/{id}/search?q= — returns (library items, error)."""
        if not self.settings.abs_base_url or not self.settings.abs_api_token:
            return [], "Audiobookshelf URL and API token are required"
        if not library_id:
            return [], "No library ID configured"

        base_url = self.settings.abs_base_url.rstrip("/")
        url = f"{base_url}/api/libraries/{library_id}/search"
        headers = _auth_headers(self.settings.abs_api_token)
        try:
            response = httpx.get(url, headers=headers, params={"q": q}, timeout=15)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                return [], f"Authentication failed (HTTP {status_code})"
            if status_code == 404:
                return [], "Library not found"
            return [], f"ABS API returned HTTP {status_code}"
        except httpx.RequestError as exc:
            return [], f"ABS connection error: {type(exc).__name__}"
        except Exception:
            return [], "Could not parse Audiobookshelf response"

        return _flatten_search_items(payload), None

    def find_item_by_relative_path(
        self,
        library_id: str,
        relative_path: str,
        title_hint: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Find a library item whose relPath (or folder audio file path) matches.

        Never compares host absolute ``path``. Title fallback only when exactly
        one candidate matches the hint; ambiguous titles return None.
        """
        target = normalize_rel_path(relative_path)
        if not target:
            return None

        items, error = self.get_library_items(library_id)
        if error:
            logger.debug("ABS get_library_items failed during match: %s", error)
            items = []

        if not items and title_hint:
            searched, search_error = self.search_library(library_id, title_hint)
            if search_error:
                logger.debug("ABS search_library failed during match: %s", search_error)
            else:
                items = searched

        path_matches: list[dict[str, Any]] = []
        for item in items:
            candidates = _item_rel_paths(item)
            if target in candidates:
                path_matches.append(item)

        if len(path_matches) == 1:
            return path_matches[0]
        if len(path_matches) > 1:
            return None

        if not title_hint:
            return None

        hint = title_hint.strip().casefold()
        if not hint:
            return None

        title_matches = [
            item
            for item in items
            if (title := _item_title(item)) is not None and title.strip().casefold() == hint
        ]
        if len(title_matches) == 1:
            return title_matches[0]
        return None
