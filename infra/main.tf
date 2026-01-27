# Hydrosat Pipeline Infrastructure - Main Configuration
# Terraform configuration for Kubernetes and Helm providers

terraform {
  required_version = ">= 1.0.0"

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.25"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.12"
    }
  }
}

# Kubernetes provider - connects to Minikube
provider "kubernetes" {
  config_path    = var.kubeconfig_path
  config_context = var.kube_context
}

# Helm provider - uses same Kubernetes connection
provider "helm" {
  kubernetes {
    config_path    = var.kubeconfig_path
    config_context = var.kube_context
  }
}

# Create namespaces for our services
resource "kubernetes_namespace" "minio" {
  metadata {
    name = "minio"
    labels = {
      app     = "minio"
      project = "hydrosat"
    }
  }
}

resource "kubernetes_namespace" "airflow" {
  metadata {
    name = "airflow"
    labels = {
      app     = "airflow"
      project = "hydrosat"
    }
  }
}
