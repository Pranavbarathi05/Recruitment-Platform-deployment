"""
Judge0 (System 3) HTTP client for the gateway API.

Replaces the Compiler 1 integration in the deployment layer while preserving
the gateway's /api/execute contract (see execute_schemas.py). The platform
(frontend and dsc-recruit backend) never learns that Judge0 exists.

Flow for one ExecuteRequest:
  1. Validate the request and resolve the platform language -> Judge0 language_id
     by querying GET /languages and picking the highest-version match.
  2. Each test case becomes an independent Judge0 submission (task isolation),
     submitted to the queue and polled until a final status.
  3. Judge0 statuses are mapped onto the platform ExecutionStatus vocabulary:
     Accepted / Wrong Answer / Compilation Error / Runtime Error /
     Time Limit Exceeded / Memory Limit Exceeded / Output Limit Exceeded /
     Internal (System) Error / queue failures.
  4. Results are aggregated into the existing ExecuteResponse shape.

Security:
  - No candidate code is ever executed here; all execution happens inside
    Judge0's isolate sandboxes.
  - Every request carries the Judge0 auth token (AUTHN_TOKEN).
  - If Judge0 is unreachable the gateway returns compiler_unavailable
    (HTTP 502) and never crashes or falls through to local execution.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import time
from typing import Any, Optional

import httpx

from .execute_schemas import (
    ExecuteRequest,
    ExecuteResponse,
    ExecutionStatus,
    TestCaseResult,
)

logger = logging.getLogger(__name__)


def _b64(text: str) -> str:
    """Base64-encode a text attribute for Judge0's base64_encoded API mode."""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _deb64(value: Optional[str]) -> Optional[str]:
    """Decode a base64-encoded attribute returned by Judge0.

    Falls back to the raw value when it is not valid base64 (e.g. mock
    responses in unit tests, or a Judge0 that already returned plaintext).
    """
    if value is None:
        return None
    try:
        return base64.b64decode(value.encode("ascii"), validate=False).decode("utf-8")
    except Exception:
        return value

# ── Configuration ────────────────────────────────────────────────────────────
JUDGE0_URL = os.getenv("JUDGE0_URL", "http://judge0-server:2358")
JUDGE0_TIMEOUT = float(os.getenv("JUDGE0_TIMEOUT", "60.0"))
JUDGE0_AUTH_HEADER = os.getenv("JUDGE0_AUTH_HEADER", "X-Judge0-Token")
JUDGE0_AUTH_TOKEN = os.getenv("JUDGE0_AUTH_TOKEN", "")
JUDGE0_MAX_POLL_SECONDS = float(os.getenv("JUDGE0_MAX_POLL_SECONDS", "120.0"))
# How much additional time (beyond the submission's own run budget) the poller
# tolerates for queue wait. Without this, a submission that is queued behind
# other candidates for >~10s gets abandoned as internal_error even though it
# would finish -- its run budget was consumed by queueing, not execution.
JUDGE0_QUEUE_ALLOWANCE_SECONDS = float(os.getenv("JUDGE0_QUEUE_ALLOWANCE_SECONDS", "90.0"))
JUDGE0_POLL_INTERVAL = float(os.getenv("JUDGE0_POLL_INTERVAL", "0.1"))
JUDGE0_LANGUAGE_CACHE_TTL = float(os.getenv("JUDGE0_LANGUAGE_CACHE_TTL", "300.0"))

# Server-side ceilings configured in gateway/judge0/judge0.conf.
_MAX_CPU_TIME_S = 60.0
_MAX_WALL_TIME_S = 90.0
_MAX_MEMORY_KB = 2_097_152  # 2 GiB (matches MAX_MEMORY_LIMIT in judge0.conf; Java needs the VA headroom)

