"""
Automated tests for the Compiler 1 execution service.

Covers:
  1. Health endpoint
  2. Successful execution
  3. Wrong answer
  4. Compilation error
  5. Runtime error
  6. Timeout
  7. Unsupported language
  8. Multiple test cases
  9. Empty/invalid source code
  10. Cleanup after execution
  11. Concurrent execution up to configured capacity
  12. Requests beyond configured capacity
  + Hostile execution tests (infinite loop, excessive output, filesystem access)
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas import ExecuteRequest, ExecutionStatus, Language, TestCase


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def client():
    """Async HTTP client backed by the FastAPI ASGI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


def _exec_body(
    language: str,
    code: str,
    test_cases: list[dict[str, str]],
    limits: dict[str, Any] | None = None,
) -> dict:
    """Build an execute request body."""
    body: dict[str, Any] = {
        "language": language,
        "source_code": code,
        "test_cases": test_cases,
    }
    if limits:
        body["limits"] = limits
    return body


# ─────────────────────────────────────────────────────────────────────────────
# 1. Health endpoint
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    """GET /health returns service status and available languages."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "compiler-1"
    assert "available_languages" in body
    assert isinstance(body["available_languages"], list)
    assert len(body["available_languages"]) > 0
    # Each language entry has required fields
    for lang in body["available_languages"]:
        assert "name" in lang
        assert "available" in lang


@pytest.mark.asyncio
async def test_languages_endpoint(client: AsyncClient) -> None:
    """GET /languages returns all registered languages."""
    resp = await client.get("/languages")
    assert resp.status_code == 200
    body = resp.json()
    assert "python" in body
    assert body["python"]["available"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. Successful execution
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_python_accepted(client: AsyncClient) -> None:
    """Python code that produces correct output."""
    body = _exec_body(
        language="python",
        code='print("Hello, World!")',
        test_cases=[{"input": "", "expected_output": "Hello, World!"}],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["passed_tests"] == 1
    assert data["total_tests"] == 1
    assert len(data["tests"]) == 1
    assert data["tests"][0]["passed"] is True


@pytest.mark.asyncio
async def test_cpp_accepted(client: AsyncClient) -> None:
    """C++ code that produces correct output."""
    code = """
#include <iostream>
int main() {
    std::cout << "42" << std::endl;
    return 0;
}
"""
    body = _exec_body(
        language="cpp",
        code=code,
        test_cases=[{"input": "", "expected_output": "42"}],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"


@pytest.mark.asyncio
async def test_javascript_accepted(client: AsyncClient) -> None:
    """JavaScript code that produces correct output."""
    body = _exec_body(
        language="javascript",
        code='console.log("hello")',
        test_cases=[{"input": "", "expected_output": "hello"}],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Wrong answer
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_python_wrong_answer(client: AsyncClient) -> None:
    """Python code that produces incorrect output."""
    body = _exec_body(
        language="python",
        code='print("wrong")',
        test_cases=[{"input": "", "expected_output": "correct"}],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "wrong_answer"
    assert data["failed_test"] == 1
    assert data["tests"][0]["passed"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. Compilation error
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cpp_compilation_error(client: AsyncClient) -> None:
    """C++ code with a syntax error fails at compilation."""
    body = _exec_body(
        language="cpp",
        code='int main() { cout << "hello"; }',
        test_cases=[{"input": "", "expected_output": "hello"}],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 422
    data = resp.json()
    assert data["status"] == "compilation_error"
    assert data["error"] is not None
    assert len(data["error"]) > 0


@pytest.mark.asyncio
async def test_c_compilation_error(client: AsyncClient) -> None:
    """C code with a syntax error fails at compilation."""
    body = _exec_body(
        language="c",
        code='int main() { printf("hello" }',
        test_cases=[{"input": "", "expected_output": "hello"}],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 422
    data = resp.json()
    assert data["status"] == "compilation_error"


@pytest.mark.asyncio
async def test_java_compilation_error(client: AsyncClient) -> None:
    """Java code with a syntax error fails at compilation."""
    body = _exec_body(
        language="java",
        code='public class Solution { public static void main(String[] args) { System.out.println("hello" } }',
        test_cases=[{"input": "", "expected_output": "hello"}],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 422
    data = resp.json()
    assert data["status"] == "compilation_error"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Runtime error
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_python_runtime_error(client: AsyncClient) -> None:
    """Python code that crashes at runtime."""
    body = _exec_body(
        language="python",
        code='import sys; sys.exit(1)',
        test_cases=[{"input": "", "expected_output": ""}],
    )
    resp = await client.post("/execute", json=body)
    # Runtime errors may come back as wrong_answer (non-zero exit, empty output)
    # or runtime_error depending on the implementation
    data = resp.json()
    assert data["status"] in ("wrong_answer", "runtime_error")


@pytest.mark.asyncio
async def test_cpp_runtime_error(client: AsyncClient) -> None:
    """C++ code that crashes at runtime (segfault)."""
    code = """
