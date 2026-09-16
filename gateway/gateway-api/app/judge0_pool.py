"""
Compiler node pool — Compiler-1 / Compiler-2 / Compiler-3.

The deployment runs up to three identical Judge0 execution machines (System 3,
System 5, System 6). This module is the single place that decides *which* node
a submission goes to; the HTTP proxy in `judge0_proxy.py` does the talking.

Configuration
-------------
Each node is configured with its own environment variable:

    COMPILER_1_URL=http://<COMPILER1_LAN_IP>:2358
    COMPILER_2_URL=http://<COMPILER2_LAN_IP>:2358
    COMPILER_3_URL=http://<COMPILER3_LAN_IP>:2358

Any subset may be set, and the order in which they are given is the
round-robin order. When *none* of them is set the pool falls back to the
existing single-node `JUDGE0_URL`, so a one-node deployment behaves exactly as
before this module existed.

Distribution
------------
Deterministic round-robin with a thread-safe cursor (the FastAPI handlers that
use it are sync and run in a thread pool). No external load balancer, no
randomness, no coordination between machines.

Failover
--------
A node that cannot be reached (connection error, timeout) or that reports its
queue full (HTTP 503) is skipped and the next node in the pool is tried. The
node that accepts a submission is then used for that submission's polling,
because a Judge0 submission token only exists on the node that queued it.
"""
from __future__ import annotations

import os
import threading
from typing import Iterable, Mapping, Optional

# ── Configuration ────────────────────────────────────────────────────────────

#: Per-node environment variables, in pool order.
COMPILER_URL_ENV_VARS: tuple[str, ...] = (
    "COMPILER_1_URL",
    "COMPILER_2_URL",
    "COMPILER_3_URL",
)

#: Environment variable holding the single-node address used before the pool
#: existed. Still fully supported (one-node deployments, local development).
LEGACY_URL_ENV_VAR = "JUDGE0_URL"
LEGACY_URL_DEFAULT = "http://judge0-server:2358"


def _normalise(url: Optional[str]) -> str:
    return (url or "").strip().rstrip("/")


def resolve_pool(env: Optional[Mapping[str, str]] = None) -> list[str]:
    """Return the ordered list of Judge0 base URLs to distribute work across.

    `COMPILER_1_URL..COMPILER_3_URL` win when at least one is set; otherwise the
    legacy single `JUDGE0_URL` is used. Never returns an empty list.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    pool = [
        _normalise(source.get(name))
        for name in COMPILER_URL_ENV_VARS
    ]
    pool = [url for url in pool if url]
    if pool:
        return pool
    return [_normalise(source.get(LEGACY_URL_ENV_VAR)) or LEGACY_URL_DEFAULT]


def pool_size(env: Optional[Mapping[str, str]] = None) -> int:
    return len(resolve_pool(env))


# ── Round-robin cursor ───────────────────────────────────────────────────────

_cursor_lock = threading.Lock()
_cursor = 0


def reset_cursor(value: int = 0) -> None:
    """Reset the round-robin cursor (used by tests)."""
    global _cursor
    with _cursor_lock:
        _cursor = value


def next_node(pool: Optional[Iterable[str]] = None) -> str:
    """Return the next node in round-robin order and advance the cursor.

    Deterministic: consecutive calls cycle through the pool in order.
    """
    nodes = list(pool) if pool is not None else resolve_pool()
    if not nodes:
        raise ValueError("compiler pool is empty")
    global _cursor
    with _cursor_lock:
        node = nodes[_cursor % len(nodes)]
        _cursor += 1
    return node


def failover_order(start_node: str, pool: Optional[Iterable[str]] = None) -> list[str]:
    """`[start_node]` followed by every other node, in pool order.

    Trying this list in order means one unreachable compiler cannot fail a
    request while another compiler is healthy.
    """
    nodes = list(pool) if pool is not None else resolve_pool()
    return [start_node] + [node for node in nodes if node != start_node]


def describe_pool(env: Optional[Mapping[str, str]] = None) -> list[dict[str, object]]:
    """Human/machine readable pool description for health endpoints.

    Each entry names the environment variable the URL came from, so an operator
    can see which `COMPILER_n_URL` to edit.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    described = [
        {"index": index + 1, "url": url, "source": name}
        for index, (name, url) in enumerate(
            (name, _normalise(source.get(name))) for name in COMPILER_URL_ENV_VARS
        )
        if url
    ]
    if described:
        return described
    return [
        {
            "index": 1,
            "url": _normalise(source.get(LEGACY_URL_ENV_VAR)) or LEGACY_URL_DEFAULT,
            "source": LEGACY_URL_ENV_VAR,
        }
    ]
