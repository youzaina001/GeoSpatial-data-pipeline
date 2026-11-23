# Crawl manifest contract tests
"""Verify malformed entries, the archive URL allowlist, and extraction from verified bytes (ADR 0019).

Also pin the bundled Cloudflare sample against drift: every manifest entry must hash to
its fixture file, no fixture may be an orphan or one-sided pair (ADR 0016), and no
fixture may carry an absolute Wayback replay URL, a script, a Wayback replay toolbar
marker, or an iframe. Relative replay link targets stay legitimate fixture content."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from geocrawl.manifest import CaptureEntry, SampleManifest, is_allowed_archive_url, load_manifest
from geocrawl.matching import match_crawl


_OMIT = object()


def _write_manifest(
    base: Path,
    later: list[object],
    *,
    earlier: list[object] | None = None,
    attribution: object = _OMIT,
) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    path = base / "manifest.json"
    data: dict[str, object] = {
        "sample_id": "x",
        "earlier_window": "e",
        "later_window": "l",
        "archive_host": None,
        "earlier": earlier or [],
        "later": later,
    }
    if attribution is not _OMIT:
        data["attribution"] = attribution
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _bundled_entry(base: Path, name: str, raw: bytes) -> dict[str, object]:
    base.mkdir(parents=True, exist_ok=True)
    (base / name).write_bytes(raw)
    return {
        "page_url": f"https://a.invalid/{name}",
        "replay_url": None,
        "captured_at": "2026-04-01T00:00:00Z",
        "file": name,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://web.archive.org:notaport/x",
        "https://web.archive.org:99999/x",
        "https://web.archive.org:443/x",
        "https://web.archive.org:8080/x",
        "https://[::1/x",
    ],
)
def test_archive_url_with_port_or_unparsable_netloc_is_disallowed(url: str) -> None:
    assert is_allowed_archive_url(url, "web.archive.org") is False


@pytest.mark.parametrize("entry", [None, "bad", 3, ["page_url"]])
def test_non_object_capture_entry_is_a_clear_manifest_error(tmp_path: Path, entry: object) -> None:
    path = _write_manifest(tmp_path, [entry])
    with pytest.raises(ValueError, match="must be a JSON object"):
        load_manifest(path)


def test_non_object_load_error_and_attribution_are_rejected(tmp_path: Path) -> None:
    entry = {
        "page_url": "https://a.invalid/",
        "replay_url": None,
        "captured_at": "2026-04-01T00:00:00Z",
        "load_error": "boom",
    }
    with pytest.raises(ValueError, match="load_error"):
        load_manifest(_write_manifest(tmp_path / "a", [entry]))

    for index, bad_attribution in enumerate(("CC BY 4.0", ["CC BY 4.0"], 123)):
        attr_dir = tmp_path / f"attr-{index}"
        valid_entry = _bundled_entry(attr_dir, "ok.html", b"<article><p>Body.</p></article>")
        with pytest.raises(ValueError, match="attribution"):
            load_manifest(_write_manifest(attr_dir, [valid_entry], attribution=bad_attribution))
    incomplete_dir = tmp_path / "attr-incomplete"
    incomplete_entry = _bundled_entry(incomplete_dir, "ok.html", b"<article><p>Body.</p></article>")
    with pytest.raises(ValueError, match="license"):
        load_manifest(_write_manifest(incomplete_dir, [incomplete_entry], attribution={}))


def test_manifest_rejects_lone_utf16_surrogates(tmp_path: Path) -> None:
    entry = _bundled_entry(tmp_path, "ok.html", b"<article><p>Body.</p></article>")
    entry["page_url"] = "https://a.invalid/\ud800"
    path = _write_manifest(tmp_path, [entry])
    with pytest.raises(ValueError, match="UTF-8"):
        load_manifest(path)


def test_extraction_uses_the_verified_bytes_not_a_later_reread(tmp_path: Path) -> None:
    earlier = _bundled_entry(tmp_path, "e.html", b"<article><p>The default timeout is ten seconds.</p></article>")
    later = _bundled_entry(tmp_path, "l.html", b"<article><p>The default timeout is ten seconds.</p></article>")
    later["page_url"] = earlier["page_url"]
    path = _write_manifest(tmp_path, [later], earlier=[earlier])

    manifest, _ = load_manifest(path)
    (tmp_path / "l.html").write_text(
        "<article><p>Completely novel replacement wording appears here.</p></article>",
        encoding="utf-8",
    )
    result = match_crawl(manifest)
    assert result.passages == ()


def test_non_utf8_fixture_fails_at_load_with_value_error(tmp_path: Path) -> None:
    entry = _bundled_entry(tmp_path, "bad.html", b"<p>caf\xe9</p>")
    with pytest.raises(ValueError, match="UTF-8"):
        load_manifest(_write_manifest(tmp_path, [entry]))


def test_capture_entry_without_file_or_load_error_is_a_value_error() -> None:
    manifest = SampleManifest(
        "x",
        "e",
        "l",
        None,
        (),
        (CaptureEntry("https://a.invalid/", None, "2026-04-01T00:00:00Z"),),
    )
    with pytest.raises(ValueError, match="neither"):
        match_crawl(manifest)


# Bundled Cloudflare sample drift (ADR 0016, NOTICE.md).


_CLOUDFLARE_SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "cloudflare-ai-crawl-control"


def test_every_cloudflare_manifest_file_exists_and_hashes() -> None:
    manifest_path = _CLOUDFLARE_SAMPLE / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    listed: set[str] = set()
    for window in ("earlier", "later"):
        for entry in data[window]:
            rel = entry["file"]
            path = _CLOUDFLARE_SAMPLE / rel
            assert path.is_file(), f"manifest file is missing on disk: {rel}"
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == entry["sha256"].lower(), f"sha256 mismatch for {rel}: expected {entry['sha256']}, got {digest}"
            assert rel not in listed, f"manifest lists the same file in both windows: {rel}"
            listed.add(rel)
    on_disk = {
        f"{window.name}/{path.name}"
        for window in (_CLOUDFLARE_SAMPLE / "earlier", _CLOUDFLARE_SAMPLE / "later")
        for path in sorted(window.glob("*.html"))
    }
    assert listed == on_disk, f"fixture files and manifest entries drift: {on_disk ^ listed}"


def test_cloudflare_sample_pairs_are_two_sided() -> None:
    data = json.loads((_CLOUDFLARE_SAMPLE / "manifest.json").read_text(encoding="utf-8"))
    earlier_urls = {entry["page_url"] for entry in data["earlier"]}
    later_urls = {entry["page_url"] for entry in data["later"]}
    assert earlier_urls == later_urls, (
        "every Cloudflare sample page must have a capture in both windows: "
        f"earlier only: {sorted(earlier_urls - later_urls)}, later only: {sorted(later_urls - earlier_urls)}"
    )


def test_cloudflare_fixtures_carry_no_wayback_chrome() -> None:
    """Reject absolute Wayback replay URLs, scripts, toolbar markers, and iframes.

    Relative "/web/<timestamp>/" link targets are part of the captured bytes the
    fixtures legitimately keep; the prose extractor ignores href and src values.
    """
    forbidden = ("web.archive.org/web/20", "<script", 'id="wm-', "<iframe")
    for window in ("earlier", "later"):
        for path in sorted((_CLOUDFLARE_SAMPLE / window).glob("*.html")):
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                assert marker not in text, f"{window}/{path.name} contains Wayback chrome: {marker}"
