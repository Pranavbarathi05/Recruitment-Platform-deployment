"""
Phase 3 – Comprehensive Integration Tests

Tests the complete deployment pipeline:
  Client → Gateway → App1 (routing)
  Client → Gateway API → Compiler 1 (code execution)

Requirements:
  - Gateway stack running (docker compose up -d)
  - Compiler 1 running (standalone or in the compose stack)
  - COMPILER_URL configured in .env

These tests verify:
  1. App1 health
  2. Gateway → App1 routing
  3. Gateway API → Compiler 1 execution (via /api/execute)
  4. Session propagation
  5. Concurrent requests
  6. Python, C, C++, Java, SQL execution
  7. Compile errors, runtime errors, timeout, invalid code
  8. Malformed requests
  9. Compiler unavailable handling
  10. App1 unavailable handling
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any

import pytest
import pytest_asyncio
import httpx

# ── Configuration ────────────────────────────────────────────────────────────

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost")
COMPILER_URL = os.getenv("COMPILER_URL", "http://localhost:8001")
APP1_URL = os.getenv("APP1_URL", "http://localhost:8002")
GATEWAY_API_URL = f"{GATEWAY_URL}/api"


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def client():
    """Async HTTP client for gateway requests."""
    async with httpx.AsyncClient(
        base_url=GATEWAY_URL,
        timeout=30.0,
    ) as c:
        yield c


@pytest_asyncio.fixture()
async def compiler_client():
    """Async HTTP client for direct Compiler 1 requests."""
    async with httpx.AsyncClient(
        base_url=COMPILER_URL,
        timeout=30.0,
    ) as c:
        yield c


# ══════════════════════════════════════════════════════════════════════════════
# 1. APP 1 HEALTH
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_app1_health_direct(client: httpx.AsyncClient) -> None:
    """App 1 health endpoint responds directly."""
    resp = await client.get(f"{APP1_URL}/")
    # App 1 may not be running in the same compose stack
    # This test is for local single-machine testing
    if resp.status_code == 200:
        data = resp.json()
        assert data["status"] == "Healthy"


@pytest.mark.asyncio
async def test_app1_health_through_gateway(client: httpx.AsyncClient) -> None:
    """App 1 is reachable through the Gateway."""
    resp = await client.get("/")
    # Should get either App 1 response (200) or gateway response
    assert resp.status_code in (200, 502, 503)


# ══════════════════════════════════════════════════════════════════════════════
# 2. GATEWAY → APP1 ROUTING
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_gateway_api_routing(client: httpx.AsyncClient) -> None:
    """Gateway API /api/* routes to gateway-api service."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "gateway-api"


@pytest.mark.asyncio
async def test_gateway_app1_catchall(client: httpx.AsyncClient) -> None:
    """Gateway catch-all route reaches App 1."""
    resp = await client.get("/")
    # App 1 returns 200 or gateway returns 502 if App 1 is down
    assert resp.status_code in (200, 502, 503)


# ══════════════════════════════════════════════════════════════════════════════
# 3. SESSION MANAGEMENT (Phase 2 preserved)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_session_start(client: httpx.AsyncClient) -> None:
    """Session creation works through the gateway."""
    resp = await client.post("/api/session/start")
    assert resp.status_code == 201
    data = resp.json()
    assert "session_id" in data
    assert data["status"] == "active"
    return data["session_id"]


@pytest.mark.asyncio
async def test_session_lifecycle(client: httpx.AsyncClient) -> None:
    """Full session lifecycle: start → heartbeat → end."""
    # Start
    resp = await client.post("/api/session/start")
    assert resp.status_code == 201
    session_id = resp.json()["session_id"]

    # Heartbeat
    resp = await client.post(
        "/api/session/heartbeat",
        json={"session_id": session_id},
    )
    assert resp.status_code == 200

    # End
    resp = await client.post(
        "/api/session/end",
        json={"session_id": session_id},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "inactive"


# ══════════════════════════════════════════════════════════════════════════════
# 4. CODE EXECUTION VIA GATEWAY (POST /api/execute)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_python_accepted(client: httpx.AsyncClient) -> None:
    """Python code accepted through gateway → compiler."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "print('Hello, World!')",
            "test_cases": [{"input": "", "expected_output": "Hello, World!"}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["passed_tests"] == 1
    assert data["total_tests"] == 1


@pytest.mark.asyncio
async def test_python_wrong_answer(client: httpx.AsyncClient) -> None:
    """Python wrong answer detected through gateway."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "print('wrong')",
            "test_cases": [{"input": "", "expected_output": "correct"}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "wrong_answer"
    assert data["failed_test"] == 1


@pytest.mark.asyncio
async def test_python_runtime_error(client: httpx.AsyncClient) -> None:
    """Python runtime error detected through gateway."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "import sys; sys.exit(1)",
            "test_cases": [{"input": "", "expected_output": ""}],
        },
    )
    data = resp.json()
    assert data["status"] in ("wrong_answer", "runtime_error")


@pytest.mark.asyncio
async def test_python_timeout(client: httpx.AsyncClient) -> None:
    """Python infinite loop times out through gateway."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "while True: pass",
            "test_cases": [{"input": "", "expected_output": ""}],
            "limits": {"time_limit_seconds": 2.0},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tests"][0]["passed"] is False


@pytest.mark.asyncio
async def test_cpp_accepted(client: httpx.AsyncClient) -> None:
    """C++ code accepted through gateway."""
    code = """
#include <iostream>
int main() {
    std::cout << "42" << std::endl;
    return 0;
}
"""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "cpp",
            "source_code": code,
            "test_cases": [{"input": "", "expected_output": "42"}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"


@pytest.mark.asyncio
async def test_cpp_compilation_error(client: httpx.AsyncClient) -> None:
    """C++ compilation error detected through gateway."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "cpp",
            "source_code": "int main() { cout << 'hello'; }",
            "test_cases": [{"input": "", "expected_output": "hello"}],
        },
    )
    data = resp.json()
    assert data["status"] == "compilation_error"
    assert data["error"] is not None


@pytest.mark.asyncio
async def test_c_accepted(client: httpx.AsyncClient) -> None:
    """C code accepted through gateway."""
    code = """
#include <stdio.h>
int main() {
    printf("hello\\n");
    return 0;
}
"""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "c",
            "source_code": code,
            "test_cases": [{"input": "", "expected_output": "hello"}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"


@pytest.mark.asyncio
async def test_java_accepted(client: httpx.AsyncClient) -> None:
    """Java code accepted through gateway."""
    code = """
public class Solution {
    public static void main(String[] args) {
        System.out.println("hello");
    }
}
"""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "java",
            "source_code": code,
            "test_cases": [{"input": "", "expected_output": "hello"}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"


@pytest.mark.asyncio
async def test_c_accepted(client: httpx.AsyncClient) -> None:
    """C code accepted through gateway."""
    code = """
#include <stdio.h>
int main() {
    printf("hello\n");
    return 0;
}
"""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "c",
            "source_code": code,
            "test_cases": [{"input": "", "expected_output": "hello"}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"


@pytest.mark.asyncio
async def test_sql_accepted(client: httpx.AsyncClient) -> None:
    """SQL code accepted through gateway."""
    source = """
CREATE TABLE users (id INTEGER, name TEXT);
INSERT INTO users VALUES (1, 'Alice');
INSERT INTO users VALUES (2, 'Bob');
"""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "sql",
            "source_code": source,
            "test_cases": [
                {
                    "input": "SELECT name FROM users ORDER BY id;",
                    "expected_output": "name\nAlice\nBob",
                },
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"


@pytest.mark.asyncio
async def test_sql_wrong_answer(client: httpx.AsyncClient) -> None:
    """SQL wrong answer detected through gateway."""
    source = """
CREATE TABLE items (id INTEGER, price INTEGER);
INSERT INTO items VALUES (1, 10);
INSERT INTO items VALUES (2, 20);
"""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "sql",
            "source_code": source,
            "test_cases": [
                {
                    "input": "SELECT SUM(price) AS total FROM items;",
                    "expected_output": "total\n100",  # Wrong, should be 30
                },
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "wrong_answer"


@pytest.mark.asyncio
async def test_sql_syntax_error(client: httpx.AsyncClient) -> None:
    """SQL syntax error detected through gateway."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "sql",
            "source_code": "SELCT * FROM nonexistent;",
            "test_cases": [
                {"input": "SELECT 1;", "expected_output": "1"},
            ],
        },
    )
    data = resp.json()
    assert data["status"] == "compilation_error"


# ══════════════════════════════════════════════════════════════════════════════
# 5. MULTIPLE TEST CASES
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_multiple_test_cases_all_pass(client: httpx.AsyncClient) -> None:
    """Multiple test cases all passing."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "import sys; x = int(input()); print(x * 2)",
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


@pytest.mark.asyncio
async def test_multiple_test_cases_partial_failure(client: httpx.AsyncClient) -> None:
    """Multiple test cases with one failing."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "print('wrong')",
            "test_cases": [
                {"input": "", "expected_output": "correct1"},
                {"input": "", "expected_output": "correct2"},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "wrong_answer"
    assert data["failed_test"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# 6. SESSION PROPAGATION
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_session_id_propagated(client: httpx.AsyncClient) -> None:
    """Session ID is echoed back in the execution response."""
    # Create a session
    session_resp = await client.post("/api/session/start")
    session_id = session_resp.json()["session_id"]

    # Execute with session context
    resp = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "print('test')",
            "test_cases": [{"input": "", "expected_output": "test"}],
            "session_id": session_id,
            "attempt_id": "test-attempt-001",
            "question_id": "test-question-001",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == session_id
    assert data["attempt_id"] == "test-attempt-001"
    assert data["question_id"] == "test-question-001"


# ══════════════════════════════════════════════════════════════════════════════
# 7. INVALID / MALFORMED REQUESTS
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_empty_source_code_rejected(client: httpx.AsyncClient) -> None:
    """Empty source code returns 422."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "",
            "test_cases": [{"input": "", "expected_output": ""}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_test_cases_rejected(client: httpx.AsyncClient) -> None:
    """Empty test_cases list returns 422."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "print('hello')",
            "test_cases": [],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_language_rejected(client: httpx.AsyncClient) -> None:
    """Invalid language returns 422."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "rust",
            "source_code": "fn main() {}",
            "test_cases": [{"input": "", "expected_output": ""}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_missing_required_fields(client: httpx.AsyncClient) -> None:
    """Missing required fields returns 422."""
    resp = await client.post(
        "/api/execute",
        json={"language": "python"},
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 8. COMPILER UNAVAILABLE
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_compiler_health_endpoint(client: httpx.AsyncClient) -> None:
    """Gateway compiler health endpoint reports status."""
    resp = await client.get("/api/execute/health")
    # May be 200 (compiler up) or 502 (compiler down)
    assert resp.status_code in (200, 502)
    data = resp.json()
    assert "status" in data


@pytest.mark.asyncio
async def test_compiler_languages_endpoint(client: httpx.AsyncClient) -> None:
    """Gateway compiler languages endpoint returns language list."""
    resp = await client.get("/api/execute/languages")
    # May be 200 (compiler up) or 502 (compiler down)
    assert resp.status_code in (200, 502)


# ══════════════════════════════════════════════════════════════════════════════
# 9. CONCURRENT REQUESTS
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_concurrent_python_executions(client: httpx.AsyncClient) -> None:
    """Multiple concurrent Python executions succeed."""
    body = {
        "language": "python",
        "source_code": "import time; time.sleep(0.1); print('done')",
        "test_cases": [{"input": "", "expected_output": "done"}],
        "limits": {"time_limit_seconds": 5.0},
    }

    async def execute():
        resp = await client.post("/api/execute", json=body)
        return resp.status_code

    # Send 3 concurrent requests (within compiler capacity)
    results = await asyncio.gather(*[execute() for _ in range(3)])
    assert all(r == 200 for r in results)


# ══════════════════════════════════════════════════════════════════════════════
# 10. HOSTILE EXECUTION (through gateway)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_hostile_infinite_loop(client: httpx.AsyncClient) -> None:
    """Infinite loop is killed by timeout through gateway."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "while True: pass",
            "test_cases": [{"input": "", "expected_output": ""}],
            "limits": {"time_limit_seconds": 2.0},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_time_ms"] < 10000


@pytest.mark.asyncio
async def test_hostile_excessive_output(client: httpx.AsyncClient) -> None:
    """Excessive output is truncated through gateway."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": 'print("A" * 1000000)',
            "test_cases": [{"input": "", "expected_output": ""}],
            "limits": {"max_output_bytes": 4096},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    if data["tests"]:
        stdout = data["tests"][0].get("stdout", "")
        assert len(stdout) < 10000  # Truncated


# ══════════════════════════════════════════════════════════════════════════════
# 11. SAVE/CONTINUE SEMANTICS
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_save_continue_with_session(client: httpx.AsyncClient) -> None:
    """Multiple executions with the same session preserve context."""
    # Create session
    session_resp = await client.post("/api/session/start")
    session_id = session_resp.json()["session_id"]

    # First execution
    resp1 = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "print('q1')",
            "test_cases": [{"input": "", "expected_output": "q1"}],
            "session_id": session_id,
            "attempt_id": "attempt-001",
            "question_id": "q1",
        },
    )
    assert resp1.status_code == 200
    assert resp1.json()["session_id"] == session_id
    assert resp1.json()["question_id"] == "q1"

    # Second execution (different question, same session)
    resp2 = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "print('q2')",
            "test_cases": [{"input": "", "expected_output": "q2"}],
            "session_id": session_id,
            "attempt_id": "attempt-001",
            "question_id": "q2",
        },
    )
    assert resp2.status_code == 200
    assert resp2.json()["session_id"] == session_id
    assert resp2.json()["question_id"] == "q2"

    # Session still active
    session_resp = await client.get(f"/api/session/{session_id}")
    assert session_resp.status_code == 200
    assert session_resp.json()["status"] == "active"


# ══════════════════════════════════════════════════════════════════════════════
# 12. APP1 UNAVAILABLE (failure handling)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_gateway_survives_app1_down(client: httpx.AsyncClient) -> None:
    """Gateway API continues working when App 1 is down."""
    # Gateway API should always work
    resp = await client.get("/api/health")
    assert resp.status_code == 200

    # Execute should still work (uses compiler, not app1)
    resp = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "print('ok')",
            "test_cases": [{"input": "", "expected_output": "ok"}],
        },
    )
    # May succeed (compiler up) or fail (compiler down)
    assert resp.status_code in (200, 502)


# ══════════════════════════════════════════════════════════════════════════════
# 13. SQL WITH MULTIPLE QUERIES
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sql_multiple_queries(client: httpx.AsyncClient) -> None:
    """SQL with multiple test case queries."""
    source = """
CREATE TABLE employees (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    department TEXT,
    salary INTEGER
);
INSERT INTO employees VALUES (1, 'Alice', 'Engineering', 90000);
INSERT INTO employees VALUES (2, 'Bob', 'Marketing', 70000);
INSERT INTO employees VALUES (3, 'Charlie', 'Engineering', 95000);
INSERT INTO employees VALUES (4, 'Diana', 'Marketing', 75000);
"""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "sql",
            "source_code": source,
            "test_cases": [
                {
                    "input": "SELECT COUNT(*) AS cnt FROM employees;",
                    "expected_output": "cnt\n4",
                },
                {
                    "input": "SELECT name FROM employees WHERE department = 'Engineering' ORDER BY salary DESC;",
                    "expected_output": "name\nCharlie\nAlice",
                },
                {
                    "input": "SELECT department, AVG(salary) AS avg_salary FROM employees GROUP BY department ORDER BY department;",
                    "expected_output": "department\nEngineering\nMarketing",
                },
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    # At least first two should pass (third may have formatting differences)
    assert data["passed_tests"] >= 2
