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


class ProductReadError(RuntimeError):
    """A Product read failed and can be reported by the CLI."""


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
    try:
        with duckdb.connect() as con:
            con.read_parquet(glob, hive_partitioning=True).create_view("field_days")
            result = con.execute(sql or DEFAULT_SQL)
            columns = [col[0] for col in result.description]
            rows = result.fetchall()
    except (duckdb.ParserException, duckdb.BinderException, duckdb.CatalogException):
        raise
    except duckdb.Error as query_error:
        # DuckDB can report a damaged page without identifying its file.
        with duckdb.connect() as probe:
            files = probe.execute("SELECT file FROM glob(?)", [glob]).fetchall()
            for (file,) in files:
                try:
                    probe.read_parquet(file, hive_partitioning=False).fetchall()
                except duckdb.Error as part_error:
                    # Attribute the query failure to a part only if it reproduces it.
                    if type(part_error) is type(query_error) and str(part_error) == str(
                        query_error
                    ):
                        raise ProductReadError(
                            f"Could not read Product part {file}: {part_error}"
                        ) from part_error
        if isinstance(query_error, (duckdb.IOException, duckdb.InvalidInputException)):
            raise ProductReadError(str(query_error)) from query_error
        raise
    return _format_table(columns, rows)


def _format_table(columns: list[str], rows: list[tuple[object, ...]]) -> str:
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
