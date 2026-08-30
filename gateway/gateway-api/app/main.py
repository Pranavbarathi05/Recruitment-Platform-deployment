"""
Gateway API – Phase 1
Provides two read-only endpoints for health and info checks.
No auth, no DB, no external dependencies.
"""
import os
import platform
import socket
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(
    title="Recruitment Platform – Gateway API",
    description="Phase 1: health & info endpoints only.",
    version=os.getenv("APP_VERSION", "0.1.0"),
)

_START_TIME = datetime.now(timezone.utc)


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
            "version": os.getenv("APP_VERSION", "0.1.0"),
            "environment": os.getenv("APP_ENV", "development"),
            "hostname": socket.gethostname(),
            "python_version": platform.python_version(),
            "uptime_seconds": round(uptime_seconds, 2),
            "started_at": _START_TIME.isoformat(),
        }
    )