# ── Language resolution ──────────────────────────────────────────────────────
# Judge0 CE v1.13.1 ships SQL (SQLite) as a language. When a platform language
# cannot be resolved, the gateway reports invalid_language instead of silently
# dropping the language.
_LANG_PATTERNS: dict[str, "re.Pattern[str]"] = {
    "python": re.compile(r"^Python \(3\.(\d+)(\.\d+)?\)"),
    "cpp": re.compile(r"^C\+\+ \(GCC (\d+\.\d+\.?\d*)\)"),
    "c": re.compile(r"^C \(GCC (\d+\.\d+\.?\d*)\)"),
    "java": re.compile(r"^Java \(OpenJDK (\d+\.\d+\.?\d*)\)"),
    "sql": re.compile(r"^SQL \(SQLite (\d+\.\d+\.?\d*)\)"),
}

# Judge0 status id -> platform status, VERIFIED against the live instance's
# GET /statuses (Judge0 CE 1.13.1 reports ids 1-14; there is no distinct
# Memory/Output Limit Exceeded status in this version, so those surface as
# Runtime Error / Internal Error).
JUDGE0_STATUS_MAP: dict[int, ExecutionStatus] = {
    1: ExecutionStatus.internal_error,   # In Queue (transient; final only via timeout)
    2: ExecutionStatus.internal_error,   # Processing (transient)
    3: ExecutionStatus.accepted,
    4: ExecutionStatus.wrong_answer,
    5: ExecutionStatus.time_limit_exceeded,
    6: ExecutionStatus.compilation_error,
    7: ExecutionStatus.runtime_error,    # SIGSEGV
    8: ExecutionStatus.runtime_error,    # SIGXFSZ
    9: ExecutionStatus.runtime_error,    # SIGFPE
    10: ExecutionStatus.runtime_error,   # SIGABRT
    11: ExecutionStatus.runtime_error,   # NZEC
    12: ExecutionStatus.runtime_error,   # Other
    13: ExecutionStatus.internal_error,  # Internal Error (Judge0/system)
    14: ExecutionStatus.internal_error,  # Exec Format Error
    # 15/16 (Memory/Output Limit Exceeded) exist only in newer Judge0.
    # This CE 1.13.1 instance reports only 1-14, so they are never emitted
    # here, but keeping them lets the map work unchanged on a newer version.
    15: ExecutionStatus.memory_limit_exceeded,
    16: ExecutionStatus.output_limit_exceeded,
}
_FINAL_JUDGE0_STATUSES = frozenset(range(3, 17))

_language_ids_cache: Optional[dict[str, Optional[int]]] = None
_language_ids_fetched_at: float = 0.0


# ── Low-level HTTP ───────────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if JUDGE0_AUTH_TOKEN:
        h[JUDGE0_AUTH_HEADER] = JUDGE0_AUTH_TOKEN
    return h


def _judge0_url(path: str) -> str:
    return f"{JUDGE0_URL.rstrip('/')}/{path.lstrip('/')}"


