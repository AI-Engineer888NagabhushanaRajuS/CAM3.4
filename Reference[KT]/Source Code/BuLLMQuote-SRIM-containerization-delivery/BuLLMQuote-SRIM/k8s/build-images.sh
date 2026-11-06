#!/bin/sh
# Builds every image this repo's k8s manifests reference, then imports them
# into the local k3d cluster (images built on the Docker Desktop host are NOT
# automatically visible to a k3d cluster's nodes -- `k3d image import` is
# required, or a registry push/pull, per this session's own k3d-on-Windows
# research).
#
# Usage: ./k8s/build-images.sh [k3d-cluster-name]
set -e
cd "$(dirname "$0")/.."   # repo root
CLUSTER="${1:-centum}"
TAG="${CENTUM_IMAGE_TAG:-dev}"

build() {
    name="$1"; service_dir="$2"; entrypoint="$3"
    echo "=== building centum/$name:$TAG ==="
    docker build -f docker/python-service.Dockerfile \
        --build-arg SERVICE_DIR="$service_dir" \
        --build-arg ENTRYPOINT="$entrypoint" \
        -t "centum/$name:$TAG" .
}

build upload-server                    fastmcp-router                    upload_server.py
build fastapi-router                   fastmcp-router                    fastapi_router.py
build hitl-router                      fastmcp-router                    hitl_router.py
build python-bridge                    fastmcp-router                    duck_db_api.py
build bom-qa-lookup                    fastmcp-router                    bom_qa_lookup_server.py
build reporting-mcp-server             mcp-tools/reporting/superset      mcp_server.py
build intake-mcp-server                mcp-tools/intake                  mcp_server.py
build distributor-pricing-mcp-server   mcp-tools/distributor-pricing     mcp_server.py
build gerber-integration-mcp-server    mcp-tools/gerber-integration      mcp_server.py
build rfq-memory-server                mcp-tools/rfq-memory              memory_service.py
build scrub-intake-mcp-server          mcp-tools/scrub-intake            scrub_mcp_server.py

echo "=== building centum/web:$TAG ==="
docker build -f docker/accomplish-ui-web.Dockerfile -t "centum/web:$TAG" ./accomplish-ui

echo "=== building centum/daemon:$TAG ==="
docker build -f docker/accomplish-ui-daemon.Dockerfile -t "centum/daemon:$TAG" ./accomplish-ui

if command -v k3d >/dev/null 2>&1; then
    echo "=== importing all centum/* images into k3d cluster '$CLUSTER' ==="
    k3d image import \
        "centum/upload-server:$TAG" "centum/fastapi-router:$TAG" "centum/hitl-router:$TAG" \
        "centum/python-bridge:$TAG" "centum/bom-qa-lookup:$TAG" "centum/reporting-mcp-server:$TAG" \
        "centum/intake-mcp-server:$TAG" "centum/distributor-pricing-mcp-server:$TAG" \
        "centum/gerber-integration-mcp-server:$TAG" "centum/rfq-memory-server:$TAG" \
        "centum/scrub-intake-mcp-server:$TAG" "centum/web:$TAG" "centum/daemon:$TAG" \
        -c "$CLUSTER"
else
    echo "k3d not found on PATH -- skipping image import. Install k3d first, or run"
    echo "docker compose up -d instead (no import step needed for plain Compose)."
fi

echo "Done. Images tagged :$TAG"
