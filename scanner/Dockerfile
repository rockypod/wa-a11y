# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

FROM mcr.microsoft.com/playwright:v1.63.0-noble
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.5.2 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY scanner/package.json scanner/
COPY styles/package.json styles/
RUN pnpm install --frozen-lockfile --filter "@wa-a11y/scanner..."
COPY scanner/tsconfig.json scanner/levels.json scanner/
COPY scanner/src scanner/src
RUN pnpm -C scanner build
# Non-root: the Playwright image's pwuser
USER pwuser
ENV PORT=3001
EXPOSE 3001
CMD ["node", "scanner/dist/server.js"]
