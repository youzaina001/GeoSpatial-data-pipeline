# Local Product query
"""DuckDB over the Field-day Parquet. No warehouse required."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SQL = """
SELECT
    date,
    status,
    count(*) AS field_days,
    round(avg(ndvi), 4) AS mean_ndvi
FROM field_days
GROUP BY 1, 2
ORDER BY 1, 2
"""


def query_product(data_root: str | Path, sql: str | None = None) -> str:
    """Run SQL against Product Parquet and return a text table."""
    import duckdb

    data_root = Path(data_root)
    parts = list((data_root / "product" / "field_days").glob("date=*/part.parquet"))
    if not parts:
        raise FileNotFoundError(
            f"No Field-day Product under {data_root}/product/field_days. "
            "Run `geopipeline run --from --to` first."
        )

    glob = str(data_root / "product" / "field_days" / "**" / "*.parquet")
    con = duckdb.connect()
    con.read_parquet(glob, hive_partitioning=True).create_view("field_days")
    result = con.execute(sql or DEFAULT_SQL)
    columns = [col[0] for col in result.description]
    rows = result.fetchall()
    return _format_table(columns, rows)


def _format_table(columns: list[str], rows: list[tuple]) -> str:
    rendered = [
        [str(value) if value is not None else "" for value in row] for row in rows
    ]
    widths = [len(col) for col in columns]
    for row in rendered:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    header = "  ".join(col.ljust(widths[i]) for i, col in enumerate(columns))
    rule = "  ".join("-" * widths[i] for i in range(len(columns)))
    body = [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        for row in rendered
    ]
    return "\n".join([header, rule, *body])
