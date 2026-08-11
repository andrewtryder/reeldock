"""Browser extension API routes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.auth import ExtensionAuthDep
from app.config import get_settings
from app.quality import QUALITY_PRESETS, audio_quality_for_preset
from app.routes import DbDep
from app.serializers import extension_job_dict
from app.services.filesystem import FilesystemService
from app.services.jobs import (
    DuplicateVideoError,
    InvalidJobUrlError,
    JobConflictError,
    JobNotFoundError,
    JobSubmitParams,
    cancel_job,
    get_job,
    retry_job,
    submit_job,
)
from app.services.ytdlp import YtDlpService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/extension", tags=["extension"])


class PairRequest(BaseModel):
    pairing_code: str
    device_name: str = "Browser"
    browser: str | None = None
    platform: str | None = None


class WsTicketRequest(BaseModel):
    job_id: str


@router.post("/pair")
async def api_extension_pair(body: PairRequest, request: Request) -> dict[str, Any]:
    """Exchange a one-use pairing code for a device token. No prior auth."""
    cfg = get_settings()
    if not cfg.extension_api_enabled:
        raise HTTPException(status_code=404, detail="Extension API not enabled")

    from app.db import get_sync_session_factory
    from app.queue import get_redis
    from app.services.pairing import (
        PairingError,
        check_pair_rate_limit,
        consume_pairing_code,
        pair_failures_blocked,
    )

    source = request.client.host if request.client else "unknown"
    try:
        redis = get_redis()
    except Exception:
        redis = None
    if redis is not None and pair_failures_blocked(redis, source):
        raise HTTPException(status_code=429, detail="Too many failed pairing attempts")

    factory = get_sync_session_factory()
    try:
        with factory() as session:
            device, token = consume_pairing_code(
                session,
                pairing_code=body.pairing_code,
                device_name=body.device_name,
                browser=body.browser,
                platform=body.platform,
            )
    except PairingError as exc:
        if redis is not None:
            check_pair_rate_limit(redis, source)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {
        "ok": True,
        "device_id": device.id,
        "device_token": token,
        "api_version": EXTENSION_API_VERSION,
        "supports": dict(EXTENSION_SUPPORTS),
    }


@router.post("/ws-ticket")
async def api_extension_ws_ticket(body: WsTicketRequest, cfg: ExtensionAuthDep) -> dict[str, str]:
    if cfg.auth_kind != "device" or not cfg.device_id:
        raise HTTPException(
            status_code=400,
            detail="WebSocket tickets are for paired devices. Legacy tokens use ?token=.",
        )
    from app.queue import get_redis
    from app.services.ws_tickets import issue_ws_ticket

    try:
        ticket = issue_ws_ticket(get_redis(), job_id=body.job_id, device_id=cfg.device_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Ticket store unavailable") from exc
    return {"ticket": ticket, "job_id": body.job_id}


@router.post("/devices/me/revoke")
async def api_extension_revoke_me(cfg: ExtensionAuthDep) -> dict[str, str]:
    if cfg.auth_kind != "device" or not cfg.device_id:
        raise HTTPException(status_code=400, detail="Only paired devices can revoke themselves")
    from app.db import get_sync_session_factory
    from app.models import ExtensionDevice
    from app.queue import get_redis
    from app.services.pairing import revoke_device
    from app.services.ws_tickets import mark_device_revoked

    factory = get_sync_session_factory()
    with factory() as session:
        device = session.get(ExtensionDevice, cfg.device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        revoke_device(session, device)
    try:
        mark_device_revoked(get_redis(), cfg.device_id)
    except Exception:
        logger.warning("Could not publish device revocation", exc_info=True)
    return {"status": "revoked"}


EXTENSION_API_VERSION = 1
EXTENSION_SUPPORTS = {
    "destinations": True,
    "quality_presets": True,
    "sponsorblock": True,
    "cancel": True,
    "retry": True,
}


class ExtensionQueueRequest(BaseModel):
    """Queue body for the extension control plane."""

    model_config = ConfigDict(extra="ignore")

    url: str
    destination_folder: str | None = None
    output_title: str = ""
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    embed_chapters: bool = True
    trigger_abs_scan: bool = False
    allow_reimport: bool = False
    quality: Literal["standard", "high", "best"] = "standard"
    sponsorblock_remove: bool = False

    @field_validator("allow_reimport", mode="before")
    @classmethod
    def _coerce_allow_reimport(cls, value: object) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)


def _safe_folder_names(names: list[str]) -> list[str]:
    """Keep OUTPUT_ROOT-relative folder names only — never host paths."""
    safe: list[str] = []
    for name in names:
        if not name or name.startswith("/") or ".." in name:
            continue
        if Path(name).is_absolute():
            continue
        safe.append(name)
    return safe


@router.get("/status")
async def api_extension_status(cfg: ExtensionAuthDep) -> dict[str, Any]:
    return {
        "ok": True,
        "app": "reeldock",
        "api_version": EXTENSION_API_VERSION,
        "supports": dict(EXTENSION_SUPPORTS),
        "extension_api_enabled": cfg.settings.extension_api_enabled,
        "auth_required": True,
        "auth_kind": cfg.auth_kind,
        "device_id": cfg.device_id,
        "device_name": cfg.device_name,
        "dry_run": cfg.dry_run,
        "abs_configured": cfg.abs_configured,
        "allow_playlists": cfg.allow_playlists,
        "allow_channels": cfg.allow_channels,
    }


@router.get("/destinations")
async def api_extension_destinations(cfg: ExtensionAuthDep) -> dict[str, Any]:
    folders = _safe_folder_names(FilesystemService(cfg.settings).list_folders())
    configured = (cfg.settings.default_destination_folder or "").strip()
    default = configured if configured in folders else ""
    return {"default": default, "folders": folders}


@router.get("/jobs/{job_id}")
async def api_extension_get_job(job_id: str, db: DbDep, _cfg: ExtensionAuthDep) -> dict[str, Any]:
    job = await get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return extension_job_dict(job)


@router.post("/jobs/{job_id}/cancel")
async def api_extension_cancel_job(
    job_id: str, db: DbDep, _cfg: ExtensionAuthDep
) -> dict[str, str]:
    try:
        await cancel_job(db, job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id, "status": "cancelled"}


@router.post("/jobs/{job_id}/retry")
async def api_extension_retry_job(job_id: str, db: DbDep, _cfg: ExtensionAuthDep) -> dict[str, str]:
    try:
        _job, rq_id = await retry_job(db, job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id, "rq_job_id": rq_id, "status": "queued"}


@router.post("/queue", status_code=201)
async def api_extension_queue(
    request: Request,
    db: DbDep,
    cfg: ExtensionAuthDep,
) -> JSONResponse:
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not data.get("url"):
        raise HTTPException(status_code=400, detail="URL is required")

    quality = data.get("quality", "standard")
    if quality not in QUALITY_PRESETS:
        raise HTTPException(
            status_code=400,
            detail="Unknown quality. Expected standard, high, or best.",
        )

    try:
        body = ExtensionQueueRequest.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Invalid request body") from exc

    url = body.url
    svc = YtDlpService(cfg.settings)
    validation = svc.validate_url(url)
    if not validation.valid:
        raise HTTPException(status_code=400, detail=validation.error)

    try:
        meta = svc.run_preview(url)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    params = JobSubmitParams(
        url=url,
        video_id=meta.id,
        source_title=meta.title,
        uploader=meta.uploader,
        uploader_id=meta.uploader_id,
        channel=meta.channel,
        channel_id=meta.channel_id,
        duration=meta.duration,
        upload_date=meta.upload_date,
        thumbnail_url=meta.thumbnail,
        chapter_count=meta.chapter_count,
        output_title=body.output_title or meta.title,
        destination_folder=body.destination_folder,
        embed_metadata=body.embed_metadata,
        embed_thumbnail=body.embed_thumbnail,
        embed_chapters=body.embed_chapters,
        trigger_abs_scan=body.trigger_abs_scan,
        allow_reimport=body.allow_reimport,
        sponsorblock_remove=body.sponsorblock_remove,
        audio_quality=audio_quality_for_preset(body.quality),
        validate_url=False,
    )

    try:
        job, rq_id = await submit_job(db, cfg.settings, params)
    except InvalidJobUrlError as exc:
        raise HTTPException(status_code=400, detail=exc.error) from exc
    except DuplicateVideoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse(
        {
            "ok": True,
            "job_id": job.id,
            "rq_job_id": rq_id,
            "status": "queued",
            "title": meta.title,
            "uploader": meta.uploader,
            "job_url": f"/jobs/{job.id}",
        },
        status_code=201,
    )
