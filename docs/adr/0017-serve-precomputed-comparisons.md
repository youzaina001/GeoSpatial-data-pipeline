# Serve precomputed comparisons to portfolio visitors

A maintainer ingests the archived crawls, processes them and publishes the resulting comparison. Portfolio visitors can explore the published results. Only the maintainer can trigger ingestion or processing.

This lets visitors inspect the same result without waiting for a crawl comparison to finish. Publishing a fresh result requires another maintainer run.

Passing CI makes a commit eligible for release. A maintainer explicitly selects a verified commit and triggers publication when its comparison is ready for visitors.

Publication has two steps, so a run never changes what visitors see.

1. `geocrawl build` processes one manifest and writes a candidate to its own run folder, `runs/<UTC time>-<commit>/`. The folder holds the candidate `comparison.json` and the maintainer's `run-summary.json`. A run that fails with an expected input, filesystem or DuckDB validation or processing error still gets a folder with its run summary, which records the failed step and reason and holds no comparison, whereas unexpected programming errors propagate with their traceback without writing a run folder. `geocrawl build` never touches the published file.
2. `geocrawl promote <run>` shows the maintainer the candidate and current public result side by side. For each, it shows both capture windows, pages compared, pages excluded and distinct new words across the crawl. When nothing is published yet, it shows the candidate figures and says "first release". It publishes only when the maintainer adds `--yes`.

For each excluded page, include its URL, capture timestamp, failed processing step and reason in the maintainer's run summary. A reviewer investigating an older exclusion will need the output from that run, so run folders are kept rather than overwritten.

`geocrawl demo` builds candidates for the bundled samples and runs its checks before writing anything. It never promotes.

For the first release, the maintainer publishes a static data file. The visitor's browser loads it and displays the comparison, including each page's contribution. This removes the need for a public query service or database credentials in the browser. The size of the first real comparison will determine whether a single download is practical.

Keep the explorer in the pipeline repository and deploy it as a standalone static site. The geocrawl entry on youzaina.fr links to its stable address. Contributors can test the explorer against the pipeline output, and maintainers can release a comparison independently of the portfolio.

Package the explorer and its comparison file as one release. The maintainer previews the exact bundle visitors will receive and publishes it even when only the data changes. A rollback restores the interface and its matching data together.

The first screen asks how much new prose the later crawl added. Show the distinct new word count, the earlier baseline window, the later sample window, and the counts of compared and excluded pages together. Use the windows from the published comparison. Keep “Reproduce this result” visible beside the summary.

Below the summary, selecting a page shows its new word count and links to the available archived captures. Visitors open those captures to inspect the wording. Keeping passage text and scraped HTML out of the public file limits download size and avoids rendering source markup on the portfolio.

The explorer makes a capture reference clickable only when it parses as an absolute HTTPS URL on the selected archive host. Compare the parsed host exactly. For a malformed or disallowed reference, show “Capture link unavailable” and preserve the page's comparison status and word count.

Each run builds its comparison separately from the published file. Before a candidate is written, verify that every passage references a page, that each eligible page count matches its passage records, and that the crawl total counts each distinct passage once. Promotion replaces the published comparison and its crawl dates together, by writing a temporary file and renaming it over the published one. If processing, validation or promotion fails, visitors continue to see the last successful publication with its original crawl dates.

Promotion also keeps a copy of each promoted comparison under `releases/<commit>/`. A rollback promotes an older release folder through the same side by side check.

Record the producing Git commit in the published comparison. `geocrawl build` and `geocrawl demo` resolve that commit from the repository that holds the manifest, and refuse to run when no commit can be resolved, when any file under the manifest's folder has uncommitted changes, or when a file the manifest names is not tracked by Git. There is no option to name a different commit. The pipeline verifies each bundled input against its recorded SHA-256 checksum and extracts prose from the same bytes it hashed, so the inputs match the checksums recorded at that commit. The explorer's “Reproduce this result” link points to instructions at that exact commit, where a reviewer can find the input checksums and the local demo command.
