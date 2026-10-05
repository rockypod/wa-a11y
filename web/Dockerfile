# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM docker.io/library/node:24.21.0-bookworm-slim AS styles
WORKDIR /src
RUN corepack enable && corepack prepare pnpm@11.5.2 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY scanner/package.json scanner/
COPY styles/package.json styles/
RUN pnpm install --frozen-lockfile --filter "@wa-a11y/styles..."
COPY styles/ styles/
COPY web/app web/app
RUN pnpm -C styles build && pnpm -C styles test

FROM docker.io/library/python:3.13.16-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY web/pyproject.toml web/uv.lock web/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY web/app ./app
COPY --from=styles /src/styles/dist/wa-a11y.css ./app/static/wa-a11y.css
COPY --from=styles /src/styles/dist/fonts ./app/static/fonts
COPY web/alembic.ini ./
COPY web/migrations ./migrations
RUN useradd --uid 10001 --create-home --home-dir /home/app --shell /usr/sbin/nologin app \
 && mkdir /data && chown app:app /data
USER app
# Egress: embedding model baked in at build time; Chroma telemetry off
ENV ANONYMIZED_TELEMETRY=False
RUN /app/.venv/bin/python -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction as E; E()(['warm up'])"
EXPOSE 8000
# One worker: SQLite has a single writer and the queue runner lives in this process.
CMD ["sh", "-c", "/app/.venv/bin/alembic upgrade head && exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