def _truncate(text: str, max_bytes: int) -> str:
    """Truncate text to max_bytes, adding a notice if truncated."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
    return truncated + f"\n... [truncated at {max_bytes} bytes]"


# ── Language mapping ─────────────────────────────────────────────────────────

def fetch_languages() -> list[dict[str, Any]]:
    """Return active languages from Judge0 (uses the shared http client)."""
    try:
        with httpx.Client(timeout=JUDGE0_TIMEOUT) as client:
            resp = client.get(_judge0_url("languages"), headers=_headers())
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return []
    except httpx.HTTPStatusError as e:
        logger.warning("Judge0 /languages HTTP %d: %s", e.response.status_code, e.response.text[:200])
        raise
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error("Judge0 /languages unreachable: %s", e)
        raise


def resolve_language_ids(languages: list[dict[str, Any]]) -> dict[str, Optional[int]]:
    """Map each platform language to the highest-version Judge0 language_id.

    Returns a dict with a None value when a platform language has no match
    (e.g. SQL in Judge0 CE), so callers can report the incompatibility.
    """
    by_family: dict[str, list[tuple[tuple[int, ...], int]]] = {}
    for lang in languages:
        name = lang.get("name", "")
        if lang.get("is_archived"):
            continue
        for family, pattern in _LANG_PATTERNS.items():
            m = pattern.match(name)
            if m:
                ver = m.group(1)
                parts = tuple(int(p) for p in re.findall(r"\d+", ver))
                by_family.setdefault(family, []).append((parts, int(lang["id"])))
                break

    resolved: dict[str, Optional[int]] = {}
    for family in _LANG_PATTERNS:
        matches = by_family.get(family, [])
        if matches:
            matches.sort(key=lambda kv: kv[0], reverse=True)
            resolved[family] = matches[0][1]
        else:
            resolved[family] = None
    return resolved


def get_language_ids(force: bool = False) -> dict[str, Optional[int]]:
    """Resolve language ids, cached with a TTL. Raises on Judge0 unavailability."""
    global _language_ids_cache, _language_ids_fetched_at
    now = time.monotonic()
    if (
        force
        or _language_ids_cache is None
        or (now - _language_ids_fetched_at) > JUDGE0_LANGUAGE_CACHE_TTL
    ):
        _language_ids_cache = resolve_language_ids(fetch_languages())
        _language_ids_fetched_at = now
        logger.info(
            "Judge0 language map: %s",
            {k: v for k, v in _language_ids_cache.items() if v is not None},
        )
    return _language_ids_cache


# ── Submissions ──────────────────────────────────────────────────────────────

def _build_submission_payload(
    request: ExecuteRequest,
    judge0_language_id: int,
    stdin_text: str,
    source_code: Optional[str] = None,
) -> dict[str, Any]:
    """Build a Judge0 submission payload from the platform request + one test case.

    `source_code` may be overridden (used for SQL, where the platform contract
    is setup script + per-test query in one program).
    """
    cpu_time = max(0.5, min(request.limits.time_limit_seconds, _MAX_CPU_TIME_S))
    wall_time = min(cpu_time + 10.0, _MAX_WALL_TIME_S)
    mem_kb = min(request.limits.memory_limit_mb * 1024, _MAX_MEMORY_KB)

    # Java: the JVM reserves a large VIRTUAL address space (default MaxHeapSize
    # scales with host RAM) even when the real heap is small. Under rlimit-based
    # memory enforcement (RLIMIT_AS, required on cgroup v2 hosts -- see
    # judge0.conf) a small memory_limit makes every Java submission die with
    # "Failed to reserve ...". Give Java the full 1 GiB ceiling; actual heap
    # usage is still bounded because the Judge0 language row caps the JVM heap
    # (java -Xmx512m) -- enforcement is not weakened, it is moved to the JVM.
    if request.language.value == "java":
        mem_kb = _MAX_MEMORY_KB

    # Judge0 CE 1.13.1 stores attributes base64-encoded and its plaintext
    # response path can 400 on valid-but-exotic content (e.g. compiler
    # messages containing UTF-8 punctuation). Always use base64_encoded=true
    # and transcode locally -- POST and GET must use the same mode.
    return {
        "source_code": _b64(source_code if source_code is not None else request.source_code),
        "language_id": judge0_language_id,
        "stdin": _b64(stdin_text),
        "cpu_time_limit": cpu_time,
        "wall_time_limit": wall_time,
        "memory_limit": mem_kb,
        "stack_limit": min(65536, mem_kb),
        "max_processes_and_or_threads": 60,
        "max_file_size": 1024,
        "number_of_runs": 1,
        # Per-process/thread limits MUST stay enabled: when they are disabled,
        # Judge0 executes with isolate's "--cg" flag, which targets the cgroup
        # v1 layout (/sys/fs/cgroup/<controller>/...) and fails on this host's
        # cgroup v2-only kernel (ENABLE_PER_PROCESS_*_LIMIT=true in
        # gateway/judge0/judge0.conf keeps the server default the same).
        "enable_per_process_and_thread_time_limit": True,
        "enable_per_process_and_thread_memory_limit": True,
        "enable_network": False,
    }


def _submit_submission(payload: dict[str, Any]) -> str:
    """POST a submission to the queue; returns the token."""
    try:
        with httpx.Client(timeout=JUDGE0_TIMEOUT) as client:
            resp = client.post(
                _judge0_url("submissions?base64_encoded=true&wait=false"),
                json=payload,
                headers=_headers(),
            )
            if resp.status_code == 503:
                raise ExecutionServiceUnavailable("Judge0 queue is full", "queue_full")
            resp.raise_for_status()
            data = resp.json()
            return str(data["token"])
    except httpx.HTTPStatusError as e:
        logger.warning("Judge0 submission rejected HTTP %d: %s", e.response.status_code, e.response.text[:300])
        raise Judge0SubmissionError(
            f"Judge0 rejected submission (HTTP {e.response.status_code}): {e.response.text[:300]}"
        )
    except httpx.ConnectError as e:
        raise ExecutionServiceUnavailable(f"Judge0 unreachable at {JUDGE0_URL}: {e}", "connect")
    except httpx.TimeoutException as e:
        raise ExecutionServiceUnavailable(f"Judge0 submission POST timed out: {e}", "timeout")


def _get_submission(token: str) -> dict[str, Any]:
    """Fetch a submission's details."""
    with httpx.Client(timeout=JUDGE0_TIMEOUT) as client:
        resp = client.get(
            _judge0_url(f"submissions/{token}?base64_encoded=true"),
            headers=_headers(),
        )
        if resp.status_code >= 400:
            # Unknown/expired token or Judge0 hiccup: treat as a clean
            # execution-service failure instead of crashing the gateway.
            raise ExecutionServiceUnavailable(
                f"Judge0 submission fetch failed (HTTP {resp.status_code}): {resp.text[:200]}",
                "fetch",
            )
        resp.raise_for_status()
        return resp.json()


