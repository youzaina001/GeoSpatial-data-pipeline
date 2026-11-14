# GeoPipeline — local Field-day backfill and query

.PHONY: help install test lint typecheck check format clean run query validate databricks

SEASON_FROM ?= 2024-04-01
SEASON_TO ?= 2024-05-15
DATA_ROOT ?= data

help:
	@echo "GeoPipeline"
	@echo ""
	@echo "  make install    Install the package and development tools"
	@echo "  make test       Run the test suite"
	@echo "  make lint       Ruff check"
	@echo "  make typecheck  Mypy typecheck"
	@echo "  make check      Run test, lint, typecheck, and validate"
	@echo "  make format     Ruff format"
	@echo "  make run        Backfill the fixture season into $(DATA_ROOT)"
	@echo "  make query      DuckDB rollup of the local Product"
	@echo "  make validate   Confirm the DAG file wraps run_date"
	@echo "  make databricks Backfill the fixture season, then databricks bundle deploy"
	@echo "  make clean      Remove caches and local data/"

install:
	uv sync --extra dev --frozen

test:
	uv run --extra dev python -m pytest tests/ -v

test-cov:
	uv run --extra dev python -m pytest tests/ -v --cov=geopipeline --cov-report=term-missing

lint:
	uv run --extra dev ruff check src/ dags/ tests/

typecheck:
	uv run --extra dev mypy src/ dags/ tests/

check: test lint typecheck validate

format:
	uv run --extra dev ruff format src/ dags/ tests/

run:
	uv run geopipeline run --from $(SEASON_FROM) --to $(SEASON_TO) --data-root $(DATA_ROOT)

query:
	uv run geopipeline query --data-root $(DATA_ROOT)

validate:
	@uv run python -c "\
from pathlib import Path; \
text = Path('dags/field_days_dag.py').read_text(); \
assert 'from geopipeline.pipeline import run_scheduled_date' in text; \
assert 'dag_id=\"field_days\"' in text; \
print('field_days DAG wraps geopipeline.pipeline.run_scheduled_date')"

databricks: run
	@command -v databricks >/dev/null 2>&1 || { \
		echo "Databricks CLI not found. Clone-default is: uv sync && make run && make query."; \
		exit 1; \
	}
	@test "$(DATA_ROOT)" = "data" || { \
		echo "make databricks syncs data/product/field_days; leave DATA_ROOT at data."; \
		exit 1; \
	}
	@test -d data/product/field_days || { \
		echo "Field-day Product missing at data/product/field_days. Run make run first."; \
		exit 1; \
	}
	databricks bundle deploy

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov data
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
