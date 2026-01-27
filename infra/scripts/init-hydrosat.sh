#!/bin/bash
# Init script to create proper Python package structure from flat ConfigMap files
# The ConfigMap mounts files with flat names like "generators__satellite_data.py"
# This script restructures them into proper Python package directories

set -e

HYDROSAT_SOURCE="/opt/airflow/hydrosat-configmap"
HYDROSAT_TARGET="/opt/airflow/hydrosat"

echo "Initializing hydrosat package structure..."

# Create package directories
mkdir -p "${HYDROSAT_TARGET}/generators"
mkdir -p "${HYDROSAT_TARGET}/clients"
mkdir -p "${HYDROSAT_TARGET}/services"

# Copy root-level files
cp "${HYDROSAT_SOURCE}/__init__.py" "${HYDROSAT_TARGET}/__init__.py" 2>/dev/null || true
cp "${HYDROSAT_SOURCE}/config.py" "${HYDROSAT_TARGET}/config.py" 2>/dev/null || true

# Copy generators module files (pattern: generators__*.py -> generators/*.py)
cp "${HYDROSAT_SOURCE}/generators___init__.py" "${HYDROSAT_TARGET}/generators/__init__.py" 2>/dev/null || true
cp "${HYDROSAT_SOURCE}/generators__satellite_data.py" "${HYDROSAT_TARGET}/generators/satellite_data.py" 2>/dev/null || true
cp "${HYDROSAT_SOURCE}/generators__field_data.py" "${HYDROSAT_TARGET}/generators/field_data.py" 2>/dev/null || true

# Copy clients module files (pattern: clients__*.py -> clients/*.py)
cp "${HYDROSAT_SOURCE}/clients___init__.py" "${HYDROSAT_TARGET}/clients/__init__.py" 2>/dev/null || true
cp "${HYDROSAT_SOURCE}/clients__storage.py" "${HYDROSAT_TARGET}/clients/storage.py" 2>/dev/null || true

# Copy services module files (pattern: services__*.py -> services/*.py)
cp "${HYDROSAT_SOURCE}/services___init__.py" "${HYDROSAT_TARGET}/services/__init__.py" 2>/dev/null || true
cp "${HYDROSAT_SOURCE}/services__ingestion.py" "${HYDROSAT_TARGET}/services/ingestion.py" 2>/dev/null || true
cp "${HYDROSAT_SOURCE}/services__processing.py" "${HYDROSAT_TARGET}/services/processing.py" 2>/dev/null || true

echo "Hydrosat package initialized successfully at ${HYDROSAT_TARGET}"
ls -la "${HYDROSAT_TARGET}"
