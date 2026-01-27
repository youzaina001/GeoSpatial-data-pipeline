# Airflow Deployment
# Apache Airflow with KubernetesExecutor

# ConfigMap for DAGs (mounted into Airflow)
resource "kubernetes_config_map" "airflow_dags" {
  metadata {
    name      = "airflow-dags"
    namespace = kubernetes_namespace.airflow.metadata[0].name
  }

  data = {
    "satellite_ingestion_dag.py" = file("${path.module}/../dags/satellite_ingestion_dag.py")
    "field_processing_dag.py"    = file("${path.module}/../dags/field_processing_dag.py")
  }
}

# ConfigMap for hydrosat Python package
resource "kubernetes_config_map" "hydrosat_package" {
  metadata {
    name      = "hydrosat-package"
    namespace = kubernetes_namespace.airflow.metadata[0].name
  }

  data = {
    "__init__.py"                   = file("${path.module}/../src/hydrosat/__init__.py")
    "config.py"                     = file("${path.module}/../src/hydrosat/config.py")
    "generators___init__.py"        = file("${path.module}/../src/hydrosat/generators/__init__.py")
    "generators__satellite_data.py" = file("${path.module}/../src/hydrosat/generators/satellite_data.py")
    "generators__field_data.py"     = file("${path.module}/../src/hydrosat/generators/field_data.py")
    "clients___init__.py"           = file("${path.module}/../src/hydrosat/clients/__init__.py")
    "clients__storage.py"           = file("${path.module}/../src/hydrosat/clients/storage.py")
    "services___init__.py"          = file("${path.module}/../src/hydrosat/services/__init__.py")
    "services__ingestion.py"        = file("${path.module}/../src/hydrosat/services/ingestion.py")
    "services__processing.py"       = file("${path.module}/../src/hydrosat/services/processing.py")
  }
}

# Airflow Helm release
resource "helm_release" "airflow" {
  name       = "airflow"
  namespace  = kubernetes_namespace.airflow.metadata[0].name
  repository = "https://airflow.apache.org"
  chart      = "airflow"
  version    = "1.13.1"

  # Don't wait for pods - deploy script handles DB migration and pod readiness
  wait    = false
  timeout = 600

  values = [
    templatefile("${path.module}/values/airflow-values.yaml", {
      airflow_admin_user      = var.airflow_admin_user
      airflow_admin_password  = var.airflow_admin_password
      airflow_fernet_key      = var.airflow_fernet_key
      airflow_namespace       = kubernetes_namespace.airflow.metadata[0].name
      dags_configmap_name     = kubernetes_config_map.airflow_dags.metadata[0].name
      hydrosat_configmap_name = kubernetes_config_map.hydrosat_package.metadata[0].name
      minio_endpoint          = "minio.${kubernetes_namespace.minio.metadata[0].name}.svc.cluster.local:9000"
      minio_access_key        = var.minio_root_user
      minio_secret_key        = var.minio_root_password
    })
  ]

  depends_on = [
    helm_release.minio,
    kubernetes_config_map.airflow_dags,
    kubernetes_config_map.hydrosat_package,
  ]
}

