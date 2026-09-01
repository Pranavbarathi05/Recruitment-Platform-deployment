# ══════════════════════════════════════════════════════════════════════════════
# Compiler 1 – Code Execution Service
#
# Contains compilers and interpreters for:
#   C++   (g++)
#   C     (gcc)
#   Java  (OpenJDK 21)
#   Python (Python 3)
#   SQL   (SQLite3)
#
# Security:
#   - Runs as non-root user.
#   - No access to host filesystem outside temp directories.
#   - No access to Docker socket or application secrets.
#   - Resource limits enforced per-execution via ulimit + timeout.
# ══════════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS builder

WORKDIR /build

COPY compiler-1/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Install compilers and interpreters
RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ \
    gcc \
    openjdk-21-jdk-headless \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application source
COPY compiler-1/app/ ./app/

# Create a non-root user for the service
RUN adduser --disabled-password --gecos "" compiler \
    && chown -R compiler /app
USER compiler

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
