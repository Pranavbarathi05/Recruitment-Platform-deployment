"""
Unit tests for the Judge0 (System 3) proxy integration.

Offline tests: Judge0 HTTP is mocked with httpx.MockTransport, so no live
Judge0 instance is required. Live end-to-end verification lives in
gateway/judge0/README.md / the integration test battery.
"""
from __future__ import annotations

from typing import Any, Callable

import httpx
import pytest

from app.execute_schemas import (
    ExecuteRequest,
    ExecuteResponse,
    ExecutionLimits,
    ExecutionStatus,
    TestCase as ExecutionTestCase,
)
from app import judge0_proxy as jp


# ── Fixtures / helpers ───────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the module-level language cache between tests."""
    monkeypatch.setattr(jp, "_language_ids_cache", None)
    monkeypatch.setattr(jp, "_language_ids_fetched_at", 0.0)
    monkeypatch.setattr(jp, "JUDGE0_AUTH_TOKEN", "test-token")


_REAL_HTTPX_CLIENT = httpx.Client


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler: Callable) -> None:
    """Route all httpx calls in judge0_proxy through a MockTransport."""

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return _REAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(jp.httpx, "Client", factory)


def _request(language: str = "python", source: str = "print(1)", n_tests: int = 1) -> ExecuteRequest:
    return ExecuteRequest(
        language=language,
        source_code=source,
        test_cases=[
            ExecutionTestCase(input="", expected_output="1\n", label="tc1")
            for _ in range(n_tests)
        ],
        limits=ExecutionLimits(),
        session_id="s-1",
        attempt_id="a-1",
        question_id="q-1",
    )


def _submission(status_id: int, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "stdout": "1\n",
        "stderr": None,
        "compile_output": None,
        "message": None,
        "time": "0.010",
        "memory": 1200,
        "token": "tok",
        "status": {"id": status_id, "description": "x"},
    }
    data.update(overrides)
    return data


_FAKE_MAP = {"python": 92, "c": 103, "cpp": 105, "java": 91, "sql": None}


# ── Language mapping ─────────────────────────────────────────────────────────

def test_resolve_language_ids_picks_highest_version() -> None:
    languages = [
        {"id": 103, "name": "C (GCC 12.2.0)", "is_archived": False},
        {"id": 50, "name": "C (GCC 9.2.0)", "is_archived": False},
        {"id": 105, "name": "C++ (GCC 12.2.0)", "is_archived": False},
        {"id": 54, "name": "C++ (GCC 9.2.0)", "is_archived": False},
        {"id": 91, "name": "Java (OpenJDK 17.0.6)", "is_archived": False},
        {"id": 62, "name": "Java (OpenJDK 13.0.1)", "is_archived": False},
        {"id": 92, "name": "Python (3.11.2)", "is_archived": False},
        {"id": 71, "name": "Python (3.8.1)", "is_archived": False},
        {"id": 5, "name": "C (gcc 6.4.0)", "is_archived": True},  # archived ignored
    ]
    resolved = jp.resolve_language_ids(languages)
    assert resolved["c"] == 103
    assert resolved["cpp"] == 105
    assert resolved["java"] == 91
    assert resolved["python"] == 92
    assert resolved["sql"] is None  # not present in CE


def test_resolve_language_ids_handles_python_two_digit_major() -> None:
    languages = [
        {"id": 100, "name": "Python (3.10.0)", "is_archived": False},
        {"id": 71, "name": "Python (3.8.1)", "is_archived": False},
        {"id": 92, "name": "Python (3.11.2)", "is_archived": False},
    ]
    assert jp.resolve_language_ids(languages)["python"] == 92


# ── Output comparison contract ───────────────────────────────────────────────

def test_outputs_match_strips_trailing_whitespace() -> None:
    assert jp._outputs_match("hello\n", "hello")
    assert jp._outputs_match("hello", "hello")
    assert jp._outputs_match("hello  ", "hello")
    assert jp._outputs_match(None, "")
    assert not jp._outputs_match("hello there", "hello")


# ── Status mapping ───────────────────────────────────────────────────────────

def test_status_map_covers_judge0_final_statuses() -> None:
    # Verified against the live instance's GET /statuses (CE 1.13.1: ids 1-14).
    expected = {
        3: ExecutionStatus.accepted,
        4: ExecutionStatus.wrong_answer,
        5: ExecutionStatus.time_limit_exceeded,
        6: ExecutionStatus.compilation_error,
        7: ExecutionStatus.runtime_error,
        8: ExecutionStatus.runtime_error,
        9: ExecutionStatus.runtime_error,
        10: ExecutionStatus.runtime_error,
        11: ExecutionStatus.runtime_error,
        12: ExecutionStatus.runtime_error,
        13: ExecutionStatus.internal_error,
        14: ExecutionStatus.internal_error,
    }
    for status_id, platform_status in expected.items():
        assert jp._status_for(status_id) == platform_status, f"status id {status_id}"
    # Newer Judge0 exposes MLE/OLE as 15/16; keep them declared defensively.
    assert jp.JUDGE0_STATUS_MAP.get(15) == ExecutionStatus.memory_limit_exceeded
    assert jp.JUDGE0_STATUS_MAP.get(16) == ExecutionStatus.output_limit_exceeded


# ── End-to-end proxy behaviour (mocked Judge0) ───────────────────────────────

