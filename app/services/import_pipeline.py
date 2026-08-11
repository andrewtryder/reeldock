"""ImportPipeline service: encapsulates the multi-stage download and conversion pipeline."""

from __future__ import annotations

import contextlib
import json
import logging
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Job, JobStatus
from app.services.audiobookshelf import AudiobookshelfClient
from app.services.ffmpeg import FfmpegProgress, FfmpegService
from app.services.filesystem import FilesystemService
from app.services.jobs import (
    sync_get_job,
    sync_mark_video_imported,
    sync_record_attempt,
    sync_update_job,
)
from app.services.ytdlp import (
    YTDLP_PHASE_PREPARING,
    YtDlpService,
    classify_ytdlp_download_line,
    parse_ytdlp_progress_line,
    ytdlp_postprocess_label,
)

logger = logging.getLogger(__name__)


@dataclass
class DownloadArtifact:
    path: Path
    format: str | None = None
    filesize: int | None = None
    title: str | None = None
    uploader: str | None = None
    chapter_count: int | None = None


@dataclass
class ConversionArtifact:
    path: Path
    used_fallback: bool
    verified: bool = False
    codec_name: str | None = None
    duration_seconds: float | None = None
    chapter_count: int | None = None
    filesize: int | None = None
    # Populated during staged-output pipeline. `staged_path` is where ffmpeg
    # writes; `final_path` is the Audiobookshelf-facing destination after
    # commit. `path` mirrors `staged_path` before commit and `final_path`
    # afterwards, matching whichever file is currently on disk.
    staged_path: Path | None = None
    final_path: Path | None = None


class PipelineCancelledError(Exception):
    """Raised when the pipeline is cancelled by the user."""

    pass


class PipelineFailedError(Exception):
    """Raised when a pipeline stage fails."""

    pass


