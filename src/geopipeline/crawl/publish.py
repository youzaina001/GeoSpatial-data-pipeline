# Atomic crawl comparison publisher
"""Produce validated public comparison.json and maintainer run-summary.json outputs atomically."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from geopipeline.crawl.manifest import load_manifest
from geopipeline.crawl.matching import match_crawl
from geopipeline.crawl.metrics import compute_metrics

SCHEMA_VERSION = 1


def _resolve_producing_commit(repo_hint: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_hint,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return "unknown"


def _write_json_atomic(target_path: Path, payload: dict[str, Any]) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2) + "\n"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target_path)
    except Exception:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
        raise


def _preview_block(comparison: dict[str, Any]) -> dict[str, Any]:
    summary = comparison["summary"]
    return {
        "earlier_window": comparison["earlier_window"],
        "later_window": comparison["later_window"],
        "compared_pages": summary["compared_pages"],
        "excluded_pages": summary["excluded_pages"],
        "distinct_new_words": summary["distinct_new_words"],
        "producing_commit": comparison.get("producing_commit"),
    }


def run_comparison(
    manifest_path: Path,
    output_path: Path,
    *,
    summary_path: Path | None = None,
    current_comparison_path: Path | None = None,
    producing_commit: str | None = None,
) -> dict[str, Any]:
    """Run one crawl comparison end-to-end and atomically publish comparison.json."""
    manifest, manifest_sha256 = load_manifest(manifest_path)
    matched = match_crawl(manifest, manifest_path.parent)
    metrics = compute_metrics(matched.pages, matched.passages)
    commit = producing_commit or _resolve_producing_commit(manifest_path.parent)

    public_payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sample_id": manifest.sample_id,
        "producing_commit": commit,
        "manifest_sha256": manifest_sha256,
        "earlier_window": manifest.earlier_window,
        "later_window": manifest.later_window,
        "archive_host": manifest.archive_host,
        "attribution": (
            None if manifest.attribution is None else manifest.attribution.to_dict()
        ),
        "summary": {
            "compared_pages": metrics.compared_pages,
            "excluded_pages": metrics.excluded_pages,
            "distinct_new_words": metrics.distinct_new_words,
        },
        "pages": [page.to_dict() for page in metrics.pages],
    }

    _write_json_atomic(output_path, public_payload)

    if summary_path is not None:
        current_preview: dict[str, Any] | None = None
        first_release = True
        if current_comparison_path is not None and current_comparison_path.is_file():
            current_data = json.loads(current_comparison_path.read_text(encoding="utf-8"))
            current_preview = _preview_block(current_data)
            first_release = False

        summary_payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "sample_id": manifest.sample_id,
            "first_release": first_release,
            "candidate": _preview_block(public_payload),
            "current": current_preview,
            "excluded_pages": [diag.to_dict() for diag in matched.excluded_diagnostics],
        }
        _write_json_atomic(summary_path, summary_payload)

    return public_payload


def run_offline_demo(
    output_dir: Path,
    *,
    fixtures_root: Path = Path("fixtures"),
    producing_commit: str | None = None,
) -> tuple[Path, Path]:
    """Run the offline demo for both the handwritten check and bundled Cloudflare captures."""
    handwritten_manifest = fixtures_root / "handwritten" / "manifest.json"
    cloudflare_manifest = fixtures_root / "cloudflare-ai-crawl-control" / "manifest.json"

    handwritten_out = output_dir / "handwritten" / "comparison.json"
    handwritten_summary = output_dir / "handwritten" / "run-summary.json"
    hw_result = run_comparison(
        handwritten_manifest,
        handwritten_out,
        summary_path=handwritten_summary,
        producing_commit=producing_commit,
    )
    if hw_result["summary"] != {
        "compared_pages": 2,
        "excluded_pages": 0,
        "distinct_new_words": 1,
    } or [p["new_words"] for p in hw_result["pages"]] != [1, 1]:
        raise ValueError(
            "Handwritten verification failed: expected 1 new word per page and 1 distinct total"
        )

    cloudflare_out = output_dir / "cloudflare-ai-crawl-control" / "comparison.json"
    cloudflare_summary = output_dir / "cloudflare-ai-crawl-control" / "run-summary.json"
    cf_result = run_comparison(
        cloudflare_manifest,
        cloudflare_out,
        summary_path=cloudflare_summary,
        producing_commit=producing_commit,
    )
    if cf_result["summary"]["compared_pages"] < 2 or cf_result["summary"]["distinct_new_words"] <= 0:
        raise ValueError("Cloudflare offline demo produced an invalid comparison result")

    return handwritten_out, cloudflare_out
