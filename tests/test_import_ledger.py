"""Authoritative import ledger, claims, and archive-independence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from app.config import Settings
from app.models import Base, ImportedVideo, Job, JobStatus, VideoImportClaim
from app.services.ffmpeg import FfprobeResult, RemuxResult
from app.services.import_ledger import (
    acquire_claim_sync,
    expire_stale_claims_sync,
    reconcile_import_state,
    release_claim_sync,
    renew_claim_sync,
)
from app.services.import_pipeline import ImportPipeline
from app.services.jobs import DuplicateVideoError, create_job
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def ledger_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def mock_settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.output_root = tmp_path / "podcasts"
    s.work_dir = tmp_path / "work"
    s.archive_file = tmp_path / "archive.txt"
    s.ytdlp_bin = "yt-dlp"
    s.ffmpeg_bin = "ffmpeg"
    s.ffprobe_bin = "ffprobe"
    s.dry_run = False
    s.cleanup_temp_on_success = True
    s.cleanup_temp_on_failure = True
    return s


def _job(
    job_id: str,
    video_id: str,
    *,
    status: JobStatus = JobStatus.queued,
    allow_reimport: bool = False,
    url: str | None = None,
) -> Job:
    return Job(
        id=job_id,
        url=url or f"https://youtube.com/watch?v={video_id}",
        video_id=video_id,
        status=status,
        output_title=f"Title {video_id}",
        destination_folder="Lib",
        collision_mode="overwrite",
        allow_reimport=allow_reimport,
    )


def _fake_remux_writes_staged(payload: bytes):
    def _write(_input_path, staged_path, _log_fh=None, **_kwargs):
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_bytes(payload)
        return RemuxResult(success=True, used_fallback=False)

    return _write


def _run_successful_pipeline(session, settings: Settings, job_id: str, tmp_path: Path) -> None:
    mock_proc = MagicMock()
    mock_proc.stdout = ["[download] 100% of 1.00MiB\n"]
    mock_proc.returncode = 0
    downloaded = tmp_path / "work" / job_id / "download" / "audio.m4a"
    downloaded.parent.mkdir(parents=True, exist_ok=True)
    downloaded.write_bytes(b"audio")

    with (
        patch("app.services.process_runner.subprocess.Popen", return_value=mock_proc),
        patch(
            "app.services.import_pipeline.YtDlpService.find_downloaded_file",
            return_value=downloaded,
        ),
        patch(
            "app.services.import_pipeline.FfmpegService.run_remux",
            side_effect=_fake_remux_writes_staged(b"x" * 50),
        ),
        patch(
            "app.services.import_pipeline.FfmpegService.verify_output",
            return_value=FfprobeResult(
                file_size=50,
                has_audio=True,
                chapter_count=0,
                duration_seconds=5.0,
                codec_name="aac",
            ),
        ),
    ):
        ImportPipeline(session, settings, job_id).run()


def test_a_first_import_writes_ledger(ledger_db, mock_settings, tmp_path):
    ledger_db.add(_job("job-a", "vidA"))
    ledger_db.commit()
    _run_successful_pipeline(ledger_db, mock_settings, "job-a", tmp_path)
    job = ledger_db.get(Job, "job-a")
    assert job is not None
    assert job.status == JobStatus.succeeded
    row = ledger_db.get(ImportedVideo, "vidA")
    assert row is not None
    assert row.job_id == "job-a"
    assert ledger_db.get(VideoImportClaim, "vidA") is None


@pytest.mark.asyncio
async def test_b_second_submit_is_duplicate():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            ImportedVideo(
                video_id="vidB",
                job_id="old",
                source_url="https://youtube.com/watch?v=vidB",
                source_title="Old",
            )
        )
        await session.commit()
        with pytest.raises(DuplicateVideoError, match="already been imported"):
            await create_job(
                session,
                "https://youtube.com/watch?v=vidB",
                Settings(),
                video_id="vidB",
            )


@pytest.mark.asyncio
async def test_c_allow_reimport_skips_ledger():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            ImportedVideo(
                video_id="vidC",
                job_id="old",
                source_url="https://youtube.com/watch?v=vidC",
                source_title="Old",
            )
        )
        await session.commit()
        job = await create_job(
            session,
            "https://youtube.com/watch?v=vidC",
            Settings(),
            video_id="vidC",
            allow_reimport=True,
        )
        assert job.allow_reimport is True
        claim = await session.get(VideoImportClaim, "vidC")
        assert claim is not None
        assert claim.job_id == job.id


@pytest.mark.asyncio
async def test_skipped_collision_reconcile_allows_later_import():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            Job(
                id="job-skip-later",
                url="https://youtube.com/watch?v=vidSkipLater",
                video_id="vidSkipLater",
                status=JobStatus.succeeded,
                phase="skipped_collision",
                owned_import=False,
                output_title="Skip",
            )
        )
        await session.commit()
        from app.services.import_ledger import reconcile_import_state_async

        await reconcile_import_state_async(session)
        await session.commit()
        assert await session.get(ImportedVideo, "vidSkipLater") is None
        job = await create_job(
            session,
            "https://youtube.com/watch?v=vidSkipLater",
            Settings(),
            video_id="vidSkipLater",
            allow_reimport=True,
        )
        assert job.video_id == "vidSkipLater"


def test_d_failed_job_releases_claim_without_ledger(ledger_db, mock_settings):
    ledger_db.add(_job("job-d", "vidD"))
    ledger_db.commit()
    mock_settings.dry_run = False
    with (
        patch(
            "app.services.import_pipeline.YtDlpService.build_download_command",
            return_value=["yt-dlp", "--", "https://youtube.com/watch?v=vidD"],
        ),
        patch("app.services.process_runner.subprocess.Popen") as mock_popen,
    ):
        proc = MagicMock()
        proc.stdout = ["ERROR: boom\n"]
        proc.returncode = 1
        mock_popen.return_value = proc
        ImportPipeline(ledger_db, mock_settings, "job-d").run()
    job = ledger_db.get(Job, "job-d")
    assert job is not None
    assert job.status == JobStatus.failed
    assert ledger_db.get(ImportedVideo, "vidD") is None
    assert ledger_db.get(VideoImportClaim, "vidD") is None


@patch("app.services.process_runner.subprocess.Popen")
def test_e_cancelled_job_releases_claim(mock_popen, ledger_db, mock_settings):
    job = _job("job-e", "vidE")
    ledger_db.add(job)
    ledger_db.commit()

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.terminate.side_effect = lambda: setattr(mock_proc, "poll", lambda: -15)

    class CancelStream:
        def __init__(self) -> None:
            self.yielded = False

        def __iter__(self):
            return self

        def __next__(self):
            if self.yielded:
                raise StopIteration
            SessionLocal = sessionmaker(bind=ledger_db.bind)
            with SessionLocal() as local_session:
                local_job = local_session.get(Job, job.id)
                if local_job:
                    local_job.status = JobStatus.cancelled
                    local_session.commit()
            self.yielded = True
            return "[download] Starting download...\n"

    mock_proc.stdout = CancelStream()
    mock_proc.returncode = 0
    mock_popen.return_value = mock_proc
    ImportPipeline(ledger_db, mock_settings, "job-e").run()
    ledger_db.refresh(job)
    assert job.status == JobStatus.cancelled
    assert ledger_db.get(ImportedVideo, "vidE") is None
    assert ledger_db.get(VideoImportClaim, "vidE") is None


def test_f_legacy_archive_does_not_block_db_absent_id(ledger_db, mock_settings, tmp_path):
    mock_settings.archive_file.write_text("vidF\n", encoding="utf-8")
    ledger_db.add(_job("job-f", "vidF"))
    ledger_db.commit()
    _run_successful_pipeline(ledger_db, mock_settings, "job-f", tmp_path)
    job = ledger_db.get(Job, "job-f")
    assert job is not None
    assert job.status == JobStatus.succeeded
    assert ledger_db.get(ImportedVideo, "vidF") is not None


def test_g_claim_blocks_concurrent_second_job(ledger_db):
    ledger_db.add(_job("job-g1", "vidG"))
    ledger_db.commit()
    assert acquire_claim_sync(ledger_db, "vidG", "job-g1") is True
    ledger_db.commit()
    assert acquire_claim_sync(ledger_db, "vidG", "job-g2") is False


def test_h_expired_claim_can_be_taken_over_and_reconcile_backfills(ledger_db):
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    ledger_db.add(_job("job-h1", "vidH", status=JobStatus.failed))
    ledger_db.add(
        VideoImportClaim(
            video_id="vidH",
            job_id="job-h1",
            claimed_at=now - timedelta(hours=8),
            expires_at=now - timedelta(minutes=1),
        )
    )
    ledger_db.add(
        _job("job-h2", "vidH2", status=JobStatus.succeeded, url="https://youtube.com/watch?v=vidH2")
    )
    skipped = _job(
        "job-h-skip",
        "vidHSkip",
        status=JobStatus.succeeded,
        url="https://youtube.com/watch?v=vidHSkip",
    )
    skipped.phase = "skipped_collision"
    skipped.owned_import = False
    ledger_db.add(skipped)
    ledger_db.commit()

    assert acquire_claim_sync(ledger_db, "vidH", "job-h-new") is True
    release_claim_sync(ledger_db, "vidH", "job-h-new")
    reconcile_import_state(ledger_db)
    ledger_db.commit()
    assert ledger_db.get(ImportedVideo, "vidH2") is not None
    assert ledger_db.get(ImportedVideo, "vidH2").job_id == "job-h2"
    assert ledger_db.get(ImportedVideo, "vidHSkip") is None


def test_running_job_keeps_claim_after_old_lease_wall(ledger_db):
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    job = _job("job-live", "vidLive", status=JobStatus.running)
    ledger_db.add(job)
    ledger_db.add(
        VideoImportClaim(
            video_id="vidLive",
            job_id="job-live",
            claimed_at=now - timedelta(hours=8),
            expires_at=now - timedelta(hours=7),
        )
    )
    ledger_db.commit()

    assert expire_stale_claims_sync(ledger_db) == 0
    assert acquire_claim_sync(ledger_db, "vidLive", "job-other") is False
    renew_claim_sync(ledger_db, "vidLive", "job-live")
    ledger_db.commit()
    claim = ledger_db.get(VideoImportClaim, "vidLive")
    assert claim is not None
    assert claim.job_id == "job-live"
    assert claim.expires_at > now
    assert acquire_claim_sync(ledger_db, "vidLive", "job-other") is False


def test_two_takeovers_of_expired_terminal_claim_one_winner(tmp_path: Path):
    from concurrent.futures import ThreadPoolExecutor

    engine = create_engine(
        f"sqlite:///{tmp_path / 'claim-race.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    with factory() as session:
        session.add(_job("job-old", "vidRace", status=JobStatus.failed))
        session.add(
            VideoImportClaim(
                video_id="vidRace",
                job_id="job-old",
                claimed_at=now - timedelta(hours=2),
                expires_at=now - timedelta(minutes=1),
            )
        )
        session.commit()

    def attempt(job_id: str) -> bool:
        with factory() as session:
            won = acquire_claim_sync(session, "vidRace", job_id)
            session.commit()
            return won

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result()
            for future in (pool.submit(attempt, "job-a"), pool.submit(attempt, "job-b"))
        ]
    assert results.count(True) == 1
    with factory() as session:
        claim = session.get(VideoImportClaim, "vidRace")
        assert claim is not None
        assert claim.job_id in {"job-a", "job-b"}
