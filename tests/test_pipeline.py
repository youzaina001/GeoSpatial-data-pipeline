# Field-day pipeline — tests at the run() seam
"""Backfill writes one Field-day row per Field per date, with glossary status order."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from geopipeline.pipeline import run, run_scheduled_date
from tests.helpers import write_tiny_fixtures


def _read_field_days(data_root: Path) -> list[dict]:
    paths = sorted((data_root / "product" / "field_days").glob("date=*/part.parquet"))
    rows: list[dict] = []
    for path in paths:
        rows.extend(pq.read_table(path).to_pylist())
    return rows


def _status(rows: list[dict], field_id: str, day: str) -> str:
    day_d = date.fromisoformat(day)
    matches = [
        row for row in rows if row["field_id"] == field_id and row["date"] == day_d
    ]
    assert len(matches) == 1, (field_id, day, matches)
    return matches[0]["status"]


def test_field_day_status_follows_glossary_order(tmp_path: Path) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    data_root = tmp_path / "data"

    run(
        "2024-04-05",
        "2024-04-16",
        data_root=data_root,
        field_master=field_master,
        scene_catalog=catalog,
    )

    rows = _read_field_days(data_root)

    # F001 is planted 2024-04-10. Ineligible beats a present Scene.
    assert _status(rows, "F001", "2024-04-05") == "ineligible"
    # After planting, catalog missing (and dates absent from the catalog) are missing-scene.
    assert _status(rows, "F001", "2024-04-12") == "missing-scene"
    assert _status(rows, "F001", "2024-04-15") == "cloudy"
    assert _status(rows, "F001", "2024-04-16") == "observed"

    # F002 was planted in March, so Scene status applies on every date in range.
    assert _status(rows, "F002", "2024-04-05") == "observed"
    assert _status(rows, "F002", "2024-04-12") == "missing-scene"
    assert _status(rows, "F002", "2024-04-15") == "cloudy"
    assert _status(rows, "F002", "2024-04-16") == "observed"
    # A calendar day with no catalog entry is a missing Scene.
    assert _status(rows, "F002", "2024-04-06") == "missing-scene"


def test_backfill_writes_one_row_per_field_per_calendar_date(tmp_path: Path) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    data_root = tmp_path / "data"

    run(
        "2024-04-05",
        "2024-04-16",
        data_root=data_root,
        field_master=field_master,
        scene_catalog=catalog,
    )

    rows = _read_field_days(data_root)
    dates = {row["date"] for row in rows}
    assert dates == {date(2024, 4, d) for d in range(5, 17)}
    assert len(rows) == 12 * 2
    keys = [(row["field_id"], row["date"]) for row in rows]
    assert len(keys) == len(set(keys))
    for day in dates:
        part = (
            data_root
            / "product"
            / "field_days"
            / f"date={day.isoformat()}"
            / "part.parquet"
        )
        assert part.is_file()


def test_rerun_overwrites_field_days_for_that_date(tmp_path: Path) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    data_root = tmp_path / "data"

    run(
        "2024-04-12",
        "2024-04-12",
        data_root=data_root,
        field_master=field_master,
        scene_catalog=catalog,
    )
    assert _status(_read_field_days(data_root), "F002", "2024-04-12") == "missing-scene"

    updated = json.loads(catalog.read_text())
    updated["2024-04-12"] = {"status": "present", "red": 2000, "nir": 6000}
    catalog.write_text(json.dumps(updated))

    run(
        "2024-04-12",
        "2024-04-12",
        data_root=data_root,
        field_master=field_master,
        scene_catalog=catalog,
    )
    rows = _read_field_days(data_root)
    assert _status(rows, "F002", "2024-04-12") == "observed"
    assert len(rows) == 2


def test_landing_holds_field_master_and_scenes(tmp_path: Path) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    data_root = tmp_path / "data"

    run(
        "2024-04-12",
        "2024-04-16",
        data_root=data_root,
        field_master=field_master,
        scene_catalog=catalog,
    )

    copied = data_root / "landing" / "fields" / "field_master.geojson"
    assert json.loads(copied.read_text())["name"] == "tiny-aoi"

    missing = data_root / "landing" / "scenes" / "date=2024-04-12"
    cloudy = data_root / "landing" / "scenes" / "date=2024-04-15"
    present = data_root / "landing" / "scenes" / "date=2024-04-16"

    assert (missing / "scene.json").is_file()
    assert not (missing / "scene.tif").exists()
    assert json.loads((missing / "scene.json").read_text())["status"] == "missing"

    assert (cloudy / "scene.tif").is_file()
    assert json.loads((cloudy / "scene.json").read_text())["status"] == "cloudy"

    assert (present / "scene.tif").is_file()
    assert json.loads((present / "scene.json").read_text())["status"] == "present"


def _row(rows: list[dict], field_id: str, day: str) -> dict:
    day_d = date.fromisoformat(day)
    matches = [
        item for item in rows if item["field_id"] == field_id and item["date"] == day_d
    ]
    assert len(matches) == 1, (field_id, day, matches)
    return matches[0]


def test_only_observed_field_days_have_ndvi(tmp_path: Path) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    data_root = tmp_path / "data"

    run(
        "2024-04-05",
        "2024-04-16",
        data_root=data_root,
        field_master=field_master,
        scene_catalog=catalog,
    )
    rows = _read_field_days(data_root)

    # (6000 - 2000) / (6000 + 2000) = 0.5 — worked example from the catalog bands.
    observed = _row(rows, "F002", "2024-04-16")
    assert observed["status"] == "observed"
    assert observed["ndvi"] == pytest.approx(0.5)

    assert _row(rows, "F001", "2024-04-05")["ndvi"] is None
    assert _row(rows, "F002", "2024-04-12")["ndvi"] is None
    assert _row(rows, "F002", "2024-04-15")["ndvi"] is None


def test_scheduled_date_uses_the_same_pipeline_as_the_cli(tmp_path: Path) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    data_root = tmp_path / "data"

    run_scheduled_date(
        "2024-04-16",
        environ={
            "GEOPIPELINE_DATA_ROOT": str(data_root),
            "GEOPIPELINE_FIELD_MASTER": str(field_master),
            "GEOPIPELINE_SCENE_CATALOG": str(catalog),
        },
    )

    rows = _read_field_days(data_root)
    assert _status(rows, "F002", "2024-04-16") == "observed"
    assert _row(rows, "F002", "2024-04-16")["ndvi"] == pytest.approx(0.5)
