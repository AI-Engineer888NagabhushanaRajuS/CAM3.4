provider "kubernetes" {
  config_path    = var.kubeconfig_path
  config_context = var.kube_context
}

locals {
  # Every manifest deploy/generate.py wrote, except the namespace (its own resource below), the kustomization and the key template
  # (the keys come from var.app_keys).
  manifest_files = toset([
    for f in fileset("${path.module}/../k8s", "*.yaml") : f
    if !strcontains(f, "template") && f != "kustomization.yaml" && f != "00-namespace.yaml"
  ])

  # Image references point at the registry and tag given by the variables.
  manifests = {
    for f in local.manifest_files : f => yamldecode(
      replace(replace(file("${path.module}/../k8s/${f}"), "REGISTRY/", "${var.registry}/"), ":latest", ":${var.image_tag}")
    )
  }
}

# The namespace first; everything else lives in it.
resource "kubernetes_manifest" "cam" {
  for_each = local.manifests

  manifest = each.value

  depends_on = [kubernetes_manifest.namespace]
}

resource "kubernetes_manifest" "namespace" {
  manifest = yamldecode(file("${path.module}/../k8s/00-namespace.yaml"))
}

# The third-party keys: one secret, built from variables so no real value is in git.
resource "kubernetes_secret_v1" "app_keys" {
  metadata {
    name      = "cam-app-keys"
    namespace = "cam"
  }
  type = "Opaque"
  data = var.app_keys

  depends_on = [kubernetes_manifest.namespace]
}
