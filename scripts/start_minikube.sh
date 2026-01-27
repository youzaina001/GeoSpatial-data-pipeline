#!/bin/bash
# Start Minikube for Hydrosat Pipeline
# This script initializes a local Kubernetes cluster

set -e

echo "=========================================="
echo "Starting Minikube for Hydrosat Pipeline"
echo "=========================================="

# Check if minikube is installed
if ! command -v minikube &> /dev/null; then
    echo "ERROR: minikube is not installed"
    echo "Install it from: https://minikube.sigs.k8s.io/docs/start/"
    exit 1
fi

# Check if docker is running
if ! docker info &> /dev/null; then
    echo "ERROR: Docker is not running"
    echo "Please start Docker and try again"
    exit 1
fi

# Configuration
CPUS=${MINIKUBE_CPUS:-2}
MEMORY=${MINIKUBE_MEMORY:-4096}
DISK_SIZE=${MINIKUBE_DISK:-20g}

echo "Configuration:"
echo "CPUs: $CPUS"
echo "Memory: ${MEMORY}MB"
echo "Disk: $DISK_SIZE"
echo ""

# Check if minikube is already running
if minikube status &> /dev/null; then
    echo "Minikube is already running"
    echo "To reset, run: minikube delete && ./start_minikube.sh"
else
    # Start minikube
    echo "Starting Minikube cluster..."
    minikube start \
        --cpus=$CPUS \
        --memory=$MEMORY \
        --disk-size=$DISK_SIZE \
        --driver=docker

    echo "Enabling ingress addon..."
    minikube addons enable ingress
fi

# Verify cluster is running
echo ""
echo "Verifying cluster..."
kubectl cluster-info

echo ""
echo "=========================================="
echo "Minikube is ready!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Deploy infrastructure: ./scripts/deploy.sh"
echo "2. Or manually: cd infra && terraform init && terraform apply"
echo ""
