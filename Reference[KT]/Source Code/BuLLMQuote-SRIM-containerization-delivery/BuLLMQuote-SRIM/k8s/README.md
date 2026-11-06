# Kubernetes deployment (k3d) -- Centum/BuLLMQuote-SRIM

Containerization Phase 3. See `C:\Users\ADMIN\.claude\plans\swirling-strolling-shore.md`
for the full plan, and `../docs/` for the architecture this is built from.

## What this is, and isn't

**Is:** a complete, server-validated set of k8s manifests for every Centum
service, tested against a real local k3d cluster this session (cluster
created, every manifest applied and scheduled correctly, PVCs bound,
`postgres`/`superset` pulled and started from their public images).

**Isn't yet:** a live, data-populated deployment. The `centum/*` custom
images still need building (`build-images.sh`) and Postgres still needs
seeding (`../database/pg_dump_seed/`, which requires YOU to run the
`pg_dump` commands -- your own Postgres password was never given to this
session). See `../docs/FINDINGS-AND-FIXES.md` and the chat history for why.

## Quick start

```powershell
# 1. Create the cluster (already done once this session as "centum" --
#    `k3d cluster list` to check, `k3d cluster start centum` if it's stopped)
k3d cluster create centum -p "18080:80@loadbalancer" --wait

# 2. If `kubectl get nodes` hangs: host.docker.internal resolved to the wrong
#    IP in this session's environment. Fix with:
kubectl config set-cluster k3d-centum --server=https://127.0.0.1:<port from `k3d cluster list`>

# 3. Build and import every image
./build-images.sh centum

# 4. Seed Postgres (run the pg_dump commands from docs/SESSION-SUMMARY.md
#    first, drop output in ../database/pg_dump_seed/) -- then apply:
kubectl create configmap postgres-init-script -n centum \
  --from-file=init-restore.sh=../infra/postgres/init-restore.sh

# 5. Apply everything
kubectl apply -k .

# 6. Seed the shared database/ PVC (DuckDB files + cognee_data) once:
kubectl cp ../database centum/<any-pod-mounting-centum-database>:/app/database

# 7. Fill in real secrets (never commit these) -- either edit a local,
#    gitignored copy of 01-config.yaml's Secret, or:
kubectl create secret generic centum-secrets -n centum --dry-run=client \
  --from-literal=JWT_SECRET=... --from-literal=POSTGRES_PASSWORD=... \
  -o yaml | kubectl apply -f -

kubectl get pods -n centum -w
```

## Port map -- nothing here collides with Centum's live bare-metal ports

| Service | k8s internal port | docker-compose host port | Live bare-metal port (untouched) |
|---|---|---|---|
| upload-server | 3100 | 13100 | 3100 |
| fastapi-router | 5100 | 15100 | 5100 |
| hitl-router | 5102 | 15102 | 5102 |
| python-bridge | 3110 | 13110 | 3110 |
| bom-qa-lookup | 8106 | 18106 | 8106 |
| reporting-mcp-server | 8105 | 18105 | 8105 |
| intake-mcp-server | 8002 | 18002 | 8002 |
| distributor-pricing-mcp-server | 8003 | 18003 | 8003 |
| gerber-integration-mcp-server | 8007 | 18007 | 8007 |
| rfq-memory-server | 8108/8109 | 18108/18109 | 8108/8109 |
| scrub-intake-mcp-server | 8004 | 18004 | n/a (new) |
| web | 80 | 15281 | 5281 |
| daemon | 9334 | 19334 | 9334 |
| superset | 8088 | 18188 | 8188 |
| postgres | 5432 | 15432 | n/a (separate instance) |
| k3d LoadBalancer | -- | 18080 (web ingress) | n/a |

## Known gaps, honestly

- **Phase 4 (independent Dify/Bifrost) not built.** Every Python service's
  `DIFY_BASE_URL`/`CENTUM_MCP_JUNGLE_URL` points back at this host's existing
  shared instances over the NetBird mesh IP (`100.121.36.255`). If that IP
  ever changes, update `01-config.yaml`'s ConfigMap.
- **`scrub-intake-mcp-server` is structurally migrated but not runtime-tested**
  end-to-end (no live Ollama/Postgres wiring test performed this session) --
  see its own migration note in `mcp-tools/scrub-intake/scrub_mcp_server.py`.
- **Row-count verification between the live shared Postgres and this
  container's restored copy (Task 7 of the plan) has not run** -- blocked on
  the same pg_dump step above.
- **`kubectl rollout undo` resilience has not been proven on a populated
  deployment yet** -- the cluster this session only got as far as scheduling
  with public images (postgres/superset); a full rollback drill needs the
  `centum/*` images built first.
