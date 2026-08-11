"""HTML page routes and Jinja2 template setup."""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_setting_sources, reload_settings, reset_setting, save_settings
from app.csrf import issue_csrf_token, validate_csrf_token
from app.db import get_sync_db
from app.diagnostics import format_free_space
from app.models import Job
from app.path_checks import check_writable_directory
from app.routes import DbDep, SettingsDep
from app.services.batch_abs import retry_batch_abs_scan
from app.services.destination import (
    blank_destination_option_label,
    initial_selected_destination_folder,
    preview_audiobook_destination,
)
from app.services.filesystem import FilesystemService
from app.services.jobs import (
    BatchJobSubmitParams,
    DuplicateVideoError,
    InvalidJobUrlError,
    JobSubmitParams,
    get_imported_video_ids,
    get_job,
    get_jobs_list,
    get_recent_jobs,
    submit_batch,
    submit_job,
)
from app.services.ytdlp import PlaylistEntry, YtDlpService, is_channel_url, is_playlist_url
from app.settings_registry import (
    COLLISION_CHOICES,
    SECRET_KEEP_KEYS,
    SECURITY_FORM_KEYS,
    parse_form_value,
    registry_groups,
)
from app.validators import (
    validate_audio_bitrate,
    validate_extra_args,
    validate_filename_template,
    validate_lufs_target,
    validate_optional_path,
)

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "--:--"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _format_date(date_str: str | None) -> str:
    """Format YYYYMMDD → YYYY-MM-DD."""
    if not date_str or len(date_str) != 8:
        return date_str or ""
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"


def _escape_html(text: str | None) -> str:
    return html.escape(text or "")


templates.env.filters["duration"] = _format_duration
templates.env.filters["format_date"] = _format_date
templates.env.filters["escape_html"] = _escape_html
templates.env.globals["format_free_space"] = format_free_space
templates.env.globals["COLLISION_CHOICES"] = COLLISION_CHOICES


def configure_templates(ui_version: str) -> None:
    templates.env.globals["app_ui_version"] = ui_version


router = APIRouter(tags=["pages"])


def _optional_form_str(value: str | None) -> str | None:
    stripped = (value or "").strip()
    return stripped or None


def _optional_form_bool(value: str | None) -> bool | None:
    stripped = (value or "").strip().lower()
    if not stripped:
        return None
    if stripped in {"true", "1", "yes", "on"}:
        return True
    if stripped in {"false", "0", "no", "off"}:
        return False
    return None


def _validate_advanced_import_fields(
    *,
    collision_mode: str | None,
    filename_template: str | None,
    ytdlp_extra_args: str | None,
    ffmpeg_extra_args: str | None,
    cookies_file: str | None,
    loudness_target_lufs: str | None = None,
    loudness_audio_bitrate: str | None = None,
) -> str | None:
    if collision_mode and collision_mode not in COLLISION_CHOICES:
        return f"Invalid collision mode: {collision_mode}"
    if filename_template:
        error, _warning = validate_filename_template(filename_template)
        if error:
            return error
    for label, value in (
        ("yt-dlp extra arguments", ytdlp_extra_args),
        ("ffmpeg extra arguments", ffmpeg_extra_args),
    ):
        if value:
            error, _warning = validate_extra_args(value)
            if error:
                return f"{label}: {error}"
    if cookies_file:
        error, _warning = validate_optional_path(cookies_file)
        if error:
            return f"Cookies file: {error}"
    if loudness_target_lufs:
        error, _warning = validate_lufs_target(loudness_target_lufs)
        if error:
            return f"Loudness target: {error}"
    if loudness_audio_bitrate:
        error, _warning = validate_audio_bitrate(loudness_audio_bitrate)
        if error:
            return f"Loudness bitrate: {error}"
    return None


def _advanced_fields_from_form(
    *,
    collision_mode: str | None = None,
    audio_format: str | None = None,
    audio_quality: str | None = None,
    output_extension: str | None = None,
    filename_template: str | None = None,
    ytdlp_extra_args: str | None = None,
    ffmpeg_extra_args: str | None = None,
    cookies_file: str | None = None,
    dry_run: bool = False,
    loudness_normalize: str | None = None,
    loudness_target_lufs: str | None = None,
    loudness_audio_bitrate: str | None = None,
) -> dict[str, object]:
    return {
        "collision_mode": _optional_form_str(collision_mode),
        "audio_format": _optional_form_str(audio_format),
        "audio_quality": _optional_form_str(audio_quality),
        "output_extension": _optional_form_str(output_extension),
        "filename_template": _optional_form_str(filename_template),
        "ytdlp_extra_args": _optional_form_str(ytdlp_extra_args),
        "ffmpeg_extra_args": _optional_form_str(ffmpeg_extra_args),
        "cookies_file": _optional_form_str(cookies_file),
        "dry_run": dry_run,
        "loudness_normalize": _optional_form_bool(loudness_normalize),
        "loudness_target_lufs": _optional_form_str(loudness_target_lufs),
        "loudness_audio_bitrate": _optional_form_str(loudness_audio_bitrate),
    }


