# CAM on Kubernetes with Terraform

1. Build and push the images (same build arguments as docker-compose.yml):
   `REGISTRY=registry.example.com/cam TAG=latest ../build-images.sh` then `docker push` each `cam-<service>` image.
2. Generated manifests live in `../k8s` (regenerate with `python deploy/generate.py` after changing docker-compose.yml).
3. Copy `terraform.tfvars.example` to `terraform.tfvars` and fill in the registry and the keys.
4. `terraform init && terraform plan && terraform apply`.

Plain kubectl works too: `kubectl apply -k ../k8s` (edit the image names in kustomization.yaml first).

Notes:
- The shared DuckDB files (/app/database), exports and the inbox need a ReadWriteMany storage class; the default PVCs
  request ReadWriteMany. Set the storage class in `../k8s/30-storage.yaml` for your cluster.
- Postgres and Temporal use the development logins in `../k8s/10-logins.yaml`. Rotate them before any shared deployment.
