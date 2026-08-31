"""
LAN Connectivity Tests for Phase 6.

These tests verify that the App/Gateway host can reach Compiler 1
over the network (LAN or localhost for testing).

Requirements:
  - Compiler 1 must be running and accessible at COMPILER_URL.
  - For local testing: COMPILER_URL=http://localhost:8001
  - For LAN testing: COMPILER_URL=http://<compiler-lan-ip>:8001

These tests prove:
  1. Network connectivity to Compiler 1
  2. Compiler 1 health endpoint works over the network
  3. Code execution works over the network
  4. The API contract is correct over the network
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
import httpx


# ── Configuration ────────────────────────────────────────────────────────────

COMPILER_URL = os.getenv("COMPILER_URL", "http://localhost:8001")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Health connectivity
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_connectivity() -> None:
    """Verify HTTP connectivity to Compiler 1 /health endpoint.

    This is the most basic connectivity test. If this fails,
    the network path between machines is broken.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{COMPILER_URL}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "compiler-1"
        assert len(data["available_languages"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. Languages endpoint
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_languages_endpoint() -> None:
    """Verify the /languages endpoint returns all supported languages."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{COMPILER_URL}/languages")
        assert resp.status_code == 200
        data = resp.json()
        # All 5 languages should be available
        for lang in ("python", "cpp", "c", "java", "javascript"):
            assert lang in data
            assert data[lang]["available"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. Execution connectivity — Python
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execution_python_hello() -> None:
    """Execute a simple Python program over the network.

    This proves the full pipeline:
      App/Gateway host → HTTP → Compiler 1 → compile/execute → result
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{COMPILER_URL}/execute",
            json={
                "language": "python",
                "source_code": 'print("hello")',
                "test_cases": [{"input": "", "expected_output": "hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["passed_tests"] == 1
        assert data["total_tests"] == 1
        assert data["execution_time_ms"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Execution connectivity — C++
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execution_cpp_hello() -> None:
    """Execute a simple C++ program over the network."""
    code = """
#include <iostream>
int main() {
    std::cout << "hello" << std::endl;
    return 0;
}
"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{COMPILER_URL}/execute",
            json={
                "language": "cpp",
                "source_code": code,
                "test_cases": [{"input": "", "expected_output": "hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Execution connectivity — Java
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execution_java_hello() -> None:
    """Execute a simple Java program over the network."""
    code = 'public class Solution { public static void main(String[] args) { System.out.println("hello"); } }'
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{COMPILER_URL}/execute",
            json={
                "language": "java",
                "source_code": code,
                "test_cases": [{"input": "", "expected_output": "hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Execution connectivity — JavaScript
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execution_javascript_hello() -> None:
    """Execute a simple JavaScript program over the network."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{COMPILER_URL}/execute",
            json={
                "language": "javascript",
                "source_code": 'console.log("hello")',
                "test_cases": [{"input": "", "expected_output": "hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Multiple test cases over network
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multiple_test_cases_over_network() -> None:
    """Execute code with multiple test cases over the network."""
    code = """
import sys
x = int(input())
print(x * 2)
"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{COMPILER_URL}/execute",
            json={
                "language": "python",
                "source_code": code,
                "test_cases": [
                    {"input": "3", "expected_output": "6"},
                    {"input": "7", "expected_output": "14"},
                    {"input": "0", "expected_output": "0"},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["total_tests"] == 3
        assert data["passed_tests"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# 8. Compiler error over network
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compilation_error_over_network() -> None:
    """Compilation error is correctly returned over the network."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{COMPILER_URL}/execute",
            json={
                "language": "cpp",
                "source_code": "int main() { cout << 42; }",
                "test_cases": [{"input": "", "expected_output": "42"}],
            },
        )
        # Compilation errors return 422 (Unprocessable Entity)
        assert resp.status_code in (200, 422)
        data = resp.json()
        assert data["status"] == "compilation_error"
        assert data["error"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# 9. Wrong answer over network
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wrong_answer_over_network() -> None:
    """Wrong answer is correctly returned over the network."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{COMPILER_URL}/execute",
            json={
                "language": "python",
                "source_code": "print(999)",
                "test_cases": [{"input": "", "expected_output": "42"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "wrong_answer"
        assert data["failed_test"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 10. Timeout over network
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_timeout_over_network() -> None:
    """Timeout is correctly returned over the network."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{COMPILER_URL}/execute",
            json={
                "language": "python",
                "source_code": "while True: pass",
                "test_cases": [{"input": "", "expected_output": ""}],
                "limits": {"time_limit_seconds": 2.0},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("wrong_answer", "time_limit_exceeded")
        assert data["execution_time_ms"] < 10000


# ─────────────────────────────────────────────────────────────────────────────
# 11. Connection refused (compiler down)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connection_refused() -> None:
    """Verify behavior when Compiler 1 is unreachable."""
    bad_url = COMPILER_URL.rsplit(":", 1)[0] + ":19999"
    async with httpx.AsyncClient(timeout=5.0) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get(f"{bad_url}/health")


# ─────────────────────────────────────────────────────────────────────────────
# 12. Response time sanity check
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_response_time_sanity() -> None:
    """Health check should respond quickly over the network."""
    import time
    async with httpx.AsyncClient(timeout=10.0) as client:
        start = time.monotonic()
        resp = await client.get(f"{COMPILER_URL}/health")
        elapsed = (time.monotonic() - start) * 1000
        assert resp.status_code == 200
        # Health check should complete in under 2 seconds (including network)
        assert elapsed < 2000, f"Health check took {elapsed:.0f}ms"