@router.get("/", response_class=HTMLResponse)
async def page_home(request: Request, db: DbDep, cfg: SettingsDep) -> HTMLResponse:
    recent_jobs = await get_recent_jobs(db, limit=6)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"request": request, "settings": cfg, "recent_jobs": recent_jobs},
    )


@router.post("/preview", response_class=HTMLResponse)
async def page_preview(
    request: Request,
    cfg: SettingsDep,
    db: DbDep,
    url: str = Form(...),
) -> HTMLResponse:
    svc = YtDlpService(cfg)
    validation = svc.validate_url(url)
    if not validation.valid:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "settings": cfg,
                "error": validation.error,
                "url": url,
            },
            status_code=400,
        )

    fs = FilesystemService(cfg)
    folders = fs.list_folders()
    is_batch_url = is_playlist_url(url) or is_channel_url(url)

    if is_batch_url:
        try:
            playlist_meta = svc.run_playlist_preview(url, cfg.max_playlist_entries)
        except Exception as exc:
            return templates.TemplateResponse(
                request,
                "index.html",
                {
                    "request": request,
                    "settings": cfg,
                    "error": str(exc),
                    "url": url,
                },
                status_code=422,
            )
        entry_ids = [entry.id for entry in playlist_meta.entries if entry.id]
        imported_ids = await get_imported_video_ids(db, entry_ids)
        default_folder = cfg.default_destination_folder or ""
        first_entry = playlist_meta.entries[0] if playlist_meta.entries else None
        preview_channel = getattr(playlist_meta, "channel", None) or (
            first_entry.channel if first_entry else None
        )
        preview_uploader = getattr(playlist_meta, "uploader", None) or (
            first_entry.uploader if first_entry else None
        )
        initial_dest = initial_selected_destination_folder(
            folders,
            default_folder=default_folder,
            uploader=getattr(playlist_meta, "uploader", None),
            uploader_id=getattr(playlist_meta, "uploader_id", None),
            channel=getattr(playlist_meta, "channel", None),
            match_channel=True,
        )
        dest_preview = preview_audiobook_destination(
            cfg,
            destination_folder=initial_dest or None,
            uploader=preview_uploader,
            channel=preview_channel,
            summary_kind="batch",
        )
        return templates.TemplateResponse(
            request,
            "playlist_preview.html",
            {
                "request": request,
                "settings": cfg,
                "meta": playlist_meta,
                "folders": folders,
                "url": url,
                "default_folder": default_folder,
                "selected_folder": initial_dest,
                "blank_folder_label": blank_destination_option_label(
                    cfg.default_destination_folder
                ),
                "dest_preview": dest_preview,
                "preview_channel": preview_channel or "",
                "preview_uploader": preview_uploader or "",
                "max_entries": cfg.max_playlist_entries,
                "imported_ids": imported_ids,
            },
        )

    try:
        video_meta = svc.run_preview(url)
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "settings": cfg,
                "error": str(exc),
                "url": url,
            },
            status_code=422,
        )

    default_folder = cfg.default_destination_folder or ""
    initial_dest = initial_selected_destination_folder(
        folders,
        default_folder=default_folder,
        uploader=getattr(video_meta, "uploader", None),
        uploader_id=getattr(video_meta, "uploader_id", None),
    )
    dest_preview = preview_audiobook_destination(
        cfg,
        destination_folder=initial_dest or None,
        output_title=getattr(video_meta, "title", "") or "",
        video_id=getattr(video_meta, "id", "") or "",
        uploader=getattr(video_meta, "uploader", None),
        channel=getattr(video_meta, "channel", None),
        upload_date=getattr(video_meta, "upload_date", None),
        summary_kind="single",
    )
    return templates.TemplateResponse(
        request,
        "preview.html",
        {
            "request": request,
            "settings": cfg,
            "meta": video_meta,
            "folders": folders,
            "url": url,
            "default_folder": default_folder,
            "selected_folder": initial_dest,
            "blank_folder_label": blank_destination_option_label(cfg.default_destination_folder),
            "dest_preview": dest_preview,
        },
    )


