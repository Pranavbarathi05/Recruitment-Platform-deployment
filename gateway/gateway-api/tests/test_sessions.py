"""
Phase 2 – Unit tests for the session control plane.

All tests use httpx.AsyncClient with ASGITransport so no live server is needed.
Each test gets a fresh SessionRegistry to avoid cross-test contamination.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.session import Session, SessionRegistry


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def fresh_registry() -> SessionRegistry:
    """Return an isolated SessionRegistry (does NOT replace the global one)."""
    return SessionRegistry()


@pytest_asyncio.fixture()
async def client():
    """Async HTTP client backed by the FastAPI ASGI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


# ─────────────────────────────────────────────────────────────────────────────
# 1. Session creation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_creation(client: AsyncClient) -> None:
    """POST /api/session/start returns 201 with all required fields."""
    response = await client.post("/api/session/start")
    assert response.status_code == 201

    data: dict[str, Any] = response.json()
    for field in ("session_id", "client_ip", "user_agent", "connected_at",
                  "last_seen", "status"):
        assert field in data, f"Missing field: {field}"

    assert data["status"] == "active"
    assert len(data["session_id"]) > 0


@pytest.mark.asyncio
async def test_session_creation_with_user_id(client: AsyncClient) -> None:
    """user_id is propagated when supplied in the request body."""
    response = await client.post(
        "/api/session/start",
        json={"user_id": "u-001"},
    )
    assert response.status_code == 201
    assert response.json()["user_id"] == "u-001"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Heartbeat
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_heartbeat(client: AsyncClient) -> None:
    """POST /api/session/heartbeat updates last_seen and returns 200."""
    # Create session
    start_resp = await client.post("/api/session/start")
    session_id = start_resp.json()["session_id"]
    first_seen = start_resp.json()["last_seen"]

    # Small sleep so timestamps can differ
    time.sleep(0.05)

    hb_resp = await client.post(
        "/api/session/heartbeat",
        json={"session_id": session_id},
    )
    assert hb_resp.status_code == 200
    assert hb_resp.json()["last_seen"] >= first_seen
    assert hb_resp.json()["status"] == "active"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Session termination
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_termination(client: AsyncClient) -> None:
    """POST /api/session/end marks the session inactive."""
    start_resp = await client.post("/api/session/start")
    session_id = start_resp.json()["session_id"]

    end_resp = await client.post(
        "/api/session/end",
        json={"session_id": session_id},
    )
    assert end_resp.status_code == 200
    assert end_resp.json()["status"] == "inactive"


@pytest.mark.asyncio
async def test_heartbeat_on_inactive_session_returns_404(client: AsyncClient) -> None:
    """Heartbeat on an ended session must return 404."""
    start_resp = await client.post("/api/session/start")
    session_id = start_resp.json()["session_id"]

    await client.post("/api/session/end", json={"session_id": session_id})

    hb_resp = await client.post(
        "/api/session/heartbeat",
        json={"session_id": session_id},
    )
    assert hb_resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 4. Retrieve a session
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_session(client: AsyncClient) -> None:
    """GET /api/session/{id} returns the session data."""
    start_resp = await client.post("/api/session/start")
    session_id = start_resp.json()["session_id"]

    get_resp = await client.get(f"/api/session/{session_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["session_id"] == session_id


# ─────────────────────────────────────────────────────────────────────────────
# 5. Stale session handling
# ─────────────────────────────────────────────────────────────────────────────

def test_stale_session_detection(fresh_registry: SessionRegistry) -> None:
    """
    Artificially back-date last_seen and verify expire_stale() marks the
    session inactive without deleting it.
    """
    session = fresh_registry.create(client_ip="1.2.3.4", user_agent="pytest")

    # Wind back last_seen by 10 minutes
    session.last_seen = datetime.now(timezone.utc) - timedelta(minutes=10)

    expired = fresh_registry.expire_stale(timeout_seconds=60)  # 1-minute timeout
    assert expired == 1

    stored = fresh_registry.get(session.session_id)
    assert stored is not None, "Session must not be deleted, only marked inactive"
    assert stored.status == "inactive"


def test_non_stale_session_not_expired(fresh_registry: SessionRegistry) -> None:
    """A recently active session must not be marked inactive."""
    fresh_registry.create(client_ip="1.2.3.4", user_agent="pytest")
    expired = fresh_registry.expire_stale(timeout_seconds=300)
    assert expired == 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. Multiple simultaneous sessions
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multiple_simultaneous_sessions(client: AsyncClient) -> None:
    """Multiple independent sessions can be created and tracked separately."""
    ids: list[str] = []
    for _ in range(5):
        resp = await client.post("/api/session/start")
        assert resp.status_code == 201
        ids.append(resp.json()["session_id"])

    # All IDs must be unique
    assert len(set(ids)) == 5

    # Each can be retrieved individually
    for sid in ids:
        resp = await client.get(f"/api/session/{sid}")
        assert resp.status_code == 200
        assert resp.json()["session_id"] == sid


# ─────────────────────────────────────────────────────────────────────────────
# 7. Invalid session IDs
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_invalid_session_id(client: AsyncClient) -> None:
    """GET /api/session/{id} returns 404 for an unknown session ID."""
    resp = await client.get("/api/session/does-not-exist-000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_heartbeat_invalid_session_id(client: AsyncClient) -> None:
    """POST /api/session/heartbeat returns 404 for an unknown session ID."""
    resp = await client.post(
        "/api/session/heartbeat",
        json={"session_id": "does-not-exist-111"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_end_invalid_session_id(client: AsyncClient) -> None:
    """POST /api/session/end returns 404 for an unknown session ID."""
    resp = await client.post(
        "/api/session/end",
        json={"session_id": "does-not-exist-222"},
    )
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 8. Admin session listing
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_sessions_listing(client: AsyncClient) -> None:
    """GET /api/admin/sessions includes sessions created in this process."""
    # Create two fresh sessions specifically for this check
    r1 = await client.post("/api/session/start")
    r2 = await client.post("/api/session/start")
    new_ids = {r1.json()["session_id"], r2.json()["session_id"]}

    admin_resp = await client.get("/api/admin/sessions")
    assert admin_resp.status_code == 200

    body = admin_resp.json()
    assert "sessions" in body
    assert "total" in body
    assert body["total"] == len(body["sessions"])

    listed_ids = {s["session_id"] for s in body["sessions"]}
    assert new_ids.issubset(listed_ids), "Newly created sessions must appear in admin list"


@pytest.mark.asyncio
async def test_admin_health(client: AsyncClient) -> None:
    """GET /api/admin/health returns gateway status and all 5 node stubs."""
    resp = await client.get("/api/admin/health")
    assert resp.status_code == 200

    body = resp.json()
    assert body["gateway"]["status"] == "ok"
    assert "uptime_seconds" in body["gateway"]
    assert "sessions" in body
    assert len(body["nodes"]) == 5

    node_names = {n["name"] for n in body["nodes"]}
    expected = {"app-01", "app-02", "compiler-01", "compiler-02", "compiler-03"}
    assert node_names == expected
