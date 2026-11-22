# geocrawl: offline crawl freshness pipeline

.PHONY: help install test test-cov test-explorer test-browser lint typecheck check format clean demo preview

DATA_ROOT ?= data
SITE_DIR ?= $(DATA_ROOT)/site
PREVIEW_PORT ?= 8000

help:
	@echo "geocrawl"
	@echo ""
	@echo "  make install       Install the package and development tools"
	@echo "  make test          Run the Python test suite"
	@echo "  make test-explorer Run explorer JS unit tests (requires node)"
	@echo "  make test-browser  Run headless Chrome explorer verification"
	@echo "  make lint          Ruff check"
	@echo "  make typecheck     Mypy typecheck"
	@echo "  make check         Run test, lint, typecheck, and explorer unit tests"
	@echo "  make format        Ruff format"
	@echo "  make demo          Offline crawl freshness demo (handwritten + Cloudflare)"
	@echo "  make preview       Promote latest Cloudflare demo to $(SITE_DIR) and serve locally"
	@echo "  make clean         Remove caches and local data/"

install:
	uv sync --extra dev --frozen

test:
	uv run --extra dev python -m pytest tests/ -v

test-cov:
	uv run --extra dev python -m pytest tests/ -v --cov=geocrawl --cov-report=term-missing

test-explorer:
	@if command -v node >/dev/null 2>&1; then \
		node --test tests/test_explorer.mjs; \
	else \
		echo "node not found on PATH; skipping tests/test_explorer.mjs"; \
	fi

test-browser:
	node tests/browser_check.mjs

lint:
	uv run --extra dev ruff check src/ tests/

typecheck:
	uv run --extra dev mypy src/ tests/

check: test lint typecheck test-explorer

format:
	uv run --extra dev ruff format src/ tests/

demo:
	uv run geocrawl demo --output-dir $(DATA_ROOT)/demo

preview: demo
	@set -e; \
	latest_run=$$(uv run python -c 'import pathlib, sys; runs = sorted(p for p in pathlib.Path(sys.argv[1]).glob("*") if p.is_dir()); print(runs[-1]) if runs else sys.exit(1)' "$(DATA_ROOT)/demo/cloudflare-ai-crawl-control/runs") || { \
		echo "No Cloudflare demo run found under $(DATA_ROOT)/demo/cloudflare-ai-crawl-control/runs" >&2; \
		exit 1; \
	}; \
	uv run geocrawl promote "$$latest_run" --publish-dir "$(SITE_DIR)" --yes && \
	echo "Serving $(SITE_DIR) at http://127.0.0.1:$(PREVIEW_PORT)/" && \
	uv run python -m http.server "$(PREVIEW_PORT)" --bind 127.0.0.1 --directory "$(SITE_DIR)"

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov data
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