def _poll_submission(token: str, max_wait: float) -> dict[str, Any]:
    """Poll until a final status or the deadline expires."""
    deadline = time.monotonic() + min(max_wait, JUDGE0_MAX_POLL_SECONDS)
    while time.monotonic() < deadline:
        data = _get_submission(token)
        status_id = int(data.get("status", {}).get("id", 1))
        if status_id in _FINAL_JUDGE0_STATUSES:
            return data
        time.sleep(JUDGE0_POLL_INTERVAL)
    return _queue_timeout_result(token)


def _queue_timeout_result(token: str) -> dict[str, Any]:
    return {
        "status": {"id": 13, "description": "Internal Error"},
        "stdout": None,
        "stderr": None,
        "compile_output": None,
        "time": 0,
        "memory": 0,
        "message": f"Judge0 did not finish submission {token} before the poll deadline; check worker health.",
    }


# ── Status mapping ───────────────────────────────────────────────────────────

def _status_for(status_id: int) -> ExecutionStatus:
    return JUDGE0_STATUS_MAP.get(status_id, ExecutionStatus.internal_error)


def _outputs_match(stdout: Optional[str], expected: str) -> bool:
    """Platform contract: exact match after stripping trailing whitespace."""
    actual = (stdout or "").rstrip()
    return actual == expected.rstrip()


