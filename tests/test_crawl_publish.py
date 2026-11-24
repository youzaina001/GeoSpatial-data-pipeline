# Crawl build, promote, and demo tests
"""Verify commit stamping (refuse dirty inputs), candidate run folders, promotion, rollback, and the CLI (ADR 0017)."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from geocrawl.cli import main
from geocrawl import publish
from geocrawl.manifest import CaptureEntry, SampleManifest, is_allowed_archive_url
from geocrawl.publish import BuildFailed, build_run, promote, run_offline_demo
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


def _as_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _as_dict_list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    for item in value:
        assert isinstance(item, dict)
    return value


def _json(path: Path) -> dict[str, object]:
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
    _as_dict_list(data["later"])[0]["sha256"] = sha256_of(later)
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


def test_gitignored_wildcard_filename_is_refused(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("samples/synthetic/earlier/\\*.html\n", encoding="utf-8")
    manifest = write_sample(repo / "samples" / "synthetic")
    commit_all(repo)

    wildcard_file = manifest.parent / "earlier" / "*.html"
    wildcard_file.write_text("<article><p>Untracked wildcard.</p></article>", encoding="utf-8")
    data = _json(manifest)
    earlier = _as_dict_list(data["earlier"])
    earlier[0]["file"] = "earlier/*.html"
    earlier[0]["sha256"] = sha256_of(wildcard_file)
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    commit_all(repo, "reference untracked wildcard filename")

    runs = tmp_path / "runs"
    with pytest.raises(BuildFailed, match="not tracked"):
        build_run(manifest, runs)
    run_dir = _only_run(runs)
    assert not (run_dir / "comparison.json").exists()
    summary = _json(run_dir / "run-summary.json")
    assert summary["status"] == "failed"


def test_processing_runtime_error_writes_failed_run_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, _ = committed_sample(tmp_path / "repo")
    data = _json(manifest)
    _as_dict_list(data["later"])[0]["page_url"] = "https://a.invalid/\ud800"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    commit_all(tmp_path / "repo", "surrogate url")

    runs_real = tmp_path / "runs-real"
    with pytest.raises(BuildFailed, match="UTF-8"):
        build_run(manifest, runs_real)
    real_run = _only_run(runs_real)
    assert not (real_run / "comparison.json").exists()
    real_summary = _json(real_run / "run-summary.json")
    assert real_summary["status"] == "failed"
    assert _as_dict(real_summary["error"])["failed_step"] == "load_manifest"

    # Also verify non-ValueError runtime failures inside DuckDB/matching still emit failed run-summary.json.
    entry = CaptureEntry("https://a.invalid/\ud800", None, "2026-04-01T00:00:00Z", text="<p>One two three.</p>")
    bad_manifest = SampleManifest("demo", "early", "late", None, (), (entry,))
    monkeypatch.setattr(publish, "resolve_clean_commit", lambda _path: "a" * 40)
    monkeypatch.setattr(publish, "load_manifest", lambda _path: (bad_manifest, "b" * 64))
    monkeypatch.setattr(publish, "_check_inputs_tracked", lambda _path, _m: None)

    runs_mock = tmp_path / "runs-mock"
    with pytest.raises(BuildFailed):
        build_run(Path("manifest.json"), runs_mock)
    mock_run = _only_run(runs_mock)
    assert not (mock_run / "comparison.json").exists()
    mock_summary = _json(mock_run / "run-summary.json")
    assert mock_summary["status"] == "failed"
    assert _as_dict(mock_summary["error"])["failed_step"] == "compute_metrics"


def test_unexpected_programming_error_propagates_without_writing_run_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, _ = committed_sample(tmp_path / "repo")

    def boom(_pages: object, _passages: object) -> object:
        raise KeyError("pages")

    monkeypatch.setattr(publish, "compute_metrics", boom)
    runs = tmp_path / "runs"
    with pytest.raises(KeyError, match="pages"):
        build_run(manifest, runs)
    assert not runs.exists()



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
    _as_dict_list(data["later"])[0]["sha256"] = sha256_of(guide)
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
    code = main(["demo", "--output-dir", str(tmp_path), "--fixtures-root", str(REPO / "fixtures")])
    assert code == 0
    head = git(REPO, "rev-parse", "HEAD")

    hw_run = _only_run(tmp_path / "handwritten" / "runs")
    hw = _json(hw_run / "comparison.json")
    assert hw["producing_commit"] == head
    assert hw["summary"] == {"compared_pages": 2, "excluded_pages": 0, "distinct_new_words": 1}
    assert [(p["url"], p["new_words"]) for p in _as_dict_list(hw["pages"])] == [
        ("https://example.invalid/guide", 1),
        ("https://example.invalid/reference", 1),
    ]

    cf = _json(_only_run(tmp_path / "cloudflare-ai-crawl-control" / "runs") / "comparison.json")
    assert cf["archive_host"] == "web.archive.org"
    assert cf["summary"] == {"compared_pages": 13, "excluded_pages": 0, "distinct_new_words": 1694}
    assert _as_dict(cf["attribution"])["license"] == "CC BY 4.0"
    assert not (tmp_path / "handwritten" / "comparison.json").exists()


def test_cli_build_and_promote_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest, head = committed_sample(tmp_path / "repo")
    runs = tmp_path / "runs"
    assert main(["build", "--manifest", str(manifest), "--runs-dir", str(runs)]) == 0
    run_dir = _only_run(runs)
    assert str(run_dir) in capsys.readouterr().out

    site = tmp_path / "site"
    assert main(["promote", str(run_dir), "--publish-dir", str(site)]) == 1
    out = capsys.readouterr()
    assert "first release" in out.out
    assert "--yes" in out.err
    assert not (site / "comparison.json").exists()

    assert main(["promote", str(run_dir), "--publish-dir", str(site), "--yes"]) == 0
    assert _json(site / "comparison.json")["producing_commit"] == head


def test_cli_build_reports_malformed_manifest_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, _ = committed_sample(tmp_path / "repo")
    data = _json(manifest)
    data["later"] = [None]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    commit_all(tmp_path / "repo", "null entry")

    code = main(["build", "--manifest", str(manifest), "--runs-dir", str(tmp_path / "runs")])
    assert code == 1
    assert "JSON object" in capsys.readouterr().err
    assert _json(_only_run(tmp_path / "runs") / "run-summary.json")["status"] == "failed"


def test_cli_build_refuses_dirty_inputs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest, _ = committed_sample(tmp_path / "repo")
    (manifest.parent / "later" / "ok.html").write_text("<p>edited</p>", encoding="utf-8")
    code = main(["build", "--manifest", str(manifest), "--runs-dir", str(tmp_path / "runs")])
    assert code == 1
    assert "uncommitted changes" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["demo", "--commit", "bogus"],
        ["build", "--manifest", "m.json", "--runs-dir", "r", "--commit", "bogus"],
        ["compare", "--manifest", "m.json", "--output", "o.json"],
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
    excluded = [p for p in _as_dict_list(comparison["pages"]) if p["status"] == "comparison_incomplete"]
    assert excluded and all(p["new_words"] is None for p in excluded)
    excluded[0]["new_words"] = "broken"
    (run_dir / "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")

    with pytest.raises(ValueError, match="inconsistent new_words"):
        promote(run_dir, tmp_path / "site", confirm=True)
    assert not (tmp_path / "site" / "comparison.json").exists()


def _tampered_excluded_page(tmp_path: Path, change: Callable[[dict[str, object]], object]) -> Path:
    manifest, _ = committed_sample(tmp_path / "repo", include_failed=True)
    run_dir = build_run(manifest, tmp_path / "runs")
    comparison = _json(run_dir / "comparison.json")
    excluded = [p for p in _as_dict_list(comparison["pages"]) if p["status"] == "comparison_incomplete"]
    change(excluded[0])
    (run_dir / "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")
    return run_dir


def test_promotion_refuses_an_excluded_page_without_new_words(tmp_path: Path) -> None:
    run_dir = _tampered_excluded_page(tmp_path, lambda page: page.pop("new_words"))
    with pytest.raises(ValueError, match="Invalid comparison"):
        promote(run_dir, tmp_path / "site", confirm=True)
    assert not (tmp_path / "site").exists()


def test_promotion_refuses_a_comparison_with_extra_fields(tmp_path: Path) -> None:
    run_dir = _tampered_excluded_page(
        tmp_path, lambda page: page.update(reason="HTTP 503 from Wayback replay")
    )
    with pytest.raises(ValueError, match="Invalid comparison"):
        promote(run_dir, tmp_path / "site", confirm=True)
    assert not (tmp_path / "site").exists()


def _excluded(comparison: dict[str, object]) -> dict[str, object]:
    return next(p for p in _as_dict_list(comparison["pages"]) if p["status"] == "comparison_incomplete")


def _compared(comparison: dict[str, object]) -> dict[str, object]:
    return next(p for p in _as_dict_list(comparison["pages"]) if p["status"] == "compared")


_BAD_VALUES: dict[str, Callable[[dict[str, object]], object]] = {
    "diagnostic in a capture link": lambda c: _excluded(c).update(
        later_capture_url={"reason": "HTTP 503 from Wayback replay"}
    ),
    "capture link off the archive host": lambda c: _compared(c).update(
        later_capture_url="https://evil.example/phish"
    ),
    "null checksum": lambda c: c.update(manifest_sha256=None),
    "diagnostic in the checksum": lambda c: c.update(manifest_sha256={"reason": "HTTP 503"}),
    "non-string archive host": lambda c: c.update(archive_host={"reason": "HTTP 503"}),
    "non-string page url": lambda c: _compared(c).update(url={"reason": "HTTP 503"}),
    "duplicate page url": lambda c: _excluded(c).update(url=_compared(c)["url"]),
    "unhashable status": lambda c: _compared(c).update(status=[]),
    "boolean schema version": lambda c: c.update(schema_version=True),
    "boolean page count": lambda c: _as_dict(c["summary"]).update(excluded_pages=True),
    "more distinct words than page words": lambda c: _as_dict(c["summary"]).update(distinct_new_words=9999),
    "fewer distinct words than one page": lambda c: (
        _compared(c).update(new_words=1),
        _as_dict(c["summary"]).update(distinct_new_words=0),
    ),
    "newline after the checksum": lambda c: c.update(manifest_sha256="b" * 64 + "\n"),
    "newline after the producing commit": lambda c: c.update(producing_commit="a" * 40 + "\n"),
}


@pytest.mark.parametrize("change", list(_BAD_VALUES.values()), ids=list(_BAD_VALUES))
def test_promotion_refuses_malformed_public_values(
    tmp_path: Path, change: Callable[[dict[str, object]], object]
) -> None:
    manifest, _ = committed_sample(tmp_path / "repo", include_failed=True)
    run_dir = build_run(manifest, tmp_path / "runs")
    comparison = _json(run_dir / "comparison.json")
    change(comparison)
    (run_dir / "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid comparison"):
        promote(run_dir, tmp_path / "site", confirm=True)
    assert not (tmp_path / "site").exists()


def test_promotion_refuses_duplicate_json_members(tmp_path: Path) -> None:
    manifest, _ = committed_sample(tmp_path / "repo", include_failed=True)
    run_dir = build_run(manifest, tmp_path / "runs")
    raw = (run_dir / "comparison.json").read_text(encoding="utf-8")
    tampered = raw.replace(
        '"new_words": null', '"new_words": {"reason": "HTTP 503"}, "new_words": null', 1
    )
    assert tampered != raw
    (run_dir / "comparison.json").write_text(tampered, encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid comparison"):
        promote(run_dir, tmp_path / "site", confirm=True)
    assert not (tmp_path / "site").exists()


def _write_explorer_dir(root: Path, files: dict[str, bytes]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def test_confirmed_promotion_bundles_explorer_assets_and_release_manifest(tmp_path: Path) -> None:
    manifest, head = committed_sample(tmp_path / "repo")
    run_dir = build_run(manifest, tmp_path / "runs")
    site = tmp_path / "site"

    preview_result = promote(run_dir, site, confirm=False)
    assert preview_result.published is False
    assert "explorer bundle" in preview_result.preview.lower()
    assert str(REPO / "explorer") in preview_result.preview
    assert not site.exists()

    result = promote(run_dir, site, confirm=True)
    assert result.published is True
    assert "explorer bundle" in result.preview.lower()
    assert str(REPO / "explorer") in result.preview

    for asset in ("index.html", "styles.css", "theme.css", "app.js", "lib.js"):
        expected = (REPO / "explorer" / asset).read_bytes()
        assert (site / asset).read_bytes() == expected
        assert (site / "releases" / head / asset).read_bytes() == expected

    candidate = (run_dir / "comparison.json").read_bytes()
    assert (site / "comparison.json").read_bytes() == candidate
    assert (site / "releases" / head / "comparison.json").read_bytes() == candidate
    assert not (site / ".bundle-manifest.json").exists()
    bundle_manifest = _json(site / "releases" / head / ".bundle-manifest.json")
    assert bundle_manifest == {
        "files": ["app.js", "index.html", "lib.js", "styles.css", "theme.css"]
    }


def test_rollback_restores_release_explorer_assets_and_removes_newer_stale_files(
    tmp_path: Path,
) -> None:
    first, second, first_commit, second_commit = _two_releases(tmp_path)
    v1_explorer = _write_explorer_dir(
        tmp_path / "v1_explorer",
        {"index.html": b"<html>v1</html>\n", "app.js": b"// v1\n"},
    )
    v2_explorer = _write_explorer_dir(
        tmp_path / "v2_explorer",
        {
            "index.html": b"<html>v2</html>\n",
            "app.js": b"// v2\n",
            "extra.js": b"// extra\n",
            "assets/v2.css": b"body{}\n",
        },
    )
    site = tmp_path / "site"

    promote(first, site, confirm=True, explorer_dir=v1_explorer)
    (site / "robots.txt").write_text("User-agent: *\n", encoding="utf-8")
    promote(second, site, confirm=True, explorer_dir=v2_explorer)
    assert (site / "index.html").read_bytes() == b"<html>v2</html>\n"
    assert (site / "extra.js").is_file()
    assert (site / "assets" / "v2.css").is_file()

    rollback = promote(site / "releases" / first_commit, site, confirm=True)
    assert rollback.published is True
    assert (site / "index.html").read_bytes() == b"<html>v1</html>\n"
    assert (site / "app.js").read_bytes() == b"// v1\n"
    assert (site / "comparison.json").read_bytes() == (first / "comparison.json").read_bytes()
    assert not (site / "extra.js").exists()
    assert not (site / "assets").exists()
    assert (site / "robots.txt").read_text(encoding="utf-8") == "User-agent: *\n"
    assert (site / "releases" / first_commit / "comparison.json").is_file()
    assert (site / "releases" / second_commit / "comparison.json").is_file()


def test_re_promoting_same_commit_with_modified_explorer_aborts(tmp_path: Path) -> None:
    manifest, head = committed_sample(tmp_path / "repo")
    first_run = build_run(manifest, tmp_path / "runs")
    second_run = build_run(manifest, tmp_path / "runs")
    v1_explorer = _write_explorer_dir(tmp_path / "v1_explorer", {"index.html": b"<html>v1</html>\n"})
    v2_explorer = _write_explorer_dir(tmp_path / "v2_explorer", {"index.html": b"<html>v2</html>\n"})
    site = tmp_path / "site"

    promote(first_run, site, confirm=True, explorer_dir=v1_explorer)
    before_index = (site / "index.html").read_bytes()
    before_comparison = (site / "comparison.json").read_bytes()

    with pytest.raises(ValueError, match="different release bundle"):
        promote(second_run, site, confirm=True, explorer_dir=v2_explorer)

    assert (site / "index.html").read_bytes() == before_index
    assert (site / "comparison.json").read_bytes() == before_comparison
    assert (site / "releases" / head / "index.html").read_bytes() == before_index


def test_failed_rename_leaves_explorer_and_comparison_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second, _, _ = _two_releases(tmp_path)
    v1_explorer = _write_explorer_dir(
        tmp_path / "v1_explorer",
        {"index.html": b"<html>v1</html>\n", "app.js": b"// v1\n"},
    )
    v2_explorer = _write_explorer_dir(
        tmp_path / "v2_explorer",
        {
            "index.html": b"<html>v2</html>\n",
            "app.js": b"// v2\n",
            "extra.js": b"// extra\n",
            "assets/v2.css": b"body{}\n",
        },
    )
    site = tmp_path / "site"
    promote(first, site, confirm=True, explorer_dir=v1_explorer)
    before_comparison = (site / "comparison.json").read_bytes()
    before_index = (site / "index.html").read_bytes()
    before_app = (site / "app.js").read_bytes()

    real_replace = os.replace

    def failing_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(dst) == site / "comparison.json":
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr(publish.os, "replace", failing_replace)
    with pytest.raises(OSError, match="disk full"):
        promote(second, site, confirm=True, explorer_dir=v2_explorer)

    assert (site / "comparison.json").read_bytes() == before_comparison
    assert (site / "index.html").read_bytes() == before_index
    assert (site / "app.js").read_bytes() == before_app
    assert not (site / "extra.js").exists()
    assert not (site / "assets").exists()
    assert [p for p in site.rglob("*") if p.name.endswith(".tmp")] == []


def test_promote_cli_accepts_explorer_dir_and_rejects_missing_index(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, head = committed_sample(tmp_path / "repo")
    run_dir = build_run(manifest, tmp_path / "runs")
    site = tmp_path / "site"

    missing_index = _write_explorer_dir(tmp_path / "missing_index", {"app.js": b"// no html\n"})
    assert (
        main(["promote", str(run_dir), "--publish-dir", str(site), "--explorer-dir", str(missing_index)])
        == 1
    )
    assert "index.html" in capsys.readouterr().err
    assert not site.exists()

    assert (
        main(
            [
                "promote",
                str(run_dir),
                "--publish-dir",
                str(site),
                "--explorer-dir",
                str(missing_index),
                "--yes",
            ]
        )
        == 1
    )
    assert "index.html" in capsys.readouterr().err
    assert not site.exists()

    symlink_explorer = _write_explorer_dir(tmp_path / "symlink_explorer", {"index.html": b"<html>ok</html>\n"})
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    (symlink_explorer / "leak.txt").symlink_to(secret)
    assert (
        main(
            [
                "promote",
                str(run_dir),
                "--publish-dir",
                str(site),
                "--explorer-dir",
                str(symlink_explorer),
                "--yes",
            ]
        )
        == 1
    )
    assert "symlink" in capsys.readouterr().err.lower()
    assert not site.exists()

    good_explorer = _write_explorer_dir(
        tmp_path / "good_explorer",
        {
            "index.html": b"<html>custom</html>\n",
            "styles.css": b"body { color: #111; }\n",
            ".DS_Store": b"ignored",
        },
    )
    assert (
        main(
            [
                "promote",
                str(run_dir),
                "--publish-dir",
                str(site),
                "--explorer-dir",
                str(good_explorer),
                "--yes",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (site / "index.html").read_bytes() == b"<html>custom</html>\n"
    assert (site / "releases" / head / "styles.css").read_bytes() == b"body { color: #111; }\n"
    assert not (site / ".DS_Store").exists()
    assert not (site / "releases" / head / ".DS_Store").exists()


@pytest.mark.parametrize(
    "reserved_name",
    ["comparison.json", "run-summary.json", "releases", ".bundle-manifest.json"],
)
def test_standalone_explorer_rejects_reserved_root_entries_and_symlinks(
    tmp_path: Path, reserved_name: str
) -> None:
    manifest, _ = committed_sample(tmp_path / "repo")
    run_dir = build_run(manifest, tmp_path / "runs")
    site = tmp_path / "site"

    file_explorer = _write_explorer_dir(
        tmp_path / f"explorer-file-{reserved_name}",
        {"index.html": b"<html>ok</html>\n"},
    )
    reserved_target = file_explorer / reserved_name
    if reserved_name == "releases":
        reserved_target.mkdir()
    else:
        reserved_target.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="reserved"):
        promote(run_dir, site, confirm=True, explorer_dir=file_explorer)
    assert not site.exists()

    symlink_explorer = _write_explorer_dir(
        tmp_path / f"explorer-link-{reserved_name}",
        {"index.html": b"<html>ok</html>\n"},
    )
    (symlink_explorer / reserved_name).symlink_to(tmp_path / "missing-target")
    with pytest.raises(ValueError, match="reserved|symlink"):
        promote(run_dir, site, confirm=True, explorer_dir=symlink_explorer)
    assert not site.exists()


def test_missing_default_explorer_suggests_explorer_dir_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, _ = committed_sample(tmp_path / "repo")
    run_dir = build_run(manifest, tmp_path / "runs")
    monkeypatch.setattr(publish, "DEFAULT_EXPLORER_DIR", tmp_path / "missing-explorer")

    with pytest.raises(ValueError, match="--explorer-dir"):
        promote(run_dir, tmp_path / "site", confirm=False)


def test_rollback_bundle_validation_rejects_broken_symlinks_missing_markers_and_conflicts(
    tmp_path: Path,
) -> None:
    first, second, first_commit, _ = _two_releases(tmp_path)
    site = tmp_path / "site"

    # Broken index.html symlink in a release-like dir must never fall back to DEFAULT_EXPLORER_DIR.
    broken_index_dir = tmp_path / "broken-index"
    broken_index_dir.mkdir()
    (broken_index_dir / "comparison.json").write_bytes((first / "comparison.json").read_bytes())
    (broken_index_dir / "index.html").symlink_to(tmp_path / "does-not-exist.html")
    (broken_index_dir / ".bundle-manifest.json").write_text('{"files": ["index.html"]}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="symlink"):
        promote(broken_index_dir, site, confirm=True)
    assert not site.exists()

    # Manifest without index.html must fail cleanly instead of falling back to DEFAULT_EXPLORER_DIR.
    manifest_only_dir = tmp_path / "manifest-only"
    manifest_only_dir.mkdir()
    (manifest_only_dir / "comparison.json").write_bytes((first / "comparison.json").read_bytes())
    (manifest_only_dir / ".bundle-manifest.json").write_text('{"files": ["index.html"]}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="index\\.html"):
        promote(manifest_only_dir, site, confirm=True)
    assert not site.exists()

    # index.html without .bundle-manifest.json must fail cleanly.
    index_only_dir = tmp_path / "index-only"
    index_only_dir.mkdir()
    (index_only_dir / "comparison.json").write_bytes((first / "comparison.json").read_bytes())
    (index_only_dir / "index.html").write_bytes(b"<html>only</html>\n")
    with pytest.raises(ValueError, match="bundle-manifest"):
        promote(index_only_dir, site, confirm=True)
    assert not site.exists()

    # Release bundle containing run-summary.json, hidden file, empty dir, or mismatched manifest fails.
    for case_name, mutator in (
        ("run-summary", lambda d: (d / "run-summary.json").write_text("{}\n", encoding="utf-8")),
        ("releases", lambda d: (d / "releases").mkdir()),
        ("hidden", lambda d: (d / ".DS_Store").write_text("x", encoding="utf-8")),
        ("empty-dir", lambda d: (d / "empty-sub").mkdir()),
        (
            "mismatched-manifest",
            lambda d: (d / ".bundle-manifest.json").write_text(
                '{"files": ["index.html", "missing.js"]}\n', encoding="utf-8"
            ),
        ),
    ):
        bad_release = tmp_path / f"bad-release-{case_name}"
        bad_release.mkdir()
        (bad_release / "comparison.json").write_bytes((first / "comparison.json").read_bytes())
        (bad_release / "index.html").write_bytes(b"<html>release</html>\n")
        (bad_release / ".bundle-manifest.json").write_text('{"files": ["index.html"]}\n', encoding="utf-8")
        mutator(bad_release)
        with pytest.raises(ValueError):
            promote(bad_release, site, confirm=True)
        assert not site.exists()

    # Passing --explorer-dir with assets conflicting with a release dir fails before modifying target site.
    v1_explorer = _write_explorer_dir(tmp_path / "v1_explorer", {"index.html": b"<html>v1</html>\n"})
    v2_explorer = _write_explorer_dir(tmp_path / "v2_explorer", {"index.html": b"<html>v2</html>\n"})
    promote(first, site, confirm=True, explorer_dir=v1_explorer)
    other_site = tmp_path / "other_site"
    promote(second, other_site, confirm=True, explorer_dir=v2_explorer)
    before = (other_site / "comparison.json").read_bytes()
    with pytest.raises(ValueError, match="different release bundle"):
        promote(site / "releases" / first_commit, other_site, confirm=True, explorer_dir=v2_explorer)
    assert (other_site / "comparison.json").read_bytes() == before
    assert (other_site / "index.html").read_bytes() == b"<html>v2</html>\n"


@pytest.mark.parametrize(
    "bad_entry",
    [
        "",
        ".",
        "./",
        "./index.html",
        "../x",
        "a\\b",
        "/etc/passwd",
        "a//b",
        "a/",
        ".hidden",
        "a/.hidden",
        "releases",
        "releases/abc",
        "comparison.json",
        "run-summary.json",
    ],
)
def test_read_bundle_manifest_rejects_unsafe_paths_and_symlinks(
    tmp_path: Path, bad_entry: str
) -> None:
    manifest_path = tmp_path / ".bundle-manifest.json"
    manifest_path.write_text(json.dumps({"files": [bad_entry]}), encoding="utf-8")
    with pytest.raises(ValueError):
        publish._read_bundle_manifest(manifest_path)

    symlink_manifest = tmp_path / "link.json"
    symlink_manifest.symlink_to(manifest_path)
    with pytest.raises(ValueError, match="symlink"):
        publish._read_bundle_manifest(symlink_manifest)


def test_promote_rejects_symlinks_in_publish_dir(tmp_path: Path) -> None:
    first, second, first_commit, _ = _two_releases(tmp_path)

    # Dangling comparison.json symlink in publish_dir.
    dangling_site = tmp_path / "dangling-site"
    dangling_site.mkdir()
    (dangling_site / "comparison.json").symlink_to(tmp_path / "nonexistent.json")
    with pytest.raises(ValueError, match="symlink"):
        promote(first, dangling_site, confirm=False)
    with pytest.raises(ValueError, match="symlink"):
        promote(first, dangling_site, confirm=True)

    # Symlinked releases/ directory in publish_dir.
    releases_link_site = tmp_path / "releases-link-site"
    releases_link_site.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (releases_link_site / "releases").symlink_to(outside)
    with pytest.raises(ValueError, match="directory|symlink"):
        promote(first, releases_link_site, confirm=True)
    assert list(outside.iterdir()) == []

    # Symlinked prev_manifest inside releases/<prev_commit>/ and symlinked prev_commit dir.
    prev_site = tmp_path / "prev-site"
    v1_explorer = _write_explorer_dir(
        tmp_path / "v1_explorer",
        {"index.html": b"<html>v1</html>\n", "old/stale.js": b"// stale\n"},
    )
    v2_explorer = _write_explorer_dir(
        tmp_path / "v2_explorer",
        {"index.html": b"<html>v2</html>\n", "assets/v2.css": b"body{}\n"},
    )
    promote(first, prev_site, confirm=True, explorer_dir=v1_explorer)
    prev_manifest = prev_site / "releases" / first_commit / ".bundle-manifest.json"
    real_manifest = tmp_path / "real-manifest.json"
    real_manifest.write_bytes(prev_manifest.read_bytes())
    prev_manifest.unlink()
    prev_manifest.symlink_to(real_manifest)
    with pytest.raises(ValueError, match="symlink"):
        promote(second, prev_site, confirm=True, explorer_dir=v2_explorer)
    assert (prev_site / "index.html").read_bytes() == b"<html>v1</html>\n"
    prev_manifest.unlink()
    prev_manifest.write_bytes(real_manifest.read_bytes())

    # Ancestor symlink for obsolete file old/stale.js must be rejected without deleting outside file.
    outside_target = outside / "stale.js"
    outside_target.write_text("keep me", encoding="utf-8")
    shutil.rmtree(prev_site / "old")
    (prev_site / "old").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        promote(second, prev_site, confirm=True, explorer_dir=v2_explorer)
    assert outside_target.read_text(encoding="utf-8") == "keep me"
    (prev_site / "old").unlink()

    # Ancestor symlink for a new target assets/v2.css must be rejected without writing outside.
    (prev_site / "assets").symlink_to(outside)
    with pytest.raises(ValueError, match="directory|symlink"):
        promote(second, prev_site, confirm=True, explorer_dir=v2_explorer)
    assert not (outside / "v2.css").exists()


def test_multi_file_rollback_restores_remaining_files_without_truncation_on_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second, _, _ = _two_releases(tmp_path)
    v1_explorer = _write_explorer_dir(
        tmp_path / "v1_explorer",
        {"index.html": b"<html>v1</html>\n", "app.js": b"// v1\n", "keep.css": b"body{v:1}\n"},
    )
    v2_explorer = _write_explorer_dir(
        tmp_path / "v2_explorer",
        {
            "index.html": b"<html>v2</html>\n",
            "app.js": b"// v2\n",
            "keep.css": b"body{v:2}\n",
            "new.js": b"// new\n",
            "sub/new.css": b"a{}\n",
        },
    )
    site = tmp_path / "site"
    promote(first, site, confirm=True, explorer_dir=v1_explorer)

    real_replace = os.replace
    saw_comparison_failure = False

    def failing_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        nonlocal saw_comparison_failure
        dst_path = Path(dst)
        if dst_path == site / "comparison.json":
            saw_comparison_failure = True
            raise OSError("disk full")
        if saw_comparison_failure and dst_path == site / "index.html":
            raise OSError("restore failed on index")
        real_replace(src, dst)

    monkeypatch.setattr(publish.os, "replace", failing_replace)
    with pytest.raises(OSError, match="restore failed on index"):
        promote(second, site, confirm=True, explorer_dir=v2_explorer)

    # New files and empty subdir removed; other overwritten files restored; failed file not truncated.
    assert not (site / "new.js").exists()
    assert not (site / "sub").exists()
    assert (site / "app.js").read_bytes() == b"// v1\n"
    assert (site / "keep.css").read_bytes() == b"body{v:1}\n"
    assert (site / "index.html").read_bytes() == b"<html>v2</html>\n"
    assert [p for p in site.rglob("*") if p.name.endswith(".tmp")] == []


def test_promoted_active_root_files_have_0644_permissions(tmp_path: Path) -> None:
    manifest, head = committed_sample(tmp_path / "repo")
    run_dir = build_run(manifest, tmp_path / "runs")
    site = tmp_path / "site"
    old_umask = os.umask(0o077)
    try:
        promote(run_dir, site, confirm=True)
    finally:
        os.umask(old_umask)

    for rel in ("comparison.json", "index.html", "styles.css", "app.js", "lib.js"):
        assert stat.S_IMODE((site / rel).stat().st_mode) == 0o644
        assert stat.S_IMODE((site / "releases" / head / rel).stat().st_mode) == 0o644


@pytest.mark.parametrize(
    "bad_char",
    ["\x00", "\x07", "\x1f", "\x7f", "\x80", "\x85", "\x9f"],
)
def test_is_allowed_archive_url_rejects_ascii_and_c1_control_characters(
    tmp_path: Path, bad_char: str
) -> None:
    bad_url = f"https://web.archive.org/web/2025{bad_char}10/page"
    assert is_allowed_archive_url(bad_url, "web.archive.org") is False

    manifest, _ = committed_sample(tmp_path / "repo", include_failed=True)
    run_dir = build_run(manifest, tmp_path / "runs")
    comparison = _json(run_dir / "comparison.json")
    _compared(comparison)["later_capture_url"] = bad_url
    (run_dir / "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")
    with pytest.raises(ValueError, match="disallowed"):
        promote(run_dir, tmp_path / "site", confirm=True)


def test_promotion_refuses_blank_attribution_field(tmp_path: Path) -> None:
    manifest, _ = committed_sample(tmp_path / "repo")
    run_dir = build_run(manifest, tmp_path / "runs")
    comparison = _json(run_dir / "comparison.json")
    comparison["attribution"] = {
        "license": "   ",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "authors": "Example",
        "source_url": "https://example.invalid/src",
        "modifications": "None",
    }
    (run_dir / "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")
    with pytest.raises(ValueError, match="attribution"):
        promote(run_dir, tmp_path / "site", confirm=True)


def test_python_generated_comparison_validates_in_explorer_lib_js(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not found on PATH")

    hw_run, cf_run = run_offline_demo(tmp_path / "demo", fixtures_root=REPO / "fixtures")
    manifest, _ = committed_sample(tmp_path / "repo", include_failed=True)
    incomplete_run = build_run(manifest, tmp_path / "runs")

    lib_uri = (REPO / "explorer" / "lib.js").as_uri()
    script = (
        f'import fs from "node:fs"; '
        f'import {{ validateComparisonPayload }} from {json.dumps(lib_uri)}; '
        f'for (const file of process.argv.slice(1)) {{ '
        f'  const raw = JSON.parse(fs.readFileSync(file, "utf8")); '
        f'  const validated = validateComparisonPayload(raw); '
        f'  if (validated.sample_id !== raw.sample_id) throw new Error("mismatch"); '
        f'}}'
    )
    paths = [
        str(hw_run / "comparison.json"),
        str(cf_run / "comparison.json"),
        str(incomplete_run / "comparison.json"),
    ]
    result = subprocess.run(
        [node, "--input-type=module", "-e", script, *paths],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
