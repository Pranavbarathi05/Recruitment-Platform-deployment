"""
Gateway API – Phase 2
Node health stubs for the 5 known compute nodes.

No communication is attempted here; this module only defines the data
structures and a pre-populated registry that future phases will update.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ── Status enum ───────────────────────────────────────────────────────────────

class NodeStatus(str, Enum):
    unknown     = "unknown"
    healthy     = "healthy"
    degraded    = "degraded"
    unreachable = "unreachable"


# ── Node data model ───────────────────────────────────────────────────────────

@dataclass
class NodeInfo:
    name: str
    role: str                          # "app" | "compiler"
    status: NodeStatus = NodeStatus.unknown
    last_checked: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "status": self.status.value,
            "last_checked": (
                self.last_checked.isoformat() if self.last_checked else None
            ),
        }


# ── Registry ──────────────────────────────────────────────────────────────────

class NodeRegistry:
    """
    Holds static metadata for all known compute nodes.
    Status is initially *unknown* for every node.
    Future phases will update status via health probes.
    """

    _NODES: list[tuple[str, str]] = [
        ("app-01",       "app"),
        ("app-02",       "app"),
        ("compiler-01",  "compiler"),
        ("compiler-02",  "compiler"),
        ("compiler-03",  "compiler"),
    ]

    def __init__(self) -> None:
        self._store: dict[str, NodeInfo] = {
            name: NodeInfo(name=name, role=role)
            for name, role in self._NODES
        }

    def get(self, name: str) -> Optional[NodeInfo]:
        """Return the NodeInfo for *name*, or None if unknown."""
        return self._store.get(name)

    def list_all(self) -> list[NodeInfo]:
        """Return all registered nodes."""
        return list(self._store.values())


# ── Module-level singleton ────────────────────────────────────────────────────

node_registry = NodeRegistry()
