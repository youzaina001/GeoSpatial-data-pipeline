# Shared crawl test fixtures
"""Temporary git repositories holding small crawl samples (ADR 0017 commit stamping)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Crawl Test",
    "GIT_AUTHOR_EMAIL": "crawl-test@example.invalid",
    "GIT_COMMITTER_NAME": "Crawl Test",
    "GIT_COMMITTER_EMAIL": "crawl-test@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, **_GIT_ENV, "GIT_CONFIG_GLOBAL": os.devnull}
    result = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def init_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    return repo


def commit_all(repo: Path, message: str = "fixtures") -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_sample(
    base: Path,
    *,
    later_text: str = "The default timeout is thirty seconds.",
    tamper: bool = False,
    include_failed: bool = False,
    later_window: str = "2026-04",
) -> Path:
    """Write a one-page Wayback-style sample (optionally with an excluded page) and return its manifest."""
    (base / "earlier").mkdir(parents=True, exist_ok=True)
    (base / "later").mkdir(parents=True, exist_ok=True)
    e_ok = base / "earlier" / "ok.html"
    l_ok = base / "later" / "ok.html"
    e_ok.write_text("<article><p>The default timeout is ten seconds.</p></article>", encoding="utf-8")
    l_ok.write_text(f"<article><p>{later_text}</p></article>", encoding="utf-8")

    page = "https://developers.cloudflare.com/ai-crawl-control/"
    earlier: list[dict[str, object]] = [
        {
            "page_url": page,
            "replay_url": f"https://web.archive.org/web/20251002000737/{page}",
            "captured_at": "2025-10-02T00:07:37Z",
            "file": "earlier/ok.html",
            "sha256": "0" * 64 if tamper else sha256_of(e_ok),
        }
    ]
    later: list[dict[str, object]] = [
        {
            "page_url": page,
            "replay_url": f"https://web.archive.org/web/20260429223141/{page}",
            "captured_at": "2026-04-29T22:31:41Z",
            "file": "later/ok.html",
            "sha256": sha256_of(l_ok),
        }
    ]
    if include_failed:
        broken = page + "broken/"
        l_bad = base / "later" / "broken.html"
        l_bad.write_text("<article><p>New page text.</p></article>", encoding="utf-8")
        earlier.append(
            {
                "page_url": broken,
                "replay_url": f"https://web.archive.org/web/20251002000000/{broken}",
                "captured_at": "2025-10-02T00:00:00Z",
                "load_error": {
                    "failed_step": "fetch_archive_capture",
                    "reason": "HTTP 503 from Wayback replay",
                },
            }
        )
        later.append(
            {
                "page_url": broken,
                "replay_url": f"https://web.archive.org/web/20260429000000/{broken}",
                "captured_at": "2026-04-29T00:00:00Z",
                "file": "later/broken.html",
                "sha256": sha256_of(l_bad),
            }
        )
    manifest = {
        "sample_id": "synthetic-check",
        "earlier_window": "2025-10",
        "later_window": later_window,
        "archive_host": "web.archive.org",
        "earlier": earlier,
        "later": later,
    }
    path = base / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def committed_sample(
    repo: Path, *, tamper: bool = False, include_failed: bool = False
) -> tuple[Path, str]:
    """Create a repo with one sample under samples/synthetic and commit it."""
    init_repo(repo)
    manifest = write_sample(
        repo / "samples" / "synthetic", tamper=tamper, include_failed=include_failed
    )
    return manifest, commit_all(repo)


def copy_bundled_fixtures(repo: Path) -> Path:
    """Copy the bundled handwritten and Cloudflare fixtures into a fresh committed repo."""
    init_repo(repo)
    root = repo / "fixtures"
    for name in ("handwritten", "cloudflare-ai-crawl-control"):
        shutil.copytree(
            REPO / "fixtures" / name,
            root / name,
        )
    commit_all(repo)
    return root
