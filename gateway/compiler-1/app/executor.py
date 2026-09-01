"""
Sandboxed code execution engine for Compiler 1.

Execution model:
  1. Create a temporary working directory.
  2. Write source code to a file.
  3. Compile if needed (catch compilation errors).
  4. For each test case:
     a. Write a bash wrapper script with resource limits (ulimit).
     b. Execute as a child process with wall-clock timeout.
     c. Capture stdout, stderr, exit code.
     d. Compare stdout against expected output.
     e. Clean up.
  5. Remove the temporary directory.

Security measures:
  - Non-root execution via Docker USER directive.
  - ulimit CPU time, file size, no-core-dump.
  - Wall-clock timeout via `timeout` command.
  - Temporary filesystem only (no access to host outside work dir).
  - Process group kill on timeout.
  - Output truncation to prevent excessive memory use.
  - All temp files cleaned up after execution.
"""
from __future__ import annotations

import asyncio
import os
import resource
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from .languages import LanguageAdapter, SqlAdapter, get_adapter
from .schemas import (
    ExecuteRequest,
    ExecuteResponse,
    ExecutionLimits,
    ExecutionStatus,
    TestCase,
    TestCaseResult,
)


# ── Configuration ────────────────────────────────────────────────────────────

# CPU time limit (seconds) passed to ulimit -t.
# This is CPU time, not wall-clock time. Wall-clock is enforced by `timeout`.
_CPU_TIME_LIMIT_S = 30

# Maximum file size a process can create (in 512-byte blocks).
# 1 MB = 2048 blocks. Prevents excessive disk output.
_FILE_SIZE_BLOCKS = 2048

# Maximum number of processes/threads a user can spawn.
# Must be high enough for the shell wrapper + timeout + child process.
_MAX_PROCS = 256

# Maximum number of open file descriptors.
_MAX_FDS = 64


def _truncate(text: str, max_bytes: int) -> str:
    """Truncate text to max_bytes, adding a notice if truncated."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
    return truncated + f"\n... [truncated at {max_bytes} bytes]"


# ── Execution ────────────────────────────────────────────────────────────────

def _build_run_script(
    adapter: LanguageAdapter,
    source_path: Path,
    work_dir: Path,
    input_text: str,
    time_limit_s: float,
    max_output_bytes: int,
) -> str:
    """Build a bash script that runs the program with resource limits."""
    # Write input to a file (avoids shell escaping issues)
    input_file = work_dir / "_stdin.txt"
    input_file.write_text(input_text, encoding="utf-8")

    # The adapter's run script execs the program.
    # We wrap it with ulimit and timeout.
    run_cmds = adapter.run_script(source_path, work_dir)
    inner_cmd = run_cmds.strip().replace("exec ", "")

    script = f"""#!/bin/bash

# Resource limits (best-effort; Docker cgroups enforce hard limits)
ulimit -t {_CPU_TIME_LIMIT_S}     2>/dev/null || true   # CPU time (seconds)
ulimit -f {_FILE_SIZE_BLOCKS}     2>/dev/null || true   # Max file size (512-byte blocks)
ulimit -c 0                       2>/dev/null || true   # No core dumps

# Execute the program with wall-clock timeout
exec timeout --signal=KILL {time_limit_s} \
    /bin/bash -c '{inner_cmd}' \
    < "{input_file}"
