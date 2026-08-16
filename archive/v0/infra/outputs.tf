# Terraform Outputs
# URLs and connection details for deployed services

output "minio_endpoint" {
  description = "MinIO API endpoint (internal)"
  value       = "minio.minio.svc.cluster.local:9000"
}

output "minio_console_command" {
  description = "Command to access MinIO console"
  value       = "minikube service minio-console -n minio --url"
}

output "airflow_webserver_command" {
  description = "Command to access Airflow webserver"
  value       = "minikube service airflow-webserver -n airflow --url"
}

output "airflow_credentials" {
  description = "Airflow login credentials"
  value = {
    username = var.airflow_admin_user
    password = var.airflow_admin_password
  }
  sensitive = true
}

output "minio_credentials" {
  description = "MinIO login credentials"
  value = {
    access_key = var.minio_root_user
    secret_key = var.minio_root_password
  }
  sensitive = true
}

output "namespaces" {
  description = "Kubernetes namespaces created"
  value = {
    minio   = kubernetes_namespace.minio.metadata[0].name
    airflow = kubernetes_namespace.airflow.metadata[0].name
  }
}

output "next_steps" {
  description = "Next steps after deployment"
  value       = <<-EOT
    ================================================
    GeoPipeline Pipeline Deployed Successfully!
    ================================================

    1. Get MinIO Console URL:
       minikube service minio-console -n minio --url

    2. Get Airflow UI URL:
       minikube service airflow-webserver -n airflow --url

    3. Login Credentials:
       - Airflow: admin / admin
       - MinIO: minioadmin / minioadmin

    4. Verify pods are running:
       kubectl get pods -n minio
       kubectl get pods -n airflow

    5. Enable and trigger DAGs in Airflow UI

    ================================================
  EOT
}
