"""
Gateway API – Code Execution Router

Provides the /api/execute endpoint that proxies code execution requests
to the active execution backend: Judge0 (System 3, default) or the legacy
Compiler 1. This is the deployment-layer integration between the
application and the execution service.

The gateway does NOT execute code itself. It:
  1. Receives the execution request from the client
  2. Forwards it to the active backend over HTTP
  3. Returns the structured result

The frontend/platform contract is identical regardless of backend — the
switch is purely deployment configuration (EXECUTION_BACKEND).
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from ..compiler_proxy import execute_on_compiler, check_compiler_health
from ..execute_schemas import (
    ExecuteRequest,
    ExecuteResponse,
    ExecutionStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["execute"])

EXECUTION_BACKEND = os.getenv("EXECUTION_BACKEND", "judge0").strip().lower()


def _is_judge0_backend() -> bool:
    return EXECUTION_BACKEND != "compiler1"


def _execute(request: ExecuteRequest) -> ExecuteResponse:
    """Dispatch to the active execution backend."""
    if _is_judge0_backend():
        from ..judge0_proxy import execute_on_judge0

        return execute_on_judge0(request)
    return execute_on_compiler(request)


@router.post(
    "/api/execute",
    status_code=status.HTTP_200_OK,
    response_model=ExecuteResponse,
    summary="Execute code via the active execution backend",
    description=(
        "Proxy a code execution request to the execution backend (Judge0 by default). "
        "The platform contract is unchanged: language, source_code, test_cases, limits. "
        "Each request is executed in an isolated sandbox with resource limits."
    ),
)
def api_execute(request: ExecuteRequest) -> JSONResponse:
    """
    Execute source code against test cases via the active backend.

    The request includes:
      - language: Programming language
      - source_code: The code to execute
      - test_cases: List of {input, expected_output} pairs
      - limits: Optional resource limits
      - session_id: Optional session tracking
      - attempt_id: Optional assessment attempt tracking
      - question_id: Optional question tracking

    The response includes:
      - status: accepted, wrong_answer, compilation_error, runtime_error,
        time_limit_exceeded, memory_limit_exceeded, etc.
      - tests: Per-test-case results
      - error: Error details if applicable
      - session/attempt/question IDs echoed back
    """
    logger.info(
        "Execute request: backend=%s language=%s tests=%d session=%s attempt=%s",
        EXECUTION_BACKEND,
        request.language.value,
        len(request.test_cases),
        request.session_id or "none",
        request.attempt_id or "none",
    )

    result = _execute(request)

    # Determine HTTP status code based on result
    http_status = status.HTTP_200_OK
    if result.status == ExecutionStatus.capacity_exceeded:
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif result.status in (
        ExecutionStatus.compilation_error,
        ExecutionStatus.invalid_language,
    ):
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif result.status == ExecutionStatus.compiler_unavailable:
        http_status = status.HTTP_502_BAD_GATEWAY

    return JSONResponse(
        status_code=http_status,
        content=result.model_dump(),
    )


@router.get(
    "/api/execute/health",
    summary="Check execution backend health",
    description="Returns health status and available languages for the active backend.",
)
def api_execution_health() -> JSONResponse:
    """Check if the active execution backend is reachable and healthy."""
    if _is_judge0_backend():
        from ..judge0_proxy import check_judge0_health

        health = check_judge0_health()
    else:
        health = check_compiler_health()
    health["backend"] = EXECUTION_BACKEND
    http_status = (
        status.HTTP_200_OK
        if health.get("status") == "ok"
        else status.HTTP_502_BAD_GATEWAY
    )
    return JSONResponse(status_code=http_status, content=health)


@router.get(
    "/api/execute/languages",
    summary="List available execution languages",
    description="Returns platform languages and their availability on the active backend.",
)
def api_execution_languages() -> JSONResponse:
    """Get the platform -> backend language mapping."""
    if _is_judge0_backend():
        from ..judge0_proxy import get_language_ids

        try:
            ids = get_language_ids(force=True)
            return JSONResponse(
                content={
                    "backend": EXECUTION_BACKEND,
                    "languages": {
                        lang: ({"judge0_id": lid} if lid is not None else {"available": False})
                        for lang, lid in ids.items()
                    },
                }
            )
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "error": f"Cannot reach Judge0 (System 3): {e}",
                    "judge0_url": os.getenv("JUDGE0_URL", "http://judge0-server:2358"),
                },
            )

    compiler_url = None
    try:
        from ..compiler_proxy import _get_compiler_url
        import httpx

        compiler_url = _get_compiler_url()
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{compiler_url}/languages")
            resp.raise_for_status()
            data = resp.json()
            return JSONResponse(content={"backend": EXECUTION_BACKEND, "languages": data})
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": f"Cannot reach Compiler 1: {e}",
                "compiler_url": compiler_url,
            },
        )
