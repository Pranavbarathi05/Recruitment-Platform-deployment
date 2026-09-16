# ══════════════════════════════════════════════════════════════════════════════
# App 2 — Containerised dsc-recruit backend
#
# Replica of gateway/app-1/Dockerfile. This image packages the EXISTING
# dsc-recruit backend as-is — no application code is modified, and no secrets
# are baked in. The two files are intentionally identical: App-2 is the same
# application, deployed on its own machine.
#
# There is NO second recruitment database: App-2 authenticates and stores data
# in the SAME Supabase project as App-1, configured through App-2's own
# .env (gateway/app-2/.env) — never by copying App-1's .env file.
#
# Build context: gateway/ (parent of this file)
# Usage: docker build -f app-2/Dockerfile .
# ══════════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS builder

WORKDIR /build

# Install Python dependencies from the existing requirements file.
# Copy only the requirements file first for better layer caching.
COPY dsc-recruit/apps/backend/requirements-dev.txt ./requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy the EXISTING dsc-recruit backend source tree.
# The full directory structure (routers/, core/, schemas/, services/, etc.)
# is needed because the backend uses relative imports between modules.
COPY dsc-recruit/apps/backend/ ./backend/

# Set working directory to the backend root so Python imports resolve correctly
# (e.g. "from routers import domains" → backend/routers/domains.py)
WORKDIR /app/backend

# Non-root user for least-privilege
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
