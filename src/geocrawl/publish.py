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
from typing import TypedDict, TypeGuard

from geocrawl.manifest import SampleManifest, is_allowed_archive_url, load_manifest
from geocrawl.matching import PageStatus, match_crawl
from geocrawl.metrics import PageMetricDict, compute_metrics

SCHEMA_VERSION = 1
COMPARISON_FILE = "comparison.json"
SUMMARY_FILE = "run-summary.json"
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")

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
    if head.returncode != 0 or not _COMMIT_RE.fullmatch(commit):
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
    tracked = _git(folder, "--literal-pathspecs", "ls-files", "--error-unmatch", "--", *names)
    if tracked.returncode != 0:
        raise ValueError(f"Manifest input is not tracked by git: {tracked.stderr.strip()}")


# Candidate computation (in memory; nothing is written here).


class ComparisonSummary(TypedDict):
    compared_pages: int
    excluded_pages: int
    distinct_new_words: int


class ComparisonDocument(TypedDict):
    schema_version: int
    sample_id: str
    producing_commit: str
    manifest_sha256: str
    earlier_window: str
    later_window: str
    archive_host: str | None
    attribution: dict[str, str] | None
    summary: ComparisonSummary
    pages: list[PageMetricDict]


class CandidateFigures(TypedDict):
    earlier_window: str
    later_window: str
    compared_pages: int
    excluded_pages: int
    distinct_new_words: int


class RunErrorDict(TypedDict):
    failed_step: str
    reason: str


class RunSummaryDocument(TypedDict):
    schema_version: int
    run_id: str
    started_at: str
    status: str
    producing_commit: str
    sample_id: str | None
    manifest_sha256: str | None
    candidate: CandidateFigures | None
    excluded_pages: list[dict[str, str]]
    error: RunErrorDict | None


@dataclass(frozen=True)
class Candidate:
    manifest_path: Path
    commit: str
    comparison: ComparisonDocument
    excluded_pages: list[dict[str, str]]


def _figures(comparison: ComparisonDocument) -> CandidateFigures:
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
    except Exception as exc:
        raise _StepError(step, str(exc)) from exc

    comparison: ComparisonDocument = {
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


def _render(payload: ComparisonDocument | RunSummaryDocument) -> bytes:
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
) -> RunSummaryDocument:
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


# ADR 0019: the public comparison carries these fields and nothing else.
_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "sample_id",
        "producing_commit",
        "manifest_sha256",
        "earlier_window",
        "later_window",
        "archive_host",
        "attribution",
        "summary",
        "pages",
    }
)
_SUMMARY_KEYS = frozenset({"compared_pages", "excluded_pages", "distinct_new_words"})
_PAGE_KEYS = frozenset({"url", "status", "new_words", "earlier_capture_url", "later_capture_url"})
_ATTRIBUTION_KEYS = frozenset({"license", "license_url", "authors", "source_url", "modifications"})


