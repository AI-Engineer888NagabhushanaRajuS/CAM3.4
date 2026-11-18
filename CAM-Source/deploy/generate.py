"""Generates the Kubernetes manifests (deploy/k8s) and the image build script (deploy/build-images.sh) from docker-compose.yml.

Compose is the single source of truth: every service, port, build argument and shared environment value comes from it, so the
cluster cannot drift from the compose stack. Run after changing docker-compose.yml:

    python deploy/generate.py

The database and service logins are written from .env (the dev values the compose stack already uses). Third-party API keys and
the JWT secret are NOT written: deploy/k8s/11-app-keys.template.yaml lists them for you to fill in at deploy time.
"""
import json
import os
import re

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
K8S = os.path.join(HERE, "k8s")
NAMESPACE = "cam"
REGISTRY_PLACEHOLDER = "REGISTRY/"  # replaced by kustomize images or terraform var registry

# Database logins only: these are the local-dev credentials the compose stack uses.
LOGIN_KEYS = ["POSTGRES_PASSWORD", "CAM_PG_APP_USER", "CAM_PG_APP_PASSWORD", "CAM_PG_SUPERUSER_PASSWORD"]


def read_env():
    values = {}
    with open(os.path.join(ROOT, ".env"), encoding="utf-8-sig") as f:
        for line in f:
            m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
            if m:
                values[m.group(1)] = m.group(2).strip().strip('"')
    return values


def write(name, doc):
    path = os.path.join(K8S, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(doc, f, sort_keys=False, default_flow_style=False)
    return name


def meta(name, **labels):
    return {"name": name, "namespace": NAMESPACE, "labels": {"app.kubernetes.io/part-of": "cam", "app": name, **labels}}


def deployment(name, image, command, ports, env_from, env=None, volumes=None, mounts=None, args=None):
    container = {
        "name": name,
        "image": image,
        "envFrom": env_from,
        "ports": [{"containerPort": p} for p in ports],
    }
    if env:
        container["env"] = env
    if command:
        container["command"] = command
    if args:
        container["args"] = args
    if mounts:
        container["volumeMounts"] = mounts
    spec = {"containers": [container]}
    if volumes:
        spec["volumes"] = volumes
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": meta(name),
        "spec": {
            "replicas": 1,
            "strategy": {"type": "Recreate"},
            "selector": {"matchLabels": {"app": name}},
            "template": {"metadata": {"labels": {"app": name, "app.kubernetes.io/part-of": "cam"}}, "spec": spec},
        },
    }


def service(name, ports):
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": meta(name),
        "spec": {"selector": {"app": name}, "ports": [{"name": f"p{p}", "port": p, "targetPort": p} for p in ports]},
    }


def pvc(name, size, access="ReadWriteMany"):
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": meta(name),
        "spec": {"accessModes": [access], "resources": {"requests": {"storage": size}}},
    }


