# One image recipe for every containerized Python service (see docker-compose.yml).
# Build context is the repo root; SERVICE_DIR is the service folder, ENTRYPOINT its script.
FROM python:3.12-slim

ARG SERVICE_DIR
ARG ENTRYPOINT

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System library needed by python-magic (file-type checks in the intake service).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Shared dependency layer first, so every service image reuses the same cached install.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --default-timeout=300 --retries 5 -r /app/requirements.txt

# Malware scanner for the intake service only (scan_local_file runs clamscan; set CLAMSCAN_PATH=clamscan).
# freshclam bakes the signature database in at build time; a long-lived deployment must refresh it.
ARG INSTALL_CLAMAV=false
RUN if [ "$INSTALL_CLAMAV" = "true" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends clamav \
        && freshclam \
        && rm -rf /var/lib/apt/lists/*; \
    fi

COPY . /app

WORKDIR /app/${SERVICE_DIR}
ENV SERVICE_ENTRYPOINT=${ENTRYPOINT}
CMD ["sh", "-c", "exec python ${SERVICE_ENTRYPOINT}"]
