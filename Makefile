# GeoPipeline — local Field-day backfill and query

.PHONY: help install test lint format clean run query validate

SEASON_FROM ?= 2024-04-01
SEASON_TO ?= 2024-05-15
DATA_ROOT ?= data

help:
	@echo "GeoPipeline"
	@echo ""
	@echo "  make install    Install the package (uv sync --all-extras)"
	@echo "  make test       Run the test suite"
	@echo "  make lint       Ruff check"
	@echo "  make format     Ruff format"
	@echo "  make run        Backfill the fixture season into $(DATA_ROOT)"
	@echo "  make query      DuckDB rollup of the local Product"
	@echo "  make validate   Confirm the DAG file wraps run_date"
	@echo "  make clean      Remove caches and local data/"

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

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov data
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
