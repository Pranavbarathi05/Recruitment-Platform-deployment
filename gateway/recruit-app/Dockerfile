# ══════════════════════════════════════════════════════════════════════════════
# recruit-app – Containerised dsc-recruit backend
#
# This image packages the EXISTING dsc-recruit backend as-is.
# No application code is modified; the deployment layer wraps it.
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
