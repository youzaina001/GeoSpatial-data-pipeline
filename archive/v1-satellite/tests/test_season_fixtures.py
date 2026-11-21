# Checked-in season fixtures
"""Field master and Scene catalog are reviewable files, not regenerated from a seed."""

from __future__ import annotations

import json
from pathlib import Path

from geopipeline.pipeline import run

REPO = Path(__file__).resolve().parents[1]
FIELD_MASTER = REPO / "fixtures" / "field_master.geojson"
SCENE_CATALOG = REPO / "fixtures" / "scene_catalog.json"


def test_field_master_has_stable_ids_and_planting_dates() -> None:
    payload = json.loads(FIELD_MASTER.read_text())
    assert payload["name"] == "ile-de-france-sample"
    assert payload["bbox"] == [2.0, 48.0, 3.0, 49.0]
    fields = payload["features"]
    assert 15 <= len(fields) <= 30
    ids = [feat["properties"]["field_id"] for feat in fields]
    assert ids == sorted(set(ids))
    for feat in fields:
        props = feat["properties"]
        assert props["crop_type"]
        assert props["planting_date"]
        assert feat["geometry"]["type"] == "Polygon"


def test_scene_catalog_is_a_fixed_calendar() -> None:
    catalog = json.loads(SCENE_CATALOG.read_text())
    assert 30 <= len(catalog) <= 60
    assert "2024-04-01" in catalog
    assert "2024-05-15" in catalog
    statuses = {entry["status"] for entry in catalog.values()}
    assert statuses == {"present", "cloudy", "missing"}


def test_season_fixtures_backfill_two_days(tmp_path: Path) -> None:
    run(
        "2024-04-01",
        "2024-04-02",
        data_root=tmp_path,
        field_master=FIELD_MASTER,
        scene_catalog=SCENE_CATALOG,
    )
    parts = list((tmp_path / "product" / "field_days").glob("date=*/part.parquet"))
    assert len(parts) == 2