@router.post("/preview/destination")
async def preview_destination(
    cfg: SettingsDep,
    new_folder: str = Form(""),
    destination_folder: str = Form(""),
    output_title: str = Form(""),
    video_id: str = Form(""),
    filename_template: str = Form(""),
    collision_mode: str = Form(""),
    uploader: str = Form(""),
    channel: str = Form(""),
    upload_date: str = Form(""),
    summary_kind: str = Form("single"),
) -> JSONResponse:
    """Return the resolved audiobook destination for live Preview updates."""
    kind: Literal["single", "batch"] = "batch" if summary_kind == "batch" else "single"
    try:
        preview = preview_audiobook_destination(
            cfg,
            new_folder=new_folder,
            destination_folder=destination_folder.strip() or None,
            output_title=output_title,
            video_id=video_id,
            filename_template=filename_template or None,
            collision_mode=collision_mode or None,
            uploader=uploader or None,
            channel=channel or None,
            upload_date=upload_date or None,
            summary_kind=kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(preview.as_dict())


@router.post("/jobs/create", response_class=HTMLResponse, response_model=None)
async def page_create_job(
    request: Request,
    db: DbDep,
    cfg: SettingsDep,
    url: str = Form(...),
    video_id: str = Form(""),
    source_title: str = Form(""),
    uploader: str = Form(""),
    uploader_id: str = Form(""),
    channel: str = Form(""),
    channel_id: str = Form(""),
    duration: int = Form(0),
    upload_date: str = Form(""),
    thumbnail_url: str = Form(""),
    chapter_count: int = Form(0),
    output_title: str = Form(""),
    destination_folder: str = Form(""),
    new_folder: str = Form(""),
    embed_metadata: bool = Form(True),
    embed_thumbnail: bool = Form(True),
    embed_chapters: bool = Form(True),
    trigger_abs_scan: bool = Form(False),
    allow_reimport: bool = Form(False),
    sponsorblock_remove: bool = Form(False),
    collision_mode: str = Form(""),
    audio_format: str = Form(""),
    audio_quality: str = Form(""),
    output_extension: str = Form(""),
    filename_template: str = Form(""),
    ytdlp_extra_args: str = Form(""),
    ffmpeg_extra_args: str = Form(""),
    cookies_file: str = Form(""),
    dry_run: bool = Form(False),
    loudness_normalize: str = Form(""),
    loudness_target_lufs: str = Form(""),
    loudness_audio_bitrate: str = Form(""),
) -> HTMLResponse | RedirectResponse:
    advanced = _advanced_fields_from_form(
        collision_mode=collision_mode,
        audio_format=audio_format,
        audio_quality=audio_quality,
        output_extension=output_extension,
        filename_template=filename_template,
        ytdlp_extra_args=ytdlp_extra_args,
        ffmpeg_extra_args=ffmpeg_extra_args,
        cookies_file=cookies_file,
        dry_run=dry_run,
        loudness_normalize=loudness_normalize,
        loudness_target_lufs=loudness_target_lufs,
        loudness_audio_bitrate=loudness_audio_bitrate,
    )
    validation_error = _validate_advanced_import_fields(
        collision_mode=advanced["collision_mode"],  # type: ignore[arg-type]
        filename_template=advanced["filename_template"],  # type: ignore[arg-type]
        ytdlp_extra_args=advanced["ytdlp_extra_args"],  # type: ignore[arg-type]
        ffmpeg_extra_args=advanced["ffmpeg_extra_args"],  # type: ignore[arg-type]
        cookies_file=advanced["cookies_file"],  # type: ignore[arg-type]
        loudness_target_lufs=advanced["loudness_target_lufs"],  # type: ignore[arg-type]
        loudness_audio_bitrate=advanced["loudness_audio_bitrate"],  # type: ignore[arg-type]
    )
    if validation_error:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"request": request, "settings": cfg, "error": validation_error, "url": url},
            status_code=400,
        )

    params = JobSubmitParams(
        url=url,
        video_id=video_id,
        source_title=source_title,
        uploader=uploader,
        uploader_id=uploader_id,
        channel=channel,
        channel_id=channel_id,
        duration=duration,
        upload_date=upload_date,
        thumbnail_url=thumbnail_url,
        chapter_count=chapter_count,
        output_title=output_title,
        destination_folder=destination_folder.strip() or None,
        new_folder=new_folder,
        embed_metadata=embed_metadata,
        embed_thumbnail=embed_thumbnail,
        embed_chapters=embed_chapters,
        trigger_abs_scan=trigger_abs_scan,
        allow_reimport=allow_reimport,
        sponsorblock_remove=sponsorblock_remove,
        **advanced,  # type: ignore[arg-type]
    )
    try:
        job, _rq_id = await submit_job(db, cfg, params)
    except InvalidJobUrlError as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"request": request, "settings": cfg, "error": exc.error},
            status_code=400,
        )
    except DuplicateVideoError as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"request": request, "settings": cfg, "error": str(exc)},
            status_code=409,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"request": request, "settings": cfg, "error": str(exc)},
            status_code=400,
        )

    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.post("/jobs/create-batch", response_class=HTMLResponse, response_model=None)