def _to_test_case_result(
    submission: dict[str, Any],
    index: int,
    label: Optional[str],
    stdin_text: str,
    expected: str,
    max_output_bytes: int,
) -> tuple[TestCaseResult, ExecutionStatus]:
    """Convert a Judge0 submission into a platform TestCaseResult + status."""
    status_id = int(submission.get("status", {}).get("id", 13))
    status = _status_for(status_id)
    # Attributes arrive base64-encoded (base64_encoded=true on GET).
    stdout = _deb64(submission.get("stdout")) or ""
    stderr = _deb64(submission.get("stderr")) or ""
    compile_output = _deb64(submission.get("compile_output")) or ""
    message = _deb64(submission.get("message")) or ""
    time_s = float(submission.get("time") or 0)

    passed = (status == ExecutionStatus.accepted) and _outputs_match(stdout, expected)

    # Surface useful diagnostics:
    #   compilation_error -> compile_output
    #   accepted/wrong_answer -> stdout (+stderr if any)
    diag = ""
    if status == ExecutionStatus.compilation_error:
        diag = compile_output or stderr or "Compilation failed."
    elif status == ExecutionStatus.time_limit_exceeded:
        diag = f"Time limit exceeded (cpu {time_s:.2f}s)."
    elif status == ExecutionStatus.memory_limit_exceeded:
        diag = "Memory limit exceeded."
    elif status == ExecutionStatus.output_limit_exceeded:
        diag = "Output limit exceeded."
    elif status in (ExecutionStatus.runtime_error, ExecutionStatus.internal_error):
        diag = stderr or message or "Runtime error."

    result = TestCaseResult(
        test_case=index + 1,
        label=label,
        passed=passed,
        execution_time_ms=int(time_s * 1000),
        input=stdin_text if len(stdin_text) < 2048 else stdin_text[:2048] + "...",
        stdout=_truncate(stdout, max_output_bytes) if stdout else "",
        stderr=_truncate(diag, max_output_bytes) if diag else "",
    )
    return result, status


# ── Public entry points ──────────────────────────────────────────────────────

def execute_on_judge0(request: ExecuteRequest) -> ExecuteResponse:
    """
    Execute code against test cases via Judge0 (System 3).

    Each test case is submitted as an independent Judge0 submission so test
    isolation is preserved (a crash/timeout in one case cannot affect others).
    """
    lang = request.language.value

    try:
        language_ids = get_language_ids()
    except Exception as e:
        logger.error("Judge0 language resolution failed: %s", e)
        return _unavailable_response(request, f"Judge0 (System 3) unreachable: {type(e).__name__}: {e}")

    judge0_id = language_ids.get(lang)
    if judge0_id is None:
        if lang in _LANG_PATTERNS:
            return _invalid_language_response(
                request,
                f"Language '{lang}' is not resolvable in Judge0 CE (System 3). "
                "Verify the language exists via GET /languages; if it does not, "
                "set EXECUTION_BACKEND=compiler1 for batches using it.",
            )
        return _invalid_language_response(
            request, f"Language '{lang}' is not supported by this gateway."
        )

    results: list[TestCaseResult] = []
    overall_status = ExecutionStatus.accepted
    failed_test: Optional[int] = None
    overall_start = time.monotonic()

    for i, tc in enumerate(request.test_cases):
        if lang == "sql":
            # Platform SQL contract: source_code is the DDL+DML setup script and
            # each test case's `input` is a query. Combine them into one program
            # so Judge0's SQLite runtime runs setup then the query.
            payload = _build_submission_payload(
                request, judge0_id, "",
                source_code=f"{request.source_code}\n{tc.input}",
            )
        else:
            payload = _build_submission_payload(request, judge0_id, tc.input)
        try:
            token = _submit_submission(payload)
            max_wait = min(
                payload["wall_time_limit"] + 10.0 + JUDGE0_QUEUE_ALLOWANCE_SECONDS,
                JUDGE0_MAX_POLL_SECONDS,
            )
            submission = _poll_submission(token, max_wait)
        except ExecutionServiceUnavailable as e:
            logger.error("Judge0 unavailable while executing: %s", e)
            return ExecuteResponse(
                status=ExecutionStatus.compiler_unavailable,
                language=lang,
                execution_time_ms=int((time.monotonic() - overall_start) * 1000),
                tests=results,
                error=str(e),
                failed_test=failed_test,
                total_tests=len(request.test_cases),
                passed_tests=sum(1 for r in results if r.passed),
                session_id=request.session_id,
                attempt_id=request.attempt_id,
                question_id=request.question_id,
            )
        except Judge0SubmissionError as e:
            return ExecuteResponse(
                status=ExecutionStatus.internal_error,
                language=lang,
                execution_time_ms=int((time.monotonic() - overall_start) * 1000),
                tests=results,
                error=str(e),
                failed_test=failed_test,
                total_tests=len(request.test_cases),
                passed_tests=sum(1 for r in results if r.passed),
                session_id=request.session_id,
                attempt_id=request.attempt_id,
                question_id=request.question_id,
            )

        result, status = _to_test_case_result(
            submission, i, tc.label, tc.input, tc.expected_output,
            request.limits.max_output_bytes,
        )
        results.append(result)

        # Judge0 marks a submission "Accepted" when no expected_output is sent;
        # the platform compares locally in _to_test_case_result. Convert a
        # local output mismatch on an otherwise-accepted run into wrong_answer.
        if status == ExecutionStatus.accepted and not result.passed:
            status = ExecutionStatus.wrong_answer
            result = TestCaseResult(
                test_case=result.test_case,
                label=result.label,
                passed=result.passed,
                execution_time_ms=result.execution_time_ms,
                input=result.input,
                stdout=result.stdout,
                stderr=result.stderr or "Wrong answer: output does not match expected output.",
            )
            results[-1] = result

        if status != ExecutionStatus.accepted:
            overall_status = status
            failed_test = result.test_case
            break

    passed_count = sum(1 for r in results if r.passed)
    return ExecuteResponse(
        status=overall_status,
        language=lang,
        execution_time_ms=int((time.monotonic() - overall_start) * 1000),
        tests=results,
        error=(results[-1].stderr if results and overall_status != ExecutionStatus.accepted else None),
        failed_test=failed_test,
        total_tests=len(request.test_cases),
        passed_tests=passed_count,
        session_id=request.session_id,
        attempt_id=request.attempt_id,
        question_id=request.question_id,
    )


