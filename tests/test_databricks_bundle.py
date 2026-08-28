# Databricks bundle wrap
"""The bundle pushes local Field-days; it does not rebuild them."""

from __future__ import annotations

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
    help_block = _make_target(text, "help")
    assert "databricks" in help_block


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