async def page_create_batch(
    request: Request,
    db: DbDep,
    cfg: SettingsDep,
) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    source_url = str(form.get("source_url") or "").strip()
    source_type = str(form.get("source_type") or "").strip()
    batch_title = str(form.get("batch_title") or "").strip()
    destination_folder = str(form.get("destination_folder") or "")
    new_folder = str(form.get("new_folder") or "")

    def _bool_field(name: str, default: bool = False) -> bool:
        raw = form.get(name)
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    selected_ids = [
        str(value).strip() for key, value in form.multi_items() if key == "selected" and value
    ]
    entries: list[PlaylistEntry] = []
    for video_id in selected_ids:
        if not video_id:
            continue
        entries.append(
            PlaylistEntry(
                id=video_id,
                title=str(form.get(f"title_{video_id}") or video_id).strip() or video_id,
                url=str(form.get(f"url_{video_id}") or "").strip()
                or f"https://www.youtube.com/watch?v={video_id}",
                duration=_parse_optional_int(form.get(f"duration_{video_id}")),
                uploader=_or_empty(form.get(f"uploader_{video_id}")),
                uploader_id=_or_empty(form.get(f"uploader_id_{video_id}")),
                channel=_or_empty(form.get(f"channel_{video_id}")),
                channel_id=_or_empty(form.get(f"channel_id_{video_id}")),
                thumbnail=_or_empty(form.get(f"thumbnail_{video_id}")),
            )
        )

    advanced = _advanced_fields_from_form(
        collision_mode=str(form.get("collision_mode") or ""),
        audio_format=str(form.get("audio_format") or ""),
        audio_quality=str(form.get("audio_quality") or ""),
        output_extension=str(form.get("output_extension") or ""),
        filename_template=str(form.get("filename_template") or ""),
        ytdlp_extra_args=str(form.get("ytdlp_extra_args") or ""),
        ffmpeg_extra_args=str(form.get("ffmpeg_extra_args") or ""),
        cookies_file=str(form.get("cookies_file") or ""),
        dry_run=_bool_field("dry_run", False),
        loudness_normalize=str(form.get("loudness_normalize") or ""),
        loudness_target_lufs=str(form.get("loudness_target_lufs") or ""),
        loudness_audio_bitrate=str(form.get("loudness_audio_bitrate") or ""),
    )
    validation_error = _validate_advanced_import_fields(
        collision_mode=advanced["collision_mode"],  # type: ignore[arg-type]
        filename_template=advanced["filename_template"],  # type: ignore[arg-type]
        ytdlp_extra_args=advanced["ytdlp_extra_args"],  # type: ignore[arg-type]
        ffmpeg_extra_args=advanced["ffmpeg_extra_args"],  # type: ignore[arg-type]
        cookies_file=advanced["cookies_file"],  # type: ignore[arg-type]
        loudness_target_lufs=advanced["loudness_target_lufs"],  # type: ignore[arg-type]
        loudness_audio_bitrate=advanced["loudness_audio_bitrate"],  # type: ignore[arg-type]
    )
    if validation_error:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"request": request, "settings": cfg, "error": validation_error, "url": source_url},
            status_code=400,
        )

    params = BatchJobSubmitParams(
        source_url=source_url,
        source_type=source_type,
        batch_title=batch_title or None,
        entries=entries,
        destination_folder=destination_folder.strip() or None,
        new_folder=new_folder,
        embed_metadata=_bool_field("embed_metadata", True),
        embed_thumbnail=_bool_field("embed_thumbnail", True),
        embed_chapters=_bool_field("embed_chapters", True),
        trigger_abs_scan=_bool_field("trigger_abs_scan", False),
        allow_reimport=_bool_field("allow_reimport", False),
        sponsorblock_remove=_bool_field("sponsorblock_remove", False),
        **advanced,  # type: ignore[arg-type]
    )

    try:
        result = await submit_batch(db, cfg, params)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"request": request, "settings": cfg, "error": str(exc), "url": source_url},
            status_code=400,
        )

    if result.created == 0 and result.skipped_duplicate == 0:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "settings": cfg,
                "error": "No jobs were created from the selected videos.",
                "url": source_url,
            },
            status_code=400,
        )

    return RedirectResponse(f"/jobs?batch={result.batch_id}", status_code=303)


