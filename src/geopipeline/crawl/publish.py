# Crawl candidate builder and publisher
"""Build candidate runs stamped with a clean commit, then promote one atomically (ADR 0017, ADR 0019)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geopipeline.crawl.manifest import SampleManifest, load_manifest
from geopipeline.crawl.matching import match_crawl
from geopipeline.crawl.metrics import compute_metrics

SCHEMA_VERSION = 1
COMPARISON_FILE = "comparison.json"
SUMMARY_FILE = "run-summary.json"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class BuildFailed(ValueError):
    """A build failed after its run folder was created; the folder holds the failed run summary."""

    def __init__(self, run_dir: Path, failed_step: str, reason: str) -> None:
        super().__init__(f"{failed_step} failed: {reason} (run summary in {run_dir})")
        self.run_dir = run_dir
        self.failed_step = failed_step
        self.reason = reason


class _StepError(Exception):
    def __init__(self, step: str, reason: str) -> None:
        super().__init__(reason)
        self.step = step
        self.reason = reason


# Commit stamping (ADR 0017): refuse dirty or unresolvable inputs.


def _git(folder: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args], cwd=folder, check=False, capture_output=True, text=True
        )
    except OSError as exc:
        raise ValueError(f"Cannot resolve producing commit: git is not available ({exc})") from exc


def resolve_clean_commit(manifest_path: Path) -> str:
    """Return HEAD for the repository holding the manifest, refusing uncommitted inputs."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")
    folder = manifest_path.resolve().parent
    head = _git(folder, "rev-parse", "--verify", "HEAD")
    commit = head.stdout.strip()
    if head.returncode != 0 or not _COMMIT_RE.match(commit):
        raise ValueError(f"Cannot resolve producing commit for {folder}: {head.stderr.strip()}")
    status = _git(folder, "status", "--porcelain", "--untracked-files=all", "--", ".")
    if status.returncode != 0:
        raise ValueError(f"Cannot check {folder} for uncommitted changes: {status.stderr.strip()}")
    if status.stdout.strip():
        changed = ", ".join(line[3:] for line in status.stdout.splitlines())
        raise ValueError(
            f"Refusing to run: uncommitted changes under {folder}: {changed}. Commit them first."
        )
    return commit


def _check_inputs_tracked(manifest_path: Path, manifest: SampleManifest) -> None:
    folder = manifest_path.resolve().parent
    names = [manifest_path.name] + [
        entry.file for entry in (*manifest.earlier, *manifest.later) if entry.file is not None
    ]
    tracked = _git(folder, "ls-files", "--error-unmatch", "--", *names)
    if tracked.returncode != 0:
        raise ValueError(f"Manifest input is not tracked by git: {tracked.stderr.strip()}")


# Candidate computation (in memory; nothing is written here).


@dataclass(frozen=True)
class Candidate:
    manifest_path: Path
    commit: str
    comparison: dict[str, Any]
    excluded_pages: list[dict[str, str]]


def _figures(comparison: dict[str, Any]) -> dict[str, Any]:
    summary = comparison["summary"]
    return {
        "earlier_window": comparison["earlier_window"],
        "later_window": comparison["later_window"],
        "compared_pages": summary["compared_pages"],
        "excluded_pages": summary["excluded_pages"],
        "distinct_new_words": summary["distinct_new_words"],
    }


def _compute(manifest_path: Path, commit: str) -> Candidate:
    step = "load_manifest"
    try:
        manifest, manifest_sha256 = load_manifest(manifest_path)
        step = "verify_tracked_inputs"
        _check_inputs_tracked(manifest_path, manifest)
        step = "match_prose"
        matched = match_crawl(manifest)
        step = "compute_metrics"
        metrics = compute_metrics(matched.pages, matched.passages)
    except (ValueError, OSError) as exc:
        raise _StepError(step, str(exc)) from exc

    comparison: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sample_id": manifest.sample_id,
        "producing_commit": commit,
        "manifest_sha256": manifest_sha256,
        "earlier_window": manifest.earlier_window,
        "later_window": manifest.later_window,
        "archive_host": manifest.archive_host,
        "attribution": None if manifest.attribution is None else manifest.attribution.to_dict(),
        "summary": {
            "compared_pages": metrics.compared_pages,
            "excluded_pages": metrics.excluded_pages,
            "distinct_new_words": metrics.distinct_new_words,
        },
        "pages": [page.to_dict() for page in metrics.pages],
    }
    return Candidate(
        manifest_path=manifest_path,
        commit=commit,
        comparison=comparison,
        excluded_pages=[diag.to_dict() for diag in matched.excluded_diagnostics],
    )


