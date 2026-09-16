"""
Unit tests for the Compiler-1/2/3 pool (app/judge0_pool.py) and its use by the
Judge0 proxy.

Offline: Judge0 HTTP is mocked with httpx.MockTransport, so no live compiler is
required. These tests prove the properties the multi-machine deployment depends
on:

  * the pool is built from COMPILER_1_URL / COMPILER_2_URL / COMPILER_3_URL
    (any subset), and falls back to the single legacy JUDGE0_URL;
  * work is distributed deterministically round-robin;
  * a submission's polling goes to the node that accepted it;
  * a dead or full node is skipped without failing the candidate's run;
  * health reports every node in the pool.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import httpx
import pytest

from app import judge0_pool as pool
from app import judge0_proxy as jp
from app.execute_schemas import (
    ExecuteRequest,
    ExecutionLimits,
    ExecutionStatus,
    TestCase as ExecutionTestCase,
)

NODE_A = "http://compiler-a:2358"
NODE_B = "http://compiler-b:2358"
NODE_C = "http://compiler-c:2358"

_FAKE_MAP = {"python": 92, "c": 103, "cpp": 105, "java": 91, "sql": 82}


# ── Env-driven pool resolution ───────────────────────────────────────────────

def test_pool_from_numbered_vars_in_order() -> None:
    env = {"COMPILER_1_URL": NODE_A, "COMPILER_2_URL": NODE_B, "COMPILER_3_URL": NODE_C}
    assert pool.resolve_pool(env) == [NODE_A, NODE_B, NODE_C]


def test_pool_accepts_a_subset_and_preserves_order() -> None:
    env = {"COMPILER_1_URL": NODE_A, "COMPILER_3_URL": NODE_C}
    assert pool.resolve_pool(env) == [NODE_A, NODE_C]


def test_pool_ignores_blank_and_trailing_slash() -> None:
    env = {"COMPILER_1_URL": "  ", "COMPILER_2_URL": f"{NODE_B}/", "COMPILER_3_URL": ""}
    assert pool.resolve_pool(env) == [NODE_B]


def test_pool_falls_back_to_legacy_single_url() -> None:
    assert pool.resolve_pool({"JUDGE0_URL": NODE_A}) == [NODE_A]


def test_pool_default_when_nothing_is_configured() -> None:
    assert pool.resolve_pool({}) == [pool.LEGACY_URL_DEFAULT]


def test_numbered_vars_win_over_legacy_url() -> None:
    env = {"COMPILER_2_URL": NODE_B, "JUDGE0_URL": NODE_A}
    assert pool.resolve_pool(env) == [NODE_B]


# ── Round-robin + failover ordering ──────────────────────────────────────────

def test_round_robin_cycles_deterministically() -> None:
    pool.reset_cursor()
    nodes = [NODE_A, NODE_B, NODE_C]
    picked = [pool.next_node(nodes) for _ in range(7)]
    assert picked == [NODE_A, NODE_B, NODE_C, NODE_A, NODE_B, NODE_C, NODE_A]


def test_single_node_pool_always_returns_that_node() -> None:
    pool.reset_cursor()
    assert {pool.next_node([NODE_A]) for _ in range(5)} == {NODE_A}


def test_failover_order_starts_at_the_chosen_node() -> None:
    order = pool.failover_order(NODE_B, [NODE_A, NODE_B, NODE_C])
    assert order == [NODE_B, NODE_A, NODE_C]


def test_describe_pool_names_the_source_variable() -> None:
    described = pool.describe_pool({"COMPILER_1_URL": NODE_A, "COMPILER_3_URL": NODE_C})
    assert [d["url"] for d in described] == [NODE_A, NODE_C]
    assert [d["source"] for d in described] == ["COMPILER_1_URL", "COMPILER_3_URL"]


# ── Proxy behaviour against a mocked pool ────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate module-level caches and the round-robin cursor between tests."""
    monkeypatch.setattr(jp, "_language_ids_cache", None)
    monkeypatch.setattr(jp, "_language_ids_fetched_at", 0.0)
    monkeypatch.setattr(jp, "JUDGE0_AUTH_TOKEN", "test-token")
    pool.reset_cursor()


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler: Callable) -> None:
    real_client = httpx.Client

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(jp.httpx, "Client", factory)


def _use_pool(monkeypatch: pytest.MonkeyPatch, nodes: list[str]) -> None:
    monkeypatch.setattr(jp, "JUDGE0_POOL", list(nodes))
    monkeypatch.setattr(jp, "get_language_ids", lambda force=False: dict(_FAKE_MAP))


