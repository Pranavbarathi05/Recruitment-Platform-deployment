"""
Gateway API – Code Execution Router

Provides the /api/execute endpoint that proxies code execution requests
to Compiler 1. This is the deployment-layer integration between the
application and the compiler service.

The gateway does NOT execute code itself. It:
  1. Receives the execution request from the client
  2. Forwards it to Compiler 1 over HTTP
  3. Returns the structured result

Session context is carried through to prevent cross-user result mixing.
Each execution is isolated by Compiler 1's sandbox.
"""
from __future__ import annotations

import logging

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


@router.post(
    "/api/execute",
    status_code=status.HTTP_200_OK,
    response_model=ExecuteResponse,
    summary="Execute code via Compiler 1",
    description=(
        "Proxy a code execution request to Compiler 1. "
        "Supports Python, C, C++, Java, and SQL. "
        "Each request is executed in an isolated sandbox with resource limits."
    ),
)
def api_execute(request: ExecuteRequest) -> JSONResponse:
    """
    Execute source code against test cases via Compiler 1.

    The request includes:
      - language: Programming language
      - source_code: The code to execute
      - test_cases: List of {input, expected_output} pairs
      - limits: Optional resource limits
      - session_id: Optional session tracking
      - attempt_id: Optional assessment attempt tracking
      - question_id: Optional question tracking

    The response includes:
      - status: accepted, wrong_answer, compilation_error, etc.
      - tests: Per-test-case results
      - error: Error details if applicable
      - session/attempt/question IDs echoed back
    """
    logger.info(
        "Execute request: language=%s, tests=%d, session=%s, attempt=%s",
        request.language.value,
        len(request.test_cases),
        request.session_id or "none",
        request.attempt_id or "none",
    )

    result = execute_on_compiler(request)

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
    summary="Check Compiler 1 health",
    description="Returns Compiler 1 health status and available languages.",
)
def api_compiler_health() -> JSONResponse:
    """Check if Compiler 1 is reachable and healthy."""
    health = check_compiler_health()
    http_status = (
        status.HTTP_200_OK
        if health.get("status") == "ok"
        else status.HTTP_502_BAD_GATEWAY
    )
    return JSONResponse(status_code=http_status, content=health)


@router.get(
    "/api/execute/languages",
    summary="List available execution languages",
    description="Returns the list of languages supported by Compiler 1.",
)
def api_compiler_languages() -> JSONResponse:
    """Get available languages from Compiler 1."""
    compiler_url = None
    try:
        from ..compiler_proxy import _get_compiler_url
        import httpx

        compiler_url = _get_compiler_url()
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{compiler_url}/languages")
            resp.raise_for_status()
            return JSONResponse(content=resp.json())
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": f"Cannot reach Compiler 1: {e}",
                "compiler_url": compiler_url,
            },
        )
