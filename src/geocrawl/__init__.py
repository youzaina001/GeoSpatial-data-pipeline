# geocrawl
"""Crawl freshness: how much new prose a later web crawl adds to a candidate training corpus."""

from __future__ import annotations

from geocrawl.publish import build_run, promote, run_offline_demo

__version__ = "0.1.0"
__all__ = ["build_run", "promote", "run_offline_demo"]
