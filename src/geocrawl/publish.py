# Crawl candidate builder and publisher
"""Build candidate runs stamped with a clean commit, then promote one atomically (ADR 0017, ADR 0019)."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Iterable
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
BUNDLE_MANIFEST_FILE = ".bundle-manifest.json"
DEFAULT_EXPLORER_DIR: Path = Path(__file__).resolve().parents[2] / "explorer"
_RESERVED_EXPLORER_ROOT_ENTRIES = frozenset(
    {COMPARISON_FILE, SUMMARY_FILE, "releases", BUNDLE_MANIFEST_FILE}
)
_RELEASE_SKIPPED_ROOT_ENTRIES = frozenset({COMPARISON_FILE, BUNDLE_MANIFEST_FILE})
_RELEASE_FORBIDDEN_ROOT_ENTRIES = frozenset({SUMMARY_FILE, "releases"})
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


def _write_atomic(target_path: Path, data: bytes, *, mode: int = 0o644) -> None:
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
        os.chmod(tmp_path, mode)
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
            if not isinstance(attr_value, str) or not attr_value.strip():
                raise bad("attribution must be null or an object of non-empty attribution strings")
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
    candidate: ComparisonDocument,
    current: ComparisonDocument | None,
    target: Path,
    explorer_source: Path,
    explorer_files: dict[Path, bytes],
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
    lines.append(f"explorer bundle: {explorer_source} ({len(explorer_files)} files)")
    return "\n".join(lines)


def _has_release_marker(run_dir: Path) -> bool:
    index_path = run_dir / "index.html"
    manifest_path = run_dir / BUNDLE_MANIFEST_FILE
    return (
        index_path.is_symlink()
        or index_path.exists()
        or manifest_path.is_symlink()
        or manifest_path.exists()
    )


def _resolve_explorer_source(run_dir: Path, explorer_dir: Path | None) -> Path:
    """Choose the explorer asset directory for promotion or rollback."""
    if explorer_dir is not None:
        return explorer_dir
    if _has_release_marker(run_dir):
        return run_dir
    return DEFAULT_EXPLORER_DIR


def _walk_explorer_dir(
    current_dir: Path, rel_dir: Path, files: dict[Path, bytes]
) -> None:
    for entry in sorted(current_dir.iterdir(), key=lambda p: p.name):
        if rel_dir == Path() and entry.name in _RESERVED_EXPLORER_ROOT_ENTRIES:
            raise ValueError(f"Explorer bundle cannot contain reserved entry: {entry}")
        if entry.name.startswith("."):
            if entry.is_symlink():
                raise ValueError(f"Explorer bundle cannot contain symlinks: {entry}")
            continue
        if entry.is_symlink():
            raise ValueError(f"Explorer bundle cannot contain symlinks: {entry}")
        rel = rel_dir / entry.name
        if entry.is_dir():
            _walk_explorer_dir(entry, rel, files)
        elif entry.is_file():
            files[rel] = entry.read_bytes()
        else:
            raise ValueError(f"Unsupported file type in explorer bundle: {entry}")


def _collect_explorer_files(source_dir: Path, *, is_default: bool = False) -> dict[Path, bytes]:
    """Read standalone explorer assets, refusing symlinks, reserved names, and missing index.html."""
    if source_dir.is_symlink() or not source_dir.is_dir():
        if is_default or source_dir == DEFAULT_EXPLORER_DIR:
            raise ValueError(
                f"Default explorer directory not found: {source_dir}. "
                "Pass --explorer-dir if running outside the repository checkout."
            )
        raise ValueError(f"Explorer directory not found: {source_dir}")
    index_path = source_dir / "index.html"
    if index_path.is_symlink():
        raise ValueError(f"Explorer bundle cannot contain symlinks: {index_path}")
    if not index_path.is_file():
        raise ValueError(f"Explorer directory {source_dir} is missing index.html")
    files: dict[Path, bytes] = {}
    _walk_explorer_dir(source_dir, Path(), files)
    index_bytes = files.get(Path("index.html"))
    if index_bytes is None or not index_bytes.strip():
        raise ValueError(f"Explorer bundle at {source_dir} must contain a non-empty index.html")
    return {rel: files[rel] for rel in sorted(files, key=lambda p: p.as_posix())}


def _walk_release_bundle_dir(
    current_dir: Path, rel_dir: Path, files: dict[Path, bytes]
) -> None:
    entries = sorted(current_dir.iterdir(), key=lambda p: p.name)
    if rel_dir != Path() and not entries:
        raise ValueError(f"Release bundle cannot contain empty directory: {current_dir}")
    for entry in entries:
        if entry.is_symlink():
            raise ValueError(f"Release bundle cannot contain symlinks: {entry}")
        if rel_dir == Path():
            if entry.name in _RELEASE_FORBIDDEN_ROOT_ENTRIES:
                raise ValueError(f"Release bundle cannot contain reserved entry: {entry}")
            if entry.name in _RELEASE_SKIPPED_ROOT_ENTRIES:
                if not entry.is_file():
                    raise ValueError(f"Release bundle metadata must be a regular file: {entry}")
                continue
        if entry.name.startswith("."):
            raise ValueError(f"Release bundle cannot contain hidden entry: {entry}")
        rel = rel_dir / entry.name
        if entry.is_dir():
            _walk_release_bundle_dir(entry, rel, files)
        elif entry.is_file():
            files[rel] = entry.read_bytes()
        else:
            raise ValueError(f"Unsupported file type in release bundle: {entry}")


def _collect_release_bundle_files(release_dir: Path) -> dict[Path, bytes]:
    """Read and validate a release rollback bundle against its .bundle-manifest.json."""
    if release_dir.is_symlink() or not release_dir.is_dir():
        raise ValueError(f"Release directory not found: {release_dir}")
    index_path = release_dir / "index.html"
    if index_path.is_symlink():
        raise ValueError(f"Release bundle cannot contain symlinks: {index_path}")
    if not index_path.is_file():
        raise ValueError(f"Release bundle {release_dir} is missing index.html")
    manifest_path = release_dir / BUNDLE_MANIFEST_FILE
    if manifest_path.is_symlink():
        raise ValueError(f"Release bundle cannot contain symlinks: {manifest_path}")
    if not manifest_path.is_file():
        raise ValueError(f"Release bundle {release_dir} is missing {BUNDLE_MANIFEST_FILE}")

    files: dict[Path, bytes] = {}
    _walk_release_bundle_dir(release_dir, Path(), files)
    index_bytes = files.get(Path("index.html"))
    if index_bytes is None or not index_bytes.strip():
        raise ValueError(f"Release bundle at {release_dir} must contain a non-empty index.html")

    recorded_entries = _read_bundle_manifest(manifest_path)
    if set(files) != recorded_entries:
        raise ValueError(
            f"Release bundle at {release_dir} does not match {BUNDLE_MANIFEST_FILE}"
        )
    return {rel: files[rel] for rel in sorted(files, key=lambda p: p.as_posix())}


def _render_bundle_manifest(explorer_files: dict[Path, bytes]) -> bytes:
    payload = {"files": sorted(rel.as_posix() for rel in explorer_files)}
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def _read_bundle_manifest(manifest_path: Path) -> set[Path]:
    """Read the managed relative explorer paths recorded for an earlier release."""
    if manifest_path.is_symlink():
        raise ValueError(f"Bundle manifest cannot be a symlink: {manifest_path}")
    if not manifest_path.exists():
        return set()
    if not manifest_path.is_file():
        raise ValueError(f"Invalid bundle manifest at {manifest_path}")
    try:
        payload: object = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_members,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"Invalid bundle manifest at {manifest_path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise ValueError(f"Invalid bundle manifest at {manifest_path}")
    managed: set[Path] = set()
    for item in payload["files"]:
        if not isinstance(item, str) or not item or "\\" in item or item.startswith("/"):
            raise ValueError(f"Unsafe bundle manifest entry {item!r} at {manifest_path}")
        raw_parts = item.split("/")
        if not raw_parts or any(part in ("", ".", "..") or part.startswith(".") for part in raw_parts):
            raise ValueError(f"Unsafe bundle manifest entry {item!r} at {manifest_path}")
        rel = Path(*raw_parts)
        if (
            not rel.parts
            or rel.is_absolute()
            or rel.parts[0] == "releases"
            or rel in {Path(COMPARISON_FILE), Path(SUMMARY_FILE), Path(BUNDLE_MANIFEST_FILE)}
        ):
            raise ValueError(f"Unsafe bundle manifest entry {item!r} at {manifest_path}")
        managed.add(rel)
    return managed


def _collect_release_entries(
    current_dir: Path,
    rel_dir: Path,
    files: dict[Path, bytes],
    release_dir: Path,
    commit: str,
) -> None:
    entries = sorted(current_dir.iterdir(), key=lambda p: p.name)
    if rel_dir != Path() and not entries:
        raise ValueError(
            f"{release_dir} already holds a different release bundle for commit {commit}"
        )
    for entry in entries:
        if entry.is_symlink():
            raise ValueError(
                f"{release_dir} already holds a different release bundle for commit {commit}"
            )
        rel = rel_dir / entry.name
        if entry.is_dir():
            _collect_release_entries(entry, rel, files, release_dir, commit)
        elif entry.is_file():
            files[rel] = entry.read_bytes()
        else:
            raise ValueError(
                f"{release_dir} already holds a different release bundle for commit {commit}"
            )


def _ensure_release_bundle(
    publish_dir: Path,
    commit: str,
    candidate_bytes: bytes,
    explorer_files: dict[Path, bytes],
) -> None:
    """Create or verify the immutable per-commit release bundle under publish_dir/releases/."""
    releases_dir = publish_dir / "releases"
    if releases_dir.is_symlink() or (releases_dir.exists() and not releases_dir.is_dir()):
        raise ValueError(f"Releases path is not a directory: {releases_dir}")
    release_dir = releases_dir / commit
    manifest_bytes = _render_bundle_manifest(explorer_files)
    expected_release: dict[Path, bytes] = {
        **explorer_files,
        Path(BUNDLE_MANIFEST_FILE): manifest_bytes,
        Path(COMPARISON_FILE): candidate_bytes,
    }

    if release_dir.is_symlink() or release_dir.exists():
        if release_dir.is_symlink() or not release_dir.is_dir():
            raise ValueError(
                f"{release_dir} already holds a different comparison for commit {commit}"
            )
        release_file = release_dir / COMPARISON_FILE
        if (
            release_file.is_symlink()
            or not release_file.is_file()
            or release_file.read_bytes() != candidate_bytes
        ):
            raise ValueError(
                f"{release_dir} already holds a different comparison for commit {commit}"
            )
        actual_release: dict[Path, bytes] = {}
        _collect_release_entries(release_dir, Path(), actual_release, release_dir, commit)
        if set(actual_release) != set(expected_release) or any(
            actual_release[rel] != expected_bytes for rel, expected_bytes in expected_release.items()
        ):
            raise ValueError(
                f"{release_dir} already holds a different release bundle for commit {commit}"
            )
        return

    releases_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(dir=releases_dir, prefix=f".{commit}.", suffix=".tmp"))
    try:
        staging_dir.chmod(0o755)
        for rel, data in expected_release.items():
            dest = staging_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(dest, 0o644)
        os.replace(staging_dir, release_dir)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def _sorted_rel_parents(rel: Path) -> list[Path]:
    return sorted((p for p in rel.parents if p != Path(".")), key=lambda p: len(p.parts))


def _ensure_no_symlink_ancestors(publish_dir: Path, rel: Path) -> None:
    for parent_rel in _sorted_rel_parents(rel):
        parent_abs = publish_dir / parent_rel
        if parent_abs.is_symlink():
            raise ValueError(f"Cannot traverse symlinked directory in publish dir: {parent_abs}")


def _snapshot_active_targets(
    publish_dir: Path, explorer_files: dict[Path, bytes]
) -> tuple[dict[Path, bytes | None], dict[Path, bool], dict[Path, int]]:
    """Verify active destinations and record prior bytes, modes, and directory existence."""
    if publish_dir.is_symlink() or (publish_dir.exists() and not publish_dir.is_dir()):
        raise ValueError(f"Publish path is not a directory: {publish_dir}")
    prior_bytes: dict[Path, bytes | None] = {}
    dir_existed: dict[Path, bool] = {}
    prior_modes: dict[Path, int] = {}
    for rel in explorer_files:
        for parent_rel in _sorted_rel_parents(rel):
            if parent_rel not in dir_existed:
                parent_abs = publish_dir / parent_rel
                if parent_abs.is_symlink() or (parent_abs.exists() and not parent_abs.is_dir()):
                    raise ValueError(f"Cannot create directory over non-directory at {parent_abs}")
                dir_existed[parent_rel] = parent_abs.is_dir()
        dest = publish_dir / rel
        if dest.is_symlink() or (dest.exists() and not dest.is_file()):
            raise ValueError(f"Cannot overwrite non-file destination at {dest}")
        if dest.is_file():
            prior_bytes[rel] = dest.read_bytes()
            prior_modes[rel] = stat.S_IMODE(dest.stat().st_mode)
        else:
            prior_bytes[rel] = None
            prior_modes[rel] = 0o644
    return prior_bytes, dir_existed, prior_modes


def _prune_empty_dirs(publish_dir: Path, rel_dirs: Iterable[Path]) -> None:
    for parent_rel in sorted(set(rel_dirs), key=lambda p: len(p.parts), reverse=True):
        if not parent_rel.parts or parent_rel == Path(".") or parent_rel.parts[0] == "releases":
            continue
        _ensure_no_symlink_ancestors(publish_dir, parent_rel)
        candidate_dir = publish_dir / parent_rel
        if candidate_dir.is_symlink():
            raise ValueError(f"Cannot prune symlinked directory in publish dir: {candidate_dir}")
        if candidate_dir.is_dir() and not any(candidate_dir.iterdir()):
            candidate_dir.rmdir()


def _restore_active_targets(
    publish_dir: Path,
    written: list[Path],
    prior_bytes: dict[Path, bytes | None],
    dir_existed: dict[Path, bool],
    prior_modes: dict[Path, int] | None = None,
) -> None:
    first_error: OSError | None = None
    for rel in reversed(written):
        if prior_bytes[rel] is not None:
            continue
        dest = publish_dir / rel
        try:
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
        except OSError as exc:
            if first_error is None:
                first_error = exc

    for rel in reversed(written):
        old = prior_bytes[rel]
        if old is None:
            continue
        dest = publish_dir / rel
        target_mode = 0o644 if prior_modes is None else prior_modes.get(rel, 0o644)
        try:
            needs_restore = (
                dest.is_symlink()
                or not dest.is_file()
                or dest.read_bytes() != old
                or stat.S_IMODE(dest.stat().st_mode) != target_mode
            )
            if needs_restore:
                _write_atomic(dest, old, mode=target_mode)
        except OSError as exc:
            if first_error is None:
                first_error = exc

    try:
        _prune_empty_dirs(publish_dir, (p for p, existed in dir_existed.items() if not existed))
    except OSError as exc:
        if first_error is None:
            first_error = exc

    if first_error is not None:
        raise first_error


def _validate_obsolete_managed_paths(
    publish_dir: Path, previous_managed: set[Path], new_managed: set[Path]
) -> list[Path]:
    obsolete = sorted(previous_managed - new_managed, key=lambda p: p.as_posix())
    safe_obsolete: list[Path] = []
    for rel in obsolete:
        if (
            not rel.parts
            or rel.is_absolute()
            or rel.parts[0] == "releases"
            or rel in {Path(COMPARISON_FILE), Path(SUMMARY_FILE), Path(BUNDLE_MANIFEST_FILE)}
        ):
            continue
        _ensure_no_symlink_ancestors(publish_dir, rel)
        dest = publish_dir / rel
        if dest.is_symlink():
            raise ValueError(f"Cannot prune symlink in publish dir: {dest}")
        safe_obsolete.append(rel)
    return safe_obsolete


def _prune_obsolete_managed(
    publish_dir: Path, previous_managed: set[Path], new_managed: set[Path]
) -> None:
    if publish_dir.is_symlink():
        raise ValueError(f"Publish path cannot be a symlink: {publish_dir}")
    obsolete = _validate_obsolete_managed_paths(publish_dir, previous_managed, new_managed)
    obsolete_parents: set[Path] = set()
    for rel in obsolete:
        dest = publish_dir / rel
        if dest.is_file() and not dest.is_symlink():
            dest.unlink()
        obsolete_parents.update(rel.parents)
    _prune_empty_dirs(publish_dir, obsolete_parents)


@dataclass(frozen=True)
class Promotion:
    preview: str
    published: bool


def promote(
    run_dir: Path,
    publish_dir: Path,
    *,
    confirm: bool,
    explorer_dir: Path | None = None,
) -> Promotion:
    """Show candidate and current figures side by side; with confirm, publish atomically.

    The candidate and its explorer bundle are kept under publish_dir/releases/<commit>/ first, so
    promoting a release folder is a rollback of both UI and data. Any failure leaves the published
    comparison and explorer assets untouched.
    """
    source = run_dir / COMPARISON_FILE
    if source.is_symlink():
        raise ValueError(f"Run {run_dir} comparison cannot be a symlink: {source}")
    if not source.is_file():
        raise ValueError(f"Run {run_dir} has no comparison to promote (a failed run has none)")
    summary_path = run_dir / SUMMARY_FILE
    if summary_path.is_symlink():
        raise ValueError(f"Run {run_dir} summary cannot be a symlink: {summary_path}")
    if summary_path.is_file() and not _has_release_marker(run_dir):
        try:
            status = json.loads(summary_path.read_text(encoding="utf-8")).get("status")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            raise ValueError(f"Invalid run summary at {summary_path}") from exc
        if status != "succeeded":
            raise ValueError(f"Run {run_dir} did not succeed (status {status!r})")
    candidate_bytes, candidate = _read_comparison(source)

    explorer_source = _resolve_explorer_source(run_dir, explorer_dir)
    if explorer_dir is None and explorer_source == run_dir:
        explorer_files = _collect_release_bundle_files(run_dir)
    else:
        explorer_files = _collect_explorer_files(
            explorer_source, is_default=(explorer_dir is None)
        )
        if _has_release_marker(run_dir):
            release_files = _collect_release_bundle_files(run_dir)
            if release_files != explorer_files:
                raise ValueError(
                    f"{run_dir} already holds a different release bundle for commit "
                    f"{candidate['producing_commit']}"
                )

    if publish_dir.is_symlink() or (publish_dir.exists() and not publish_dir.is_dir()):
        raise ValueError(f"Publish path is not a directory: {publish_dir}")
    target = publish_dir / COMPARISON_FILE
    if target.is_symlink():
        raise ValueError(f"Published comparison path cannot be a symlink: {target}")
    if target.exists() and not target.is_file():
        raise ValueError(f"Published comparison path is not a regular file: {target}")
    releases_dir = publish_dir / "releases"
    if releases_dir.is_symlink() or (releases_dir.exists() and not releases_dir.is_dir()):
        raise ValueError(f"Releases path is not a directory: {releases_dir}")

    current: ComparisonDocument | None = None
    if target.exists():
        try:
            _, current = _read_comparison(target)
        except (ValueError, OSError) as exc:
            raise ValueError(f"Cannot read the current comparison at {target}: {exc}") from exc
    preview = _preview(candidate, current, target, explorer_source, explorer_files)
    if not confirm:
        return Promotion(preview=preview, published=False)

    previous_managed: set[Path] = set()
    if current is not None:
        prev_release_dir = releases_dir / current["producing_commit"]
        if prev_release_dir.is_symlink() or (
            prev_release_dir.exists() and not prev_release_dir.is_dir()
        ):
            raise ValueError(f"Previous release path is not a directory: {prev_release_dir}")
        prev_manifest = prev_release_dir / BUNDLE_MANIFEST_FILE
        previous_managed = _read_bundle_manifest(prev_manifest)
        _validate_obsolete_managed_paths(publish_dir, previous_managed, set(explorer_files))

    prior_bytes, dir_existed, prior_modes = _snapshot_active_targets(publish_dir, explorer_files)
    _ensure_release_bundle(publish_dir, candidate["producing_commit"], candidate_bytes, explorer_files)

    written: list[Path] = []
    try:
        for rel, data in explorer_files.items():
            _write_atomic(publish_dir / rel, data, mode=0o644)
            written.append(rel)
        _write_atomic(target, candidate_bytes, mode=0o644)
    except BaseException as exc:
        try:
            _restore_active_targets(publish_dir, written, prior_bytes, dir_existed, prior_modes)
        except OSError as restore_exc:
            raise restore_exc from exc
        raise

    _prune_obsolete_managed(publish_dir, previous_managed, set(explorer_files))
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
