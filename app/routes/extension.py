"""Browser extension API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.auth import ExtensionAuthDep
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

router = APIRouter(prefix="/api/extension", tags=["extension"])

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
        "extension_api_enabled": cfg.extension_api_enabled,
        "auth_required": bool(cfg.extension_api_token),
        "dry_run": cfg.dry_run,
        "abs_configured": cfg.abs_configured,
        "allow_playlists": cfg.allow_playlists,
        "allow_channels": cfg.allow_channels,
    }


@router.get("/destinations")
async def api_extension_destinations(cfg: ExtensionAuthDep) -> dict[str, Any]:
    folders = _safe_folder_names(FilesystemService(cfg).list_folders())
    configured = (cfg.default_destination_folder or "").strip()
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
    svc = YtDlpService(cfg)
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
        job, rq_id = await submit_job(db, cfg, params)
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