def _or_empty(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_optional_int(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


@router.get("/jobs", response_class=HTMLResponse)
async def page_jobs(request: Request, db: DbDep, cfg: SettingsDep) -> HTMLResponse:
    items = await get_jobs_list(db)
    highlight_batch = request.query_params.get("batch") or ""
    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "request": request,
            "settings": cfg,
            "items": items,
            "highlight_batch": highlight_batch,
            "csrf_token": issue_csrf_token(),
        },
    )


@router.post("/jobs/batches/{batch_id}/abs-scan", response_class=HTMLResponse)
async def page_retry_batch_abs_scan(
    request: Request, batch_id: str, cfg: SettingsDep
) -> RedirectResponse:
    form = {key: str(value) for key, value in (await request.form()).items()}
    if not validate_csrf_token(form.get("csrf_token")):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    db = get_sync_db()
    try:
        retry_batch_abs_scan(db, batch_id, cfg)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Batch not found") from exc
    finally:
        db.close()
    return RedirectResponse(f"/jobs?batch={batch_id}", status_code=303)


@router.post("/jobs/{job_id}/abs-scan", response_class=HTMLResponse)
async def page_retry_job_abs_scan(
    request: Request, job_id: str, cfg: SettingsDep
) -> RedirectResponse:
    form = {key: str(value) for key, value in (await request.form()).items()}
    if not validate_csrf_token(form.get("csrf_token")):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    from app.services.abs_index import retry_job_abs_scan

    db = get_sync_db()
    try:
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        retry_job_abs_scan(db, job, cfg)
        db.commit()
    finally:
        db.close()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/abs-check", response_class=HTMLResponse)
async def page_check_job_abs_index(
    request: Request, job_id: str, cfg: SettingsDep
) -> RedirectResponse:
    form = {key: str(value) for key, value in (await request.form()).items()}
    if not validate_csrf_token(form.get("csrf_token")):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    from app.services.abs_index import check_job_abs_index_again

    db = get_sync_db()
    try:
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        check_job_abs_index_again(db, job, cfg)
        db.commit()
    finally:
        db.close()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def page_job_detail(
    request: Request, job_id: str, db: DbDep, cfg: SettingsDep
) -> HTMLResponse:
    job = await get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    fs = FilesystemService(cfg)
    log_path = fs.log_path(job_id)
    log_content = ""
    if log_path.exists():
        log_content = log_path.read_text(encoding="utf-8", errors="replace")

    conversion_meta: dict[str, object] = {}
    collision_meta: dict[str, object] = {}
    if job.attempts_log:
        latest = max(job.attempts_log, key=lambda a: a.started_at or a.id)
        if latest.artifact_metadata:
            try:
                import json

                parsed = json.loads(latest.artifact_metadata)
                if isinstance(parsed.get("conversion"), dict):
                    conversion_meta = parsed["conversion"]
                if isinstance(parsed.get("collision"), dict):
                    collision_meta = parsed["collision"]
            except json.JSONDecodeError, TypeError:
                pass

    from app.services.audiobookshelf import item_open_url

    abs_open_url = None
    if cfg.abs_base_url and job.abs_library_item_id:
        abs_open_url = item_open_url(cfg.abs_base_url, job.abs_library_item_id)
    elif cfg.abs_base_url and (job.abs_library_id or cfg.abs_library_id):
        lid = job.abs_library_id or cfg.abs_library_id
        abs_open_url = f"{cfg.abs_base_url.rstrip('/')}/#/library/{lid}"

    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {
            "request": request,
            "settings": cfg,
            "job": job,
            "log": log_content,
            "conversion_meta": conversion_meta,
            "collision_meta": collision_meta,
            "csrf_token": issue_csrf_token(),
            "abs_open_url": abs_open_url,
        },
    )


