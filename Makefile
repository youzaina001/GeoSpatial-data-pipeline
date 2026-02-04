# GeoPipeline Pipeline Makefile
# Common commands for development and deployment

.PHONY: help install test lint format clean deploy destroy start-minikube access

# Default target
help:
	@echo "GeoPipeline Pipeline - Available Commands"
	@echo ""
	@echo "Development:"
	@echo "  make install      Install dependencies"
	@echo "  make test         Run test suite"
	@echo "  make test-cov     Run tests with coverage"
	@echo "  make lint         Run linter"
	@echo "  make format       Format code"
	@echo "  make clean        Clean cache files"
	@echo ""
	@echo "Infrastructure:"
	@echo "  make start        Start Minikube cluster"
	@echo "  make deploy       Deploy to Kubernetes"
	@echo "  make destroy      Tear down infrastructure"
	@echo "  make access       Get service URLs"
	@echo ""
	@echo "DAGs:"
	@echo "  make validate     Validate DAG syntax"

# ============================================================
# Development
# ============================================================

install:
	uv sync --all-extras

test:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ -v --cov=geopipeline --cov-report=term-missing

lint:
	uv run ruff check src/ dags/ tests/

format:
	uv run ruff format src/ dags/ tests/

clean:
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf src/**/__pycache__
	rm -rf tests/**/__pycache__
	rm -rf .coverage
	rm -rf htmlcov
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# ============================================================
# Infrastructure
# ============================================================

start:
	./scripts/start_minikube.sh

deploy:
	./scripts/deploy.sh

destroy:
	cd infra && terraform destroy -auto-approve

access:
	./scripts/access_services.sh

# ============================================================
# DAG Validation
# ============================================================

validate:
	@echo "Validating DAGs..."
	@uv run python -c "\
import sys; \
sys.path.insert(0, 'src'); \
sys.path.insert(0, 'dags'); \
from satellite_ingestion_dag import dag as d1; \
from field_processing_dag import dag as d2; \
print('✓ satellite_ingestion:', list(d1.task_dict.keys())); \
print('✓ field_processing:', list(d2.task_dict.keys())); \
print('All DAGs valid!')"

# ============================================================
# Quick commands
# ============================================================

# Run a specific test file
test-file:
	uv run pytest $(FILE) -v

# Watch tests (requires pytest-watch)
test-watch:
	uv run ptw tests/

# Open Airflow UI (requires minikube running)
airflow-ui:
	minikube service airflow-webserver -n airflow

# Open MinIO Console (requires minikube running)  
minio-ui:
	minikube service minio-console -n minio
