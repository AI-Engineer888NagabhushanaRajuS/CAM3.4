# Code-only rebuild: copies the current source over an ALREADY BUILT service image. No pip, no apt, so it works when PyPI is
# unreachable (seen 2026-11-17: pypi.org resolved to IPv6 only and `docker compose build` died in `pip install`).
# Use it only when requirements.txt and the system packages did not change; otherwise use the normal `docker compose build`.
#
#   docker build -f docker/overlay.Dockerfile --build-arg BASE=cam-e2e-temporal-worker:latest -t cam-e2e-temporal-worker:latest .
#   docker compose -p cam-e2e up -d --no-deps temporal-worker        # without --build: it uses the image tagged above
#
# WORKDIR, ENV and CMD come from the base image. The runtime data (./database) is mounted by the compose file, so it is not copied.
ARG BASE
FROM ${BASE}
COPY . /app
