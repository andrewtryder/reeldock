"""Diagnostics page and API routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.csrf import issue_csrf_token, validate_csrf_token
from app.diagnostics import diagnostic_groups, run_diagnostics
from app.routes import SettingsDep
from app.routes.pages import templates

router = APIRouter(tags=["diagnostics"])


@router.get("/diagnostics", response_class=HTMLResponse)
async def page_diagnostics(request: Request, cfg: SettingsDep) -> HTMLResponse:
    checks = await asyncio.to_thread(run_diagnostics, cfg)
    return templates.TemplateResponse(
        request,
        "diagnostics.html",
        {
            "request": request,
            "settings": cfg,
            "groups": diagnostic_groups(checks),
            "csrf_token": issue_csrf_token(),
        },
    )


@router.get("/api/diagnostics")
async def api_diagnostics(cfg: SettingsDep) -> dict[str, Any]:
    checks = await asyncio.to_thread(run_diagnostics, cfg)
    return {"checks": [check.to_dict() for check in checks]}


async def _csrf_token_from_request(request: Request) -> str | None:
    header = request.headers.get("x-csrf-token")
    if header:
        return header
    form = await request.form()
    value = form.get("csrf_token")
    return str(value) if value else None


@router.post("/api/diagnostics/test-scan")
async def api_diagnostics_test_scan(request: Request, cfg: SettingsDep) -> dict[str, Any]:
    from app.diagnostics import check_abs_integration

    if not validate_csrf_token(await _csrf_token_from_request(request)):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    checks = await asyncio.to_thread(check_abs_integration, cfg, test_scan=True)
    scan_check = next((c for c in checks if c.id == "abs_scan"), None)
    return {"check": scan_check.to_dict() if scan_check else None}
