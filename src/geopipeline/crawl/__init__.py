# Crawl freshness package
"""Offline crawl freshness comparison: manifest loading, prose extraction, matching, and DuckDB metrics."""

from __future__ import annotations

from geopipeline.crawl.publish import run_comparison, run_offline_demo

__all__ = ["run_comparison", "run_offline_demo"]