class ImportPipeline:
    """Synchronously orchestrates a job's import pipeline stages."""

    # Stage-local progress uses 0-100 within the active stage (download/convert).
    # Indeterminate stages (verify/save/scan) clear percent and rely on labels.
    # Only a succeeded job may persist 100 with label "Complete".
    _M_COMPLETE = 100.0

    _THROTTLE_INTERVAL = 1.0  # seconds between DB writes during streaming phases

    @staticmethod
    def _split_extra_args(raw: str | None) -> list[str] | None:
        if raw is None:
            return None
        stripped = raw.strip()
        if not stripped:
            return []
        return shlex.split(stripped)

    def __init__(self, db: Session, settings: Settings, job_id: str) -> None:
        self.db = db
        self.settings = settings
        self.job_id = job_id
        self._last_progress = -1.0
        self._last_progress_write_time = 0.0
        self._progress_throttle_interval = self._THROTTLE_INTERVAL

    # ── Progress helpers ───────────────────────────────────────────────────

    @staticmethod
    def _map_range(value: float, start: float, end: float) -> float:
        """Map *value* (0.0-1.0) into [start, end]. Overshoot clamps to *end*."""
        ratio = max(0.0, min(1.0, value))
        return start + ratio * (end - start)

    def _set_progress(
        self,
        job: Job,
        *,
        percent: float | None = None,
        label: str | None = None,
        eta: str | None = None,
        speed: str | None = None,
        force: bool = False,
        clear_percent: bool = False,
    ) -> None:
        """Persist progress fields, throttled unless *force* is True.

        Stage-local percents may reach 100 for download/convert completion.
        Job-complete ``100`` + ``Complete`` is reserved for the success path.
        Indeterminate stages pass *clear_percent* so the UI does not reuse a
        prior stage percent.
        """
        now = time.time()
        pct_changed = percent is not None and round(percent) != round(job.progress_percent or 0)
        label_changed = label is not None and label != job.progress_label
        time_passed = now - self._last_progress_write_time > self._THROTTLE_INTERVAL

        if (
            not force
            and not clear_percent
            and not pct_changed
            and not label_changed
            and not time_passed
        ):
            return

        if clear_percent:
            job.progress = None
            job.progress_percent = None
            if label is not None:
                job.progress_label = label
            if eta is not None:
                job.progress_eta = eta
            if speed is not None:
                job.progress_speed = speed
            job.updated_at = datetime.now(tz=UTC)
            self.db.flush()
            self.db.commit()
            self._last_progress_write_time = now
            return

        kwargs: dict[str, Any] = {}
        if percent is not None:
            clamped = max(0.0, min(100.0, percent))
            kwargs["progress"] = round(clamped)
            kwargs["progress_percent"] = clamped
        if label is not None:
            kwargs["progress_label"] = label
        if eta is not None:
            kwargs["progress_eta"] = eta
        if speed is not None:
            kwargs["progress_speed"] = speed

        if kwargs:
            sync_update_job(self.db, job, **kwargs)
            self.db.commit()
            self._last_progress_write_time = now
            if percent is not None:
                self._last_progress = percent

    # ── Main entry point ───────────────────────────────────────────────────

    def run(self) -> None:
        """Execute the import pipeline."""
        started_at = datetime.now(tz=UTC)
        job = sync_get_job(self.db, self.job_id)
        if job is None:
            logger.error("Job %s not found in database", self.job_id)
            return

        # Initialize optional artifact variables to build metadata on completion/failure
        dl_artifact: DownloadArtifact | None = None
        conv_artifact: ConversionArtifact | None = None
        # Staged output paths are resolved inside the try block but referenced
        # by cancel/failure handlers for cleanup, so initialize them up front.
        staged_path: Path | None = None
        final_temp_path: Path | None = None

        # ── Setup ─────────────────────────────────────────────────────────────
        fs = FilesystemService(self.settings)
        log_path = fs.log_path(self.job_id)
        work_dir = fs.ensure_work_dir(self.job_id)

        # Increment attempts and update initial status
        job.attempts = (job.attempts or 0) + 1
        sync_update_job(
            self.db,
            job,
            status=JobStatus.running,
            phase="resolving_output",
            log_file_path=str(log_path),
            work_dir=str(work_dir),
        )
        self.db.commit()
        self._set_progress(job, percent=0.0, label="Setup", eta="", speed="", force=True)

        log_fh = log_path.open("a", encoding="utf-8")

        def log(msg: str) -> None:
            log_fh.write(msg + "\n")
            log_fh.flush()
            logger.info("[%s] %s", self.job_id, msg)

        def check_cancelled() -> bool:
            self.db.commit()
            self.db.refresh(job)
            return job.status == JobStatus.cancelled

        try:
            log(f"=== Job {self.job_id} started at {started_at.isoformat()} ===")
            log(f"[setup] Output root: {self.settings.output_root}")
            log(f"[setup] Work directory: {work_dir}")

            ytdlp_svc = YtDlpService(self.settings)
            ffmpeg_svc = FfmpegService(self.settings)
            abs_client = AudiobookshelfClient(self.settings)

            # ── Resolve output path ────────────────────────────────────────────
            dest_folder = job.destination_folder or ""
            output_title = job.output_title or job.source_title or "Unknown"
            video_id = job.video_id or "unknown"

            try:
                # Final audiobook container is always .m4b regardless of legacy
                # per-job output_extension overrides.
                output_path = fs.resolve_output_path(
                    dest_folder,
                    output_title,
                    video_id,
                    job.collision_mode,
                    extension="m4b",
                    filename_template=job.filename_template,
                    uploader=job.uploader,
                    channel=job.channel,
                    upload_date=job.upload_date,
                )
            except ValueError as exc:
                raise PipelineFailedError(f"Invalid output path: {exc}") from exc

            eff_dry_run = self.settings.dry_run or job.dry_run
            eff_ytdlp_extra = self._split_extra_args(job.ytdlp_extra_args)
            eff_ffmpeg_extra = self._split_extra_args(job.ffmpeg_extra_args)
            eff_cookies = Path(job.cookies_file) if job.cookies_file else None
            # Source extract format is an internal constant (m4a). Quality
            # presets map to --audio-quality only; YTDLP_AUDIO_FORMAT is ignored.
            eff_audio_format = "m4a"
            eff_audio_quality = job.audio_quality
            eff_loudness_normalize = (
                job.loudness_normalize
                if job.loudness_normalize is not None
                else self.settings.loudness_normalize
            )
            eff_loudness_target = job.loudness_target_lufs or self.settings.loudness_target_lufs
            eff_loudness_bitrate = (
                job.loudness_audio_bitrate or self.settings.loudness_audio_bitrate
            )

            # Stage conversion inside the job work directory so scanners never
            # see partial .m4b files in the Audiobookshelf-facing output root.
            staged_path = fs.staged_output_path(self.job_id, output_path)
            final_temp_path = output_path.with_name(output_path.name + ".partial")

            log(f"[setup] Final output path: {output_path}")
            log(f"[setup] Staged output path: {staged_path}")
            log(f"[setup] Final temp (commit) sibling: {final_temp_path}")
            log(f"URL: {job.url}")
            log(f"DRY_RUN: {eff_dry_run}")
            log(f"LOUDNESS_NORMALIZE: {eff_loudness_normalize}")
            log(f"COLLISION_MODE: {job.collision_mode}")

            self._set_progress(job, percent=2.0, label="Setup complete", eta="", speed="")

            # ── Collision skip: keep existing file, do not re-download/overwrite ─
            if job.collision_mode == "skip" and output_path.exists():
                log(
                    f"[setup] Collision mode=skip and file exists; "
                    f"reusing {output_path} without download or conversion"
                )
                # Filename collision is not proof this video_id produced the
                # existing file — do not write ImportedVideo on this path.
                log(
                    "[setup] Dedup ledger not updated for collision skip "
                    "(existing file ownership for this video_id is unconfirmed)"
                )
                existing_size = output_path.stat().st_size
                self._set_progress(
                    job,
                    percent=self._M_COMPLETE,
                    label="Skipped (file exists)",
                    eta="",
                    speed="",
                    force=True,
                )
                sync_update_job(
                    self.db,
                    job,
                    status=JobStatus.succeeded,
                    phase="skipped_collision",
                    final_output_path=str(output_path),
                    output_file_size=existing_size,
                )
                self.db.commit()
                sync_record_attempt(
                    self.db,
                    job,
                    status="succeeded",
                    started_at=started_at,
                    finished_at=datetime.now(tz=UTC),
                    artifact_metadata=json.dumps(
                        {
                            "collision": {
                                "mode": "skip",
                                "path": str(output_path),
                                "filesize": existing_size,
                            }
                        }
                    ),
                )
                self.db.commit()
                log(f"=== Job {self.job_id} skipped (collision) ===")
                return

            # ── DRY RUN Mode ──────────────────────────────────────────────────
            if eff_dry_run:
                log("--- DRY RUN: building commands only ---")
                dl_template = ytdlp_svc.get_output_template(self.job_id)
                dl_cmd = ytdlp_svc.build_download_command(
                    job.url,
                    self.job_id,
                    dl_template,
                    embed_metadata=job.embed_metadata,
                    embed_thumbnail=job.embed_thumbnail,
                    embed_chapters=job.embed_chapters,
                    audio_format=eff_audio_format,
                    audio_quality=eff_audio_quality,
                    sponsorblock_remove=job.sponsorblock_remove,
                    cookies_file=eff_cookies,
                    extra_args=eff_ytdlp_extra,
                )
                log(f"[download] yt-dlp command: {' '.join(dl_cmd)}")

                fake_m4a = work_dir / "fake_download.m4a"
                # In real runs ffmpeg writes to staged_path; commit later moves
                # that file into output_path. Show both commands here so the
                # dry-run log reflects the staged-output flow.
                cmd_p = ffmpeg_svc.build_remux_command(
                    fake_m4a,
                    staged_path,
                    extra_args=eff_ffmpeg_extra,
                    loudness_normalize=eff_loudness_normalize,
                    loudness_target_lufs=eff_loudness_target,
                    audio_bitrate=eff_loudness_bitrate,
                )
                cmd_f = ffmpeg_svc.build_remux_command_fallback(
                    fake_m4a,
                    staged_path,
                    extra_args=eff_ffmpeg_extra,
                    loudness_normalize=eff_loudness_normalize,
                    loudness_target_lufs=eff_loudness_target,
                    audio_bitrate=eff_loudness_bitrate,
                )
                log(f"[convert] ffmpeg primary (staged): {' '.join(cmd_p)}")
                log(f"[convert] ffmpeg fallback (staged): {' '.join(cmd_f)}")
                log(f"[commit] Would copy {staged_path} -> {final_temp_path} -> {output_path}")

                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"DRY RUN fake .m4b content")
                log(f"DRY RUN: created fake output file at {output_path}")

                if check_cancelled():
                    raise PipelineCancelledError()

                self._set_progress(
                    job,
                    percent=self._M_COMPLETE,
                    label="Complete",
                    eta="",
                    speed="",
                    force=True,
                )
                sync_update_job(
                    self.db,
                    job,
                    status=JobStatus.succeeded,
                    phase="succeeded",
                    final_output_path=str(output_path),
                    output_file_size=output_path.stat().st_size,
                )
                self.db.commit()
                sync_record_attempt(
                    self.db,
                    job,
                    status="succeeded",
                    started_at=started_at,
                    finished_at=datetime.now(tz=UTC),
                )
                self.db.commit()
                log(f"=== Job {self.job_id} completed successfully ===")
                return

            if check_cancelled():
                raise PipelineCancelledError()

            # ── Download ──────────────────────────────────────────────────────
            sync_update_job(
                self.db,
                job,
                status=JobStatus.downloading,
                phase="downloading",
            )
            self.db.commit()
            self._set_progress(
                job,
                percent=0.0,
                label="Downloading source…",
                eta="",
                speed="",
                force=True,
            )
            log("[download] Starting yt-dlp")

            dl_template = ytdlp_svc.get_output_template(self.job_id)
            # Bypass yt-dlp's download-archive on retry attempts: archive may
            # record success before conversion/commit finishes. Allow-reimport
            # also bypasses so intentional redownloads are not blocked.
            bypass_archive = bool(job.allow_reimport) or (job.attempts or 1) > 1

            if self.settings.release_smoke_fixture:
                from app.release_smoke import resolve_fixture_dir, stage_download_fixture

                fixture_dir = resolve_fixture_dir(self.settings.release_smoke_fixture_dir)
                log(
                    "[download] RELEASE_SMOKE_FIXTURE=1 — staging canned audio "
                    f"from {fixture_dir} (skipping yt-dlp network)"
                )
                staged = stage_download_fixture(self.job_id, self.settings.work_dir, fixture_dir)
                log(f"[download] Staged fixture at {staged}")
                # Simulate yt-dlp having written the archive on a prior attempt.
                if bypass_archive and self.settings.archive_file:
                    self.settings.archive_file.parent.mkdir(parents=True, exist_ok=True)
                    self.settings.archive_file.touch(exist_ok=True)
                if self.settings.release_smoke_fail_once and (job.attempts or 1) == 1:
                    if self.settings.archive_file and job.video_id:
                        self.settings.archive_file.parent.mkdir(parents=True, exist_ok=True)
                        with self.settings.archive_file.open("a", encoding="utf-8") as fh:
                            fh.write(f"{job.video_id}\n")
                        log(
                            f"[download] RELEASE_SMOKE_FAIL_ONCE: wrote {job.video_id} "
                            "to archive, failing first attempt"
                        )
                    raise PipelineFailedError(
                        "release smoke intentional first-attempt failure after download"
                    )
            else:
                dl_cmd = ytdlp_svc.build_download_command(
                    job.url,
                    self.job_id,
                    dl_template,
                    embed_metadata=job.embed_metadata,
                    embed_thumbnail=job.embed_thumbnail,
                    embed_chapters=job.embed_chapters,
                    force_archive_bypass=bypass_archive,
                    audio_format=eff_audio_format,
                    audio_quality=eff_audio_quality,
                    sponsorblock_remove=job.sponsorblock_remove,
                    cookies_file=eff_cookies,
                    extra_args=eff_ytdlp_extra,
                )
                if bypass_archive:
                    log(
                        "[download] Bypassing yt-dlp download-archive "
                        f"(allow_reimport={bool(job.allow_reimport)} attempts={job.attempts})"
                    )

                # Ensure archive parent dir exists
                if self.settings.archive_file:
                    self.settings.archive_file.parent.mkdir(parents=True, exist_ok=True)

                dl_success = self._run_subprocess(
                    dl_cmd, log, check_cancelled, is_download=True, job=job
                )
                if not dl_success:
                    if check_cancelled():
                        raise PipelineCancelledError()
                    raise PipelineFailedError("yt-dlp download failed")

            if check_cancelled():
                raise PipelineCancelledError()

            self._set_progress(
                job,
                clear_percent=True,
                label="Download complete",
                eta="",
                speed="",
                force=True,
            )
            sync_update_job(self.db, job, phase="download_complete")
            self.db.commit()

            # ── Locate Artifact ────────────────────────────────────────────────
            self._set_progress(
                job,
                clear_percent=True,
                label="Locating downloaded audio",
                eta="",
                speed="",
                force=True,
            )
            sync_update_job(
                self.db,
                job,
                status=JobStatus.postprocessing,
                phase="locating_artifact",
            )
            self.db.commit()

            downloaded_file = ytdlp_svc.find_downloaded_file(
                self.job_id, preferred_format=eff_audio_format
            )
            if downloaded_file is None:
                # Check download archive message
                log_content = ""
                if log_path.exists():
                    log_content = log_path.read_text(encoding="utf-8", errors="replace")

                if "has already been recorded in the archive" in log_content:
                    err_msg = (
                        "Video has already been recorded in the download archive. "
                        "Retry this job to bypass the archive, or remove the video ID "
                        "from your youtube-archive.txt file."
                    )
                else:
                    err_msg = "Could not locate downloaded audio file in work directory"
                raise PipelineFailedError(err_msg)

            # Wrap in DownloadArtifact
            dl_artifact = DownloadArtifact(
                path=downloaded_file,
                format=downloaded_file.suffix.lstrip(".") or eff_audio_format,
                filesize=downloaded_file.stat().st_size,
                title=job.source_title,
                uploader=job.uploader,
                chapter_count=job.chapter_count,
            )

            log(f"[download] Completed: {dl_artifact.path}")
            log(f"[download] Artifact: format={dl_artifact.format} size={dl_artifact.filesize}")

            self._set_progress(
                job,
                clear_percent=True,
                label="Download artifact ready",
                eta="",
                speed="",
                force=True,
            )

            if check_cancelled():
                raise PipelineCancelledError()

            # ── Remux to .m4b ─────────────────────────────────────────────────
            self._set_progress(
                job,
                percent=0.0,
                label="Preparing conversion",
                eta="",
                speed="",
                force=True,
            )
            sync_update_job(
                self.db,
                job,
                status=JobStatus.converting,
                phase="converting",
            )
            self.db.commit()
            log("[convert] Starting ffmpeg remux")
            log(f"[convert] Input: {dl_artifact.path}")
            log(f"[convert] Staged output: {staged_path}")
            log(f"[convert] Final output (deferred): {output_path}")

            # Only the staged directory needs to exist during conversion. The
            # final output directory is created at commit time to avoid touching
            # the Audiobookshelf-facing tree until a verified file is ready.
            staged_path.parent.mkdir(parents=True, exist_ok=True)

            # Determine media duration for conversion progress mapping
            media_duration: float | None = float(job.duration) if job.duration is not None else None
            if media_duration is None or media_duration <= 0:
                try:
                    probe_in = ffmpeg_svc.verify_output(dl_artifact.path)
                    if probe_in.duration_seconds and probe_in.duration_seconds > 0:
                        media_duration = float(probe_in.duration_seconds)
                        if not job.duration:
                            job.duration = round(media_duration)
                            self.db.commit()
                except FileNotFoundError, RuntimeError, OSError:
                    media_duration = None

            # Build progress callback for ffmpeg
            def _on_ffmpeg_progress(fp: FfmpegProgress) -> None:
                if (
                    media_duration is not None
                    and media_duration > 0
                    and fp.out_time_seconds is not None
                ):
                    ratio = min(fp.out_time_seconds / media_duration, 1.0)
                    stage_pct = round(ratio * 100.0, 1)
                    processed = fp.out_time_seconds
                    label = (
                        "Retrying conversion without cover art"
                        if fp.raw.get("_fallback")
                        else f"Converting audiobook… {processed:.0f}s / {media_duration:.0f}s"
                    )
                    self._set_progress(
                        job,
                        percent=stage_pct,
                        label=label,
                        speed=fp.speed,
                    )
                else:
                    self._set_progress(
                        job,
                        clear_percent=True,
                        label="Converting audiobook…",
                        speed=fp.speed or "",
                    )

            # Wrap on_progress to inject fallback flag
            _in_fallback = False

            def _on_ffmpeg_progress_primary(fp: FfmpegProgress) -> None:
                _on_ffmpeg_progress(fp)

            def _on_ffmpeg_progress_fallback(fp: FfmpegProgress) -> None:
                fp.raw["_fallback"] = "1"
                _on_ffmpeg_progress(fp)

            remux_result = ffmpeg_svc.run_remux(
                dl_artifact.path,
                staged_path,
                log_fh,
                check_cancelled=check_cancelled,
                on_progress=_on_ffmpeg_progress,
                extra_args=eff_ffmpeg_extra,
                loudness_normalize=eff_loudness_normalize,
                loudness_target_lufs=eff_loudness_target,
                audio_bitrate=eff_loudness_bitrate,
            )

            if not remux_result.success:
                if check_cancelled():
                    raise PipelineCancelledError()
                raise PipelineFailedError(f"ffmpeg remux failed: {remux_result.error}")

            self._set_progress(
                job,
                percent=100.0,
                label="Conversion complete",
                eta="",
                speed="",
                force=True,
            )

            # Wrap in ConversionArtifact. `path` is set to the staged file here;
            # it is rewritten to the final output path after successful commit.
            conv_artifact = ConversionArtifact(
                path=staged_path,
                staged_path=staged_path,
                final_path=output_path,
                used_fallback=remux_result.used_fallback,
                filesize=staged_path.stat().st_size if staged_path.exists() else None,
            )

            log(f"[convert] Completed (staged): {conv_artifact.path}")
            log(f"[convert] Used fallback: {str(conv_artifact.used_fallback).lower()}")

            if check_cancelled():
                raise PipelineCancelledError()

            sync_update_job(self.db, job, phase="conversion_complete")
            self.db.commit()

            # ── Verify ────────────────────────────────────────────────────────
            self._set_progress(
                job,
                clear_percent=True,
                label="Checking audio, chapters and metadata…",
                eta="",
                speed="",
                force=True,
            )
            sync_update_job(
                self.db,
                job,
                status=JobStatus.verifying,
                phase="verifying",
            )
            self.db.commit()
            log(f"[verify] Running ffprobe on staged output: {staged_path}")

            try:
                probe = ffmpeg_svc.verify_output(staged_path)
                conv_artifact.verified = True
                conv_artifact.codec_name = probe.codec_name
                conv_artifact.duration_seconds = probe.duration_seconds
                conv_artifact.chapter_count = probe.chapter_count
                conv_artifact.filesize = probe.file_size

                log(f"[verify] Audio codec: {conv_artifact.codec_name}")
                log(f"[verify] Duration: {conv_artifact.duration_seconds}s")
                log(f"[verify] Chapters: {conv_artifact.chapter_count}")
                log(f"[verify] File size: {conv_artifact.filesize} bytes")

                self._set_progress(
                    job,
                    clear_percent=True,
                    label="Output verified",
                    eta="",
                    speed="",
                    force=True,
                )
                sync_update_job(
                    self.db,
                    job,
                    chapter_count=conv_artifact.chapter_count,
                    phase="verified",
                )
                self.db.commit()
            except (FileNotFoundError, RuntimeError) as exc:
                self._set_progress(
                    job,
                    clear_percent=True,
                    label="Verification failed",
                    eta="",
                    speed="",
                    force=True,
                )
                raise PipelineFailedError(f"Output verification failed: {exc}") from exc

            if check_cancelled():
                raise PipelineCancelledError()

            # ── Commit staged output to final destination ─────────────────────
            self._set_progress(
                job,
                clear_percent=True,
                label="Saving audiobook to library…",
                eta="",
                speed="",
                force=True,
            )
            sync_update_job(self.db, job, phase="committing_output")
            self.db.commit()
            log(f"[commit] Publishing staged output to {output_path}")
            log(f"[commit] Via temp sibling: {final_temp_path}")

            try:
                fs.commit_staged_output(staged_path, output_path)
            except (OSError, RuntimeError) as exc:
                raise PipelineFailedError(f"Failed to commit output: {exc}") from exc

            if not output_path.exists():
                raise PipelineFailedError("Commit reported success but final output is missing")

            committed_size = output_path.stat().st_size
            if conv_artifact.filesize is not None and committed_size != conv_artifact.filesize:
                raise PipelineFailedError(
                    "Committed file size does not match verified staged size "
                    f"(staged={conv_artifact.filesize} committed={committed_size})"
                )

            # From here on, conv_artifact.path refers to the committed file.
            conv_artifact.path = output_path
            log(f"[commit] Final output committed: {output_path} ({committed_size} bytes)")
            self._set_progress(
                job,
                clear_percent=True,
                label="Audiobook saved to library",
                eta="",
                speed="",
                force=True,
            )
            sync_update_job(self.db, job, phase="output_committed")
            self.db.commit()

            if check_cancelled():
                raise PipelineCancelledError()

            # ── Audiobookshelf Scan ───────────────────────────────────────────
            # Per-job checkbox controls whether this job scans. Global
            # ABS_SCAN_AFTER_SUCCESS is only the UI default for that checkbox.
            if job.trigger_abs_scan:
                self._set_progress(
                    job,
                    clear_percent=True,
                    label="Refreshing Audiobookshelf…",
                    eta="",
                    speed="",
                    force=True,
                )
                sync_update_job(
                    self.db,
                    job,
                    status=JobStatus.scanning,
                    phase="scanning",
                )
                self.db.commit()
                log("[scan] Triggering Audiobookshelf scan")
                scan_result = abs_client.trigger_scan()
                if scan_result.skipped:
                    log("[scan] ABS scan skipped (not configured)")
                    self._set_progress(
                        job,
                        clear_percent=True,
                        label="Audiobookshelf scan skipped",
                        eta="",
                        speed="",
                        force=True,
                    )
                elif scan_result.success:
                    log("[scan] ABS scan triggered successfully")
                    self._set_progress(
                        job,
                        clear_percent=True,
                        label="Audiobookshelf refreshed",
                        eta="",
                        speed="",
                        force=True,
                    )
                else:
                    log(f"[scan] ABS scan failed (non-fatal): {scan_result.error}")
                    self._set_progress(
                        job,
                        clear_percent=True,
                        label="Audiobookshelf scan failed",
                        eta="",
                        speed="",
                        force=True,
                    )

            if check_cancelled():
                raise PipelineCancelledError()

            # ── Cleanup ───────────────────────────────────────────────────────
            self._set_progress(
                job,
                clear_percent=True,
                label="Cleaning up temporary files",
                eta="",
                speed="",
                force=True,
            )
            sync_update_job(self.db, job, phase="cleanup")
            self.db.commit()
            # Always remove the staged file and any leftover temp sibling after a
            # successful commit. The work-dir cleanup below remains settings-gated.
            fs.cleanup_output_partials(staged_path, final_temp_path)
            if self.settings.cleanup_temp_on_success:
                fs.cleanup_work_dir(self.job_id)
                log("[cleanup] Temporary files removed")
            else:
                log("[cleanup] Skipped work-dir cleanup (cleanup_temp_on_success=false)")

            self._set_progress(
                job,
                clear_percent=True,
                label="Cleanup complete",
                eta="",
                speed="",
                force=True,
            )

            # Record successful imports in the DB-backed dedup ledger before
            # marking the job succeeded. This also protects against races.
            if not sync_mark_video_imported(self.db, job, overwrite=bool(job.allow_reimport)):
                raise PipelineFailedError(
                    "Video has already been imported. Duplicate import blocked."
                )

            # ── Success ───────────────────────────────────────────────────────
            self._set_progress(
                job,
                percent=self._M_COMPLETE,
                label="Complete",
                eta="",
                speed="",
                force=True,
            )
            output_file_size = conv_artifact.filesize
            if output_file_size is None and output_path.exists():
                output_file_size = output_path.stat().st_size
            sync_update_job(
                self.db,
                job,
                status=JobStatus.succeeded,
                phase="succeeded",
                final_output_path=str(output_path),
                output_file_size=output_file_size,
            )
            self.db.commit()
            sync_record_attempt(
                self.db,
                job,
                status="succeeded",
                started_at=started_at,
                finished_at=datetime.now(tz=UTC),
                artifact_metadata=self._build_metadata_json(dl_artifact, conv_artifact),
            )
            self.db.commit()

            log(f"=== Job {self.job_id} completed successfully ===")
            log(f"Output: {output_path}")

        except PipelineCancelledError:
            log("Job execution halted due to cancellation.")
            self._set_progress(
                job,
                label="Cancelled",
                eta="",
                speed="",
                force=True,
            )
            sync_update_job(
                self.db,
                job,
                status=JobStatus.cancelled,
                phase="cancelled",
            )
            self.db.commit()
            sync_record_attempt(
                self.db,
                job,
                status="cancelled",
                started_at=started_at,
                finished_at=datetime.now(tz=UTC),
                artifact_metadata=self._build_metadata_json(dl_artifact, conv_artifact),
            )
            self.db.commit()
            # Clean up any staged/partial artifacts before removing the work
            # dir so a cancelled job never leaves a partial final .m4b behind.
            fs.cleanup_output_partials(staged_path, final_temp_path)
            if self.settings.cleanup_temp_on_failure:
                fs.cleanup_work_dir(self.job_id)

        except Exception as exc:
            err_msg = str(exc)
            log(f"FAILED: {err_msg}")
            self._set_progress(
                job,
                label="Failed",
                eta="",
                speed="",
                force=True,
            )
            sync_update_job(
                self.db,
                job,
                status=JobStatus.failed,
                phase="failed",
                error_message=err_msg,
            )
            self.db.commit()
            sync_record_attempt(
                self.db,
                job,
                status="failed",
                error_message=err_msg,
                started_at=started_at,
                finished_at=datetime.now(tz=UTC),
                artifact_metadata=self._build_metadata_json(dl_artifact, conv_artifact),
            )
            self.db.commit()
            # Clean up any staged/partial artifacts on failure. This must run
            # regardless of cleanup_temp_on_failure because the temp sibling
            # lives next to the final .m4b, not inside the work directory.
            fs.cleanup_output_partials(staged_path, final_temp_path)
            if self.settings.cleanup_temp_on_failure:
                fs.cleanup_work_dir(self.job_id)

        finally:
            with contextlib.suppress(Exception):
                log_fh.close()

    def _run_subprocess(
        self,
        cmd: list[str],
        log_func: Callable[[str], None],
        check_cancelled: Callable[[], bool],
        is_download: bool = False,
        job: Job | None = None,
    ) -> bool:
        """Run a subprocess, stream stdout to log, parse progress, check cancellation."""
        from app.services.process_runner import run_streaming_process

        def on_line(line: str) -> None:
            if is_download and job:
                progress_info = parse_ytdlp_progress_line(line)
                if progress_info and progress_info.percent is not None:
                    # Stage-local download percent (0-100); UI does not treat
                    # this as whole-job completion. At 100% the network transfer
                    # is done but yt-dlp may still ExtractAudio — clear percent.
                    dl_pct = max(0.0, min(100.0, float(progress_info.percent)))
                    now = time.time()

                    if dl_pct >= 100.0:
                        preparing = ytdlp_postprocess_label(YTDLP_PHASE_PREPARING)
                        if job.progress_percent is not None or job.progress_label != preparing:
                            self._set_progress(
                                job,
                                clear_percent=True,
                                label=preparing,
                                eta="",
                                speed="",
                                force=True,
                            )
                            self._last_progress = 100.0
                        return

                    pct_int = round(dl_pct)
                    prog_changed = pct_int != round(self._last_progress)
                    eta_changed = progress_info.eta != (job.progress_eta or "")
                    speed_changed = progress_info.speed != (job.progress_speed or "")
                    time_passed = now - self._last_progress_write_time > self._THROTTLE_INTERVAL

                    if prog_changed or eta_changed or speed_changed or time_passed:
                        sync_update_job(
                            self.db,
                            job,
                            progress=pct_int,
                            progress_percent=round(dl_pct, 1),
                            progress_eta=progress_info.eta,
                            progress_speed=progress_info.speed,
                            progress_label="Downloading source…",
                        )
                        self.db.commit()
                        self._last_progress = dl_pct
                        self._last_progress_write_time = now
                    return

                phase = classify_ytdlp_download_line(line)
                if phase:
                    label = ytdlp_postprocess_label(phase)
                    if job.progress_label != label or job.progress_percent is not None:
                        self._set_progress(
                            job,
                            clear_percent=True,
                            label=label,
                            eta="",
                            speed="",
                            force=True,
                        )

        res = run_streaming_process(
            cmd,
            log_line=log_func,
            check_cancelled=check_cancelled,
            on_line=on_line,
        )

        return res.returncode == 0 and not res.cancelled

    def _build_metadata_json(
        self,
        dl_artifact: DownloadArtifact | None,
        conv_artifact: ConversionArtifact | None,
    ) -> str | None:
        """Serialize DownloadArtifact and ConversionArtifact to a compact JSON string."""
        data: dict[str, Any] = {}
        if dl_artifact:
            data["download"] = {
                "path": str(dl_artifact.path),
                "format": dl_artifact.format,
                "filesize": dl_artifact.filesize,
            }
        if conv_artifact:
            data["conversion"] = {
                "path": str(conv_artifact.path),
                "staged_path": (
                    str(conv_artifact.staged_path)
                    if conv_artifact.staged_path is not None
                    else None
                ),
                "final_path": (
                    str(conv_artifact.final_path) if conv_artifact.final_path is not None else None
                ),
                "used_fallback": conv_artifact.used_fallback,
                "codec_name": conv_artifact.codec_name,
                "duration_seconds": conv_artifact.duration_seconds,
                "chapter_count": conv_artifact.chapter_count,
                "filesize": conv_artifact.filesize,
            }
        if not data:
            return None
        return json.dumps(data)
