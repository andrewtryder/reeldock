"""Diagnostics page and API routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

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
        },
    )


@router.get("/api/diagnostics")
async def api_diagnostics(cfg: SettingsDep) -> dict[str, Any]:
    checks = await asyncio.to_thread(run_diagnostics, cfg)
    return {"checks": [check.to_dict() for check in checks]}


@router.post("/api/diagnostics/test-scan")
async def api_diagnostics_test_scan(cfg: SettingsDep) -> dict[str, Any]:
    from app.diagnostics import check_abs_integration

    checks = await asyncio.to_thread(check_abs_integration, cfg, test_scan=True)
    scan_check = next((c for c in checks if c.id == "abs_scan"), None)
    return {"check": scan_check.to_dict() if scan_check else None}
