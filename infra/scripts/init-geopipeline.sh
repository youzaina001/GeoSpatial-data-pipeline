#!/bin/bash
# Init script to create proper Python package structure from flat ConfigMap files
# The ConfigMap mounts files with flat names like "generators__satellite_data.py"
# This script restructures them into proper Python package directories

set -e

GEOPIPELINE_SOURCE="/opt/airflow/geopipeline-configmap"
GEOPIPELINE_TARGET="/opt/airflow/geopipeline"

echo "Initializing geopipeline package structure..."

# Create package directories
mkdir -p "${GEOPIPELINE_TARGET}/generators"
mkdir -p "${GEOPIPELINE_TARGET}/clients"
mkdir -p "${GEOPIPELINE_TARGET}/services"

# Copy root-level files
cp "${GEOPIPELINE_SOURCE}/__init__.py" "${GEOPIPELINE_TARGET}/__init__.py" 2>/dev/null || true
cp "${GEOPIPELINE_SOURCE}/config.py" "${GEOPIPELINE_TARGET}/config.py" 2>/dev/null || true

# Copy generators module files (pattern: generators__*.py -> generators/*.py)
cp "${GEOPIPELINE_SOURCE}/generators___init__.py" "${GEOPIPELINE_TARGET}/generators/__init__.py" 2>/dev/null || true
cp "${GEOPIPELINE_SOURCE}/generators__satellite_data.py" "${GEOPIPELINE_TARGET}/generators/satellite_data.py" 2>/dev/null || true
cp "${GEOPIPELINE_SOURCE}/generators__field_data.py" "${GEOPIPELINE_TARGET}/generators/field_data.py" 2>/dev/null || true

# Copy clients module files (pattern: clients__*.py -> clients/*.py)
cp "${GEOPIPELINE_SOURCE}/clients___init__.py" "${GEOPIPELINE_TARGET}/clients/__init__.py" 2>/dev/null || true
cp "${GEOPIPELINE_SOURCE}/clients__storage.py" "${GEOPIPELINE_TARGET}/clients/storage.py" 2>/dev/null || true

# Copy services module files (pattern: services__*.py -> services/*.py)
cp "${GEOPIPELINE_SOURCE}/services___init__.py" "${GEOPIPELINE_TARGET}/services/__init__.py" 2>/dev/null || true
cp "${GEOPIPELINE_SOURCE}/services__ingestion.py" "${GEOPIPELINE_TARGET}/services/ingestion.py" 2>/dev/null || true
cp "${GEOPIPELINE_SOURCE}/services__processing.py" "${GEOPIPELINE_TARGET}/services/processing.py" 2>/dev/null || true

echo "GeoPipeline package initialized successfully at ${GEOPIPELINE_TARGET}"
ls -la "${GEOPIPELINE_TARGET}"
