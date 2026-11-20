# End-to-end crawl freshness pipeline tests
"""Verify manifest SHA-256 checks, exclusions, allowlist, DuckDB validation, atomicity, and CLI demo."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from geopipeline.cli import main
from geopipeline.crawl.manifest import is_allowed_archive_url
from geopipeline.crawl.matching import PageRow, PassageRow
from geopipeline.crawl.metrics import compute_metrics
from geopipeline.crawl.publish import run_comparison

REPO = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_sample(base: Path, *, tamper: bool = False, include_failed: bool = False) -> Path:
    earlier_dir = base / "earlier"
    later_dir = base / "later"
    earlier_dir.mkdir(parents=True)
    later_dir.mkdir(parents=True)

    e_ok = earlier_dir / "ok.html"
    l_ok = later_dir / "ok.html"
    e_ok.write_text("<article><p>The default timeout is ten seconds.</p></article>", encoding="utf-8")
    l_ok.write_text("<article><p>The default timeout is thirty seconds.</p></article>", encoding="utf-8")

    earlier_entries: list[dict[str, object]] = [
        {
            "page_url": "https://developers.cloudflare.com/ai-crawl-control/",
            "replay_url": "https://web.archive.org/web/20251002000737/https://developers.cloudflare.com/ai-crawl-control/",
            "captured_at": "2025-10-02T00:07:37Z",
            "file": "earlier/ok.html",
            "sha256": "0" * 64 if tamper else _sha256(e_ok),
        }
    ]
    later_entries: list[dict[str, object]] = [
        {
            "page_url": "https://developers.cloudflare.com/ai-crawl-control/",
            "replay_url": "https://web.archive.org/web/20260429223141/https://developers.cloudflare.com/ai-crawl-control/",
            "captured_at": "2026-04-29T22:31:41Z",
            "file": "later/ok.html",
            "sha256": _sha256(l_ok),
        }
    ]

    if include_failed:
        l_bad = later_dir / "missing.html"
        l_bad.write_text("<article><p>New page text.</p></article>", encoding="utf-8")
        earlier_entries.append(
            {
                "page_url": "https://developers.cloudflare.com/ai-crawl-control/broken/",
                "replay_url": "https://web.archive.org/web/20251002000000/https://developers.cloudflare.com/ai-crawl-control/broken/",
                "captured_at": "2025-10-02T00:00:00Z",
                "load_error": {
                    "failed_step": "fetch_archive_capture",
                    "reason": "HTTP 503 from Wayback replay",
                },
            }
        )
        later_entries.append(
            {
                "page_url": "https://developers.cloudflare.com/ai-crawl-control/broken/",
                "replay_url": "https://web.archive.org/web/20260429000000/https://developers.cloudflare.com/ai-crawl-control/broken/",
                "captured_at": "2026-04-29T00:00:00Z",
                "file": "later/missing.html",
                "sha256": _sha256(l_bad),
            }
        )

    manifest = {
        "sample_id": "synthetic-check",
        "earlier_window": "2025-10",
        "later_window": "2026-04",
        "archive_host": "web.archive.org",
        "earlier": earlier_entries,
        "later": later_entries,
    }
    manifest_path = base / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


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


def test_tampered_checksum_fails_without_overwriting_existing_comparison(tmp_path: Path) -> None:
    manifest_path = _write_sample(tmp_path / "sample", tamper=True)
    output_path = tmp_path / "comparison.json"
    sentinel = '{"preserved": true}\n'
    output_path.write_text(sentinel, encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        run_comparison(manifest_path, output_path, producing_commit="a" * 40)

    assert output_path.read_text(encoding="utf-8") == sentinel


def test_comparison_incomplete_excluded_from_public_totals_and_logged_in_run_summary(
    tmp_path: Path,
) -> None:
    manifest_path = _write_sample(tmp_path / "sample", include_failed=True)
    output_path = tmp_path / "comparison.json"
    summary_path = tmp_path / "run-summary.json"

    run_comparison(
        manifest_path,
        output_path,
        summary_path=summary_path,
        producing_commit="b" * 40,
    )

    public = json.loads(output_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert public["producing_commit"] == "b" * 40
    assert public["summary"] == {
        "compared_pages": 1,
        "excluded_pages": 1,
        "distinct_new_words": 1,
    }
    by_url = {row["url"]: row for row in public["pages"]}
    assert by_url["https://developers.cloudflare.com/ai-crawl-control/"]["status"] == "compared"
    assert by_url["https://developers.cloudflare.com/ai-crawl-control/"]["new_words"] == 1
    assert (
        by_url["https://developers.cloudflare.com/ai-crawl-control/broken/"]["status"]
        == "comparison_incomplete"
    )
    assert (
        by_url["https://developers.cloudflare.com/ai-crawl-control/broken/"]["new_words"]
        is None
    )
    # Public payload must not contain passage text, scraped HTML, or internal error strings.
    raw_public = output_path.read_text(encoding="utf-8")
    assert "HTTP 503" not in raw_public
    assert "thirty seconds" not in raw_public

    assert summary["first_release"] is True
    assert summary["excluded_pages"] == [
        {
            "url": "https://developers.cloudflare.com/ai-crawl-control/broken/",
            "captured_at": "2025-10-02T00:00:00Z",
            "failed_step": "fetch_archive_capture",
            "reason": "HTTP 503 from Wayback replay",
        }
    ]


def test_run_summary_includes_side_by_side_current_comparison(tmp_path: Path) -> None:
    manifest_path = _write_sample(tmp_path / "sample")
    current_path = tmp_path / "current.json"
    output_path = tmp_path / "candidate.json"
    summary_path = tmp_path / "run-summary.json"

    run_comparison(manifest_path, current_path, producing_commit="c" * 40)
    run_comparison(
        manifest_path,
        output_path,
        summary_path=summary_path,
        current_comparison_path=current_path,
        producing_commit="d" * 40,
    )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["first_release"] is False
    assert summary["current"]["distinct_new_words"] == 1
    assert summary["candidate"]["distinct_new_words"] == 1


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


def test_cli_crawl_demo_runs_offline_for_cloudflare_and_handwritten(tmp_path: Path) -> None:
    code = main(
        [
            "crawl",
            "demo",
            "--output-dir",
            str(tmp_path),
            "--fixtures-root",
            str(REPO / "fixtures"),
        ]
    )
    assert code == 0

    hw = json.loads((tmp_path / "handwritten" / "comparison.json").read_text(encoding="utf-8"))
    assert hw["sample_id"] == "handwritten"
    assert hw["summary"] == {
        "compared_pages": 2,
        "excluded_pages": 0,
        "distinct_new_words": 1,
    }
    assert [(p["url"], p["new_words"]) for p in hw["pages"]] == [
        ("https://example.invalid/guide", 1),
        ("https://example.invalid/reference", 1),
    ]

    cf = json.loads(
        (tmp_path / "cloudflare-ai-crawl-control" / "comparison.json").read_text(encoding="utf-8")
    )
    assert cf["sample_id"] == "cloudflare-ai-crawl-control"
    assert cf["archive_host"] == "web.archive.org"
    assert cf["earlier_window"] == "2025-10"
    assert cf["later_window"] == "2026-04"
    assert cf["summary"]["compared_pages"] == 2
    assert cf["summary"]["excluded_pages"] == 0
    assert cf["summary"]["distinct_new_words"] > 0
    assert all(p["new_words"] > 0 for p in cf["pages"])
    assert cf["attribution"]["license"] == "CC BY 4.0"
