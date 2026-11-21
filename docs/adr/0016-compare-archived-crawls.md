# Compare two archived crawls of one documentation site

The first crawl freshness release compares two archived crawls of one documentation site. Fixed captures let a reviewer repeat the comparison and trace a reported change to its source. Live scraping, including scheduling requests and managing publisher rate limits, is deferred.

Before selecting a source, open two public captures, extract prose from both with Python and verify a change in the article itself.

The selected pilot uses Wayback Machine captures under Cloudflare's AI Crawl Control documentation path in October 2025 and April 2026. These are monthly sampling windows. Each page retains its own capture timestamp.

Include the changelog in both samples and show its page count alongside the guides. If an announcement and a guide repeat the same new passage, each page gets credit and the crawl total counts the passage once.

The archive index returned 13 URLs in both windows. The following pairs returned HTTP 200 at their exact replay URLs and yielded paragraph text inside the main content. The April overview adds guidance on monitoring robots.txt directives. The remaining 11 pairs need another replay check because the archive connection failed during verification.

| Page | October 2025 | April 2026 |
| --- | --- | --- |
| Overview | [October capture](https://web.archive.org/web/20251002000737/https://developers.cloudflare.com/ai-crawl-control/) | [April capture](https://web.archive.org/web/20260429223141/https://developers.cloudflare.com/ai-crawl-control/) |
| Changelog | [October capture](https://web.archive.org/web/20251012003851/https://developers.cloudflare.com/ai-crawl-control/changelog/) | [April capture](https://web.archive.org/web/20260411015127/https://developers.cloudflare.com/ai-crawl-control/changelog/) |

### Offline reproduction

After dependency installation, the local demo must run from ingestion through a validated candidate comparison without network access. Promotion to the public file stays a separate maintainer step ([ADR 0017](0017-serve-precomputed-comparisons.md)). Bundle the article HTML from each of the four captures above. Preserve headings, paragraphs, lists, links and code blocks so the demo exercises prose extraction. Omit surrounding navigation, replay toolbars and scripts. For each fixture, record the original page URL, exact replay URL, UTC capture timestamp and a SHA-256 checksum of the bundled bytes.

These fixtures exercise the pipeline from article HTML through the candidate comparison. Test article selection from a full replay page separately.

The local demo also checks a pair of handwritten HTML samples through the same build path. In the earlier sample, two pages each say “The default timeout is ten seconds.” In the later sample, both say “The default timeout is thirty seconds.” Check the candidate result against the hand calculation: one new word on each page and one distinct new word across the crawl.

For each pull request that changes pipeline code or fixtures, CI starts from a clean checkout, installs dependencies and runs the reviewer's offline demo command. The check passes when the four Cloudflare captures produce a valid comparison file and the handwritten example matches its expected page and crawl counts.

Cloudflare licenses its documentation under CC BY 4.0 except where otherwise noted. Preserve applicable notices, credit the authors, link to the source and license, and identify any changes made when preparing fixtures. The license statement covers the documentation; the rights for additional Wayback replay assets have not been verified. [Cloudflare license notice](https://github.com/cloudflare/cloudflare-docs#license-and-legal-notices).

### Other source considered

Flask's deployment guide passed this check for one URL. Both captures returned HTTP 200. The later article explains that an application serving a single private user can still be a production deployment. Both captures also include a version banner outside the article. Coverage of other pages in the same periods is still open. [May 2021 capture](https://web.archive.org/web/20210531050836/https://flask.palletsprojects.com/en/latest/deploying/) and [May 2023 capture](https://web.archive.org/web/20230524030227/https://flask.palletsprojects.com/en/latest/deploying/).
