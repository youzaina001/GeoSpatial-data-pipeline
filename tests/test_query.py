# DuckDB Product query
"""A clone with no cloud can query Field-days from local Parquet."""

from __future__ import annotations

from pathlib import Path

import pytest

from geopipeline.pipeline import run
from geopipeline.query import query_product
from tests.helpers import write_tiny_fixtures


def test_query_rolls_up_field_days_by_date_and_status(tmp_path: Path) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    data_root = tmp_path / "data"
    run(
        "2024-04-15",
        "2024-04-16",
        data_root=data_root,
        field_master=field_master,
        scene_catalog=catalog,
    )

    table = query_product(data_root)
    assert "status" in table
    assert "cloudy" in table
    assert "observed" in table
    assert "0.5" in table


def test_query_accepts_custom_sql(tmp_path: Path) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    data_root = tmp_path / "data"
    run(
        "2024-04-16",
        "2024-04-16",
        data_root=data_root,
        field_master=field_master,
        scene_catalog=catalog,
    )

    table = query_product(
        data_root,
        sql="SELECT count(*) AS n FROM field_days WHERE status = 'observed'",
    )
    assert "2" in table


def test_query_fails_clearly_when_product_is_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Field-day Product"):
        query_product(tmp_path / "empty")