# Writing run folders.


def _render(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def _write_atomic(target_path: Path, data: bytes) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target_path.parent, prefix=f".{target_path.name}.", suffix=".tmp", delete=False
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target_path)
    except BaseException:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
        raise


def _new_run_dir(runs_dir: Path, commit: str, now: Clock) -> tuple[Path, str]:
    started = now().astimezone(UTC)
    run_dir = runs_dir / f"{started:%Y%m%dT%H%M%S.%f}Z-{commit}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir, started.isoformat().replace("+00:00", "Z")


def _summary(
    run_dir: Path,
    started_at: str,
    commit: str,
    candidate: Candidate | None,
    error: _StepError | None,
) -> dict[str, Any]:
    comparison = None if candidate is None else candidate.comparison
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_dir.name,
        "started_at": started_at,
        "status": "succeeded" if error is None else "failed",
        "producing_commit": commit,
        "sample_id": None if comparison is None else comparison["sample_id"],
        "manifest_sha256": None if comparison is None else comparison["manifest_sha256"],
        "candidate": None if comparison is None else _figures(comparison),
        "excluded_pages": [] if candidate is None else candidate.excluded_pages,
        "error": None if error is None else {"failed_step": error.step, "reason": error.reason},
    }


def _write_success(runs_dir: Path, candidate: Candidate, now: Clock) -> Path:
    run_dir, started_at = _new_run_dir(runs_dir, candidate.commit, now)
    _write_atomic(run_dir / COMPARISON_FILE, _render(candidate.comparison))
    _write_atomic(
        run_dir / SUMMARY_FILE, _render(_summary(run_dir, started_at, candidate.commit, candidate, None))
    )
    return run_dir


def build_run(manifest_path: Path, runs_dir: Path, *, now: Clock = _utc_now) -> Path:
    """Build one candidate into runs_dir/<UTC time>-<commit>/; never touches a published file.

    Refuses (raising ValueError, writing nothing) when the inputs are uncommitted or no commit
    resolves. A later processing failure still writes the run folder with a failed run summary
    and raises BuildFailed.
    """
    commit = resolve_clean_commit(manifest_path)
    try:
        candidate = _compute(manifest_path, commit)
    except _StepError as error:
        run_dir, started_at = _new_run_dir(runs_dir, commit, now)
        _write_atomic(run_dir / SUMMARY_FILE, _render(_summary(run_dir, started_at, commit, None, error)))
        raise BuildFailed(run_dir, error.step, error.reason) from error
    return _write_success(runs_dir, candidate, now)


# Promotion.