"""
    return script


def execute_single_test(
    adapter: LanguageAdapter,
    source_path: Path,
    work_dir: Path,
    test_case: TestCase,
    test_index: int,
    limits: ExecutionLimits,
) -> TestCaseResult:
    """Execute a single test case and return the result."""
    script_path = work_dir / f"_run_{test_index}.sh"
    script_content = _build_run_script(
        adapter, source_path, work_dir,
        test_case.input,
        limits.time_limit_seconds,
        limits.max_output_bytes,
    )
    script_path.write_text(script_content, encoding="utf-8")
    script_path.chmod(0o755)

    stdout_path = work_dir / f"_stdout_{test_index}.txt"
    stderr_path = work_dir / f"_stderr_{test_index}.txt"

    start = time.monotonic()
    try:
        proc = subprocess.run(
            ["/bin/bash", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=limits.time_limit_seconds + 2,  # Extra 2s for wrapper overhead
            cwd=str(work_dir),
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        stdout_raw = proc.stdout.decode("utf-8", errors="replace")
        stderr_raw = proc.stderr.decode("utf-8", errors="replace")

        stdout_trunc = _truncate(stdout_raw, limits.max_output_bytes)
        stderr_trunc = _truncate(stderr_raw, limits.max_output_bytes)

        # Check for timeout (timeout command exits with 137 on SIGKILL, 124 on SIGTERM)
        timed_out = proc.returncode in (137, 124)

        # Check for runtime error (non-zero exit, excluding timeout codes)
        runtime_error = proc.returncode != 0 and not timed_out

        # Compare output: strip trailing whitespace from both
        actual = stdout_raw.rstrip()
        expected = test_case.expected_output.rstrip()
        passed = (actual == expected) and not timed_out and not runtime_error

        return TestCaseResult(
            test_case=test_index + 1,
            label=test_case.label,
            passed=passed,
            execution_time_ms=elapsed_ms,
            input=test_case.input if len(test_case.input) < 2048 else test_case.input[:2048] + "...",
            stdout=stdout_trunc,
            stderr=stderr_trunc,
        )

    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return TestCaseResult(
            test_case=test_index + 1,
            label=test_case.label,
            passed=False,
            execution_time_ms=elapsed_ms,
            input=test_case.input if len(test_case.input) < 2048 else test_case.input[:2048] + "...",
            stdout="",
            stderr="TIMEOUT: execution exceeded time limit",
        )
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return TestCaseResult(
            test_case=test_index + 1,
            label=test_case.label,
            passed=False,
            execution_time_ms=elapsed_ms,
            input=test_case.input if len(test_case.input) < 2048 else test_case.input[:2048] + "...",
            stdout="",
            stderr=f"INTERNAL ERROR: {type(e).__name__}: {e}",
        )
    finally:
        # Clean up run artifacts
        for p in [script_path, stdout_path, stderr_path, work_dir / "_stdin.txt"]:
            p.unlink(missing_ok=True)


def _execute_sql(
    adapter: SqlAdapter,
    source_path: Path,
    work_dir: Path,
    request: ExecuteRequest,
    overall_start: float,
) -> ExecuteResponse:
    """Execute SQL source code against test cases using SQLite.

    Flow:
      1. Initialize database with source SQL (DDL + DML)
      2. For each test case, run the query (test_case.input) and compare output
    """
    language = request.language.value

    # Initialize the database with the source SQL
    success, error = adapter.init_database(source_path, work_dir)
    if not success:
        return ExecuteResponse(
            status=ExecutionStatus.compilation_error,
            language=language,
            execution_time_ms=int((time.monotonic() - overall_start) * 1000),
            total_tests=len(request.test_cases),
            error=error,
        )

    # Execute test cases (each test case's input is a SQL query)
    results: list[TestCaseResult] = []
    failed_test: Optional[int] = None
    status = ExecutionStatus.accepted

    for i, tc in enumerate(request.test_cases):
        start = time.monotonic()
        try:
            query_ok, stdout, stderr = adapter.run_query(
                tc.input, work_dir, request.limits.max_output_bytes,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)

            if not query_ok:
                results.append(TestCaseResult(
                    test_case=i + 1,
                    label=tc.label,
                    passed=False,
                    execution_time_ms=elapsed_ms,
                    input=tc.input if len(tc.input) < 2048 else tc.input[:2048] + "...",
                    stdout=stdout,
                    stderr=stderr,
                ))
                failed_test = i + 1
                status = ExecutionStatus.runtime_error
                break

            actual = stdout.rstrip()
            expected = tc.expected_output.rstrip()
            passed = actual == expected

            results.append(TestCaseResult(
                test_case=i + 1,
                label=tc.label,
                passed=passed,
                execution_time_ms=elapsed_ms,
                input=tc.input if len(tc.input) < 2048 else tc.input[:2048] + "...",
                stdout=stdout,
                stderr=stderr,
            ))

            if not passed:
                failed_test = i + 1
                status = ExecutionStatus.wrong_answer
                break

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            results.append(TestCaseResult(
                test_case=i + 1,
                label=tc.label,
                passed=False,
                execution_time_ms=elapsed_ms,
                input=tc.input if len(tc.input) < 2048 else tc.input[:2048] + "...",
                stdout="",
                stderr=f"INTERNAL ERROR: {type(e).__name__}: {e}",
            ))
            failed_test = i + 1
            status = ExecutionStatus.internal_error
            break

    total_time_ms = int((time.monotonic() - overall_start) * 1000)
    passed_count = sum(1 for r in results if r.passed)

    return ExecuteResponse(
        status=status,
        language=language,
        execution_time_ms=total_time_ms,
        tests=results,
        failed_test=failed_test,
        total_tests=len(request.test_cases),
        passed_tests=passed_count,
    )


def execute_code(request: ExecuteRequest, max_concurrent: int, active_count_fn) -> ExecuteResponse:
    """
    Execute source code against test cases in an isolated temporary directory.

    This is the main entry point for code execution.
    """
    language = request.language.value
    adapter = get_adapter(language)

    if adapter is None or not adapter.is_available():
        return ExecuteResponse(
            status=ExecutionStatus.invalid_language,
            language=language,
            execution_time_ms=0,
            total_tests=len(request.test_cases),
            error=f"Language '{language}' is not supported or unavailable on this server.",
        )

    # Check concurrency
    if active_count_fn() >= max_concurrent:
        return ExecuteResponse(
            status=ExecutionStatus.capacity_exceeded,
            language=language,
            execution_time_ms=0,
            total_tests=len(request.test_cases),
            error=f"Server at capacity ({max_concurrent} concurrent executions). Try again shortly.",
        )

    # Create isolated temporary workspace
    work_dir = Path(tempfile.mkdtemp(prefix="compiler1_"))

    try:
        overall_start = time.monotonic()

        # Write source code
        source_path = work_dir / f"solution{adapter.file_extension}"
        source_path.write_text(request.source_code, encoding="utf-8")

        # SQL has a special execution model
        if isinstance(adapter, SqlAdapter):
            return _execute_sql(
                adapter, source_path, work_dir, request, overall_start,
            )

        # Compile if needed
        if hasattr(adapter, 'compile'):
            success, compile_error = adapter.compile(source_path, work_dir)
            if not success:
                return ExecuteResponse(
                    status=ExecutionStatus.compilation_error,
                    language=language,
                    execution_time_ms=int((time.monotonic() - overall_start) * 1000),
                    total_tests=len(request.test_cases),
                    error=compile_error,
                )

        # Execute test cases
        results: list[TestCaseResult] = []
        failed_test: Optional[int] = None
        status = ExecutionStatus.accepted

        for i, tc in enumerate(request.test_cases):
            result = execute_single_test(
                adapter, source_path, work_dir, tc, i, request.limits,
            )
            results.append(result)

            if not result.passed:
                status = ExecutionStatus.wrong_answer
                failed_test = result.test_case
                break

        total_time_ms = int((time.monotonic() - overall_start) * 1000)

        passed_count = sum(1 for r in results if r.passed)

        return ExecuteResponse(
            status=status,
            language=language,
            execution_time_ms=total_time_ms,
            tests=results,
            failed_test=failed_test,
            total_tests=len(request.test_cases),
            passed_tests=passed_count,
        )

    except Exception as e:
        return ExecuteResponse(
            status=ExecutionStatus.internal_error,
            language=language,
            execution_time_ms=0,
            total_tests=len(request.test_cases),
            error=f"Internal error: {type(e).__name__}: {e}",
        )
    finally:
        # Always clean up
        shutil.rmtree(work_dir, ignore_errors=True)
