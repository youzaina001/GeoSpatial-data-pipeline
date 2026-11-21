# geocrawl

**How much new prose does a later web crawl add to a training corpus?**

When an AI training corpus is refreshed with a newer crawl of the same site,
much of what comes back is text the corpus already has. geocrawl compares two
archived samples of one documentation site and counts the
[new prose](GLOSSARY.md#crawl-freshness) in the later one: wording that appears
on no page of the earlier crawl, even when a page moved to a new URL.

The first comparison uses October 2025 and April 2026 archive captures of
Cloudflare's AI Crawl Control documentation. Everything runs offline from
bundled fixtures, with no cloud account or credentials.

## Try it

You need Python 3.12 or newer, [uv](https://docs.astral.sh/uv/) and Make.

```bash
git clone https://github.com/youzaina001/GeoSpatial-data-pipeline.git geocrawl
cd geocrawl
make install   # pinned dependencies and dev tools
make demo      # compare the bundled samples
make check     # tests, Ruff and mypy
```

`make demo` writes one run per sample under `data/demo/<sample>/runs/`. Each
run has a public `comparison.json` and a maintainer `run-summary.json`. The
headline figure is `summary.distinct_new_words` in `comparison.json`: 1358
for the Cloudflare sample. A small
handwritten sample must report exactly one, or the demo stops before writing.

## How it works

1. **Load a manifest** of archived captures, with checksums and an archive
   host allowlist ([ADR 0016](docs/adr/0016-compare-archived-crawls.md),
   [ADR 0019](docs/adr/0019-manifest-and-comparison-contracts.md)).
2. **Extract visible prose** with a browser-grade HTML parser, skipping
   navigation, controls and hidden text.
3. **Match three-word runs** so moved, copied and lightly edited text is not
   counted twice, then **aggregate and check** the figures in DuckDB
   ([ADR 0018](docs/adr/0018-python-and-duckdb.md)).
4. **Build, then promote.** `geocrawl build` writes a candidate and never
   publishes. `geocrawl promote <run> --publish-dir <site> --yes` publishes it
   and keeps each release for rollback
   ([ADR 0017](docs/adr/0017-serve-precomputed-comparisons.md)).

## What's next

A static explorer where visitors browse the published comparison, then more
archived page pairs. Open work is tracked in
[GitHub Issues](https://github.com/youzaina001/GeoSpatial-data-pipeline/issues).

## Repository map

| Path | What it holds |
| --- | --- |
| `src/geocrawl/` | The pipeline and the `geocrawl` CLI |
| `fixtures/` | Bundled archive samples and manifests |
| `tests/` | Test suite (`make check`) |
| `GLOSSARY.md`, `docs/adr/` | Domain terms and design decisions |
| `archive/` | Earlier projects, kept for the record and not supported |

This repository began as a satellite NDVI pipeline. That example now lives in
[`archive/v1-satellite/`](archive/v1-satellite/), and its Kubernetes
predecessor in [`archive/v0/`](archive/v0/)
([ADR 0021](docs/adr/0021-archive-the-satellite-example.md)).
