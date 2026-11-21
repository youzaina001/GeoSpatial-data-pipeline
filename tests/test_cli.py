# CLI surface
"""The geocrawl CLI offers build, promote and demo; satellite run and query are archived."""

from __future__ import annotations

import pytest

from geocrawl.cli import main


@pytest.mark.parametrize("retired", ["run", "query", "crawl"])
def test_satellite_commands_are_not_offered(retired: str) -> None:
    with pytest.raises(SystemExit) as exc:
        main([retired])
    assert exc.value.code == 2
