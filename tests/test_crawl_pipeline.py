# Crawl manifest allowlist, timestamp, and DuckDB invariant tests
"""Verify the archive host allowlist, UTC capture timestamps, and DuckDB pre-write checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from geopipeline.crawl.manifest import is_allowed_archive_url, load_manifest
from geopipeline.crawl.matching import PageRow, PassageRow
from geopipeline.crawl.metrics import compute_metrics
from tests.crawl_helpers import write_sample


def test_archive_url_allowlist_enforces_exact_https_host_and_no_userinfo() -> None:
    assert is_allowed_archive_url(
        "https://web.archive.org/web/20251002000737/https://developers.cloudflare.com/ai-crawl-control/",
        "web.archive.org",
    )
    assert not is_allowed_archive_url(
        "http://web.archive.org/web/20251002000737/https://example.com/",
        "web.archive.org",
    )
    assert not is_allowed_archive_url(
        "https://evil.web.archive.org/web/20251002000737/https://example.com/",
        "web.archive.org",
    )
    assert not is_allowed_archive_url(
        "https://user@web.archive.org/web/20251002000737/https://example.com/",
        "web.archive.org",
    )
    assert not is_allowed_archive_url("javascript:alert(1)", "web.archive.org")


def test_manifest_rejects_non_utc_or_malformed_captured_at(tmp_path: Path) -> None:
    manifest_path = write_sample(tmp_path / "sample")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["earlier"][0]["captured_at"] = "2025-10-02T00:07:37+02:00"
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="UTC"):
        load_manifest(manifest_path)


def test_duckdb_prepublish_checks_reject_inconsistent_passage_records() -> None:
    pages = [
        PageRow("https://example.com/a", "compared", None, None),
        PageRow("https://example.com/b", "compared", None, None),
    ]
    # Conflicting word_count for the same passage_id across pages.
    conflicting = [
        PassageRow("https://example.com/a", "pid-1", 1),
        PassageRow("https://example.com/b", "pid-1", 6),
    ]
    with pytest.raises(ValueError, match="word_count"):
        compute_metrics(pages, conflicting)

    # Orphan passage referencing an unknown page.
    orphan = [PassageRow("https://example.com/missing", "pid-2", 3)]
    with pytest.raises(ValueError, match="unknown"):
        compute_metrics(pages, orphan)
