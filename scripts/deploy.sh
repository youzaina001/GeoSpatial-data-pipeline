#!/bin/bash
# Deploy Hydrosat Pipeline Infrastructure
# This script deploys MinIO and Airflow to Kubernetes using Terraform

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INFRA_DIR="$PROJECT_ROOT/infra"

echo "=========================================="
echo "Deploying Hydrosat Pipeline"
echo "=========================================="

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v terraform &> /dev/null; then
    echo "ERROR: terraform is not installed"
    echo "Install it from: https://developer.hashicorp.com/terraform/install"
    exit 1
fi

if ! command -v kubectl &> /dev/null; then
    echo "ERROR: kubectl is not installed"
    exit 1
fi

if ! kubectl cluster-info &> /dev/null; then
    echo "ERROR: Kubernetes cluster is not running"
    echo "Run: ./scripts/start_minikube.sh"
    exit 1
fi

echo "All prerequisites met!"
echo ""

# Initialize Terraform
echo "Initializing Terraform..."
cd "$INFRA_DIR"
terraform init

# Plan deployment
echo ""
echo "Planning deployment..."
terraform plan -out=tfplan

# Apply deployment
echo ""
read -p "Apply this plan? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Applying Terraform plan..."
    terraform apply tfplan
    rm tfplan
    
    echo ""
    echo "=========================================="
    echo "Deployment Complete!"
    echo "=========================================="
    
    # Show outputs
    terraform output -raw next_steps
    
    echo ""
    echo "Waiting for pods to be ready..."
    echo ""
    
    # Wait for MinIO
    echo "Waiting for MinIO..."
    kubectl wait --for=condition=ready pod -l app=minio -n minio --timeout=300s || true
    
    # Wait for Airflow Postgres to be running
    echo "Waiting for Postgres..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=postgresql -n airflow --timeout=300s || true

    # Wait for all Airflow pods to be scheduled
    echo "Waiting for Airflow pods to be scheduled..."
    kubectl wait --for=condition=podscheduled pod -l release=airflow -n airflow --timeout=300s || true
    
    # Wait for Airflow API server to be ready
    echo "Waiting for Airflow API Server to be ready..."
    kubectl wait --for=condition=ready pod -l component=api-server -n airflow --timeout=300s || true
    
    # Wait for DAG processor to be ready
    echo "Waiting for Airflow DAG Processor to be ready..."
    kubectl wait --for=condition=ready pod -l component=dag-processor -n airflow --timeout=300s || true
    
    echo ""
    echo "Pod status:"
    kubectl get pods -n minio  
    kubectl get pods -n airflow
    
else
    echo "Deployment cancelled"
    rm -f tfplan
    exit 0
fi
