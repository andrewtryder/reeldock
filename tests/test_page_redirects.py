"""UUID sanitizers for job/batch HTML redirects."""

from __future__ import annotations

import pytest
from app.routes.pages import _canonical_uuid, _job_page_redirect, _jobs_batch_redirect
from fastapi import HTTPException


def test_canonical_uuid_rejects_open_redirect_payload():
    with pytest.raises(HTTPException) as exc:
        _canonical_uuid("https://evil.example/jobs")
    assert exc.value.status_code == 404


def test_jobs_batch_redirect_uses_canonical_uuid():
    uid = "550e8400-e29b-41d4-a716-446655440000"
    response = _jobs_batch_redirect(uid.upper())
    assert response.status_code == 303
    assert response.headers["location"] == f"/jobs?batch={uid}"


def test_job_page_redirect_uses_canonical_uuid():
    uid = "550e8400-e29b-41d4-a716-446655440000"
    response = _job_page_redirect(uid)
    assert response.status_code == 303
    assert response.headers["location"] == f"/jobs/{uid}"
