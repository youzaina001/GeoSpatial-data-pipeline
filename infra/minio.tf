# MinIO Deployment
# S3-compatible object storage for satellite imagery

resource "helm_release" "minio" {
  name       = "minio"
  namespace  = kubernetes_namespace.minio.metadata[0].name
  repository = "https://charts.min.io"
  chart      = "minio"
  version    = "5.0.15"

  wait    = true
  timeout = 600

  values = [
    templatefile("${path.module}/values/minio-values.yaml", {
      minio_root_user     = var.minio_root_user
      minio_root_password = var.minio_root_password
      minio_storage_size  = var.minio_storage_size
    })
  ]
}

# MinIO service endpoint for internal use
data "kubernetes_service" "minio" {
  metadata {
    name      = "minio"
    namespace = kubernetes_namespace.minio.metadata[0].name
  }

  depends_on = [helm_release.minio]
}
