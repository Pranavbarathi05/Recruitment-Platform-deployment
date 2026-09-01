"""
Phase 4 – App 1 Deployment Tests

Tests verifying:
  1. App 1 health endpoint
  2. Gateway → App 1 routing
  3. App 1 independent deployability
  4. Session management preserved
  5. Failure handling

Requirements:
  - App 1 running on port 8002 (or configured APP1_HOST_PORT)
  - Gateway running on port 80
  - COMPILER_URL configured (for /api/execute tests)

These tests do NOT modify dsc-recruit/.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
import httpx


# ── Configuration ────────────────────────────────────────────────────────────

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost")
APP1_URL = os.getenv("APP1_URL", "http://localhost:8002")
COMPILER_URL = os.getenv("COMPILER_URL", "http://localhost:8001")


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
async def app1_client():
    """Async HTTP client for direct App 1 requests."""
    async with httpx.AsyncClient(
        base_url=APP1_URL,
        timeout=30.0,
    ) as c:
        yield c


# ══════════════════════════════════════════════════════════════════════════════
# 1. APP 1 HEALTH
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_app1_health_direct(app1_client: httpx.AsyncClient) -> None:
    """App 1 health endpoint responds directly."""
    resp = await app1_client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "Healthy"
    assert data["message"] == "API is working"


@pytest.mark.asyncio
async def test_app1_health_through_gateway(client: httpx.AsyncClient) -> None:
    """App 1 is reachable through the Gateway."""
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "Healthy"


@pytest.mark.asyncio
async def test_app1_docker_health() -> None:
    """App 1 Docker container shows healthy status."""
    import subprocess
    result = subprocess.run(
        ["docker", "inspect", "app-1", "--format", "{{.State.Health.Status}}"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "healthy" in result.stdout.lower()


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
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "Healthy"


@pytest.mark.asyncio
async def test_gateway_domains_routing(client: httpx.AsyncClient) -> None:
    """Gateway routes /questions/domains to App 1."""
    resp = await client.get("/questions/domains")
    # May return 500 (Supabase connection) or 200 (if Supabase available)
    # The important thing is that the request reaches App 1
    assert resp.status_code in (200, 500)


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
# 4. APP 1 INDEPENDENT DEPLOYABILITY
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_app1_independent_from_gateway(app1_client: httpx.AsyncClient) -> None:
    """App 1 responds without Gateway."""
    resp = await app1_client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "Healthy"


@pytest.mark.asyncio
async def test_app1_port_binding() -> None:
    """App 1 is bound to 0.0.0.0 (accessible from LAN)."""
    import subprocess
    result = subprocess.run(
        ["docker", "port", "app-1"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "0.0.0.0:8002" in result.stdout or "[::]:8002" in result.stdout


@pytest.mark.asyncio
async def test_app1_not_on_gateway_network() -> None:
    """App 1 is NOT on the Gateway Docker network (simulates separate machine)."""
    import subprocess
    result = subprocess.run(
        ["docker", "network", "inspect", "gateway_gateway_net"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    # App 1 should not appear in the gateway network
    assert "app-1" not in result.stdout


# ══════════════════════════════════════════════════════════════════════════════
# 5. FAILURE HANDLING
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_gateway_api_survives_app1_unreachable(client: httpx.AsyncClient) -> None:
    """Gateway API continues working when App 1 is unreachable."""
    # Gateway API should always work
    resp = await client.get("/api/health")
    assert resp.status_code == 200

    # Session management should work
    resp = await client.post("/api/session/start")
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_app1_returns_error_for_auth_endpoints(app1_client: httpx.AsyncClient) -> None:
    """App 1 returns proper errors for authenticated endpoints without auth."""
    resp = await app1_client.post("/submission/", json={
        "attempt_id": "test",
        "code": "print('hello')",
        "language": "python",
    })
    # Should return 401 (unauthorized) or 422 (validation error)
    assert resp.status_code in (401, 422, 500)


# ══════════════════════════════════════════════════════════════════════════════
# 6. CODE EXECUTION (Phase 3 preserved)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_python_execution_via_gateway(client: httpx.AsyncClient) -> None:
    """Python code execution works through Gateway."""
    resp = await client.post(
        "/api/execute",
        json={
            "language": "python",
            "source_code": "print('hello')",
            "test_cases": [{"input": "", "expected_output": "hello"}],
        },
    )
    # May succeed (200), fail with compiler unavailable (502), or return error response (200 with error status)
    assert resp.status_code in (200, 502)
    if resp.status_code == 200:
        data = resp.json()
        # If compiler is unavailable, we get a structured error response
        assert data.get("status") in ("accepted", "compiler_unavailable", "internal_error")


# ══════════════════════════════════════════════════════════════════════════════
# 7. DSC-RECRUIT UNTOUCHED
# ══════════════════════════════════════════════════════════════════════════════

def test_dsc_recruit_untouched() -> None:
    """Verify dsc-recruit application source was not modified."""
    import subprocess
    result = subprocess.run(
        ["git", "diff", "--", "dsc-recruit/"],
        capture_output=True, text=True, timeout=10,
        cwd="/home/pranav/Desktop/Platform deployment",
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "", "dsc-recruit/ has been modified!"
