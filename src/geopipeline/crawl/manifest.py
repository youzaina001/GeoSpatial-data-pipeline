# Crawl sample manifest loader
"""Validate manifest.json inputs, verify file SHA-256 checksums, and enforce archive host allowlist."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class LoadError:
    failed_step: str
    reason: str


@dataclass(frozen=True)
class CaptureEntry:
    page_url: str
    replay_url: str | None
    captured_at: str
    file: str | None = None
    sha256: str | None = None
    load_error: LoadError | None = None


@dataclass(frozen=True)
class Attribution:
    license: str
    license_url: str
    authors: str
    source_url: str
    modifications: str

    def to_dict(self) -> dict[str, str]:
        return {
            "license": self.license,
            "license_url": self.license_url,
            "authors": self.authors,
            "source_url": self.source_url,
            "modifications": self.modifications,
        }


@dataclass(frozen=True)
class SampleManifest:
    sample_id: str
    earlier_window: str
    later_window: str
    archive_host: str | None
    earlier: tuple[CaptureEntry, ...]
    later: tuple[CaptureEntry, ...]
    attribution: Attribution | None = None


def is_allowed_archive_url(url: str, archive_host: str) -> bool:
    """Return True only for absolute HTTPS URLs matching archive_host exactly with no userinfo."""
    if not url or any(ch.isspace() for ch in url):
        return False
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if parsed.hostname is None:
        return False
    return parsed.hostname.lower() == archive_host.lower()


def _validate_utc_iso8601(value: str, *, page_url: str) -> str:
    if "T" not in value:
        raise ValueError(f"captured_at must be UTC ISO-8601 with time component for {page_url}: {value}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"captured_at must be valid UTC ISO-8601 for {page_url}: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"captured_at must be in UTC (Z or +00:00) for {page_url}: {value}")
    return value


def _parse_capture_entry(
    raw: dict[str, Any],
    *,
    manifest_dir: Path,
    archive_host: str | None,
) -> CaptureEntry:
    page_url = _require_str(raw, "page_url")
    captured_at = _validate_utc_iso8601(_require_str(raw, "captured_at"), page_url=page_url)
    replay_url_val = raw.get("replay_url")
    if replay_url_val is not None and not isinstance(replay_url_val, str):
        raise ValueError(f"replay_url must be a string or null for {page_url}")
    if archive_host is not None and replay_url_val is not None:
        if not is_allowed_archive_url(replay_url_val, archive_host):
            raise ValueError(
                f"Disallowed archive URL for {page_url}: expected https://{archive_host}"
            )

    raw_error = raw.get("load_error")
    file_val = raw.get("file")
    sha_val = raw.get("sha256")

    if raw_error is not None:
        if file_val is not None or sha_val is not None:
            raise ValueError(
                f"Capture entry for {page_url} cannot specify both load_error and file/sha256"
            )
        if not isinstance(raw_error, dict):
            raise ValueError(f"load_error must be an object for {page_url}")
        load_error = LoadError(
            failed_step=_require_str(raw_error, "failed_step"),
            reason=_require_str(raw_error, "reason"),
        )
        return CaptureEntry(
            page_url=page_url,
            replay_url=replay_url_val,
            captured_at=captured_at,
            load_error=load_error,
        )

    rel_file = _require_str(raw, "file")
    expected_sha = _require_str(raw, "sha256").lower()
    base_dir = manifest_dir.resolve()
    target_path = (base_dir / rel_file).resolve()
    if not target_path.is_relative_to(base_dir):
        raise ValueError(f"Fixture file escapes manifest directory: {rel_file}")
    if not target_path.is_file():
        raise FileNotFoundError(f"Bundled fixture file missing: {target_path}")
    actual_sha = hashlib.sha256(target_path.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError(
            f"SHA-256 mismatch for {rel_file}: expected {expected_sha}, got {actual_sha}"
        )

    return CaptureEntry(
        page_url=page_url,
        replay_url=replay_url_val,
        captured_at=captured_at,
        file=rel_file,
        sha256=expected_sha,
    )


def _parse_attribution(raw: Any) -> Attribution | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("attribution must be an object or null")
    return Attribution(
        license=_require_str(raw, "license"),
        license_url=_require_str(raw, "license_url"),
        authors=_require_str(raw, "authors"),
        source_url=_require_str(raw, "source_url"),
        modifications=_require_str(raw, "modifications"),
    )


def _require_str(obj: dict[str, Any], key: str) -> str:
    val = obj.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"Manifest field '{key}' must be a non-empty string")
    return val


def load_manifest(manifest_path: Path) -> tuple[SampleManifest, str]:
    """Load manifest.json, verify every bundled file's SHA-256, and return (manifest, manifest_sha256)."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")
    raw_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    data = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Manifest root must be a JSON object")

    sample_id = _require_str(data, "sample_id")
    earlier_window = _require_str(data, "earlier_window")
    later_window = _require_str(data, "later_window")
    archive_host = data.get("archive_host")
    if archive_host is not None and (not isinstance(archive_host, str) or not archive_host.strip()):
        raise ValueError("archive_host must be a non-empty string or null")

    raw_earlier = data.get("earlier")
    raw_later = data.get("later")
    if not isinstance(raw_earlier, list) or not isinstance(raw_later, list):
        raise ValueError("Manifest 'earlier' and 'later' must be lists")
    if not raw_later:
        raise ValueError("Manifest 'later' must contain at least one capture entry")

    manifest_dir = manifest_path.parent
    earlier = tuple(
        _parse_capture_entry(item, manifest_dir=manifest_dir, archive_host=archive_host)
        for item in raw_earlier
    )
    later = tuple(
        _parse_capture_entry(item, manifest_dir=manifest_dir, archive_host=archive_host)
        for item in raw_later
    )
    _check_unique_urls(earlier, "earlier")
    _check_unique_urls(later, "later")

    attribution = _parse_attribution(data.get("attribution"))
    return (
        SampleManifest(
            sample_id=sample_id,
            earlier_window=earlier_window,
            later_window=later_window,
            archive_host=archive_host,
            earlier=earlier,
            later=later,
            attribution=attribution,
        ),
        manifest_sha256,
    )


def _check_unique_urls(entries: tuple[CaptureEntry, ...], window_name: str) -> None:
    seen: set[str] = set()
    for entry in entries:
        if entry.page_url in seen:
            raise ValueError(f"Duplicate page_url in {window_name}: {entry.page_url}")
        seen.add(entry.page_url)
