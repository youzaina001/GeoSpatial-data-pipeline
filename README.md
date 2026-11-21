# GeoPipeline

GeoPipeline is a portfolio project demonstrating full-stack data engineering
and software engineering. A reviewer can follow an analytical question across
the data lifecycle, from ingestion to serving analytics, and inspect the
decisions and tests that make the answer trustworthy. The question guides
the choice of data.

The next project in this repository will measure crawl freshness for AI
training data. Its guiding question is how much [new prose](GLOSSARY.md#crawl-freshness) a later web
crawl adds to a candidate training corpus. The first release will compare
[October 2025 and April 2026 archive samples of Cloudflare's AI Crawl Control documentation](docs/adr/0016-compare-archived-crawls.md).
Visitors will [explore a comparison published by a maintainer](docs/adr/0017-serve-precomputed-comparisons.md).
A reviewer will be able to run the pipeline locally without cloud credentials.
One command will ingest two small, fixed archived samples, compare their prose,
and write the same file format the public explorer reads.
The [processing stack decision](docs/adr/0018-python-and-duckdb.md) describes how Python and DuckDB share that work.
Whether to rename this repository to reflect its crawl freshness focus is an open decision.

An earlier satellite Field-day example is archived in
[`archive/v1-satellite/`](archive/v1-satellite/) ([ADR 0021](docs/adr/0021-archive-the-satellite-example.md)).

See [`GLOSSARY.md`](GLOSSARY.md) for the glossary and [`docs/adr/`](docs/adr/)
for design decisions.

## Crawl freshness

The crawl freshness pipeline compares two archived samples of one
documentation site and counts the [new prose](GLOSSARY.md#crawl-freshness)
in the later sample. It runs offline from bundled fixtures:

```bash
make install
make crawl-demo   # handwritten check plus four Cloudflare captures
```

`make crawl-demo` writes one candidate run per sample under
`data/crawl-demo/<sample>/runs/<UTC time>-<commit>/`, each with a public
`comparison.json` and a maintainer `run-summary.json`. The handwritten
sample must give one new word on each page and one distinct new word across
the crawl, or the demo fails before writing anything.

The demo and `crawl build` record the Git commit that produced the result.
They refuse to run when the fixture folder has uncommitted changes, so commit
any fixture edit first.

A maintainer publishes in two steps
([ADR 0017](docs/adr/0017-serve-precomputed-comparisons.md)):

```bash
uv run geopipeline crawl build --manifest fixtures/cloudflare-ai-crawl-control/manifest.json --runs-dir data/crawl/runs
uv run geopipeline crawl promote data/crawl/runs/<run> --publish-dir data/crawl/site          # preview only
uv run geopipeline crawl promote data/crawl/runs/<run> --publish-dir data/crawl/site --yes    # publish
```

`crawl promote` prints the candidate beside the current public figures (or
"first release") and replaces `comparison.json` only with `--yes`. Each
promoted comparison is kept under `releases/<commit>/`. To roll back, promote
an older release folder.

How prose is selected and matched is described in
[ADR 0018](docs/adr/0018-python-and-duckdb.md). File formats are in
[ADR 0019](docs/adr/0019-manifest-and-comparison-contracts.md).

## Tests

```bash
make check   # pytest, Ruff and mypy
```

## Stack

| Piece        | Role                                         |
| ------------ | -------------------------------------------- |
| Python 3.12+ | Pipeline, CLI                                |
| selectolax   | Browser-grade HTML parsing for visible prose |
| DuckDB       | In-memory metrics and checks                 |
