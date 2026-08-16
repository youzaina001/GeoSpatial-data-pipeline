#!/bin/bash
# Access Services
# This script provides URLs for accessing Airflow and MinIO

set -e

echo "=========================================="
echo "GeoPipeline Pipeline - Service Access"
echo "=========================================="
echo ""

# Check if cluster is running
if ! kubectl cluster-info &> /dev/null; then
    echo "ERROR: Kubernetes cluster is not running"
    exit 1
fi

echo "Opening services..."
echo ""

# Function to get service URL in background
get_service_url() {
    local service=$1
    local namespace=$2
    local url
    
    # Try to get URL with a 2 second timeout
    # If using docker driver on linux, this will hang, so we want to time out
    if url=$(timeout 2s minikube service "$service" -n "$namespace" --url 2>/dev/null); then
        echo "$url"
    else
        echo "Run: minikube service $service -n $namespace"
    fi
}

echo "MinIO Console:"
echo "URL: $(get_service_url minio-console minio 2>/dev/null || echo 'Run: minikube service minio-console -n minio')"
echo "Credentials: minioadmin / minioadmin"
echo ""

echo "Airflow Webserver:"
echo "URL: $(get_service_url airflow-api-server airflow 2>/dev/null || echo 'Run: minikube service airflow-api-server -n airflow')"
echo "Credentials: admin / admin"
echo ""

echo "Quick access commands:"
echo "minikube service minio-console -n minio"
echo "minikube service airflow-api-server -n airflow"
echo ""
