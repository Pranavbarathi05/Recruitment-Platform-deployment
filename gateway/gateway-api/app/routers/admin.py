"""
Gateway API – Phase 2
Admin endpoints: session listing and system health overview.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..node_health import node_registry
from ..session import registry

router = APIRouter(tags=["admin"])

_START_TIME = datetime.now(timezone.utc)


@router.get("/api/admin/sessions")
async def admin_sessions() -> JSONResponse:
    """
    List all sessions (any status).
    Returns the full session list and a total count.
    """
    sessions = registry.list_all()
    return JSONResponse(
        content={
            "sessions": [s.to_dict() for s in sessions],
            "total": len(sessions),
        }
    )


@router.get("/api/admin/health")
async def admin_health() -> JSONResponse:
    """
    System health overview:
      - Gateway uptime
      - Session counts by status
      - Node health stubs for all known compute nodes
    """
    sessions = registry.list_all()
    active_count = sum(1 for s in sessions if s.status == "active")
    inactive_count = len(sessions) - active_count

    uptime_seconds = (datetime.now(timezone.utc) - _START_TIME).total_seconds()

    return JSONResponse(
        content={
            "gateway": {
                "status": "ok",
                "uptime_seconds": round(uptime_seconds, 2),
            },
            "sessions": {
                "total": len(sessions),
                "active": active_count,
                "inactive": inactive_count,
            },
            "nodes": [n.to_dict() for n in node_registry.list_all()],
        }
    )