def _build_settings_context(
    request: Request,
    cfg: Settings,
    *,
    form_values: dict[str, str] | None = None,
    field_errors: dict[str, str] | None = None,
    field_warnings: dict[str, str] | None = None,
    error: str | None = None,
    success: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, object]:
    sources = get_setting_sources()
    groups: list[dict[str, object]] = []
    for group_id, group_label, specs in registry_groups():
        fields: list[dict[str, object]] = []
        for spec in specs:
            meta = sources[spec.key]
            value = form_values.get(spec.key, meta["value"]) if form_values else meta["value"]
            fields.append(
                {
                    "spec": spec,
                    "value": value,
                    "source": meta["source"],
                    "label": meta.get("label", meta["source"]),
                    "locked": meta["locked"],
                    "restart_required": meta["restart_required"],
                    "secret": meta.get("secret", spec.secret),
                    "has_value": meta.get("has_value", True),
                    "error": (field_errors or {}).get(spec.key),
                    "warning": (field_warnings or {}).get(spec.key),
                }
            )
        groups.append({"id": group_id, "label": group_label, "fields": fields})

    from sqlalchemy import select

    from app.db import get_sync_session_factory
    from app.models import ExtensionDevice

    devices: list[ExtensionDevice] = []
    try:
        with get_sync_session_factory()() as session:
            devices = list(
                session.scalars(select(ExtensionDevice).order_by(ExtensionDevice.created_at.desc()))
            )
    except Exception:
        devices = []

    host = (request.url.hostname or "").lower()
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    private_http = request.url.scheme == "http" and not loopback

    return {
        "request": request,
        "settings": cfg,
        "setting_groups": groups,
        "error": error,
        "success": success,
        "warnings": warnings or [],
        "library_path_writable": check_writable_directory(cfg.output_root, create=False) is None,
        "library_path": str(cfg.output_root),
        "csrf_token": issue_csrf_token(),
        "extension_devices": devices,
        "config_mode": cfg.reeldock_config_mode,
        "private_http": private_http,
        "current_origin": str(request.base_url).rstrip("/"),
        "deployment": {
            "app_host": cfg.app_host,
            "app_port": cfg.app_port,
            "redis_url": cfg.redis_url,
            "database_url": cfg.database_url,
            "output_root": str(cfg.output_root),
            "work_dir": str(cfg.work_dir),
            "config_mode": cfg.reeldock_config_mode,
        },
    }


def _process_settings_form(
    form: dict[str, str],
) -> tuple[dict[str, str], dict[str, str], dict[str, str], list[str]]:
    """Validate submitted settings form; return overrides, errors, warnings, global warnings."""
    from app.settings_registry import SETTINGS_REGISTRY

    sources = get_setting_sources()
    overrides: dict[str, str] = {}
    errors: dict[str, str] = {}
    warnings: dict[str, str] = {}
    global_warnings: list[str] = []

    for spec in SETTINGS_REGISTRY:
        if not spec.mutable or sources[spec.key]["locked"]:
            continue
        if spec.key in SECURITY_FORM_KEYS:
            continue
        raw = form.get(spec.key)
        if (spec.secret or spec.key in SECRET_KEEP_KEYS) and not (raw or "").strip():
            continue
        value = parse_form_value(raw, spec)
        if spec.validate:
            error, warning = spec.validate(value)
            if error:
                errors[spec.key] = error
                continue
            if warning:
                warnings[spec.key] = warning
        overrides[spec.key] = value
        if spec.restart_required:
            global_warnings.append(
                f"{spec.label} may require a process restart to take full effect."
            )

    _apply_security_form(form, sources, overrides, errors)
    return overrides, errors, warnings, global_warnings


def _apply_security_form(
    form: dict[str, str],
    sources: dict[str, dict[str, object]],
    overrides: dict[str, str],
    errors: dict[str, str],
) -> None:
    from app.settings_registry import SETTINGS_BY_KEY

    for key in SECURITY_FORM_KEYS:
        spec = SETTINGS_BY_KEY[key]
        if sources[key]["locked"]:
            continue
        if key == "auth_enabled":
            continue
        raw = form.get(key, "")
        if key == "auth_password":
            if not raw.strip():
                continue
            if form.get("auth_password_confirm", "") != raw:
                errors["auth_password"] = "Password and confirmation do not match."  # noqa: S105
                continue
        overrides[key] = parse_form_value(raw, spec)

    if sources["auth_enabled"]["locked"]:
        return

    want_enabled = form.get("auth_enabled") in {"on", "true", "1", "yes"}
    currently_enabled = sources["auth_enabled"]["value"] == "true"
    if want_enabled:
        overrides["auth_enabled"] = "true"
        username = (overrides.get("auth_username") or "").strip()
        password = (overrides.get("auth_password") or "").strip()
        has_existing_password = bool(sources["auth_password"].get("has_value"))
        if not username:
            errors["auth_username"] = "Username is required when sign-in is enabled."
        if not password and not has_existing_password:
            errors["auth_password"] = "Password is required when enabling sign-in."  # noqa: S105
    elif currently_enabled:
        if form.get("confirm_disable_auth") != "on":
            errors["auth_enabled"] = "Confirm disable to turn off Web UI sign-in."
        else:
            overrides["auth_enabled"] = "false"
    else:
        overrides["auth_enabled"] = "false"


@router.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request, cfg: SettingsDep) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "settings.html",
        _build_settings_context(request, cfg),
    )


def _csrf_or_error(form: dict[str, str]) -> str | None:
    if not validate_csrf_token(form.get("csrf_token")):
        return "This form expired or was missing a security token. Reload Settings and try again."
    return None


