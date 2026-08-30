"""
Gateway API – Phase 2
Session lifecycle endpoints.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..session import registry

router = APIRouter(tags=["session"])


# ── Request bodies ────────────────────────────────────────────────────────────

class SessionIdBody(BaseModel):
    session_id: str


class StartSessionBody(BaseModel):
    user_id: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_client_ip(request: Request) -> str:
    """
    Return the real client IP.

    Preference order:
      1. X-Forwarded-For header (first value) – set by Traefik.
      2. request.client.host – direct connection / fallback.

    No per-IP restrictions are applied here.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/session/start", status_code=status.HTTP_201_CREATED)
async def session_start(
    request: Request,
    body: StartSessionBody = StartSessionBody(),
) -> JSONResponse:
    """
    Start a new session for the calling client.
    Returns the full session object including the generated session_id.
    """
    client_ip = _extract_client_ip(request)
    user_agent = request.headers.get("user-agent", "")
    session = registry.create(
        client_ip=client_ip,
        user_agent=user_agent,
        user_id=body.user_id,
    )
    return JSONResponse(content=session.to_dict(), status_code=status.HTTP_201_CREATED)


@router.post("/api/session/heartbeat")
async def session_heartbeat(body: SessionIdBody) -> JSONResponse:
    """
    Refresh a session's last_seen timestamp.
    Returns 404 if the session does not exist or is already inactive.
    """
    session = registry.heartbeat(body.session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{body.session_id}' not found or inactive.",
        )
    return JSONResponse(content=session.to_dict())


@router.post("/api/session/end")
async def session_end(body: SessionIdBody) -> JSONResponse:
    """
    Terminate a session (marks it inactive; does not delete).
    Returns 404 if the session does not exist.
    """
    session = registry.end(body.session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{body.session_id}' not found.",
        )
    return JSONResponse(content=session.to_dict())


@router.get("/api/session/{session_id}")
async def session_get(session_id: str) -> JSONResponse:
    """
    Retrieve a single session by ID.
    Returns 404 if the session does not exist.
    """
    session = registry.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    return JSONResponse(content=session.to_dict())
