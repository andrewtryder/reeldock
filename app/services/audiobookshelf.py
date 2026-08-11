"""Audiobookshelf API client."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    success: bool
    skipped: bool = False
    error: str | None = None


class AudiobookshelfClient:
    """
    Minimal Audiobookshelf API client.

    Only exposes the library scan endpoint. API token is never logged.
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

        # Build headers — never log the token value
        headers = {
            "Authorization": f"Bearer {self.settings.abs_api_token}",
            "Content-Type": "application/json",
        }
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

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
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
                if lib_id:
                    libraries.append({"id": lib_id, "name": name})
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
        headers = {
            "Authorization": f"Bearer {self.settings.abs_api_token}",
            "Content-Type": "application/json",
        }
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
