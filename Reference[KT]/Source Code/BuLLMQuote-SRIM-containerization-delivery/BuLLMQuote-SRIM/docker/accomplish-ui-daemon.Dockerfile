# Production build for accomplish-ui's daemon -- no Dockerfile existed for
# this service before (confirmed this session). Entrypoint mirrors the
# confirmed production command already used by fastmcp-router/manage_backend.py:
# `pnpm run build` (tsup bundle) then `node dist/index.js`.
#
# Build context must be ./accomplish-ui (see docker-compose.yml's `daemon`
# service) for the same pnpm-workspace reason as accomplish-ui-web.Dockerfile.

FROM node:24-bookworm-slim AS build
WORKDIR /app
RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/daemon ./apps/daemon
COPY packages ./packages

RUN pnpm install --config.engine-strict=false --config.confirmModulesPurge=false --frozen-lockfile
RUN pnpm --filter @accomplish/daemon run build

FROM node:24-bookworm-slim AS run
WORKDIR /app
RUN corepack enable
ENV NODE_ENV=production

COPY --from=build /app/apps/daemon/dist ./dist
COPY --from=build /app/apps/daemon/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules

# ACCOMPLISH_DAEMON_DEV=0 (set in docker-compose.yml) -- dev mode (ACCOMPLISH_DAEMON_DEV=1)
# enables the fixed-credentials login bypass via ACCOMPLISH_TEST_LOGIN, which
# must never be on for anything other than a local dev run. --data-dir mirrors
# manage_backend.py's own daemon launch args.
EXPOSE 9334
CMD ["node", "dist/index.js", "--data-dir", "/data"]
