# README guardrail
"""The README stays short, and its links and make targets exist."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = (REPO / "README.md").read_text()


def test_readme_is_short_enough_for_a_first_visit() -> None:
    assert len(README.splitlines()) <= 80


def _anchors(markdown: str) -> set[str]:
    headings = re.findall(r"^#+ (.+)$", markdown, flags=re.MULTILINE)
    return {re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-") for h in headings}


def test_readme_relative_links_and_anchors_exist() -> None:
    for target, anchor in re.findall(r"\]\(([^)#]+)(?:#([^)]*))?\)", README):
        if "://" in target:
            continue
        path = REPO / target
        assert path.exists(), target
        if anchor:
            assert anchor in _anchors(path.read_text()), f"{target}#{anchor}"


def test_readme_make_targets_exist() -> None:
    makefile = (REPO / "Makefile").read_text()
    targets = {line.split(":", 1)[0] for line in makefile.splitlines() if re.match(r"^[a-z][\w-]*:", line)}
    code = "\n".join(re.findall(r"```[a-z]*\n(.*?)```", README, flags=re.DOTALL) + re.findall(r"`([^`\n]+)`", README))
    for target in re.findall(r"\bmake ([a-z][\w-]*)", code):
        assert target in targets, target
