"""
Request and response schemas for the gateway execution proxy.

This module defines the API contract for the /api/execute endpoint,
which proxies code execution requests to Compiler 1.

The gateway does NOT execute code itself — it forwards requests to
the compiler service and returns structured results.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Supported languages ──────────────────────────────────────────────────────

class Language(str, Enum):
    cpp = "cpp"
    c = "c"
    java = "java"
    python = "python"
    sql = "sql"


# ── Resource limits ──────────────────────────────────────────────────────────

class ExecutionLimits(BaseModel):
    """Per-execution resource limits."""
    time_limit_seconds: float = Field(
        default=10.0,
        ge=0.5,
        le=60.0,
        description="Maximum wall-clock time per test case in seconds.",
    )
    memory_limit_mb: int = Field(
        default=256,
        ge=32,
        le=2048,
        description="Memory limit in MB (best-effort, OS-enforced).",
    )
    max_output_bytes: int = Field(
        default=65536,
        ge=1024,
        le=1048576,
        description="Maximum stdout/stderr output in bytes before truncation.",
    )


# ── Test case ────────────────────────────────────────────────────────────────

class TestCase(BaseModel):
    """A single test case with input and expected output."""
    input: str = Field(default="", description="Stdin input for the program.")
    expected_output: str = Field(description="Expected stdout (exact match after stripping trailing whitespace).")
    label: Optional[str] = Field(default=None, description="Human-readable label for this test case.")


# ── Execute request ──────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    """Request to execute code against one or more test cases."""
    language: Language
    source_code: str = Field(..., min_length=1, max_length=100_000, description="Source code to execute.")
    test_cases: list[TestCase] = Field(..., min_length=1, max_length=50, description="Test cases to run.")
    limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    # Optional context for session/request tracking
    session_id: Optional[str] = Field(default=None, description="Session ID for request tracking.")
    attempt_id: Optional[str] = Field(default=None, description="Assessment attempt ID.")
    question_id: Optional[str] = Field(default=None, description="Question ID being evaluated.")


# ── Test result ──────────────────────────────────────────────────────────────

class TestCaseResult(BaseModel):
    """Result for a single test case."""
    test_case: int = Field(description="1-based test case number.")
    label: Optional[str] = None
    passed: bool
    execution_time_ms: int
    input: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None


# ── Execute response ─────────────────────────────────────────────────────────

class ExecutionStatus(str, Enum):
    accepted = "accepted"
    wrong_answer = "wrong_answer"
    time_limit_exceeded = "time_limit_exceeded"
    runtime_error = "runtime_error"
    compilation_error = "compilation_error"
    memory_limit_exceeded = "memory_limit_exceeded"
    output_limit_exceeded = "output_limit_exceeded"
    invalid_language = "invalid_language"
    internal_error = "internal_error"
    capacity_exceeded = "capacity_exceeded"
    compiler_unavailable = "compiler_unavailable"


class ExecuteResponse(BaseModel):
    """Structured result of a code execution request."""
    status: ExecutionStatus
    language: str
    execution_time_ms: int = Field(ge=0, description="Total wall-clock time for all test cases.")
    tests: list[TestCaseResult] = Field(default_factory=list, description="Per-test-case results.")
    error: Optional[str] = Field(default=None, description="Error details for compilation/runtime/internal errors.")
    failed_test: Optional[int] = Field(default=None, description="1-based index of the first failing test case.")
    total_tests: int = Field(default=0, ge=0)
    passed_tests: int = Field(default=0, ge=0)
    # Request context echoed back
    session_id: Optional[str] = None
    attempt_id: Optional[str] = None
    question_id: Optional[str] = None
