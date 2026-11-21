# Supported repository surface
"""The supported build is the crawl freshness pipeline; the satellite example lives in archive/v1-satellite/."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SATELLITE_ARCHIVE = REPO / "archive" / "v1-satellite"


def test_satellite_dependencies_are_not_installed() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    extras = project.get("optional-dependencies", {})
    names = " ".join([*project["dependencies"], *(dep for group in extras.values() for dep in group)])
    for retired in ("rasterio", "pyarrow", "numpy"):
        assert retired not in names
    assert "airflow" not in extras


def test_satellite_sources_live_in_the_archive() -> None:
    for retired in (
        "src/geopipeline/pipeline.py",
        "src/geopipeline/ndvi.py",
        "src/geopipeline/query.py",
        "dags",
        "databricks",
        "databricks.yml",
        "fixtures/field_master.geojson",
        "fixtures/scene_catalog.json",
    ):
        assert not (REPO / retired).exists(), retired
        assert (SATELLITE_ARCHIVE / retired).exists(), retired
    assert (SATELLITE_ARCHIVE / "README.md").is_file()


def test_makefile_and_ci_run_only_the_crawl_pipeline() -> None:
    makefile = (REPO / "Makefile").read_text()
    targets = {line.split(":", 1)[0] for line in makefile.splitlines() if line and not line[0].isspace() and ":" in line}
    for retired in ("run", "query", "databricks", "test-airflow", "validate"):
        assert retired not in targets, retired
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    assert "airflow" not in ci.lower()
    assert "make run" not in ci


def test_project_is_named_geocrawl() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    assert project["name"] == "geocrawl"
    assert project["scripts"] == {"geocrawl": "geocrawl.cli:main"}
    assert (REPO / "src" / "geocrawl" / "publish.py").is_file()
    assert not (REPO / "src" / "geopipeline").exists()
