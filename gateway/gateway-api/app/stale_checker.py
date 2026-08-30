"""
Gateway API – Phase 2
Background daemon thread that periodically marks stale sessions inactive.

Configuration (via environment variables):
  SESSION_TIMEOUT_SECONDS     – idle time before a session is stale (default 300)
  STALE_CHECK_INTERVAL_SECONDS – how often this thread wakes up (default 60)
"""
from __future__ import annotations

import logging
import os
import threading
import time

from .session import registry

logger = logging.getLogger(__name__)


def _stale_checker_loop(timeout: float, interval: float) -> None:
    """Run forever, expiring stale sessions on each tick."""
    logger.info(
        "Stale-session checker started (timeout=%ss, interval=%ss).",
        timeout,
        interval,
    )
    while True:
        time.sleep(interval)
        try:
            expired = registry.expire_stale(timeout)
            if expired:
                logger.info("Stale-session check: marked %d session(s) inactive.", expired)
            else:
                logger.debug("Stale-session check: no sessions expired.")
        except Exception:
            logger.exception("Unexpected error in stale-session checker.")


def start_stale_checker() -> threading.Thread:
    """
    Start and return the background stale-checker daemon thread.
    Should be called once, from the FastAPI lifespan handler.
    """
    timeout = float(os.getenv("SESSION_TIMEOUT_SECONDS", "300"))
    interval = float(os.getenv("STALE_CHECK_INTERVAL_SECONDS", "60"))

    thread = threading.Thread(
        target=_stale_checker_loop,
        args=(timeout, interval),
        daemon=True,        # dies with the main process
        name="stale-checker",
    )
    thread.start()
    return thread
