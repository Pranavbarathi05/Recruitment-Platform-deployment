"""
Compiler 1 HTTP proxy client.

This module provides a synchronous HTTP client for communicating with
Compiler 1 from the gateway API. It translates between the gateway's
execution schema and Compiler 1's API contract.

Design decisions:
  - Uses httpx (sync client) because the gateway API endpoints that call
    this are synchronous FastAPI handlers.
  - Connection pooling via httpx.Client for efficiency.
  - Configurable timeout and compiler URL via environment variables.
  - Clear error classification: infrastructure errors vs code errors.
  - All communication is over HTTP; no shared memory or process coupling.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

from .execute_schemas import (
    ExecuteRequest,
    ExecuteResponse,
    ExecutionStatus,
    TestCaseResult,
)

logger = logging.getLogger(__name__)

# Configuration
COMPILER_URL = os.getenv("COMPILER_URL", "http://compiler-1:8000")
COMPILER_TIMEOUT = float(os.getenv("COMPILER_TIMEOUT", "60.0"))


def _get_compiler_url() -> str:
    """Get the Compiler 1 base URL from environment."""
    return COMPILER_URL.rstrip("/")


def _build_compiler_payload(request: ExecuteRequest) -> dict[str, Any]:
    """Convert ExecuteRequest to Compiler 1 API format."""
    return {
        "language": request.language.value,
        "source_code": request.source_code,
        "test_cases": [
            {
                "input": tc.input,
                "expected_output": tc.expected_output,
                "label": tc.label,
            }
            for tc in request.test_cases
        ],
        "limits": {
            "time_limit_seconds": request.limits.time_limit_seconds,
            "memory_limit_mb": request.limits.memory_limit_mb,
            "max_output_bytes": request.limits.max_output_bytes,
        },
    }


def _parse_compiler_response(
    data: dict[str, Any],
    request: ExecuteRequest,
) -> ExecuteResponse:
    """Parse Compiler 1 JSON response into ExecuteResponse."""
    tests = []
    for t in data.get("tests", []):
        tests.append(TestCaseResult(
            test_case=t.get("test_case", 0),
            label=t.get("label"),
            passed=t.get("passed", False),
            execution_time_ms=t.get("execution_time_ms", 0),
            input=t.get("input"),
            stdout=t.get("stdout"),
            stderr=t.get("stderr"),
        ))

    status_str = data.get("status", "internal_error")
    try:
        status = ExecutionStatus(status_str)
    except ValueError:
        status = ExecutionStatus.internal_error

    return ExecuteResponse(
        status=status,
        language=data.get("language", request.language.value),
        execution_time_ms=data.get("execution_time_ms", 0),
        tests=tests,
        error=data.get("error"),
        failed_test=data.get("failed_test"),
        total_tests=data.get("total_tests", 0),
        passed_tests=data.get("passed_tests", 0),
        session_id=request.session_id,
        attempt_id=request.attempt_id,
        question_id=request.question_id,
    )


def execute_on_compiler(request: ExecuteRequest) -> ExecuteResponse:
    """
    Send an execution request to Compiler 1 and return the result.

    This is the core integration function. It:
    1. Builds the request payload for Compiler 1
    2. Sends HTTP POST to Compiler 1's /execute endpoint
    3. Parses the response
    4. Handles infrastructure failures (connection errors, timeouts)

    Args:
        request: The execution request from the gateway.

    Returns:
        ExecuteResponse with the result from Compiler 1, or an
        infrastructure error response if the compiler is unavailable.
    """
    compiler_url = _get_compiler_url()
    payload = _build_compiler_payload(request)

    logger.info(
        "Compiler proxy: sending %s execution to %s (tests=%d, session=%s)",
        request.language.value,
        compiler_url,
        len(request.test_cases),
        request.session_id or "none",
    )

    try:
        with httpx.Client(timeout=COMPILER_TIMEOUT) as client:
            resp = client.post(f"{compiler_url}/execute", json=payload)

            # Handle HTTP errors
            if resp.status_code >= 400:
                logger.warning(
                    "Compiler 1 returned HTTP %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                # Try to parse error response from compiler
                try:
                    error_data = resp.json()
                    return _parse_compiler_response(error_data, request)
                except Exception:
                    return ExecuteResponse(
                        status=ExecutionStatus.compiler_unavailable,
                        language=request.language.value,
                        execution_time_ms=0,
                        total_tests=len(request.test_cases),
                        error=f"Compiler returned HTTP {resp.status_code}",
                        session_id=request.session_id,
                        attempt_id=request.attempt_id,
                        question_id=request.question_id,
                    )

            data = resp.json()
            logger.info(
                "Compiler 1 response: status=%s, passed=%d/%d",
                data.get("status"),
                data.get("passed_tests", 0),
                data.get("total_tests", 0),
            )
            return _parse_compiler_response(data, request)

    except httpx.ConnectError:
        logger.error("Compiler 1 is unreachable at %s", compiler_url)
        return ExecuteResponse(
            status=ExecutionStatus.compiler_unavailable,
            language=request.language.value,
            execution_time_ms=0,
            total_tests=len(request.test_cases),
            error=f"Compiler 1 is unreachable at {compiler_url}",
            session_id=request.session_id,
            attempt_id=request.attempt_id,
            question_id=request.question_id,
        )
    except httpx.TimeoutException:
        logger.error("Compiler 1 request timed out after %ss", COMPILER_TIMEOUT)
        return ExecuteResponse(
            status=ExecutionStatus.compiler_unavailable,
            language=request.language.value,
            execution_time_ms=0,
            total_tests=len(request.test_cases),
            error="Compiler 1 request timed out",
            session_id=request.session_id,
            attempt_id=request.attempt_id,
            question_id=request.question_id,
        )
    except Exception as e:
        logger.exception("Unexpected error communicating with Compiler 1")
        return ExecuteResponse(
            status=ExecutionStatus.internal_error,
            language=request.language.value,
            execution_time_ms=0,
            total_tests=len(request.test_cases),
            error=f"Unexpected error: {type(e).__name__}: {e}",
            session_id=request.session_id,
            attempt_id=request.attempt_id,
            question_id=request.question_id,
        )


def check_compiler_health() -> dict[str, Any]:
    """
    Check Compiler 1 health status.

    Returns:
        Health response dict, or error dict if unreachable.
    """
    compiler_url = _get_compiler_url()
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{compiler_url}/health")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {
            "status": "unreachable",
            "error": f"{type(e).__name__}: {e}",
            "compiler_url": compiler_url,
        }
