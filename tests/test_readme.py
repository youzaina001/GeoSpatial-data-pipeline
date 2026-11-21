# README guardrail
"""The README stays short, and its links and make targets exist."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = (REPO / "README.md").read_text()


def test_readme_is_short_enough_for_a_first_visit() -> None:
    assert len(README.splitlines()) <= 80


def test_readme_relative_links_exist() -> None:
    for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", README):
        if "://" in target:
            continue
        assert (REPO / target).exists(), target


def test_readme_make_targets_exist() -> None:
    makefile = (REPO / "Makefile").read_text()
    targets = {line.split(":", 1)[0] for line in makefile.splitlines() if re.match(r"^[a-z][\w-]*:", line)}
    for target in re.findall(r"\bmake ([a-z][\w-]*)", README):
        assert target in targets, target
