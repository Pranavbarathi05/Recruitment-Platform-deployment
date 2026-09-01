"""
Integration tests for the App 1 → Compiler 1 pipeline.

These tests verify that the compiler_client library correctly communicates
with Compiler 1 and maps responses to the format the application expects.

Requirements:
  - Compiler 1 must be running and accessible at COMPILER_URL.
  - For Docker: run `docker compose -f compiler-1/docker-compose.yml up -d`
  - For local: run the compiler-1 service on port 8001.

These tests do NOT modify dsc-recruit/.
"""
from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio

from compiler_client.client import CompilerClient, CompilerError, ExecutionResult, LANGUAGE_MAP


# ── Configuration ────────────────────────────────────────────────────────────

COMPILER_URL = os.getenv("COMPILER_URL", "http://localhost:8001")


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def client():
    """Compiler client pointed at the running Compiler 1 service."""
    c = CompilerClient(url=COMPILER_URL, timeout=30.0)
    yield c
    await c.close()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Health check
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compiler_health(client: CompilerClient) -> None:
    """Compiler 1 health endpoint is reachable."""
    health = await client.health()
    assert health["status"] == "ok"
    assert health["service"] == "compiler-1"
    assert len(health["available_languages"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. Python accepted
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_python_accepted(client: CompilerClient) -> None:
    """Python code that produces correct output is accepted."""
    result = await client.execute(
        language="python",
        source_code="print(42)",
        test_cases=[{"input": "", "expected_output": "42"}],
    )
    assert result.status == "accepted"
    assert result.is_success
    assert result.passed_tests == 1
    assert result.total_tests == 1
    assert result.execution_time_ms > 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Python wrong answer
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_python_wrong_answer(client: CompilerClient) -> None:
    """Python code that produces incorrect output is marked wrong_answer."""
    result = await client.execute(
        language="python",
        source_code="print(999)",
        test_cases=[{"input": "", "expected_output": "42"}],
    )
    assert result.status == "wrong_answer"
    assert not result.is_success
    assert result.is_code_error
    assert result.failed_test == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. Python runtime error
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_python_runtime_error(client: CompilerClient) -> None:
    """Python code that crashes is marked runtime_error or wrong_answer."""
    result = await client.execute(
        language="python",
        source_code="import sys; sys.exit(1)",
        test_cases=[{"input": "", "expected_output": ""}],
    )
    assert result.status in ("runtime_error", "wrong_answer")
    assert result.is_code_error


# ─────────────────────────────────────────────────────────────────────────────
# 5. Python timeout
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_python_timeout(client: CompilerClient) -> None:
    """Python infinite loop is killed by timeout."""
    result = await client.execute(
        language="python",
        source_code="while True: pass",
        test_cases=[{"input": "", "expected_output": ""}],
        limits={"time_limit_seconds": 2.0},
    )
    assert result.status in ("wrong_answer", "time_limit_exceeded")
    assert result.execution_time_ms < 10000  # Should complete quickly due to timeout


# ─────────────────────────────────────────────────────────────────────────────
# 6. C++ accepted
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cpp_accepted(client: CompilerClient) -> None:
    """C++ code that produces correct output is accepted."""
    code = """
#include <iostream>
int main() {
    std::cout << "hello" << std::endl;
    return 0;
}
"""
    result = await client.execute(
        language="cpp",
        source_code=code,
        test_cases=[{"input": "", "expected_output": "hello"}],
    )
    assert result.status == "accepted"
    assert result.is_success


# ─────────────────────────────────────────────────────────────────────────────
# 7. C++ compilation error
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cpp_compilation_error(client: CompilerClient) -> None:
    """C++ code with syntax error is marked compilation_error."""
    result = await client.execute(
        language="cpp",
        source_code="int main() { cout << 42; }",
        test_cases=[{"input": "", "expected_output": "42"}],
    )
    assert result.status == "compilation_error"
    assert result.is_code_error
    assert result.error is not None
    assert len(result.error) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 8. Java accepted
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_java_accepted(client: CompilerClient) -> None:
    """Java code that produces correct output is accepted."""
    code = 'public class Solution { public static void main(String[] args) { System.out.println("hello"); } }'
    result = await client.execute(
        language="java",
        source_code=code,
        test_cases=[{"input": "", "expected_output": "hello"}],
    )
    assert result.status == "accepted"
    assert result.is_success


# ─────────────────────────────────────────────────────────────────────────────
# 9. Multiple test cases
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multiple_test_cases(client: CompilerClient) -> None:
    """Multiple test cases are all executed."""
    code = """
import sys
x = int(input())
print(x * 2)
"""
    result = await client.execute(
        language="python",
        source_code=code,
        test_cases=[
            {"input": "3", "expected_output": "6"},
            {"input": "7", "expected_output": "14"},
            {"input": "0", "expected_output": "0"},
        ],
    )
    assert result.status == "accepted"
    assert result.total_tests == 3
    assert result.passed_tests == 3
    assert len(result.tests) == 3


# ─────────────────────────────────────────────────────────────────────────────
# 10. Invalid language
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_language(client: CompilerClient) -> None:
    """Unsupported language returns invalid_language status."""
    result = await client.execute(
        language="rust",
        source_code="fn main() {}",
        test_cases=[{"input": "", "expected_output": ""}],
    )
    assert result.status == "invalid_language"
    assert result.is_code_error
    assert result.error is not None


# ─────────────────────────────────────────────────────────────────────────────
# 11. Language mapping
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_language_mapping(client: CompilerClient) -> None:
    """Various language string formats are mapped correctly."""
    # "python3" should map to "python"
    result = await client.execute(
        language="python3",
        source_code="print(1)",
        test_cases=[{"input": "", "expected_output": "1"}],
    )
    assert result.status == "accepted"

    # "c++" should map to "cpp"
    result = await client.execute(
        language="c++",
        source_code='#include <iostream>\nint main() { std::cout << 1 << std::endl; }',
        test_cases=[{"input": "", "expected_output": "1"}],
    )
    assert result.status == "accepted"


# ─────────────────────────────────────────────────────────────────────────────
# 12. Execution result properties
# ─────────────────────────────────────────────────────────────────────────────

def test_execution_result_properties() -> None:
    """ExecutionResult properties correctly classify statuses."""
    # Success
    r = ExecutionResult(status="accepted", language="python", total_tests=1, passed_tests=1)
    assert r.is_success
    assert not r.is_code_error
    assert not r.is_infrastructure_error

    # Code errors
    for status in ("wrong_answer", "compilation_error", "runtime_error", "time_limit_exceeded", "invalid_language"):
        r = ExecutionResult(status=status, language="python")
        assert not r.is_success
        assert r.is_code_error
        assert not r.is_infrastructure_error

    # Infrastructure errors
    for status in ("compiler_error", "compiler_unavailable", "capacity_exceeded"):
        r = ExecutionResult(status=status, language="python")
        assert not r.is_success
        assert not r.is_code_error
        assert r.is_infrastructure_error


# ─────────────────────────────────────────────────────────────────────────────
# 13. to_dict serialization
# ─────────────────────────────────────────────────────────────────────────────

def test_execution_result_to_dict() -> None:
    """ExecutionResult serializes to dict correctly."""
    r = ExecutionResult(
        status="accepted",
        language="python",
        execution_time_ms=100,
        total_tests=3,
        passed_tests=3,
        tests=[{"test_case": 1, "passed": True}],
    )
    d = r.to_dict()
    assert d["status"] == "accepted"
    assert d["language"] == "python"
    assert d["execution_time_ms"] == 100
    assert d["total_tests"] == 3
    assert d["passed_tests"] == 3
    assert len(d["tests"]) == 1

    # Error fields only included when present
    r2 = ExecutionResult(status="wrong_answer", language="python", error="wrong", failed_test=2)
    d2 = r2.to_dict()
    assert d2["error"] == "wrong"
    assert d2["failed_test"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# 14. Compiler unavailable
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compiler_unavailable() -> None:
    """Compiler 1 being unreachable raises CompilerError."""
    bad_client = CompilerClient(url="http://localhost:19999", timeout=2.0)
    try:
        with pytest.raises(CompilerError) as exc_info:
            await bad_client.execute(
                language="python",
                source_code="print(1)",
                test_cases=[{"input": "", "expected_output": "1"}],
            )
        assert exc_info.value.status == "compiler_unavailable"
    finally:
        await bad_client.close()


# ─────────────────────────────────────────────────────────────────────────────
# 15. Empty test cases
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_test_cases(client: CompilerClient) -> None:
    """Empty test cases list returns internal_error."""
    result = await client.execute(
        language="python",
        source_code="print(1)",
        test_cases=[],
    )
    assert result.status == "internal_error"
    assert result.is_infrastructure_error


# ─────────────────────────────────────────────────────────────────────────────
# 16. SQL accepted
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sql_accepted(client: CompilerClient) -> None:
    """SQL code that produces correct output is accepted."""
    result = await client.execute(
        language="sql",
        source_code="CREATE TABLE t (id INTEGER); INSERT INTO t VALUES (1);",
        test_cases=[{"input": "SELECT * FROM t;", "expected_output": "id\n1"}],
    )
    assert result.status == "accepted"
    assert result.is_success


# ─────────────────────────────────────────────────────────────────────────────
# 17. Multiple simultaneous submissions
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_submissions(client: CompilerClient) -> None:
    """Multiple concurrent submissions are handled correctly."""
    async def submit_one(n: int):
        return await client.execute(
            language="python",
            source_code=f"print({n})",
            test_cases=[{"input": "", "expected_output": str(n)}],
        )

    results = await asyncio.gather(*[submit_one(i) for i in range(4)])
    for i, result in enumerate(results):
        assert result.status == "accepted", f"Submission {i} failed: {result.status}"
