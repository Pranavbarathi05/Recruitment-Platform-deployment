# ══════════════════════════════════════════════════════════════════════════════
# Recruitment Frontend — Multi-stage Docker Build
#
# Build context: project root (so we can COPY from dsc-recruit/)
# Dockerfile location: gateway/frontend/Dockerfile
#
# Stage 1: Node 22 — install deps + run vite build
# Stage 2: nginx:1.27 — serve static assets
# ══════════════════════════════════════════════════════════════════════════════

# ── Stage 1: Build ──────────────────────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

# Copy frontend source from the application repository
COPY dsc-recruit/apps/frontend/package.json ./
COPY dsc-recruit/apps/frontend/package-lock.json ./

# package.json's `postinstall` runs BOTH `copy-pyodide` and `copy-duckdb`, so
# every scripts/*.mjs that hook needs must already be on disk when `npm ci`
# runs. Copying the whole scripts/ tree would also drag in the ~8 MB of wheel
# files, which change rarely — copy just the Node scripts here and let the
# later `COPY ... ./` bring in scripts/pyodide-packages/*.whl.
COPY dsc-recruit/apps/frontend/scripts/*.mjs ./scripts/

RUN npm ci

COPY dsc-recruit/apps/frontend/ ./

# Regenerate the local WASM runtimes from the packages just installed
# (Pyodide runtime + stdlib + wheels, DuckDB-WASM + workers). `prebuild`
# re-runs both, but doing it explicitly here keeps the failure obvious.
RUN npm run copy-pyodide && npm run copy-duckdb

# Vite reads VITE_* env vars at build time
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ARG VITE_API_URL=

ENV VITE_SUPABASE_URL=${VITE_SUPABASE_URL}
ENV VITE_SUPABASE_ANON_KEY=${VITE_SUPABASE_ANON_KEY}
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build

# ── Stage 2: Serve ──────────────────────────────────────────────────────────
FROM nginx:1.27-alpine

# Remove default nginx site
RUN rm -rf /usr/share/nginx/html/*

# Copy built assets from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# ── Fix same-origin API base ──────────────────────────────────────────────────
# The app is built with VITE_API_URL=".", so every fetch is route-relative
# (e.g. `${apiUrl}/auth/me` == "./auth/me"). On deep SPA routes such as
# /assessment/<id> that resolves to /assessment/auth/me instead of /auth/me,
# which falls through to the SPA catch-all and returns index.html instead of
# JSON. Pinning <base href="/"> makes all document-relative fetches resolve
# against the origin root regardless of the current route depth, so they reach
# Traefik/app-1 with the canonical path. Deployment-side only — no app change.
RUN sed -i 's|<head>|<head><base href="/" />|' /usr/share/nginx/html/index.html

# Copy custom nginx config
COPY gateway/frontend/nginx.conf /etc/nginx/conf.d/default.conf

# Run as non-root
RUN addgroup -g 1001 -S appgroup && \
    adduser  -u 1001 -S appuser -G appgroup && \
    chown -R appuser:appgroup /usr/share/nginx/html && \
    chown -R appuser:appgroup /var/cache/nginx && \
    chown -R appuser:appgroup /var/log/nginx && \
    touch /var/run/nginx.pid && \
    chown -R appuser:appgroup /var/run/nginx.pid

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=10s \
  CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