def _request(n_tests: int = 1) -> ExecuteRequest:
    return ExecuteRequest(
        language="python",
        source_code="print(1)",
        test_cases=[
            ExecutionTestCase(input="", expected_output="1\n", label=f"tc{i}")
            for i in range(n_tests)
        ],
        limits=ExecutionLimits(),
    )


def _submission(status_id: int = 3, **overrides: Any) -> dict[str, Any]:
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


def test_submissions_are_distributed_round_robin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_hosts: list[str] = []
    poll_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            post_hosts.append(request.url.host)
            return httpx.Response(201, json={"token": f"tok-{len(post_hosts)}"})
        poll_hosts.append(request.url.host)
        return httpx.Response(200, json=_submission(3))

    _install_mock(monkeypatch, handler)
    _use_pool(monkeypatch, [NODE_A, NODE_B])

    resp = jp.execute_on_judge0(_request(n_tests=4))

    assert resp.status == ExecutionStatus.accepted
    assert resp.passed_tests == 4
    # 4 test cases alternate across the 2 nodes.
    assert post_hosts == ["compiler-a", "compiler-b", "compiler-a", "compiler-b"]
    # Polling of each submission happens on the node that queued it.
    assert poll_hosts == post_hosts


def test_dead_node_is_skipped_and_run_still_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_hosts: list[str] = []
    poll_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if request.method == "POST":
            if host == "compiler-a":  # node A is down
                raise httpx.ConnectError("connection refused", request=request)
            post_hosts.append(host)
            return httpx.Response(201, json={"token": "tok-b"})
        poll_hosts.append(host)
        return httpx.Response(200, json=_submission(3))

    _install_mock(monkeypatch, handler)
    _use_pool(monkeypatch, [NODE_A, NODE_B])

    resp = jp.execute_on_judge0(_request())

    assert resp.status == ExecutionStatus.accepted
    # A was chosen first (round-robin) and failed over to B.
    assert post_hosts == ["compiler-b"]
    assert poll_hosts == ["compiler-b"]
    assert all(t.passed for t in resp.tests)


def test_queue_full_node_fails_over_to_a_healthy_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            if request.url.host == "compiler-a":
                return httpx.Response(503, json={"error": "queue is full"})
            return httpx.Response(201, json={"token": "tok-b"})
        return httpx.Response(200, json=_submission(3))

    _install_mock(monkeypatch, handler)
    _use_pool(monkeypatch, [NODE_A, NODE_B])

    resp = jp.execute_on_judge0(_request())
    assert resp.status == ExecutionStatus.accepted


def test_all_nodes_down_reports_compiler_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _install_mock(monkeypatch, handler)
    _use_pool(monkeypatch, [NODE_A, NODE_B])

    resp = jp.execute_on_judge0(_request())
    assert resp.status == ExecutionStatus.compiler_unavailable
    assert "Judge0" in (resp.error or "")


def test_language_resolution_uses_a_surviving_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The language map (not just execution) must survive one dead node."""
    queried: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        queried.append(host)
        if host == "compiler-a":
            raise httpx.ConnectError("down", request=request)
        if request.url.path.endswith("/languages"):
            return httpx.Response(200, json=[{"id": 92, "name": "Python (3.11.2)", "is_archived": False}])
        return httpx.Response(201, json={"token": "tok-b"})

    _install_mock(monkeypatch, handler)
    monkeypatch.setattr(jp, "JUDGE0_POOL", [NODE_A, NODE_B])

    ids = jp.get_language_ids(force=True)
    assert ids["python"] == 92
    assert "compiler-b" in queried


def test_health_reports_every_node_in_the_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "compiler-b":
            raise httpx.ConnectError("down", request=request)
        if request.url.path.endswith("/about"):
            return httpx.Response(200, json={"version": "1.13.1"})
        if request.url.path.endswith("/languages"):
            return httpx.Response(200, json=[{"id": 92, "name": "Python (3.11.2)", "is_archived": False}])
        return httpx.Response(404, json={})

    _install_mock(monkeypatch, handler)
    monkeypatch.setattr(jp, "JUDGE0_POOL", [NODE_A, NODE_B])

    health = jp.check_judge0_health()
    assert health["status"] == "ok"
    assert health["compiler_pool_size"] == 2
    assert health["serving_node"] == NODE_A
    by_url = {n["url"]: n["status"] for n in health["nodes"]}
    assert by_url == {NODE_A: "ok", NODE_B: "unreachable"}


def test_health_unreachable_when_no_node_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    _install_mock(monkeypatch, handler)
    monkeypatch.setattr(jp, "JUDGE0_POOL", [NODE_A, NODE_C])

    health = jp.check_judge0_health()
    assert health["status"] == "unreachable"
    assert "error" in health
    assert len(health["nodes"]) == 2
