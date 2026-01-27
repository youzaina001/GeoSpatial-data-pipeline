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
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=minio -n minio --timeout=300s || true
    
    # Wait for Airflow Postgres to be running (needed for initialization)
    echo "Waiting for Postgres..."
    kubectl wait --for=condition=ready pod -l component=postgresql -n airflow --timeout=300s || true

    # Wait for Airflow webserver (might be crashing if DB not init)
    # We don't wait for 'ready' yet because it might fail readiness probe without DB
    echo "Waiting for Airflow pods to be scheduled..."
    kubectl wait --for=condition=podscheduled pod -l release=airflow -n airflow --timeout=300s || true
    
    echo ""
    echo "Ensuring Airflow Database is initialized..."
    # Helper to check if DB is initialized (simplistic check: try to list users)
    # If not, run migrate
    
    # We run a temporary pod to check/migrate because the actual pods might be in CrashLoopBackOff
    echo "Running database migrations (this may take a minute)..."
    kubectl run init-db-check -n airflow --rm -i --restart=Never \
      --image=apache/airflow:2.8.1-python3.11 \
      --env="AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql://postgres:postgres@airflow-postgresql.airflow:5432/postgres?sslmode=disable" \
      --command -- airflow db migrate
      
    echo "Creating admin user if not exists..."
    kubectl run create-user-check -n airflow --rm -i --restart=Never \
      --image=apache/airflow:2.8.1-python3.11 \
      --env="AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql://postgres:postgres@airflow-postgresql.airflow:5432/postgres?sslmode=disable" \
      --command -- airflow users create --username admin --firstname Admin --lastname User --role Admin --email admin@example.com --password admin || true

    # Now wait for proper webserver readiness
    echo "Waiting for Airflow Webserver to be ready..."
    kubectl wait --for=condition=ready pod -l component=webserver -n airflow --timeout=300s || true
    
    echo ""
    echo "Pod status:"
    kubectl get pods -n minio  
    kubectl get pods -n airflow
    
else
    echo "Deployment cancelled"
    rm -f tfplan
    exit 0
fi
