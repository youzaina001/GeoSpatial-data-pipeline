# GeoPipeline: offline crawl freshness pipeline

.PHONY: help install test test-cov lint typecheck check format clean crawl-demo

DATA_ROOT ?= data

help:
	@echo "GeoPipeline"
	@echo ""
	@echo "  make install    Install the package and development tools"
	@echo "  make test       Run the test suite"
	@echo "  make lint       Ruff check"
	@echo "  make typecheck  Mypy typecheck"
	@echo "  make check      Run test, lint, and typecheck"
	@echo "  make format     Ruff format"
	@echo "  make crawl-demo Offline crawl freshness demo (handwritten + Cloudflare)"
	@echo "  make clean      Remove caches and local data/"

install:
	uv sync --extra dev --frozen

test:
	uv run --extra dev python -m pytest tests/ -v

test-cov:
	uv run --extra dev python -m pytest tests/ -v --cov=geopipeline --cov-report=term-missing

lint:
	uv run --extra dev ruff check src/ tests/

typecheck:
	uv run --extra dev mypy src/ tests/

check: test lint typecheck

format:
	uv run --extra dev ruff format src/ tests/

crawl-demo:
	uv run geopipeline crawl demo --output-dir $(DATA_ROOT)/crawl-demo

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov data
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
