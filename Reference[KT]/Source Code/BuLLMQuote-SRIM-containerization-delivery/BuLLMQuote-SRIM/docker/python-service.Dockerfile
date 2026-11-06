# Shared Dockerfile for every Python service in this repo. ONE image recipe,
# parameterized per service via build args -- because several services
# (duck_db_api.py, bom_qa_lookup_server.py) reach across directories at
# runtime via sys.path inserts (e.g. fastmcp-router/ -> ../mcp-tools/reporting/
# superset/), so every service's build context must be the WHOLE repo root,
# not just its own folder. Building one Dockerfile per service's own
# subfolder would silently break those cross-imports.
#
# Build (from the repo root, NOT from docker/):
#   docker build -f docker/python-service.Dockerfile \
#     --build-arg SERVICE_DIR=fastmcp-router \
#     --build-arg ENTRYPOINT=upload_server.py \
#     -t centum/upload-server:latest .
#
# See docker-compose.yml for the full, already-filled-in build args for every
# service -- that's the reference list, not this comment.

FROM python:3.10.11-slim AS base

# python-magic needs libmagic; psycopg2-binary/duckdb need no extra system
# libs beyond what the slim image already has for their wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# --timeout/--retries -- this session's network hit 3 separate transient
# read-timeouts against files.pythonhosted.org on large wheels (pandas,
# duckdb); pip's defaults (15s timeout, minimal retry) aren't resilient
# enough for that. Bumping both rather than re-running the whole build by
# hand every time one large download blips.
RUN pip install --no-cache-dir --timeout=120 --retries=10 -r requirements.txt

# Whole repo, minus what .dockerignore excludes (node_modules, .venv, .git,
# *.duckdb data files -- those are volume-mounted at runtime, never baked
# into the image).
COPY fastmcp-router/ ./fastmcp-router/
COPY mcp-tools/ ./mcp-tools/

ARG SERVICE_DIR
ARG ENTRYPOINT
ENV SERVICE_DIR=${SERVICE_DIR}
ENV ENTRYPOINT=${ENTRYPOINT}
WORKDIR /app/${SERVICE_DIR}

# Shell form so $SERVICE_DIR/$ENTRYPOINT expand -- ENTRYPOINT/SERVICE_DIR are
# baked in at build time via the ARGs above, not left for `docker run` to supply.
CMD python ${ENTRYPOINT}
