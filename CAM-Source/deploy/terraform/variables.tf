variable "kubeconfig_path" {
  type        = string
  default     = "~/.kube/config"
  description = "Kubeconfig used to reach the cluster."
}

variable "kube_context" {
  type        = string
  default     = null
  description = "Context in the kubeconfig (null = current context)."
}

variable "registry" {
  type        = string
  description = "Image registry that holds the cam-<service> images built by deploy/build-images.sh, e.g. registry.example.com/cam."
}

variable "image_tag" {
  type        = string
  default     = "latest"
  description = "Tag of the cam-<service> images."
}

variable "app_keys" {
  type        = map(string)
  sensitive   = true
  default     = {}
  description = "Third-party API keys and the JWT secret (JWT_SECRET, OPENROUTER_API_KEY, DIGIKEY_CLIENT_ID, ...). Set in terraform.tfvars (git-ignored) or TF_VAR_app_keys; never commit real values."
}
