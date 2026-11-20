# DuckDB crawl freshness metrics and pre-publish validation
"""Aggregate pages and passages in DuckDB SQL and enforce ADR 0017/0018 integrity invariants."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import duckdb

from geopipeline.crawl.matching import PageRow, PassageRow


@dataclass(frozen=True)
class PageMetric:
    url: str
    status: str
    new_words: int | None
    earlier_capture_url: str | None
    later_capture_url: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "status": self.status,
            "new_words": self.new_words,
            "earlier_capture_url": self.earlier_capture_url,
            "later_capture_url": self.later_capture_url,
        }


@dataclass(frozen=True)
class CrawlMetrics:
    compared_pages: int
    excluded_pages: int
    distinct_new_words: int
    pages: tuple[PageMetric, ...]


def compute_metrics(
    pages: Sequence[PageRow],
    passages: Sequence[PassageRow],
) -> CrawlMetrics:
    """Load pages and passages into DuckDB, verify pre-publish invariants, and compute metrics."""
    with duckdb.connect() as db:
        db.execute(
            """
            CREATE TABLE pages (
                page_url VARCHAR PRIMARY KEY,
                status VARCHAR NOT NULL,
                earlier_capture_url VARCHAR,
                later_capture_url VARCHAR
            )
            """
        )
        db.execute(
            """
            CREATE TABLE passages (
                page_url VARCHAR NOT NULL,
                passage_id VARCHAR NOT NULL,
                word_count INTEGER NOT NULL,
                PRIMARY KEY (page_url, passage_id)
            )
            """
        )

        if pages:
            db.executemany(
                "INSERT INTO pages VALUES (?, ?, ?, ?)",
                [
                    (
                        row.page_url,
                        row.status,
                        row.earlier_capture_url,
                        row.later_capture_url,
                    )
                    for row in pages
                ],
            )
        if passages:
            db.executemany(
                "INSERT INTO passages VALUES (?, ?, ?)",
                [(row.page_url, row.passage_id, row.word_count) for row in passages],
            )

        _verify_invariants(db)

        page_rows = db.execute(
            """
            SELECT
                pg.page_url,
                pg.status,
                CASE
                    WHEN pg.status = 'compared' THEN CAST(coalesce(sum(p.word_count), 0) AS BIGINT)
                    ELSE NULL
                END AS new_words,
                pg.earlier_capture_url,
                pg.later_capture_url
            FROM pages pg
            LEFT JOIN passages p USING (page_url)
            GROUP BY pg.page_url, pg.status, pg.earlier_capture_url, pg.later_capture_url
            ORDER BY pg.page_url
            """
        ).fetchall()

        summary_row = db.execute(
            """
            SELECT
                CAST(coalesce(sum(CASE WHEN status = 'compared' THEN 1 ELSE 0 END), 0) AS BIGINT),
                CAST(coalesce(sum(CASE WHEN status = 'comparison_incomplete' THEN 1 ELSE 0 END), 0) AS BIGINT)
            FROM pages
            """
        ).fetchone()
        assert summary_row is not None
        compared_pages, excluded_pages = int(summary_row[0]), int(summary_row[1])

        distinct_row = db.execute(
            """
            SELECT CAST(coalesce(sum(word_count), 0) AS BIGINT)
            FROM (SELECT DISTINCT passage_id, word_count FROM passages)
            """
        ).fetchone()
        assert distinct_row is not None
        distinct_new_words = int(distinct_row[0])

    page_metrics = tuple(
        PageMetric(
            url=str(url),
            status=str(status),
            new_words=None if new_words is None else int(new_words),
            earlier_capture_url=None if earlier_url is None else str(earlier_url),
            later_capture_url=None if later_url is None else str(later_url),
        )
        for url, status, new_words, earlier_url, later_url in page_rows
    )
    return CrawlMetrics(
        compared_pages=compared_pages,
        excluded_pages=excluded_pages,
        distinct_new_words=distinct_new_words,
        pages=page_metrics,
    )


def _verify_invariants(db: duckdb.DuckDBPyConnection) -> None:
    invalid_status = db.execute(
        "SELECT count(*) FROM pages WHERE status NOT IN ('compared', 'comparison_incomplete')"
    ).fetchone()
    assert invalid_status is not None
    if invalid_status[0] != 0:
        raise ValueError("Invalid page comparison status in pages table")

    orphan_passages = db.execute(
        """
        SELECT count(*)
        FROM passages p
        LEFT JOIN pages pg USING (page_url)
        WHERE pg.page_url IS NULL
        """
    ).fetchone()
    assert orphan_passages is not None
    if orphan_passages[0] != 0:
        raise ValueError("Passages reference unknown page_url not present in pages")

    incomplete_passages = db.execute(
        """
        SELECT count(*)
        FROM passages p
        JOIN pages pg USING (page_url)
        WHERE pg.status != 'compared'
        """
    ).fetchone()
    assert incomplete_passages is not None
    if incomplete_passages[0] != 0:
        raise ValueError("Excluded pages cannot have passage records")

    conflicting_counts = db.execute(
        """
        SELECT count(*)
        FROM (
            SELECT passage_id
            FROM passages
            GROUP BY passage_id
            HAVING count(DISTINCT word_count) > 1
        )
        """
    ).fetchone()
    assert conflicting_counts is not None
    if conflicting_counts[0] != 0:
        raise ValueError("Conflicting word_count values found for the same passage_id")

    non_positive = db.execute(
        "SELECT count(*) FROM passages WHERE word_count <= 0"
    ).fetchone()
    assert non_positive is not None
    if non_positive[0] != 0:
        raise ValueError("Passage word_count must be strictly positive")
