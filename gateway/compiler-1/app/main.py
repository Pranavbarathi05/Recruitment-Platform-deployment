"""
Gateway Compiler 1 – Code Execution Service

A standalone HTTP service that accepts structured code execution requests,
runs untrusted code in an isolated sandbox with resource limits, and returns
structured JSON results.

Security model:
  - All code runs in temporary directories that are cleaned up after execution.
  - Child processes have CPU time limits, file size limits, and process limits.
  - Wall-clock timeout enforced by `timeout` command with SIGKILL.
  - Non-root execution (Docker USER directive).
  - No network access, no host filesystem access.
  - Output is truncated to prevent excessive memory use.
  - Bounded concurrency prevents resource exhaustion.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import execute, health

_VERSION = os.getenv("COMPILER_VERSION", "0.1.0")

app = FastAPI(
    title="Gateway Compiler 1",
    description=(
        "Code execution service for the Recruitment Platform. "
        "Accepts structured execution requests and returns machine-readable results."
    ),
    version=_VERSION,
)

# CORS for development / cross-origin access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(execute.router)
