# Crawl build, promote, and demo tests
"""Verify commit stamping (refuse dirty inputs), candidate run folders, promotion, rollback, and the CLI (ADR 0017)."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from geopipeline.cli import main
from geopipeline.crawl import publish
from geopipeline.crawl.publish import BuildFailed, build_run, promote, run_offline_demo
from tests.crawl_helpers import (
    REPO,
    commit_all,
    committed_sample,
    copy_bundled_fixtures,
    git,
    init_repo,
    sha256_of,
    write_sample,
)

RUN_NAME = re.compile(r"^\d{8}T\d{6}\.\d{6}Z-[0-9a-f]{40}$")


def _json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _only_run(runs_dir: Path) -> Path:
    runs = sorted(runs_dir.iterdir())
    assert len(runs) == 1
    return runs[0]


# Decision 1: commit stamp refuses uncommitted or unresolvable inputs.


def test_edited_fixture_with_updated_checksum_is_refused_before_any_run(tmp_path: Path) -> None:
    # Reproduced at 16b27d6: this edit was stamped with HEAD and gave a different total.
    manifest, _ = committed_sample(tmp_path / "repo")
    later = manifest.parent / "later" / "ok.html"
    later.write_text("<article><p>The default timeout is thirty seconds forever now.</p></article>")
    data = _json(manifest)
    data["later"][0]["sha256"] = sha256_of(later)
    manifest.write_text(json.dumps(data), encoding="utf-8")

    runs = tmp_path / "runs"
    with pytest.raises(ValueError, match="uncommitted changes"):
        build_run(manifest, runs)
    assert not runs.exists()


def test_untracked_file_under_the_manifest_folder_is_refused(tmp_path: Path) -> None:
    manifest, _ = committed_sample(tmp_path / "repo")
    (manifest.parent / "notes.txt").write_text("scratch", encoding="utf-8")
    with pytest.raises(ValueError, match="uncommitted changes"):
        build_run(manifest, tmp_path / "runs")


def test_manifest_outside_a_git_repository_is_refused(tmp_path: Path) -> None:
    manifest = write_sample(tmp_path / "loose")
    with pytest.raises(ValueError, match="producing commit"):
        build_run(manifest, tmp_path / "runs")


def test_gitignored_input_named_by_the_manifest_is_refused(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("samples/synthetic/later/\n", encoding="utf-8")
    manifest = write_sample(repo / "samples" / "synthetic")
    commit_all(repo)
    runs = tmp_path / "runs"
    with pytest.raises(BuildFailed, match="not tracked"):
        build_run(manifest, runs)
    summary = _json(_only_run(runs) / "run-summary.json")
    assert summary["status"] == "failed"


def test_clean_build_stamps_head_and_names_the_run_folder(tmp_path: Path) -> None:
    manifest, head = committed_sample(tmp_path / "repo")
    fixed = datetime(2026, 11, 21, 9, 30, 0, 123456, tzinfo=UTC)
    run_dir = build_run(manifest, tmp_path / "runs", now=lambda: fixed)
    assert run_dir.name == f"20261121T093000.123456Z-{head}"
    assert RUN_NAME.match(run_dir.name)
    comparison = _json(run_dir / "comparison.json")
    assert comparison["producing_commit"] == head


# Decision 4: build writes candidates to run folders, including failed runs.


def test_build_writes_candidate_and_run_summary_with_excluded_diagnostics(tmp_path: Path) -> None:
    manifest, head = committed_sample(tmp_path / "repo", include_failed=True)
    run_dir = build_run(manifest, tmp_path / "runs")

    public = _json(run_dir / "comparison.json")
    assert public["summary"] == {"compared_pages": 1, "excluded_pages": 1, "distinct_new_words": 1}
    raw_public = (run_dir / "comparison.json").read_text(encoding="utf-8")
    assert "HTTP 503" not in raw_public
    assert "thirty seconds" not in raw_public

    summary = _json(run_dir / "run-summary.json")
    assert summary["status"] == "succeeded"
    assert summary["run_id"] == run_dir.name
    assert summary["producing_commit"] == head
    assert summary["error"] is None
    assert summary["candidate"] == {
        "earlier_window": "2025-10",
        "later_window": "2026-04",
        "compared_pages": 1,
        "excluded_pages": 1,
        "distinct_new_words": 1,
    }
    assert summary["excluded_pages"] == [
        {
            "url": "https://developers.cloudflare.com/ai-crawl-control/broken/",
            "captured_at": "2025-10-02T00:00:00Z",
            "failed_step": "fetch_archive_capture",
            "reason": "HTTP 503 from Wayback replay",
        }
    ]


def test_each_build_keeps_its_own_run_folder(tmp_path: Path) -> None:
    manifest, _ = committed_sample(tmp_path / "repo")
    first = build_run(manifest, tmp_path / "runs")
    second = build_run(manifest, tmp_path / "runs")
    assert first != second
    assert (first / "run-summary.json").is_file()
    assert (second / "run-summary.json").is_file()


def test_failed_build_records_the_failed_step_and_writes_no_comparison(tmp_path: Path) -> None:
    manifest, _ = committed_sample(tmp_path / "repo", tamper=True)
    runs = tmp_path / "runs"
    with pytest.raises(BuildFailed, match="SHA-256"):
        build_run(manifest, runs)
    run_dir = _only_run(runs)
    assert not (run_dir / "comparison.json").exists()
    summary = _json(run_dir / "run-summary.json")
    assert summary["status"] == "failed"
    assert summary["candidate"] is None
    error = summary["error"]
    assert isinstance(error, dict)
    assert error["failed_step"] == "load_manifest"
    assert "SHA-256" in error["reason"]


# Decision 4: promote previews side by side and publishes only with confirmation.


def _two_releases(tmp_path: Path) -> tuple[Path, Path, str, str]:
    repo = tmp_path / "repo"
    manifest, first_commit = committed_sample(repo)
    first = build_run(manifest, tmp_path / "runs")
    write_sample(manifest.parent, later_text="The default timeout is thirty long seconds.", later_window="2026-05")
    second_commit = commit_all(repo, "refresh")
    second = build_run(manifest, tmp_path / "runs")
    return first, second, first_commit, second_commit


def test_first_promotion_preview_says_first_release_and_publishes_nothing(tmp_path: Path) -> None:
    manifest, _ = committed_sample(tmp_path / "repo")
    run_dir = build_run(manifest, tmp_path / "runs")
    site = tmp_path / "site"

    result = promote(run_dir, site, confirm=False)
    assert result.published is False
    assert "first release" in result.preview
    assert "2025-10" in result.preview and "2026-04" in result.preview
    assert not (site / "comparison.json").exists()


def test_confirmed_promotion_publishes_and_keeps_a_release(tmp_path: Path) -> None:
    manifest, head = committed_sample(tmp_path / "repo")
    run_dir = build_run(manifest, tmp_path / "runs")
    site = tmp_path / "site"

    result = promote(run_dir, site, confirm=True)
    assert result.published is True
    candidate = (run_dir / "comparison.json").read_bytes()
    assert (site / "comparison.json").read_bytes() == candidate
    assert (site / "releases" / head / "comparison.json").read_bytes() == candidate


def test_second_promotion_shows_current_and_candidate_side_by_side(tmp_path: Path) -> None:
    first, second, first_commit, second_commit = _two_releases(tmp_path)
    site = tmp_path / "site"
    promote(first, site, confirm=True)

    preview = promote(second, site, confirm=False).preview
    assert "first release" not in preview
    rows = {line.split("  ")[0].strip(): line for line in preview.splitlines() if "  " in line}
    assert first_commit[:12] in rows["commit"] and second_commit[:12] in rows["commit"]
    assert "2026-04" in rows["later window"] and "2026-05" in rows["later window"]
    for label in ("earlier window", "pages compared", "pages excluded", "distinct new words"):
        assert label in rows
    assert _json(site / "comparison.json")["producing_commit"] == first_commit


def test_rollback_promotes_an_older_release(tmp_path: Path) -> None:
    first, second, first_commit, second_commit = _two_releases(tmp_path)
    site = tmp_path / "site"
    promote(first, site, confirm=True)
    promote(second, site, confirm=True)
    assert _json(site / "comparison.json")["producing_commit"] == second_commit

    promote(site / "releases" / first_commit, site, confirm=True)
    assert _json(site / "comparison.json")["producing_commit"] == first_commit
    assert _json(site / "comparison.json")["later_window"] == "2026-04"


def test_failed_run_cannot_be_promoted(tmp_path: Path) -> None:
    manifest, _ = committed_sample(tmp_path / "repo", tamper=True)
    with pytest.raises(BuildFailed):
        build_run(manifest, tmp_path / "runs")
    with pytest.raises(ValueError, match="no comparison"):
        promote(_only_run(tmp_path / "runs"), tmp_path / "site", confirm=True)
    assert not (tmp_path / "site" / "comparison.json").exists()


def test_corrupt_current_comparison_aborts_promotion_without_overwriting(tmp_path: Path) -> None:
    manifest, _ = committed_sample(tmp_path / "repo")
    run_dir = build_run(manifest, tmp_path / "runs")
    site = tmp_path / "site"
    site.mkdir()
    (site / "comparison.json").write_text("{not-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="current comparison"):
        promote(run_dir, site, confirm=True)
    assert (site / "comparison.json").read_text(encoding="utf-8") == "{not-json\n"


def test_conflicting_release_for_the_same_commit_aborts_promotion(tmp_path: Path) -> None:
    manifest, head = committed_sample(tmp_path / "repo")
    run_dir = build_run(manifest, tmp_path / "runs")
    release = tmp_path / "site" / "releases" / head
    release.mkdir(parents=True)
    (release / "comparison.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="different comparison"):
        promote(run_dir, tmp_path / "site", confirm=True)
    assert not (tmp_path / "site" / "comparison.json").exists()


def test_failed_rename_leaves_the_published_file_and_no_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second, first_commit, _ = _two_releases(tmp_path)
    site = tmp_path / "site"
    promote(first, site, confirm=True)
    before = (site / "comparison.json").read_bytes()

    real_replace = os.replace

    def failing_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(dst) == site / "comparison.json":
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr(publish.os, "replace", failing_replace)
    with pytest.raises(OSError, match="disk full"):
        promote(second, site, confirm=True)
    assert (site / "comparison.json").read_bytes() == before
    assert [p.name for p in site.iterdir() if p.name.endswith(".tmp")] == []


# Demo builds candidates only, after its checks pass.


def test_demo_runs_checks_before_writing_anything(tmp_path: Path) -> None:
    fixtures = copy_bundled_fixtures(tmp_path / "repo")
    guide = fixtures / "handwritten" / "later" / "guide.html"
    guide.write_text("<p>The default timeout is thirty long seconds.</p>\n", encoding="utf-8")
    manifest = fixtures / "handwritten" / "manifest.json"
    data = _json(manifest)
    data["later"][0]["sha256"] = sha256_of(guide)
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    commit_all(tmp_path / "repo", "break the hand calculation")

    out = tmp_path / "out"
    with pytest.raises(ValueError, match="Handwritten verification failed"):
        run_offline_demo(out, fixtures_root=fixtures)
    assert not out.exists()


def test_demo_refuses_dirty_fixtures(tmp_path: Path) -> None:
    fixtures = copy_bundled_fixtures(tmp_path / "repo")
    (fixtures / "cloudflare-ai-crawl-control" / "stray.html").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="uncommitted changes"):
        run_offline_demo(tmp_path / "out", fixtures_root=fixtures)
    assert not (tmp_path / "out").exists()


# CLI paths.


def test_cli_crawl_demo_builds_candidates_for_both_samples(tmp_path: Path) -> None:
    code = main(["crawl", "demo", "--output-dir", str(tmp_path), "--fixtures-root", str(REPO / "fixtures")])
    assert code == 0
    head = git(REPO, "rev-parse", "HEAD")

    hw_run = _only_run(tmp_path / "handwritten" / "runs")
    hw = _json(hw_run / "comparison.json")
    assert hw["producing_commit"] == head
    assert hw["summary"] == {"compared_pages": 2, "excluded_pages": 0, "distinct_new_words": 1}
    assert [(p["url"], p["new_words"]) for p in hw["pages"]] == [
        ("https://example.invalid/guide", 1),
        ("https://example.invalid/reference", 1),
    ]

    cf = _json(_only_run(tmp_path / "cloudflare-ai-crawl-control" / "runs") / "comparison.json")
    assert cf["archive_host"] == "web.archive.org"
    assert cf["summary"] == {"compared_pages": 2, "excluded_pages": 0, "distinct_new_words": 1358}
    assert cf["attribution"]["license"] == "CC BY 4.0"
    assert not (tmp_path / "handwritten" / "comparison.json").exists()


def test_cli_build_and_promote_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest, head = committed_sample(tmp_path / "repo")
    runs = tmp_path / "runs"
    assert main(["crawl", "build", "--manifest", str(manifest), "--runs-dir", str(runs)]) == 0
    run_dir = _only_run(runs)
    assert str(run_dir) in capsys.readouterr().out

    site = tmp_path / "site"
    assert main(["crawl", "promote", str(run_dir), "--publish-dir", str(site)]) == 1
    out = capsys.readouterr()
    assert "first release" in out.out
    assert "--yes" in out.err
    assert not (site / "comparison.json").exists()

    assert main(["crawl", "promote", str(run_dir), "--publish-dir", str(site), "--yes"]) == 0
    assert _json(site / "comparison.json")["producing_commit"] == head


def test_cli_build_reports_malformed_manifest_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, _ = committed_sample(tmp_path / "repo")
    data = _json(manifest)
    data["later"] = [None]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    commit_all(tmp_path / "repo", "null entry")

    code = main(["crawl", "build", "--manifest", str(manifest), "--runs-dir", str(tmp_path / "runs")])
    assert code == 1
    assert "JSON object" in capsys.readouterr().err
    assert _json(_only_run(tmp_path / "runs") / "run-summary.json")["status"] == "failed"


def test_cli_build_refuses_dirty_inputs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest, _ = committed_sample(tmp_path / "repo")
    (manifest.parent / "later" / "ok.html").write_text("<p>edited</p>", encoding="utf-8")
    code = main(["crawl", "build", "--manifest", str(manifest), "--runs-dir", str(tmp_path / "runs")])
    assert code == 1
    assert "uncommitted changes" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["crawl", "demo", "--commit", "bogus"],
        ["crawl", "build", "--manifest", "m.json", "--runs-dir", "r", "--commit", "bogus"],
        ["crawl", "compare", "--manifest", "m.json", "--output", "o.json"],
    ],
)
def test_cli_has_no_commit_override_and_no_compare_command(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == 2


def test_promotion_keeps_maintainer_diagnostics_out_of_the_site(tmp_path: Path) -> None:
    manifest, head = committed_sample(tmp_path / "repo", include_failed=True)
    run_dir = build_run(manifest, tmp_path / "runs")
    site = tmp_path / "site"

    assert promote(run_dir, site, confirm=True).published is True
    assert not (site / "releases" / head / "run-summary.json").exists()
    for path in site.rglob("*"):
        if path.is_file():
            assert "Wayback replay" not in path.read_text(encoding="utf-8"), path


def test_promotion_refuses_an_excluded_page_with_a_word_count(tmp_path: Path) -> None:
    manifest, _ = committed_sample(tmp_path / "repo", include_failed=True)
    run_dir = build_run(manifest, tmp_path / "runs")
    comparison = _json(run_dir / "comparison.json")
    excluded = [p for p in comparison["pages"] if p["status"] == "comparison_incomplete"]
    assert excluded and all(p["new_words"] is None for p in excluded)
    excluded[0]["new_words"] = "broken"
    (run_dir / "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")

    with pytest.raises(ValueError, match="inconsistent new_words"):
        promote(run_dir, tmp_path / "site", confirm=True)
    assert not (tmp_path / "site" / "comparison.json").exists()
