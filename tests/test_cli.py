# CLI backfill
"""`geopipeline run --from --to` is the season backfill."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import rasterio

from geopipeline.cli import main
from tests.helpers import write_tiny_fixtures


def _run_fixture(
    data_root: Path,
    field_master: Path,
    catalog: Path,
    start: str = "2024-04-16",
    end: str = "2024-04-16",
) -> int:
    return main(
        [
            "run",
            "--from",
            start,
            "--to",
            end,
            "--data-root",
            str(data_root),
            "--field-master",
            str(field_master),
            "--scene-catalog",
            str(catalog),
        ]
    )


def test_cli_run_backfills_inclusive_date_range(tmp_path: Path) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    data_root = tmp_path / "data"

    exit_code = main(
        [
            "run",
            "--from",
            "2024-04-15",
            "--to",
            "2024-04-16",
            "--data-root",
            str(data_root),
            "--field-master",
            str(field_master),
            "--scene-catalog",
            str(catalog),
        ]
    )

    assert exit_code == 0
    dates = sorted(
        path.parent.name
        for path in (data_root / "product" / "field_days").glob("date=*/part.parquet")
    )
    assert dates == ["date=2024-04-15", "date=2024-04-16"]
    rows = pq.read_table(
        data_root / "product" / "field_days" / "date=2024-04-16" / "part.parquet"
    ).to_pylist()
    assert {row["field_id"] for row in rows} == {"F001", "F002"}


def test_cli_query_exits_nonzero_when_product_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["query", "--data-root", str(tmp_path / "missing")])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Field-day Product" in captured.err


def test_cli_run_exits_nonzero_on_invalid_iso_date(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "run",
            "--from",
            "not-a-date",
            "--to",
            "2024-04-16",
            "--data-root",
            str(tmp_path / "data"),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "not-a-date" in captured.err


def test_cli_run_exits_nonzero_when_start_is_after_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "run",
            "--from",
            "2024-04-16",
            "--to",
            "2024-04-15",
            "--data-root",
            str(tmp_path / "data"),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "start 2024-04-16 is after end 2024-04-15" in captured.err


def test_cli_run_exits_nonzero_when_input_fixture_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "run",
            "--from",
            "2024-04-15",
            "--to",
            "2024-04-16",
            "--data-root",
            str(tmp_path / "data"),
            "--field-master",
            str(tmp_path / "missing.geojson"),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "missing.geojson" in captured.err


def test_cli_run_rejects_duplicate_field_ids_before_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    payload = json.loads(field_master.read_text())
    payload["features"].append(payload["features"][0])
    field_master.write_text(json.dumps(payload))
    data_root = tmp_path / "data"

    assert _run_fixture(data_root, field_master, catalog) == 1
    assert "duplicate Field ID 'F001'" in capsys.readouterr().err
    assert not data_root.exists()


@pytest.mark.parametrize(
    ("keys", "value", "diagnostic"),
    [
        (("bbox",), [2.4, 48, 2, 48.4], "AOI bbox"),
        (
            ("crs",),
            {"type": "name", "properties": {"name": "EPSG:3857"}},
            "WGS 84",
        ),
        (("features", 0, "properties", "field_id"), "", "field_id"),
        (("features", 0, "properties", "planting_date"), "2024-02-30", "planting_date"),
        (("features", 0, "geometry", "coordinates"), [], "F001"),
        (("features", 0, "geometry", "coordinates", 0, 1, 0), 3, "F001"),
    ],
)
def test_cli_run_rejects_invalid_field_master(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    keys: tuple[str | int, ...],
    value: object,
    diagnostic: str,
) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    payload = json.loads(field_master.read_text())
    changed = payload
    for key in keys[:-1]:
        changed = changed[key]
    changed[keys[-1]] = value
    field_master.write_text(json.dumps(payload))
    data_root = tmp_path / "data"

    assert _run_fixture(data_root, field_master, catalog) == 1
    assert diagnostic in capsys.readouterr().err
    assert not data_root.exists()


@pytest.mark.parametrize(
    ("key", "value"),
    [("status", "invalid"), ("red", -1), ("nir", 65536), ("red", True), ("nir", 3.5)],
)
def test_cli_run_validates_scene_catalog_before_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], key: str, value: object
) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    payload = json.loads(catalog.read_text())
    payload["2024-04-05"][key] = value
    catalog.write_text(json.dumps(payload))
    data_root = tmp_path / "data"

    assert _run_fixture(data_root, field_master, catalog) == 1
    error = capsys.readouterr().err
    assert "2024-04-05" in error
    assert key in error
    assert not data_root.exists()


@pytest.mark.parametrize("failure", ["empty_mask", "zero_denominator"])
def test_cli_run_preserves_prior_product_on_unusable_ndvi(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    data_root = tmp_path / "data"
    assert _run_fixture(data_root, field_master, catalog) == 0
    query = [
        "query",
        "--data-root",
        str(data_root),
        "--sql",
        "SELECT * FROM field_days WHERE date = DATE '2024-04-16' ORDER BY field_id",
    ]
    assert main(query) == 0
    before = capsys.readouterr().out
    assert "observed" in before and "0.5" in before

    if failure == "empty_mask":
        payload = json.loads(field_master.read_text())
        payload["features"][0]["geometry"]["coordinates"] = [
            [
                [2.0001, 48.0001],
                [2.0002, 48.0001],
                [2.0002, 48.0002],
                [2.0001, 48.0002],
                [2.0001, 48.0001],
            ]
        ]
        field_master.write_text(json.dumps(payload))
    else:
        payload = json.loads(catalog.read_text())
        payload["2024-04-16"] = {"status": "present", "red": 0, "nir": 0}
        catalog.write_text(json.dumps(payload))

    assert (
        _run_fixture(data_root, field_master, catalog, "2024-04-15", "2024-04-17") == 1
    )
    error = capsys.readouterr().err
    assert (
        "F001" in error and "2024-04-16" in error and "no usable NDVI pixels" in error
    )
    assert main(query) == 0
    assert capsys.readouterr().out == before
    parts = data_root / "product" / "field_days"
    assert (parts / "date=2024-04-15" / "part.parquet").is_file()
    assert not (parts / "date=2024-04-17").exists()


def test_cli_run_reads_scene_once_for_multiple_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    data_root = tmp_path / "data"
    payload = json.loads(catalog.read_text())
    payload["2024-04-16"] = {"status": "present", "red": 0, "nir": 6000}
    catalog.write_text(json.dumps(payload))
    open_raster = rasterio.open
    reads = []

    def tracked_open(path: Path, mode: str = "r", **kwargs: object) -> object:
        if mode == "r":
            reads.append(path)
        return open_raster(path, mode, **kwargs)

    monkeypatch.setattr(rasterio, "open", tracked_open)
    assert _run_fixture(data_root, field_master, catalog) == 0
    assert len(reads) == 1
    assert (
        main(
            [
                "query",
                "--data-root",
                str(data_root),
                "--sql",
                "SELECT count(*) AS positive_ndvi FROM field_days WHERE ndvi = 1.0",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.splitlines()[-1].strip() == "2"


@pytest.mark.parametrize("damaged_date", ["2024-04-15", "2024-04-16"])
def test_cli_query_names_a_truncated_product_part(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], damaged_date: str
) -> None:
    field_master, catalog = write_tiny_fixtures(tmp_path / "fixtures")
    data_root = tmp_path / "data"
    assert _run_fixture(data_root, field_master, catalog, "2024-04-15") == 0
    part = (
        data_root / "product" / "field_days" / f"date={damaged_date}" / "part.parquet"
    )
    part.write_bytes(part.read_bytes()[:16])

    assert main(["query", "--data-root", str(data_root)]) == 1
    output = capsys.readouterr()
    assert str(part) in output.err
    assert "Traceback" not in output.err
    assert not output.out
