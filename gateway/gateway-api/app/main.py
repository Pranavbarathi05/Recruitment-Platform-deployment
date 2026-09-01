"""
Gateway API – Phase 2
Extends Phase 1 with:
  - Session lifecycle endpoints  (/api/session/*)
  - Admin endpoints              (/api/admin/*)
  - Background stale-session detection
  - Node health stubs
Phase 1 endpoints (/api/health, /api/info) are preserved unchanged.
"""
import os
import platform
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .routers import admin, execute, session
from .stale_checker import start_stale_checker

_START_TIME = datetime.now(timezone.utc)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background threads on startup; nothing to clean up on shutdown."""
    start_stale_checker()
    yield


# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Recruitment Platform – Gateway API",
    description=(
        "Phase 2: session registry, admin endpoints, and node health stubs. "
        "Phase 1 health & info endpoints preserved."
    ),
    version=os.getenv("APP_VERSION", "0.2.0"),
    lifespan=lifespan,
)

app.include_router(session.router)
app.include_router(admin.router)
app.include_router(execute.router)


# ── Phase 1 endpoints (unchanged) ────────────────────────────────────────────

@app.get("/api/health", tags=["ops"])
async def health() -> JSONResponse:
    """
    Returns 200 when the service is up.
    Downstream health-check tooling (Traefik, Docker) may poll this.
    """
    return JSONResponse(
        {
            "status": "ok",
            "service": "gateway-api",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.get("/api/info", tags=["ops"])
async def info() -> JSONResponse:
    """
    Returns build / environment metadata.
    Useful for confirming the correct image is deployed.
    """
    uptime_seconds = (datetime.now(timezone.utc) - _START_TIME).total_seconds()
    return JSONResponse(
        {
            "service": "gateway-api",
            "version": os.getenv("APP_VERSION", "0.2.0"),
            "environment": os.getenv("APP_ENV", "development"),
            "hostname": socket.gethostname(),
            "python_version": platform.python_version(),
            "uptime_seconds": round(uptime_seconds, 2),
            "started_at": _START_TIME.isoformat(),
        }
    )
