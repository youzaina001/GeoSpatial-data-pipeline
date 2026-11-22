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
make preview   # promote the Cloudflare sample to data/site/ and serve locally
make check     # pytest, Ruff, mypy and explorer JS unit tests
```

`make demo` writes one run per sample under `data/demo/<sample>/runs/`. Each
run has a public `comparison.json` and a maintainer `run-summary.json`. The
headline figure is `summary.distinct_new_words` in `comparison.json`: 1358
for the Cloudflare sample. A small handwritten sample must report exactly one,
or the demo stops before writing. Run `make test-browser` where Node >= 22 and
Google Chrome are installed to verify the explorer end-to-end.

## How it works

1. **Load a manifest** of archived captures, with checksums and an archive
   host allowlist ([ADR 0016](docs/adr/0016-compare-archived-crawls.md),
   [ADR 0019](docs/adr/0019-manifest-and-comparison-contracts.md)).
2. **Extract visible prose** with a browser-grade HTML parser, skipping
   navigation, controls and hidden text.
3. **Match three-word runs** so moved, copied and lightly edited text is not
   counted twice, then **aggregate and check** the figures in DuckDB
   ([ADR 0018](docs/adr/0018-python-and-duckdb.md)).
4. **Build, promote and publish.** `geocrawl build` writes a candidate and never
   publishes. `geocrawl promote <run> --publish-dir <site> --yes` bundles
   `explorer/` with `comparison.json` under `<site>/releases/<commit>/` and
   publishes `<site>/` atomically
   ([ADR 0017](docs/adr/0017-serve-precomputed-comparisons.md),
   [ADR 0023](docs/adr/0023-static-explorer-and-release-bundle.md)). For
   Cloudflare Pages, copy the active files in `<site>/` excluding `releases/`
   to a staging directory and run `wrangler pages deploy`.

## What's next

The static explorer is live under `explorer/` (`make preview` serves it locally).
Next is adding the remaining 11 archived page pairs for Cloudflare AI Crawl
Control. Open work is tracked in
[GitHub Issues](https://github.com/youzaina001/GeoSpatial-data-pipeline/issues).

## Repository map

| Path | What it holds |
| --- | --- |
| `src/geocrawl/` | The pipeline and the `geocrawl` CLI |
| `explorer/` | Zero-build static comparison explorer (HTML, CSS, ES modules) |
| `fixtures/` | Bundled archive samples and manifests |
| `tests/` | Python, Node (`node --test`) and Chrome browser checks |
| `GLOSSARY.md`, `docs/adr/` | Domain terms and design decisions |
| `archive/` | Earlier projects, kept for the record and not supported |

This repository began as a satellite NDVI pipeline. That example now lives in
[`archive/v1-satellite/`](archive/v1-satellite/), and its Kubernetes
predecessor in [`archive/v0/`](archive/v0/)
([ADR 0021](docs/adr/0021-archive-the-satellite-example.md)).
