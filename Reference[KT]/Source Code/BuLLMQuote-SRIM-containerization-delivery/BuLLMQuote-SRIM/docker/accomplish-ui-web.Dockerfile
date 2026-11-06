# Production build for accomplish-ui's web app -- NOT the existing
# accomplish-ui/Dockerfile (that one runs `pnpm dev:web`, a dev server).
# Multi-stage: build the static bundle with pnpm/vite, serve it with nginx.
#
# Build context must be ./accomplish-ui (see docker-compose.yml's `web`
# service) since this needs the whole pnpm workspace (root package.json,
# pnpm-workspace.yaml, packages/agent-core) to resolve workspace deps, not
# just apps/web in isolation.

FROM node:24-bookworm-slim AS build
WORKDIR /app
RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web ./apps/web
COPY packages ./packages

RUN pnpm install --config.engine-strict=false --config.confirmModulesPurge=false --frozen-lockfile
RUN pnpm build:web

# vite.config.ts's own build.outDir -- confirmed this session, not guessed
# (apps/web/dist/client, not the bare apps/web/dist some vite setups use).
FROM nginx:1.27-alpine AS serve
COPY --from=build /app/apps/web/dist/client /usr/share/nginx/html

# Hash-based React Router (confirmed in docs/SYSTEM-AND-TECH-STACK.md) needs
# no server-side rewrite rules -- every route is already a query/hash on
# index.html, so the default nginx static config is sufficient; no custom
# nginx.conf needed for SPA fallback the way a history-mode router would.

EXPOSE 80
