#!/usr/bin/env bash
# Builds one image per Python service, with the build arguments from docker-compose.yml.
# Usage: REGISTRY=registry.example.com/cam TAG=latest ./deploy/build-images.sh
set -euo pipefail
REGISTRY="${REGISTRY:-cam}"; TAG="${TAG:-latest}"
cd "$(dirname "$0")/.."
docker build -f docker/python-service.Dockerfile --build-arg SERVICE_DIR=fastapi-router --build-arg ENTRYPOINT=upload_server.py -t "$REGISTRY/cam-upload-server:$TAG" .
docker build -f docker/python-service.Dockerfile --build-arg SERVICE_DIR=fastapi-router --build-arg ENTRYPOINT=fastapi_router.py -t "$REGISTRY/cam-fastapi-router:$TAG" .
docker build -f docker/python-service.Dockerfile --build-arg SERVICE_DIR=fastapi-router --build-arg ENTRYPOINT=duck_db_api.py --build-arg INSTALL_CLAMAV=true -t "$REGISTRY/cam-python-bridge:$TAG" .
docker build -f docker/python-service.Dockerfile --build-arg SERVICE_DIR=fastapi-router --build-arg ENTRYPOINT=hitl_router.py -t "$REGISTRY/cam-hitl-router:$TAG" .
docker build -f docker/python-service.Dockerfile --build-arg SERVICE_DIR=temporal_worker --build-arg ENTRYPOINT=worker.py -t "$REGISTRY/cam-temporal-worker:$TAG" .
docker build -f docker/python-service.Dockerfile --build-arg SERVICE_DIR=mcp-tools/reporting/superset --build-arg ENTRYPOINT=mcp_server.py --build-arg INSTALL_LIBREOFFICE=true -t "$REGISTRY/cam-reporting-mcp-server:$TAG" .
docker build -f docker/python-service.Dockerfile --build-arg SERVICE_DIR=mcp-tools/price-gate --build-arg ENTRYPOINT=mcp_server.py -t "$REGISTRY/cam-price-gate-mcp-server:$TAG" .
docker build -f docker/python-service.Dockerfile --build-arg SERVICE_DIR=mcp-tools/intake --build-arg ENTRYPOINT=mcp_server.py --build-arg INSTALL_CLAMAV=true -t "$REGISTRY/cam-intake-mcp-server:$TAG" .
docker build -f docker/python-service.Dockerfile --build-arg SERVICE_DIR=mcp-tools/distributor-pricing --build-arg ENTRYPOINT=mcp_server.py -t "$REGISTRY/cam-distributor-pricing-mcp-server:$TAG" .
docker build -f docker/python-service.Dockerfile --build-arg SERVICE_DIR=mcp-tools/gerber-integration --build-arg ENTRYPOINT=mcp_server.py -t "$REGISTRY/cam-gerber-integration-mcp-server:$TAG" .
docker build -f docker/python-service.Dockerfile --build-arg SERVICE_DIR=mcp-tools/scrub-intake --build-arg ENTRYPOINT=scrub_mcp_server.py -t "$REGISTRY/cam-scrub-intake-mcp-server:$TAG" .
docker build -f docker/python-service.Dockerfile --build-arg SERVICE_DIR=mcp-tools/rfq-memory --build-arg ENTRYPOINT=memory_service.py --build-arg EXTRA_REQUIREMENTS=mcp-tools/rfq-memory/requirements.txt -t "$REGISTRY/cam-rfq-memory-server:$TAG" .
echo "built 12 images"