@router.post("/settings", response_class=HTMLResponse)
async def page_update_settings(request: Request, cfg: SettingsDep) -> HTMLResponse:
    form = {
        key: value for key, value in (await request.form()).multi_items() if isinstance(value, str)
    }
    csrf_error = _csrf_or_error(form)
    if csrf_error:
        return templates.TemplateResponse(
            request,
            "settings.html",
            _build_settings_context(request, cfg, error=csrf_error),
            status_code=403,
        )
    overrides, field_errors, field_warnings, global_warnings = _process_settings_form(form)

    if field_errors:
        from app.settings_registry import SETTINGS_REGISTRY

        form_values = {
            spec.key: parse_form_value(form.get(spec.key), spec) for spec in SETTINGS_REGISTRY
        }
        return templates.TemplateResponse(
            request,
            "settings.html",
            _build_settings_context(
                request,
                cfg,
                form_values=form_values,
                field_errors=field_errors,
                field_warnings=field_warnings,
                error="Please fix the highlighted settings before saving.",
            ),
            status_code=400,
        )

    try:
        save_settings(overrides)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "settings.html",
            _build_settings_context(
                request,
                cfg,
                error=str(exc),
            ),
            status_code=400,
        )
    new_cfg = reload_settings()

    return templates.TemplateResponse(
        request,
        "settings.html",
        _build_settings_context(
            request,
            new_cfg,
            field_warnings=field_warnings,
            success="Settings saved successfully and reloaded.",
            warnings=global_warnings,
        ),
    )


@router.post("/settings/reset", response_class=HTMLResponse)
async def page_reset_setting(request: Request, cfg: SettingsDep) -> HTMLResponse:
    form = {
        key: value for key, value in (await request.form()).multi_items() if isinstance(value, str)
    }
    csrf_error = _csrf_or_error(form)
    if csrf_error:
        return templates.TemplateResponse(
            request,
            "settings.html",
            _build_settings_context(request, cfg, error=csrf_error),
            status_code=403,
        )
    key = (form.get("key") or "").strip()
    from app.settings_registry import SETTINGS_BY_KEY

    spec = SETTINGS_BY_KEY.get(key)
    if spec is None or not spec.mutable:
        return templates.TemplateResponse(
            request,
            "settings.html",
            _build_settings_context(request, cfg, error="That setting cannot be reset."),
            status_code=400,
        )
    try:
        reset_setting(key)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "settings.html",
            _build_settings_context(request, cfg, error=str(exc)),
            status_code=400,
        )
    new_cfg = reload_settings()
    return templates.TemplateResponse(
        request,
        "settings.html",
        _build_settings_context(
            request, new_cfg, success=f"{spec.label} reset to the deployment/default value."
        ),
    )


@router.post("/settings/extension/pair-code", response_class=HTMLResponse)
async def page_create_pairing_code(request: Request, cfg: SettingsDep) -> HTMLResponse:
    form = {
        key: value for key, value in (await request.form()).multi_items() if isinstance(value, str)
    }
    csrf_error = _csrf_or_error(form)
    if csrf_error:
        return templates.TemplateResponse(
            request,
            "settings.html",
            _build_settings_context(request, cfg, error=csrf_error),
            status_code=403,
        )
    if not cfg.extension_api_enabled:
        return templates.TemplateResponse(
            request,
            "settings.html",
            _build_settings_context(
                request,
                cfg,
                error="Enable the browser extension API before pairing a browser.",
            ),
            status_code=400,
        )
    from app.db import get_sync_session_factory
    from app.services.pairing import create_pairing_code

    factory = get_sync_session_factory()
    with factory() as session:
        row, code = create_pairing_code(
            session,
            created_by=cfg.auth_username,
            user_agent=request.headers.get("user-agent"),
        )
    ctx = _build_settings_context(
        request, cfg, success="Pairing code created. It expires in 5 minutes."
    )
    ctx["pairing_code"] = code
    ctx["pairing_id"] = row.id
    ctx["pairing_expires_at"] = row.expires_at.isoformat() + "Z"
    ctx["pairing_origin"] = cfg.extension_public_url or str(request.base_url).rstrip("/")
    return templates.TemplateResponse(request, "settings.html", ctx)


@router.get("/api/settings/extension/pairing/{pairing_id}/status")
async def api_pairing_status(pairing_id: str, cfg: SettingsDep) -> JSONResponse:
    """Authenticated Web-UI poll for pairing progress. No HMAC, token, or hash."""
    from app.db import get_sync_session_factory
    from app.queue import get_redis
    from app.services.pairing import PairingError, pairing_status

    try:
        redis = get_redis()
    except Exception:
        redis = None
    factory = get_sync_session_factory()
    try:
        with factory() as session:
            payload = pairing_status(session, pairing_id, redis=redis)
    except PairingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return JSONResponse(payload)