def _install_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jp, "get_language_ids", lambda force=False: dict(_FAKE_MAP))


def test_execute_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, int] = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/submissions"):
            calls["n"] += 1
            return httpx.Response(201, json={"token": f"tok-{calls['n']}"})
        if request.method == "GET" and "/submissions/" in request.url.path:
            token = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=_submission(3, token=token))
        return httpx.Response(404, json={"error": "not found"})

    _install_mock(monkeypatch, handler)
    _install_defaults(monkeypatch)

    resp = jp.execute_on_judge0(_request(n_tests=2))
    assert resp.status == ExecutionStatus.accepted
    assert resp.passed_tests == 2
    assert resp.total_tests == 2
    assert resp.failed_test is None
    assert all(t.passed for t in resp.tests)
    assert resp.session_id == "s-1" and resp.attempt_id == "a-1" and resp.question_id == "q-1"
    # Each test case ran as its own submission -> two POSTs.
    assert calls["n"] == 2


def test_execute_wrong_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"token": "tok-1"})
        return httpx.Response(200, json=_submission(4, stdout="2\n"))

    _install_mock(monkeypatch, handler)
    _install_defaults(monkeypatch)

    resp = jp.execute_on_judge0(_request(n_tests=3))
    assert resp.status == ExecutionStatus.wrong_answer
    assert resp.failed_test == 1
    assert resp.passed_tests == 0
    assert resp.tests[0].stdout == "2\n"


def test_execute_compilation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"token": "tok-1"})
        return httpx.Response(
            200,
            json=_submission(6, stdout=None, compile_output="error: expected ';'"),
        )

    _install_mock(monkeypatch, handler)
    _install_defaults(monkeypatch)

    resp = jp.execute_on_judge0(_request(language="cpp", n_tests=2))
    assert resp.status == ExecutionStatus.compilation_error
    assert resp.error is not None and "expected ';'" in resp.error
    assert resp.tests[0].stderr and "expected ';'" in resp.tests[0].stderr


@pytest.mark.parametrize(
    "status_id,expected",
    [
        (5, ExecutionStatus.time_limit_exceeded),
        (7, ExecutionStatus.runtime_error),
        (15, ExecutionStatus.memory_limit_exceeded),
        (16, ExecutionStatus.output_limit_exceeded),
        (13, ExecutionStatus.internal_error),
    ],
)
def test_execute_distinguishes_failures(
    monkeypatch: pytest.MonkeyPatch, status_id: int, expected: ExecutionStatus
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"token": "tok-1"})
        return httpx.Response(200, json=_submission(status_id, stdout=""))

    _install_mock(monkeypatch, handler)
    _install_defaults(monkeypatch)

    resp = jp.execute_on_judge0(_request())
    assert resp.status == expected
    assert resp.failed_test == 1
    assert resp.passed_tests == 0


def test_execute_sql_reports_incompatibility(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_defaults(monkeypatch)  # sql -> None in _FAKE_MAP

    resp = jp.execute_on_judge0(_request(language="sql", source="SELECT 1;"))
    assert resp.status == ExecutionStatus.invalid_language
    assert "Judge0 CE" in (resp.error or "")


def test_execute_compiler_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _install_mock(monkeypatch, handler)

    # Language resolution itself fails -> unavailable (does not crash).
    resp = jp.execute_on_judge0(_request())
    assert resp.status == ExecutionStatus.compiler_unavailable
    assert "Judge0" in (resp.error or "")


def test_execute_queue_full(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(503, json={"error": "queue is full"})
        return httpx.Response(200, json=_submission(3))

    _install_mock(monkeypatch, handler)
    _install_defaults(monkeypatch)

    resp = jp.execute_on_judge0(_request())
    assert resp.status == ExecutionStatus.compiler_unavailable
    assert "queue is full" in (resp.error or "")


def test_execute_timeout_poll_returns_internal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"token": "tok-1"})
        # Always In Queue -> poller will hit its deadline
        return httpx.Response(200, json=_submission(1, status={"id": 1, "description": "In Queue"}))

    _install_mock(monkeypatch, handler)
    _install_defaults(monkeypatch)
    monkeypatch.setattr(jp, "JUDGE0_MAX_POLL_SECONDS", 0.2)
    monkeypatch.setattr(jp, "JUDGE0_POLL_INTERVAL", 0.01)

    resp = jp.execute_on_judge0(_request())
    assert resp.status == ExecutionStatus.internal_error
    assert "poll deadline" in (resp.error or "")


def test_check_health_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/about"):
            return httpx.Response(200, json={"version": "1.13.1"})
        if request.url.path.endswith("/languages"):
            return httpx.Response(
                200,
                json=[
                    {"id": 92, "name": "Python (3.11.2)", "is_archived": False},
                    {"id": 50, "name": "C (GCC 9.2.0)", "is_archived": False},
                ],
            )
        return httpx.Response(404, json={})

    _install_mock(monkeypatch, handler)

    health = jp.check_judge0_health()
    assert health["status"] == "ok"
    assert health["version"] == "1.13.1"
    assert health["language_id_map"]["python"] == 92
    assert health["language_id_map"]["sql"] is None


def test_check_health_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    _install_mock(monkeypatch, handler)

    health = jp.check_judge0_health()
    assert health["status"] == "unreachable"
    assert "error" in health