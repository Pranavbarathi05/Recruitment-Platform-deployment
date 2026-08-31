"""
HTTP client for Compiler 1 code execution service.

This client wraps Compiler 1's REST API and provides:
- Structured request/response handling
- Error classification (infrastructure vs. code errors)
- Timeout and connection error handling
- Language string mapping
- Configurable compiler URL for multi-machine deployment

Design:
  - The client is a thin HTTP wrapper. It does NOT contain execution logic.
  - All code execution happens inside Compiler 1's sandbox.
  - The client maps Compiler 1's response to a format the application can use.
  - Infrastructure failures are clearly distinguishable from code failures.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Default compiler URL — configurable via COMPILER_URL environment variable.
# For local Docker: http://compiler-1:8000
# For LAN deployment: http://192.168.x.x:8001
DEFAULT_COMPILER_URL = "http://compiler-1:8000"

# Request timeout (seconds)
DEFAULT_TIMEOUT = 30.0

# Language mapping: application language strings → Compiler 1 language names
LANGUAGE_MAP = {
    "python": "python",
    "python3": "python",
    "cpp": "cpp",
    "c++": "cpp",
    "c": "c",
    "java": "java",
    "javascript": "javascript",
    "js": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
}

# Supported languages for validation
SUPPORTED_LANGUAGES = {"python", "cpp", "c", "java", "javascript"}


class CompilerError(Exception):
    """Raised when the compiler service itself fails (infrastructure error)."""

    def __init__(self, message: str, status: str = "compiler_error", details: Optional[dict] = None):
        super().__init__(message)
        self.status = status
        self.details = details or {}


@dataclass
class ExecutionResult:
    """Result of a code execution request.

    This maps Compiler 1's response to a format the application can use.
    """
    status: str  # accepted, wrong_answer, compilation_error, runtime_error, etc.
    language: str
    execution_time_ms: int = 0
    tests: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    failed_test: Optional[int] = None
    total_tests: int = 0
    passed_tests: int = 0

    @property
    def is_success(self) -> bool:
        """Whether the code was accepted (all tests passed)."""
        return self.status == "accepted"

    @property
    def is_code_error(self) -> bool:
        """Whether the failure is in the submitted code (not infrastructure)."""
        return self.status in (
            "wrong_answer",
            "compilation_error",
            "runtime_error",
            "time_limit_exceeded",
            "invalid_language",
        )

    @property
    def is_infrastructure_error(self) -> bool:
        """Whether the failure is in the infrastructure (not the code)."""
        return self.status in ("compiler_error", "compiler_unavailable", "capacity_exceeded", "internal_error")

    def to_dict(self) -> dict:
        """Convert to a dictionary suitable for API responses."""
        result = {
            "status": self.status,
            "language": self.language,
            "execution_time_ms": self.execution_time_ms,
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
        }
        if self.error:
            result["error"] = self.error
        if self.failed_test is not None:
            result["failed_test"] = self.failed_test
        if self.tests:
            result["tests"] = self.tests
        return result


class CompilerClient:
    """HTTP client for Compiler 1 code execution service.

    Args:
        url: Compiler 1 base URL. Defaults to COMPILER_URL env var or http://compiler-1:8000.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.url = (url or os.getenv("COMPILER_URL", DEFAULT_COMPILER_URL)).rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def health(self) -> dict:
        """Check Compiler 1 health.

        Returns:
            Health response dict.

        Raises:
            CompilerError: If the compiler is unreachable.
        """
        client = await self._get_client()
        try:
            resp = await client.get(f"{self.url}/health")
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            raise CompilerError(
                "Compiler 1 is unreachable",
                status="compiler_unavailable",
            )
        except httpx.TimeoutException:
            raise CompilerError(
                "Compiler 1 health check timed out",
                status="compiler_unavailable",
            )
        except httpx.HTTPStatusError as e:
            raise CompilerError(
                f"Compiler 1 returned HTTP {e.response.status_code}",
                status="compiler_unavailable",
            )

    async def execute(
        self,
        language: str,
        source_code: str,
        test_cases: list[dict[str, str]],
        limits: Optional[dict] = None,
    ) -> ExecutionResult:
        """Execute code against test cases via Compiler 1.

        Args:
            language: Programming language (e.g., "python", "cpp", "java").
            source_code: The source code to execute.
            test_cases: List of {input, expected_output} dicts.
            limits: Optional execution limits override.

        Returns:
            ExecutionResult with status, test results, and timing.

        Raises:
            CompilerError: If the compiler service itself fails.
        """
        # Map language string
        mapped_language = LANGUAGE_MAP.get(language.lower().strip())
        if mapped_language is None:
            return ExecutionResult(
                status="invalid_language",
                language=language,
                error=f"Unsupported language: '{language}'. Supported: {', '.join(sorted(SUPPORTED_LANGUAGES))}",
            )

        # Validate test cases
        if not test_cases:
            return ExecutionResult(
                status="internal_error",
                language=language,
                error="No test cases provided",
            )

        # Build request payload
        payload: dict[str, Any] = {
            "language": mapped_language,
            "source_code": source_code,
            "test_cases": test_cases,
        }
        if limits:
            payload["limits"] = limits

        # Send request to Compiler 1
        client = await self._get_client()
        try:
            logger.info("Sending execution request to Compiler 1: language=%s, tests=%d", mapped_language, len(test_cases))
            resp = await client.post(f"{self.url}/execute", json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.info("Compiler 1 response: status=%s, passed=%d/%d", data.get("status"), data.get("passed_tests", 0), data.get("total_tests", 0))
            return ExecutionResult(
                status=data.get("status", "internal_error"),
                language=data.get("language", language),
                execution_time_ms=data.get("execution_time_ms", 0),
                tests=data.get("tests", []),
                error=data.get("error"),
                failed_test=data.get("failed_test"),
                total_tests=data.get("total_tests", 0),
                passed_tests=data.get("passed_tests", 0),
            )

        except httpx.ConnectError:
            logger.error("Compiler 1 is unreachable at %s", self.url)
            raise CompilerError(
                "Compiler 1 is unavailable",
                status="compiler_unavailable",
            )
        except httpx.TimeoutException:
            logger.error("Compiler 1 request timed out after %ss", self.timeout)
            raise CompilerError(
                "Compiler 1 request timed out",
                status="compiler_unavailable",
            )
        except httpx.HTTPStatusError as e:
            logger.error("Compiler 1 returned HTTP %d", e.response.status_code)
            # Try to parse the error response
            try:
                error_data = e.response.json()
                return ExecutionResult(
                    status=error_data.get("status", "compiler_error"),
                    language=language,
                    error=error_data.get("error", f"Compiler returned HTTP {e.response.status_code}"),
                )
            except Exception:
                raise CompilerError(
                    f"Compiler 1 returned HTTP {e.response.status_code}",
                    status="compiler_error",
                )
        except Exception as e:
            logger.exception("Unexpected error communicating with Compiler 1")
            raise CompilerError(
                f"Unexpected compiler error: {type(e).__name__}: {e}",
                status="compiler_error",
            )
