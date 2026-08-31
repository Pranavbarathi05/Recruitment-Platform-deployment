"""
Health and language information endpoints for Compiler 1.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..languages import get_all_adapters
from ..schemas import HealthResponse, LanguageInfo

router = APIRouter(tags=["health"])

_SERVICE_START = datetime.now(timezone.utc)
_VERSION = os.getenv("COMPILER_VERSION", "0.1.0")


@router.get("/health")
async def health() -> JSONResponse:
    """Report compiler service health, available languages, and capacity."""
    adapters = get_all_adapters()
    lang_infos = []
    for name, adapter in sorted(adapters.items()):
        available = adapter.is_available()
        ver = adapter.version() if available else None
        lang_infos.append(LanguageInfo(name=name, available=available, version=ver))

    return JSONResponse(content=HealthResponse(
        status="ok",
        service="compiler-1",
        version=_VERSION,
        available_languages=lang_infos,
        max_concurrent=int(os.getenv("MAX_CONCURRENT", "4")),
        current_executions=0,  # Will be updated by the executor
    ).model_dump())


@router.get("/languages")
async def languages() -> JSONResponse:
    """List all registered languages and their availability."""
    adapters = get_all_adapters()
    result = {}
    for name, adapter in sorted(adapters.items()):
        available = adapter.is_available()
        ver = adapter.version() if available else None
        result[name] = {"available": available, "version": ver}
    return JSONResponse(content=result)
