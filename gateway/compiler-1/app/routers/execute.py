"""
Code execution endpoint for Compiler 1.
"""
from __future__ import annotations

import os
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ..executor import execute_code
from ..schemas import ExecuteRequest, ExecuteResponse

router = APIRouter(tags=["execute"])

# Bounded concurrency tracking
_MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "4"))
_semaphore = threading.Semaphore(_MAX_CONCURRENT)
_active_count = 0
_count_lock = threading.Lock()


def _get_active_count() -> int:
    with _count_lock:
        return _active_count


def _increment_active() -> bool:
    """Try to acquire a slot. Returns True if acquired."""
    global _active_count
    if _semaphore.acquire(blocking=False):
        with _count_lock:
            _active_count += 1
        return True
    return False


def _release_active():
    global _active_count
    with _count_lock:
        _active_count -= 1
    _semaphore.release()


@router.post("/execute")
async def execute(request: ExecuteRequest) -> JSONResponse:
    """Execute source code against one or more test cases.

    Returns structured JSON with overall status and per-test-case results.
    """
    if not _increment_active():
        return JSONResponse(
            status_code=503,
            content=ExecuteResponse(
                status="capacity_exceeded",
                language=request.language.value,
                execution_time_ms=0,
                total_tests=len(request.test_cases),
                error=f"Server at capacity ({_MAX_CONCURRENT} concurrent executions). Try again shortly.",
            ).model_dump(),
        )

    try:
        result = execute_code(
            request,
            max_concurrent=_MAX_CONCURRENT,
            active_count_fn=_get_active_count,
        )
        status_code = 200
        if result.status in ("compilation_error", "runtime_error", "invalid_language", "internal_error"):
            status_code = 422
        return JSONResponse(status_code=status_code, content=result.model_dump())
    finally:
        _release_active()