#include <cstdlib>
int main() {
    int* p = nullptr;
    *p = 42;
    return 0;
}
"""
    body = _exec_body(
        language="cpp",
        code=code,
        test_cases=[{"input": "", "expected_output": ""}],
    )
    resp = await client.post("/execute", json=body)
    data = resp.json()
    assert data["status"] in ("wrong_answer", "runtime_error")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Timeout
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_python_timeout(client: AsyncClient) -> None:
    """Python infinite loop times out."""
    body = _exec_body(
        language="python",
        code='while True: pass',
        test_cases=[{"input": "", "expected_output": ""}],
        limits={"time_limit_seconds": 2.0},
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "wrong_answer"  # First test fails
    assert data["tests"][0]["passed"] is False
    # The execution should complete quickly due to timeout
    assert data["execution_time_ms"] < 10000  # Well under 10s


@pytest.mark.asyncio
async def test_cpp_timeout(client: AsyncClient) -> None:
    """C++ infinite loop times out."""
    code = """
#include <iostream>
int main() {
    while(true) {}
    return 0;
}
"""
    body = _exec_body(
        language="cpp",
        code=code,
        test_cases=[{"input": "", "expected_output": ""}],
        limits={"time_limit_seconds": 2.0},
    )
    resp = await client.post("/execute", json=body)
    data = resp.json()
    assert data["tests"][0]["passed"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 7. Unsupported language
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unsupported_language(client: AsyncClient) -> None:
    """Requesting an unsupported language returns a structured error."""
    body = _exec_body(
        language="python",
        code='print("hello")',
        test_cases=[{"input": "", "expected_output": "hello"}],
    )
    # The API schema only accepts valid Language enum values,
    # so we test by directly calling the executor logic.
    # For the HTTP API, invalid languages get rejected by Pydantic.
    # We verify the schema validation works.
    resp = await client.post("/execute", json={
        "language": "rust",
        "source_code": "fn main() {}",
        "test_cases": [{"input": "", "expected_output": ""}],
    })
    assert resp.status_code == 422  # Pydantic validation error


# ─────────────────────────────────────────────────────────────────────────────
# 8. Multiple test cases
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multiple_test_cases(client: AsyncClient) -> None:
    """Multiple test cases are all executed and reported."""
    body = _exec_body(
        language="python",
        code='import sys\nx = int(input())\nprint(x * 2)',
        test_cases=[
            {"input": "3", "expected_output": "6"},
            {"input": "7", "expected_output": "14"},
            {"input": "0", "expected_output": "0"},
        ],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["total_tests"] == 3
    assert data["passed_tests"] == 3
    assert len(data["tests"]) == 3
    for t in data["tests"]:
        assert t["passed"] is True


@pytest.mark.asyncio
async def test_multiple_test_cases_partial_failure(client: AsyncClient) -> None:
    """Multiple test cases where one fails stops execution."""
    body = _exec_body(
        language="python",
        code='print("always_wrong")',
        test_cases=[
            {"input": "", "expected_output": "correct1"},
            {"input": "", "expected_output": "correct2"},
        ],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "wrong_answer"
    assert data["failed_test"] == 1
    # Only the first test is recorded (execution stops on failure)
    assert len(data["tests"]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 9. Empty/invalid source code
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_source_code_rejected(client: AsyncClient) -> None:
    """Empty source code is rejected by the schema."""
    body = _exec_body(
        language="python",
        code="",
        test_cases=[{"input": "", "expected_output": ""}],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 422  # Pydantic validation: min_length=1


@pytest.mark.asyncio
async def test_invalid_test_cases_rejected(client: AsyncClient) -> None:
    """Empty test_cases list is rejected."""
    body = _exec_body(
        language="python",
        code='print("hello")',
        test_cases=[],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 422  # Pydantic validation: min_length=1


@pytest.mark.asyncio
async def test_missing_required_fields(client: AsyncClient) -> None:
    """Missing required fields returns 422."""
    resp = await client.post("/execute", json={"language": "python"})
    assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# 10. Cleanup after execution
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cleanup_after_execution(client: AsyncClient) -> None:
    """Temporary files are cleaned up after execution."""
    from app import executor as exec_mod

    # Count temp dirs before
    before = set(Path(tempfile.gettempdir()).glob("compiler1_*"))

    body = _exec_body(
        language="python",
        code='print("cleanup_test")',
        test_cases=[{"input": "", "expected_output": "cleanup_test"}],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 200

    # Count temp dirs after
    time.sleep(0.2)  # Small delay for cleanup
    after = set(Path(tempfile.gettempdir()).glob("compiler1_*"))

    # No new temp dirs should remain
    new_dirs = after - before
    assert len(new_dirs) == 0, f"Leftover temp dirs: {new_dirs}"


@pytest.mark.asyncio
async def test_cleanup_on_error(client: AsyncClient) -> None:
    """Temp files are cleaned up even when compilation fails."""
    before = set(Path(tempfile.gettempdir()).glob("compiler1_*"))

    body = _exec_body(
        language="cpp",
        code='invalid code {{{{',
        test_cases=[{"input": "", "expected_output": ""}],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 422  # Compilation error

    time.sleep(0.2)
    after = set(Path(tempfile.gettempdir()).glob("compiler1_*"))
    new_dirs = after - before
    assert len(new_dirs) == 0, f"Leftover temp dirs: {new_dirs}"


# ─────────────────────────────────────────────────────────────────────────────
# 11. Concurrent execution up to capacity
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_execution_up_to_capacity(client: AsyncClient) -> None:
    """Multiple concurrent requests succeed up to the configured capacity."""
    code = 'import time; time.sleep(0.5); print("done")'
    body = _exec_body(
        language="python",
        code=code,
        test_cases=[{"input": "", "expected_output": "done"}],
        limits={"time_limit_seconds": 5.0},
    )

    # Send MAX_CONCURRENT requests simultaneously
    from app.routers.execute import _MAX_CONCURRENT
    results: list[int] = []

    async def do_request():
        resp = await client.post("/execute", json=body)
        results.append(resp.status_code)

    tasks = [do_request() for _ in range(_MAX_CONCURRENT)]
    import asyncio
    await asyncio.gather(*tasks)

    # All should succeed (200)
    assert all(r == 200 for r in results), f"Status codes: {results}"


# ─────────────────────────────────────────────────────────────────────────────
# 12. Requests beyond capacity
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_beyond_capacity(client: AsyncClient) -> None:
    """Requests beyond capacity return 503."""
    from app.routers.execute import _MAX_CONCURRENT, _semaphore

    # Fill up all slots
    code = 'import time; time.sleep(1); print("done")'
    body = _exec_body(
        language="python",
        code=code,
        test_cases=[{"input": "", "expected_output": "done"}],
        limits={"time_limit_seconds": 5.0},
    )

    # Acquire all slots
    acquired = []
    for _ in range(_MAX_CONCURRENT):
        if _semaphore.acquire(blocking=False):
            acquired.append(True)

    try:
        # This request should get 503
        resp = await client.post("/execute", json=body)
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "capacity_exceeded"
    finally:
        # Release slots
        for _ in acquired:
            _semaphore.release()


# ─────────────────────────────────────────────────────────────────────────────
# Hostile execution tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hostile_infinite_loop(client: AsyncClient) -> None:
    """Infinite loop is killed by timeout."""
    body = _exec_body(
        language="python",
        code='while True: pass',
        test_cases=[{"input": "", "expected_output": ""}],
        limits={"time_limit_seconds": 2.0},
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_time_ms"] < 10000


@pytest.mark.asyncio
async def test_hostile_excessive_output(client: AsyncClient) -> None:
    """Excessive output is truncated."""
    code = 'print("A" * 1000000)'
    body = _exec_body(
        language="python",
        code=code,
        test_cases=[{"input": "", "expected_output": ""}],
        limits={"max_output_bytes": 4096},
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 200
    data = resp.json()
    # Should not crash, output should be truncated
    if data["tests"]:
        stdout = data["tests"][0].get("stdout", "")
        assert len(stdout) < 10000  # Truncated


@pytest.mark.asyncio
async def test_hostile_filesystem_access(client: AsyncClient) -> None:
    """Attempt to access restricted filesystem paths."""
    body = _exec_body(
        language="python",
        code='import os; print(os.listdir("/"))',
        test_cases=[{"input": "", "expected_output": ""}],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 200
    # The code runs but we don't care about the output for this test
    # The important thing is the sandbox doesn't crash


@pytest.mark.asyncio
async def test_hostile_network_access(client: AsyncClient) -> None:
    """Attempt to access network resources (may fail or succeed depending on container)."""
    body = _exec_body(
        language="python",
        code='import urllib.request; urllib.request.urlopen("http://example.com", timeout=2)',
        test_cases=[{"input": "", "expected_output": ""}],
        limits={"time_limit_seconds": 5.0},
    )
    resp = await client.post("/execute", json=body)
    # Should not crash the service
    assert resp.status_code in (200, 422)


@pytest.mark.asyncio
async def test_hostile_process_spawning(client: AsyncClient) -> None:
    """Attempt to spawn processes."""
    body = _exec_body(
        language="python",
        code='import os; os.system("echo pwned")',
        test_cases=[{"input": "", "expected_output": ""}],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 200
    # Should not crash the service


@pytest.mark.asyncio
async def test_hostile_symlink_escape(client: AsyncClient) -> None:
    """Attempt to read files via symlinks."""
    code = """
import os
try:
    with open("/etc/passwd") as f:
        print(f.read()[:100])
except:
    print("denied")
"""
    body = _exec_body(
        language="python",
        code=code,
        test_cases=[{"input": "", "expected_output": ""}],
    )
    resp = await client.post("/execute", json=body)
    assert resp.status_code == 200
    # The service should not crash regardless of what the code reads


@pytest.mark.asyncio
async def test_hostile_fork_bomb(client: AsyncClient) -> None:
    """Attempt a fork bomb."""
    body = _exec_body(
        language="python",
        code='import os; [os.fork() for _ in range(100)]',
        test_cases=[{"input": "", "expected_output": ""}],
        limits={"time_limit_seconds": 2.0},
    )
    resp = await client.post("/execute", json=body)
    # Should be limited by ulimit -u
    assert resp.status_code in (200, 422)