def _validate_comparison(data: object, source: Path) -> dict[str, Any]:
    def bad(why: str) -> ValueError:
        return ValueError(f"Invalid comparison at {source}: {why}")

    if not isinstance(data, dict):
        raise bad("root must be an object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise bad(f"schema_version must be {SCHEMA_VERSION}")
    commit = data.get("producing_commit")
    if not isinstance(commit, str) or not _COMMIT_RE.match(commit):
        raise bad("producing_commit must be a 40-character commit hash")
    for key in ("sample_id", "earlier_window", "later_window"):
        if not isinstance(data.get(key), str):
            raise bad(f"{key} must be a string")
    summary, pages = data.get("summary"), data.get("pages")
    if not isinstance(summary, dict) or not isinstance(pages, list):
        raise bad("summary must be an object and pages a list")
    counts = {"compared": 0, "comparison_incomplete": 0}
    for page in pages:
        if not isinstance(page, dict) or page.get("status") not in counts:
            raise bad("each page needs a known status")
        words = page.get("new_words")
        if page["status"] == "compared":
            consistent = isinstance(words, int) and not isinstance(words, bool) and words >= 0
        else:
            consistent = words is None
        if not consistent:
            raise bad(f"page {page.get('url')} has an inconsistent new_words")
        counts[page["status"]] += 1
    expected = {"compared_pages": counts["compared"], "excluded_pages": counts["comparison_incomplete"]}
    if {key: summary.get(key) for key in expected} != expected:
        raise bad("summary page counts do not match pages")
    total = summary.get("distinct_new_words")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise bad("distinct_new_words must be a non-negative integer")
    return data


def _read_comparison(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid comparison at {path}: {exc}") from exc
    return raw, _validate_comparison(data, path)


def _preview(candidate: dict[str, Any], current: dict[str, Any] | None, target: Path) -> str:
    rows = [("commit", lambda c: c["producing_commit"][:12])] + [
        (label, lambda c, key=key: str(_figures(c)[key]))
        for label, key in (
            ("earlier window", "earlier_window"),
            ("later window", "later_window"),
            ("pages compared", "compared_pages"),
            ("pages excluded", "excluded_pages"),
            ("distinct new words", "distinct_new_words"),
        )
    ]
    lines = [f"Promote to {target}"]
    if current is None:
        lines.append("Nothing is published yet: this is the first release.")
        lines.append(f"{'':<20}  {'candidate':<14}")
        lines += [f"{label:<20}  {value(candidate):<14}" for label, value in rows]
    else:
        lines.append(f"{'':<20}  {'current':<14}  {'candidate':<14}")
        lines += [f"{label:<20}  {value(current):<14}  {value(candidate):<14}" for label, value in rows]
    return "\n".join(lines)


@dataclass(frozen=True)
class Promotion:
    preview: str
    published: bool


def promote(run_dir: Path, publish_dir: Path, *, confirm: bool) -> Promotion:
    """Show candidate and current figures side by side; with confirm, publish atomically.

    The candidate is kept under publish_dir/releases/<commit>/ first, so promoting a release
    folder is a rollback. Any failure leaves the published comparison untouched.
    """
    source = run_dir / COMPARISON_FILE
    if not source.is_file():
        raise ValueError(f"Run {run_dir} has no comparison to promote (a failed run has none)")
    summary_path = run_dir / SUMMARY_FILE
    if summary_path.is_file():
        try:
            status = json.loads(summary_path.read_text(encoding="utf-8")).get("status")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            raise ValueError(f"Invalid run summary at {summary_path}") from exc
        if status != "succeeded":
            raise ValueError(f"Run {run_dir} did not succeed (status {status!r})")
    candidate_bytes, candidate = _read_comparison(source)

    target = publish_dir / COMPARISON_FILE
    current: dict[str, Any] | None = None
    if target.exists():
        try:
            _, current = _read_comparison(target)
        except (ValueError, OSError) as exc:
            raise ValueError(f"Cannot read the current comparison at {target}: {exc}") from exc
    preview = _preview(candidate, current, target)
    if not confirm:
        return Promotion(preview=preview, published=False)

    release_dir = publish_dir / "releases" / candidate["producing_commit"]
    release_file = release_dir / COMPARISON_FILE
    if release_file.exists():
        if release_file.read_bytes() != candidate_bytes:
            raise ValueError(
                f"{release_dir} already holds a different comparison for commit "
                f"{candidate['producing_commit']}"
            )
    else:
        _write_atomic(release_file, candidate_bytes)
    _write_atomic(target, candidate_bytes)
    return Promotion(preview=preview, published=True)


# Offline demo: candidates only, checks first.


def run_offline_demo(
    output_dir: Path,
    *,
    fixtures_root: Path = Path("fixtures"),
    now: Clock = _utc_now,
) -> tuple[Path, Path]:
    """Build candidates for the handwritten and Cloudflare samples after their checks pass."""
    samples = ("handwritten", "cloudflare-ai-crawl-control")
    manifests = [fixtures_root / name / "manifest.json" for name in samples]
    commits = [resolve_clean_commit(path) for path in manifests]
    candidates: list[Candidate] = []
    for path, commit in zip(manifests, commits, strict=True):
        try:
            candidates.append(_compute(path, commit))
        except _StepError as error:
            raise ValueError(f"{path}: {error.step} failed: {error.reason}") from error

    hw, cf = (candidate.comparison for candidate in candidates)
    if hw["summary"] != {"compared_pages": 2, "excluded_pages": 0, "distinct_new_words": 1} or [
        page["new_words"] for page in hw["pages"]
    ] != [1, 1]:
        raise ValueError(
            "Handwritten verification failed: expected 1 new word per page and 1 distinct total"
        )
    if cf["summary"]["compared_pages"] < 2 or cf["summary"]["distinct_new_words"] <= 0:
        raise ValueError("Cloudflare offline demo produced an invalid comparison result")

    hw_run, cf_run = (
        _write_success(output_dir / name / "runs", candidate, now)
        for name, candidate in zip(samples, candidates, strict=True)
    )
    return hw_run, cf_run
