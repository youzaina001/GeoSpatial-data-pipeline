# Terraform Variables

variable "kubeconfig_path" {
  description = "Path to the kubeconfig file"
  type        = string
  default     = "~/.kube/config"
}

variable "kube_context" {
  description = "Kubernetes context to use"
  type        = string
  default     = "minikube"
}

# MinIO Configuration
variable "minio_root_user" {
  description = "MinIO root username"
  type        = string
  default     = "minioadmin"
}

variable "minio_root_password" {
  description = "MinIO root password"
  type        = string
  default     = "minioadmin"
  sensitive   = true
}

variable "minio_storage_size" {
  description = "Storage size for MinIO PVC"
  type        = string
  default     = "10Gi"
}

# Airflow Configuration
variable "airflow_admin_user" {
  description = "Airflow admin username"
  type        = string
  default     = "admin"
}

variable "airflow_admin_password" {
  description = "Airflow admin password"
  type        = string
  default     = "admin"
  sensitive   = true
}

variable "airflow_fernet_key" {
  description = "Fernet key for Airflow encryption"
  type        = string
  default     = "zTvhk_0YJ2_8q3KN8dkpB7hLxUgI2TZgESfB5n4f4Uk="
  sensitive   = true
}

# Resource Limits
variable "airflow_worker_replicas" {
  description = "Number of Airflow worker replicas (for KubernetesExecutor this is 0)"
  type        = number
  default     = 0
}
