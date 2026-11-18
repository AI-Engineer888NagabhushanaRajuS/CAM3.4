output "namespace" {
  value       = "cam"
  description = "Namespace the CAM stack is deployed into."
}

output "manifest_count" {
  value       = length(local.manifests)
  description = "Number of manifests applied from deploy/k8s."
}
