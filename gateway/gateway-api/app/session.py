"""
Gateway API – Phase 2
Session registry: in-memory, thread-safe, no external dependencies.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ── Session data model ────────────────────────────────────────────────────────

@dataclass
class Session:
    session_id: str
    client_ip: str
    user_agent: str
    connected_at: datetime
    last_seen: datetime
    status: str                    # "active" | "inactive"
    user_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "connected_at": self.connected_at.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "status": self.status,
        }


# ── Registry ──────────────────────────────────────────────────────────────────

class SessionRegistry:
    """Thread-safe, in-memory store for Session objects."""

    def __init__(self) -> None:
        self._store: dict[str, Session] = {}
        self._lock = threading.Lock()

    # ── Write operations ──────────────────────────────────────────────────────

    def create(
        self,
        client_ip: str,
        user_agent: str,
        user_id: Optional[str] = None,
    ) -> Session:
        """Create and register a new active session."""
        now = datetime.now(timezone.utc)
        session = Session(
            session_id=str(uuid.uuid4()),
            client_ip=client_ip,
            user_agent=user_agent,
            connected_at=now,
            last_seen=now,
            status="active",
            user_id=user_id,
        )
        with self._lock:
            self._store[session.session_id] = session
        return session

    def heartbeat(self, session_id: str) -> Optional[Session]:
        """
        Refresh last_seen for an active session.
        Returns the updated Session, or None if not found / inactive.
        """
        with self._lock:
            session = self._store.get(session_id)
            if session is None or session.status != "active":
                return None
            session.last_seen = datetime.now(timezone.utc)
            return session

    def end(self, session_id: str) -> Optional[Session]:
        """
        Mark a session inactive (soft delete).
        Returns the updated Session, or None if not found.
        """
        with self._lock:
            session = self._store.get(session_id)
            if session is None:
                return None
            session.status = "inactive"
            return session

    # ── Read operations ───────────────────────────────────────────────────────

    def get(self, session_id: str) -> Optional[Session]:
        """Return the Session for the given ID, or None."""
        with self._lock:
            return self._store.get(session_id)

    def list_all(self) -> list[Session]:
        """Return a snapshot of all sessions (any status)."""
        with self._lock:
            return list(self._store.values())

    # ── Maintenance ───────────────────────────────────────────────────────────

    def expire_stale(self, timeout_seconds: float) -> int:
        """
        Mark active sessions that have not sent a heartbeat within
        *timeout_seconds* as inactive.

        Returns the number of sessions that were newly marked inactive.
        Sessions already inactive are left unchanged.
        """
        now = datetime.now(timezone.utc)
        count = 0
        with self._lock:
            for session in self._store.values():
                if session.status != "active":
                    continue
                idle = (now - session.last_seen).total_seconds()
                if idle > timeout_seconds:
                    session.status = "inactive"
                    count += 1
        return count


# ── Module-level singleton ────────────────────────────────────────────────────

registry = SessionRegistry()