@router.post("/settings/extension/devices/{device_id}/revoke", response_class=HTMLResponse)
async def page_revoke_device(request: Request, device_id: str, cfg: SettingsDep) -> HTMLResponse:
    form = {
        key: value for key, value in (await request.form()).multi_items() if isinstance(value, str)
    }
    csrf_error = _csrf_or_error(form)
    if csrf_error:
        return templates.TemplateResponse(
            request,
            "settings.html",
            _build_settings_context(request, cfg, error=csrf_error),
            status_code=403,
        )
    from app.db import get_sync_session_factory
    from app.models import ExtensionDevice
    from app.queue import get_redis
    from app.services.pairing import revoke_device
    from app.services.ws_tickets import mark_device_revoked

    factory = get_sync_session_factory()
    with factory() as session:
        device = session.get(ExtensionDevice, device_id)
        if device is None:
            return templates.TemplateResponse(
                request,
                "settings.html",
                _build_settings_context(request, cfg, error="Device not found."),
                status_code=404,
            )
        revoke_device(session, device)
    try:
        mark_device_revoked(get_redis(), device_id)
    except Exception:
        logger.warning("Could not publish device revocation", exc_info=True)
    return templates.TemplateResponse(
        request,
        "settings.html",
        _build_settings_context(
            request, cfg, success="Device revoked. That browser must pair again."
        ),
    )


@router.post("/settings/extension/devices/revoke-all", response_class=HTMLResponse)
async def page_revoke_all_devices(request: Request, cfg: SettingsDep) -> HTMLResponse:
    form = {
        key: value for key, value in (await request.form()).multi_items() if isinstance(value, str)
    }
    csrf_error = _csrf_or_error(form)
    if csrf_error:
        return templates.TemplateResponse(
            request,
            "settings.html",
            _build_settings_context(request, cfg, error=csrf_error),
            status_code=403,
        )
    if (form.get("confirm_text") or "").strip() != "REVOKE":
        return templates.TemplateResponse(
            request,
            "settings.html",
            _build_settings_context(
                request,
                cfg,
                error="Type REVOKE to confirm revoking every paired browser.",
            ),
            status_code=400,
        )
    from sqlalchemy import select

    from app.db import get_sync_session_factory
    from app.models import ExtensionDevice
    from app.queue import get_redis
    from app.services.pairing import revoke_all_devices
    from app.services.ws_tickets import mark_device_revoked

    factory = get_sync_session_factory()
    with factory() as session:
        ids = [row.id for row in session.scalars(select(ExtensionDevice)).all()]
        count = revoke_all_devices(session)
    try:
        redis = get_redis()
        for device_id in ids:
            mark_device_revoked(redis, device_id)
    except Exception:
        logger.warning("Could not publish device revocations", exc_info=True)
    return templates.TemplateResponse(
        request,
        "settings.html",
        _build_settings_context(request, cfg, success=f"Revoked {count} device(s)."),
    )


@router.post("/settings/abs/test")
async def page_abs_test(request: Request, cfg: SettingsDep) -> JSONResponse:
    form = {
        key: value for key, value in (await request.form()).multi_items() if isinstance(value, str)
    }
    if not validate_csrf_token(form.get("csrf_token")):
        raise HTTPException(status_code=403, detail="Invalid security token")
    from app.services.audiobookshelf import AudiobookshelfClient

    base_url = (form.get("abs_base_url") or cfg.abs_base_url or "").strip()
    token = (form.get("abs_api_token") or "").strip() or (cfg.abs_api_token or "")
    current_id = (form.get("abs_library_id") or cfg.abs_library_id or "").strip()
    libraries, error = AudiobookshelfClient(cfg).list_libraries(base_url=base_url, api_token=token)
    if error:
        return JSONResponse(
            {
                "ok": False,
                "error": error,
                "libraries": [],
                "preferred_library_ids": [],
                "current_library_id": current_id or None,
                "library_missing": False,
                "warning": None,
            },
            status_code=400,
        )

    preferred = [
        lib["id"]
        for lib in libraries
        if str(lib.get("mediaType") or "").lower() in {"book", "audiobook"}
    ]
    known_ids = {lib["id"] for lib in libraries}
    library_missing = bool(current_id) and current_id not in known_ids
    warning = (
        "Saved library is no longer on this Audiobookshelf server. "
        "Pick a library below — nothing was changed until you Save."
        if library_missing
        else None
    )
    return JSONResponse(
        {
            "ok": True,
            "libraries": libraries,
            "preferred_library_ids": preferred,
            "current_library_id": current_id or None,
            "library_missing": library_missing,
            "warning": warning,
        }
    )