def main():
    os.makedirs(K8S, exist_ok=True)
    for old in os.listdir(K8S):
        if old.endswith(".yaml"):
            os.remove(os.path.join(K8S, old))

    compose = yaml.safe_load(open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8"))
    env = read_env()
    logins = {k: env[k] for k in LOGIN_KEYS if k in env}
    if "POSTGRES_PASSWORD" not in logins:
        raise SystemExit("POSTGRES_PASSWORD is not in .env: cannot write the login secret")
    pg_pw = logins["POSTGRES_PASSWORD"]

    files = []
    files.append(write("00-namespace.yaml", {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NAMESPACE}}))

    files.append(write("10-logins.yaml", {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": meta("cam-logins"),
        "type": "Opaque",
        "stringData": {
            "POSTGRES_USER": "centum",
            "POSTGRES_DB": "postgres",
            **logins,
        },
    }))

    # Shared non-secret environment, with the compose service names turned into in-cluster Service names.
    shared = dict(compose["x-python-env"])
    secret_refs = {"LOGIC_DB_URL", "FILE_METADATA_DB_URL", "STAGING_LOGIC_DB_URL", "STAGING_FILE_METADATA_DB_URL", "JWT_SECRET"}
    config = {}
    for k, v in shared.items():
        if k in secret_refs or "${" in str(v) or "PASSWORD" in k or "SECRET" in k or "KEY" in k:
            continue
        config[k] = str(v)
    config["CAM_TEMPORAL_HOST"] = "temporal:7233"
    files.append(write("20-config.yaml", {
        "apiVersion": "v1", "kind": "ConfigMap", "metadata": meta("cam-config"), "data": config,
    }))

    # Database URLs: built from the login secret; same databases as the compose stack.
    db_urls = {}
    for k in ("LOGIC_DB_URL", "FILE_METADATA_DB_URL", "STAGING_LOGIC_DB_URL", "STAGING_FILE_METADATA_DB_URL"):
        url = re.sub(r"\$\{POSTGRES_PASSWORD[^}]*\}", pg_pw, str(shared[k]))
        if "${" in url:
            raise SystemExit(f"{k} still has an unresolved placeholder")
        db_urls[k] = url
    files.append(write("21-db-urls.yaml", {
        "apiVersion": "v1", "kind": "Secret", "metadata": meta("cam-db-urls"), "type": "Opaque", "stringData": db_urls,
    }))

    files.append(write("11-app-keys.template.yaml", {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": meta("cam-app-keys"),
        "type": "Opaque",
        "stringData": {
            "# fill in at deploy time; never commit real values": "",
            "JWT_SECRET": "REPLACE_ME",
            "OPENROUTER_API_KEY": "REPLACE_ME",
            "DIGIKEY_CLIENT_ID": "REPLACE_ME",
            "DIGIKEY_CLIENT_SECRET": "REPLACE_ME",
            "MOUSER_API_KEY": "REPLACE_ME",
            "ELEMENT14_API_KEY": "REPLACE_ME",
        },
    }))

    files.append(write("30-storage.yaml", pvc("cam-database", "20Gi")))
    # The other two volumes: written as separate documents.
    files.append(write("31-exports.yaml", pvc("cam-exports", "10Gi")))
    files.append(write("32-inbox.yaml", pvc("cam-inbox", "10Gi")))

    # Infrastructure: Postgres 18 and Temporal (with its UI), both logins from the secret.
    pg_env = [
        {"name": "POSTGRES_USER", "valueFrom": {"secretKeyRef": {"name": "cam-logins", "key": "POSTGRES_USER"}}},
        {"name": "POSTGRES_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "cam-logins", "key": "POSTGRES_PASSWORD"}}},
        {"name": "POSTGRES_DB", "valueFrom": {"secretKeyRef": {"name": "cam-logins", "key": "POSTGRES_DB"}}},
        {"name": "PGDATA", "value": "/var/lib/postgresql/18/docker"},
    ]
    pg = deployment("postgres", "postgres:18", None, [5432], [], env=pg_env, volumes=[
        {"name": "data", "persistentVolumeClaim": {"claimName": "postgres-data"}}],
        mounts=[{"name": "data", "mountPath": "/var/lib/postgresql"}])
    files.append(write("40-postgres-data.yaml", pvc("postgres-data", "20Gi", "ReadWriteOnce")))
    files.append(write("41-postgres.yaml", pg))
    files.append(write("42-postgres-service.yaml", service("postgres", [5432])))

    temporal_env = [
        {"name": "DB", "value": "postgres12"},
        {"name": "DB_PORT", "value": "5432"},
        {"name": "POSTGRES_SEEDS", "value": "postgres"},
        {"name": "POSTGRES_USER", "valueFrom": {"secretKeyRef": {"name": "cam-logins", "key": "POSTGRES_USER"}}},
        {"name": "POSTGRES_PWD", "valueFrom": {"secretKeyRef": {"name": "cam-logins", "key": "POSTGRES_PASSWORD"}}},
    ]
    files.append(write("43-temporal.yaml", deployment("temporal", "temporalio/auto-setup:1.24", None, [7233], [], env=temporal_env)))
    files.append(write("44-temporal-service.yaml", service("temporal", [7233])))
    files.append(write("45-temporal-ui.yaml", deployment("temporal-ui", "temporalio/ui:2.26.0", None, [8080], [], env=[
        {"name": "TEMPORAL_ADDRESS", "value": "temporal:7233"}, {"name": "TEMPORAL_CORS_ORIGINS", "value": "http://localhost:3000"}])))
    files.append(write("46-temporal-ui-service.yaml", service("temporal-ui", [8080])))

    # One Deployment + Service per compose service that is a Python process (the same image, different entry point).
    services = []
    for name, s in compose["services"].items():
        if name in ("postgres", "temporal", "temporal-ui"):
            continue
        build = s.get("build")
        if not isinstance(build, dict):
            continue
        ports = []
        for p in s.get("ports", []) or []:
            inner = str(p).split(":")[-1]
            if inner.isdigit():
                ports.append(int(inner))
        image = f"{REGISTRY_PLACEHOLDER}cam-{name}:latest"
        entry = build.get("args", {}).get("ENTRYPOINT")
        workdir = build.get("args", {}).get("SERVICE_DIR")
        command = ["sh", "-c", f"cd /app/{workdir} && exec python {entry}"] if entry and workdir else None
        env_refs = [
            {"secretRef": {"name": "cam-db-urls"}},
            {"secretRef": {"name": "cam-app-keys"}},
            {"configMapRef": {"name": "cam-config"}},
        ]
        mounts = [
            {"name": "database", "mountPath": "/app/database"},
            {"name": "exports", "mountPath": "/app/exports"},
            {"name": "inbox", "mountPath": "/app/fastapi-router/staged/inbox"},
        ]
        volumes = [
            {"name": "database", "persistentVolumeClaim": {"claimName": "cam-database"}},
            {"name": "exports", "persistentVolumeClaim": {"claimName": "cam-exports"}},
            {"name": "inbox", "persistentVolumeClaim": {"claimName": "cam-inbox"}},
        ]
        doc = deployment(name, image, command, ports, env_refs, volumes=volumes, mounts=mounts)
        files.append(write(f"6{len(services):02d}-{name}.yaml", doc))
        if ports:
            files.append(write(f"7{len(services):02d}-{name}-service.yaml", service(name, ports)))
        services.append(name)

    kust = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "namespace": NAMESPACE,
        "resources": sorted(f for f in files if "template" not in f),
        "images": [{"name": f"REGISTRY/cam-{s}", "newName": f"REPLACE_WITH_REGISTRY/cam-{s}", "newTag": "latest"} for s in services],
    }
    with open(os.path.join(K8S, "kustomization.yaml"), "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(kust, f, sort_keys=False)

    # Build script: the same build arguments compose uses, one image per Python service.
    lines = ["#!/usr/bin/env bash", "# Builds one image per Python service, with the build arguments from docker-compose.yml.",
             "# Usage: REGISTRY=registry.example.com/cam TAG=latest ./deploy/build-images.sh", "set -euo pipefail",
             'REGISTRY="${REGISTRY:-cam}"; TAG="${TAG:-latest}"', "cd \"$(dirname \"$0\")/..\""]
    for name in services:
        b = compose["services"][name]["build"]
        args = " ".join(f"--build-arg {k}={v}" for k, v in (b.get("args") or {}).items())
        dockerfile = b.get("dockerfile", "docker/python-service.Dockerfile")
        lines.append(f'docker build -f {dockerfile} {args} -t "$REGISTRY/cam-{name}:$TAG" .')
    lines.append('echo "built ${#} images"'.replace("${#}", str(len(services))))
    with open(os.path.join(HERE, "build-images.sh"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print(f"wrote {len(files)} manifests for {len(services)} python services + infra; login values from .env")


if __name__ == "__main__":
    main()
