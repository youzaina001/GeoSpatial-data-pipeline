# Databricks bundle wrap
"""The bundle pushes local Field-days; it does not rebuild them."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUNDLE_PATH = REPO / "databricks.yml"
MAKEFILE_PATH = REPO / "Makefile"
NOTEBOOK_PATH = REPO / "databricks" / "query_field_days.py"
SQL_PATH = REPO / "databricks" / "query_field_days.sql"


def test_bundle_syncs_notebook_sql_and_local_product() -> None:
    text = BUNDLE_PATH.read_text()
    assert "query_field_days.py" in text
    assert "query_field_days.sql" in text
    assert "data/product/field_days" in text


def test_bundle_does_not_recompute_rasters() -> None:
    bundle = BUNDLE_PATH.read_text()
    notebook = NOTEBOOK_PATH.read_text()
    sql = SQL_PATH.read_text()
    for source in (bundle, notebook, sql):
        assert "geopipeline.pipeline" not in source
        assert "geopipeline.ndvi" not in source
        assert "run_scheduled_date" not in source
        assert "rasterio" not in source
    assert "spark.read.parquet" in notebook
    assert "landing" not in bundle.lower()
    assert "jobs:" not in bundle
    assert "host:" not in bundle


def test_notebook_and_sql_product_path_matches_bundle_sync() -> None:
    bundle = BUNDLE_PATH.read_text()
    notebook = NOTEBOOK_PATH.read_text()
    sql = SQL_PATH.read_text()
    assert "file_path: /Users/${workspace.current_user.userName}/geopipeline" in bundle
    assert "geopipeline/data/product/field_days" in notebook
    assert "geopipeline/data/product/field_days" in sql


def test_make_databricks_backfills_then_deploys() -> None:
    text = MAKEFILE_PATH.read_text()
    databricks_block = _make_target(text, "databricks")
    assert "run" in databricks_block.splitlines()[0]
    assert "databricks bundle deploy" in databricks_block
    assert "product/field_days" in databricks_block
    assert 'DATA_ROOT)" = "data"' in databricks_block
    help_block = _make_target(text, "help")
    assert "databricks" in help_block


def test_product_parquet_stays_gitignored() -> None:
    text = (REPO / ".gitignore").read_text()
    assert "*.parquet" in text
    assert "/data/" in text
    assert _is_git_ignored("data/product/field_days")
    assert _is_git_ignored("data/product/field_days/date=2024-04-16/part.parquet")


def test_context_and_adrs_are_not_gitignored() -> None:
    gitignore_lines = (REPO / ".gitignore").read_text().splitlines()
    assert "CONTEXT.md" not in gitignore_lines
    assert "!docs/adr/" in gitignore_lines
    assert "!docs/adr/**" in gitignore_lines
    assert (REPO / "CONTEXT.md").is_file()
    adrs = sorted((REPO / "docs" / "adr").glob("*.md"))
    assert len(adrs) >= 15
    assert not _is_git_ignored("CONTEXT.md")
    assert not _is_git_ignored("docs/adr/0001-portfolio-not-operations.md")
    assert _is_git_ignored("docs/agents/issue-tracker.md")


def _is_git_ignored(relpath: str) -> bool:
    """True when gitignore excludes relpath. A matching `!` pattern is not ignored."""
    result = subprocess.run(
        ["git", "check-ignore", "-v", "--no-index", relpath],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 1:
        return False
    assert result.returncode == 0, (
        f"git check-ignore failed for {relpath}: {result.stderr.strip()}"
    )
    meta = result.stdout.splitlines()[-1].split("\t", 1)[0]
    pattern = meta.split(":", 2)[2]
    return not pattern.startswith("!")


def test_clone_default_stays_local() -> None:
    text = MAKEFILE_PATH.read_text()
    help_block = _make_target(text, "help")
    assert "make run" in help_block or "run" in help_block
    assert "make query" in help_block or "query" in help_block
    run_block = _make_target(text, "run")
    query_block = _make_target(text, "query")
    assert "geopipeline run" in run_block
    assert "geopipeline query" in query_block
    assert "databricks bundle" not in run_block
    assert "databricks bundle" not in query_block


def test_ci_and_makefile_wire_typecheck_and_validate() -> None:
    pyproject = (REPO / "pyproject.toml").read_text()
    makefile = MAKEFILE_PATH.read_text()
    ci_workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text()

    assert '"mypy>=' in pyproject
    typecheck_block = _make_target(makefile, "typecheck")
    assert (
        "mypy src/ dags/ tests/" in typecheck_block
        or "mypy src/ tests/" in typecheck_block
    )
    check_block = _make_target(makefile, "check")
    for required in ("test", "lint", "typecheck", "validate"):
        assert required in check_block.splitlines()[0]
    assert "make check" in ci_workflow


def _make_target(makefile: str, name: str) -> str:
    lines = makefile.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith(f"{name}:"):
            start = i
            break
    assert start is not None, f"make target {name} missing"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j] and not lines[j].startswith("\t") and not lines[j].startswith(" "):
            if not lines[j].startswith("#"):
                end = j
                break
    return "\n".join(lines[start:end])