def check_judge0_health() -> dict[str, Any]:
    """Probe Judge0 and report server info plus the resolved language map."""
    try:
        with httpx.Client(timeout=10.0) as client:
            about_resp = client.get(_judge0_url("about"), headers=_headers())
            about_resp.raise_for_status()
            about = about_resp.json()
        languages = fetch_languages()
        resolved = resolve_language_ids(languages)
        names: dict[str, Optional[str]] = {}
        langs_by_id = {int(l["id"]): l["name"] for l in languages}
        for platform, lid in resolved.items():
            names[platform] = langs_by_id.get(lid) if lid is not None else None
        return {
            "status": "ok",
            "service": "judge0",
            "version": about.get("version"),
            "judge0_url": JUDGE0_URL,
            "languages": names,
            "language_id_map": resolved,
        }
    except Exception as e:
        return {
            "status": "unreachable",
            "service": "judge0",
            "error": f"{type(e).__name__}: {e}",
            "judge0_url": JUDGE0_URL,
        }


# ── Internal helpers ─────────────────────────────────────────────────────────

def _unavailable_response(request: ExecuteRequest, message: str) -> ExecuteResponse:
    return ExecuteResponse(
        status=ExecutionStatus.compiler_unavailable,
        language=request.language.value,
        execution_time_ms=0,
        total_tests=len(request.test_cases),
        error=message,
        session_id=request.session_id,
        attempt_id=request.attempt_id,
        question_id=request.question_id,
    )


def _invalid_language_response(request: ExecuteRequest, message: str) -> ExecuteResponse:
    return ExecuteResponse(
        status=ExecutionStatus.invalid_language,
        language=request.language.value,
        execution_time_ms=0,
        total_tests=len(request.test_cases),
        error=message,
        session_id=request.session_id,
        attempt_id=request.attempt_id,
        question_id=request.question_id,
    )


class ExecutionServiceUnavailable(Exception):
    """Judge0 is unreachable or its queue is full."""

    def __init__(self, message: str, reason: str = "unavailable"):
        super().__init__(message)
        self.reason = reason


class Judge0SubmissionError(Exception):
    """Judge0 rejected a submission (validation / unexpected error)."""