def _is_count(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_comparison(data: object, source: Path) -> ComparisonDocument:
    def bad(why: str) -> ValueError:
        return ValueError(f"Invalid comparison at {source}: {why}")

    if not isinstance(data, dict):
        raise bad("root must be an object")
    if set(data) != _ROOT_KEYS:
        raise bad(f"root keys must be exactly {sorted(_ROOT_KEYS)}")
    schema = data["schema_version"]
    if not isinstance(schema, int) or isinstance(schema, bool) or schema != SCHEMA_VERSION:
        raise bad(f"schema_version must be {SCHEMA_VERSION}")
    commit = data["producing_commit"]
    if not isinstance(commit, str) or not _COMMIT_RE.fullmatch(commit):
        raise bad("producing_commit must be a 40-character commit hash")
    checksum = data["manifest_sha256"]
    if not isinstance(checksum, str) or not _SHA256_RE.fullmatch(checksum):
        raise bad("manifest_sha256 must be a 64-character SHA-256 hex digest")
    sample_id = data["sample_id"]
    earlier_window = data["earlier_window"]
    later_window = data["later_window"]
    for key, value in (
        ("sample_id", sample_id),
        ("earlier_window", earlier_window),
        ("later_window", later_window),
    ):
        if not isinstance(value, str):
            raise bad(f"{key} must be a string")
    assert isinstance(sample_id, str) and isinstance(earlier_window, str) and isinstance(later_window, str)
    archive_host = data["archive_host"]
    if archive_host is not None and (not isinstance(archive_host, str) or not archive_host.strip()):
        raise bad("archive_host must be a non-empty string or null")
    summary, pages = data["summary"], data["pages"]
    if not isinstance(summary, dict) or not isinstance(pages, list):
        raise bad("summary must be an object and pages a list")
    if set(summary) != _SUMMARY_KEYS:
        raise bad(f"summary keys must be exactly {sorted(_SUMMARY_KEYS)}")
    raw_attribution = data["attribution"]
    validated_attribution: dict[str, str] | None = None
    if raw_attribution is not None:
        if not isinstance(raw_attribution, dict) or set(raw_attribution) != _ATTRIBUTION_KEYS:
            raise bad("attribution must be null or an object of the attribution strings")
        validated_attribution = {}
        for attr_key in _ATTRIBUTION_KEYS:
            attr_value = raw_attribution[attr_key]
            if not isinstance(attr_value, str):
                raise bad("attribution must be null or an object of the attribution strings")
            validated_attribution[attr_key] = attr_value

    counts = {"compared": 0, "comparison_incomplete": 0}
    urls: set[str] = set()
    page_words = 0
    largest_page = 0
    validated_pages: list[PageMetricDict] = []
    for page in pages:
        if not isinstance(page, dict) or set(page) != _PAGE_KEYS:
            raise bad(f"each page must be an object with exactly {sorted(_PAGE_KEYS)}")
        url, raw_status = page["url"], page["status"]
        if not isinstance(url, str) or not url or url in urls:
            raise bad("each page needs its own non-empty url string")
        urls.add(url)
        if raw_status == "compared":
            page_status: PageStatus = "compared"
        elif raw_status == "comparison_incomplete":
            page_status = "comparison_incomplete"
        else:
            raise bad(f"page {url} needs a known status")

        links: dict[str, str | None] = {}
        for key in ("earlier_capture_url", "later_capture_url"):
            link = page[key]
            if link is None:
                links[key] = None
                continue
            if not isinstance(link, str) or (
                archive_host is not None and not is_allowed_archive_url(link, archive_host)
            ):
                raise bad(f"page {url} has a disallowed {key}")
            links[key] = link

        raw_words = page["new_words"]
        if page_status == "compared":
            if not _is_count(raw_words):
                raise bad(f"page {url} has an inconsistent new_words")
            new_words: int | None = raw_words
            page_words += raw_words
            largest_page = max(largest_page, raw_words)
        else:
            if raw_words is not None:
                raise bad(f"page {url} has an inconsistent new_words")
            new_words = None
        counts[page_status] += 1
        validated_pages.append(
            {
                "url": url,
                "status": page_status,
                "new_words": new_words,
                "earlier_capture_url": links["earlier_capture_url"],
                "later_capture_url": links["later_capture_url"],
            }
        )

    compared_count = summary["compared_pages"]
    excluded_count = summary["excluded_pages"]
    if not _is_count(compared_count) or compared_count != counts["compared"]:
        raise bad("summary page counts do not match pages")
    if not _is_count(excluded_count) or excluded_count != counts["comparison_incomplete"]:
        raise bad("summary page counts do not match pages")
    total = summary["distinct_new_words"]
    if not _is_count(total) or not largest_page <= total <= page_words:
        raise bad("distinct_new_words must lie between the largest page count and the page totals")

    return {
        "schema_version": schema,
        "sample_id": sample_id,
        "producing_commit": commit,
        "manifest_sha256": checksum,
        "earlier_window": earlier_window,
        "later_window": later_window,
        "archive_host": archive_host,
        "attribution": validated_attribution,
        "summary": {
            "compared_pages": compared_count,
            "excluded_pages": excluded_count,
            "distinct_new_words": total,
        },
        "pages": validated_pages,
    }


def _reject_duplicate_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate member {key!r}")
        result[key] = value
    return result


def _read_comparison(path: Path) -> tuple[bytes, ComparisonDocument]:
    raw = path.read_bytes()
    try:
        data: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_members)
    except ValueError as exc:
        raise ValueError(f"Invalid comparison at {path}: {exc}") from exc
    return raw, _validate_comparison(data, path)


def _preview(
    candidate: ComparisonDocument, current: ComparisonDocument | None, target: Path
) -> str:
    rows: list[tuple[str, Callable[[ComparisonDocument], str]]] = [
        ("commit", lambda c: c["producing_commit"][:12]),
        ("earlier window", lambda c: c["earlier_window"]),
        ("later window", lambda c: c["later_window"]),
        ("pages compared", lambda c: str(c["summary"]["compared_pages"])),
        ("pages excluded", lambda c: str(c["summary"]["excluded_pages"])),
        ("distinct new words", lambda c: str(c["summary"]["distinct_new_words"])),
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
    current: ComparisonDocument | None = None
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
