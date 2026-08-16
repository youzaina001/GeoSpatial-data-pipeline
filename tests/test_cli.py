# CLI backfill
"""`geopipeline run --from --to` is the season backfill."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from geopipeline.cli import main
from tests.helpers import write_tiny_fixtures


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
    tmp_path: Path, capsys
) -> None:
    exit_code = main(["query", "--data-root", str(tmp_path / "missing")])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Field-day Product" in captured.err
