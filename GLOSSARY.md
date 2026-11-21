# GeoPipeline

## Crawl freshness

**New prose** is wording in the later crawl sample that was absent from the prose on
every page in the earlier sample. The comparison applies across URLs. A guide
copied to a new URL contains new prose only where it adds previously unseen
text. “New” describes what the samples contain, regardless of publication date.

**New words on this page** counts the words in new prose found on that page.
**Distinct new words across the crawl** counts each distinct new passage once.
If the same new 100-word notice appears on ten pages, each page shows 100
and the crawl total is 100, regardless of processing order. Repeated words
within the notice still count toward its length.

**Comparison incomplete** applies when a page's earlier capture failed to load.
The report shows this status in place of a word count and excludes the page
from freshness totals. Beside the crawl total, it shows how many pages were
excluded.

A URL listed in the later sample only is eligible. Compare its prose with
every readable page in the earlier sample. If a guide moves from `/setup`
to `/install` and adds one previously unseen sentence, only that sentence
counts. The archive may have missed other pages containing the same wording.

When an existing paragraph gains a sentence, only the added text is eligible
to count. Adding a previously unseen 12-word sentence to an unchanged 80-word
paragraph contributes 12 new words.

Replacing one word in an otherwise unchanged sentence contributes one new
word if the revised wording was absent from the earlier sample. For example,
changing “The default timeout is ten seconds” to “The default timeout is
thirty seconds” contributes one word. If the revised sentence already appeared
on another page in the earlier sample, the change contributes zero.

The surrounding wording distinguishes edits that introduce the same word.
If a timeout changes to thirty seconds and a retention period changes to
thirty days, the two edits contribute two new words across the crawl.
Copies of the same revised timeout sentence still contribute one word in total.

A formatting change that preserves the visible wording of prose contributes
zero new words. This includes making a word bold, changing capitalization, or
turning a sentence into a heading. Matching is case-insensitive, and
contractions, hyphenated words, and dotted technical identifiers (such as
`robots.txt`) count as single words.

Code blocks (`<pre>`) are excluded from the first release. If only a code block
changes, the page contributes zero new prose. Inline `<code>` terms inside prose
sentences (such as `robots.txt` or `User-agent`) remain visible prose words, and
an added sentence explaining a code block is eligible under the same rules as
other prose.

Wording is compared as short runs of consecutive words. A later word is new
only when no run of three words around it, inside its sentence, appears
anywhere in the earlier sample. Merging two earlier sentences into one adds
only the joining words. Reordering earlier sentences adds zero. A sentence that
copies earlier wording except for one changed word adds one word, wherever it
appears. Consecutive new words form a **new passage**. The crawl total counts
each distinct new passage once, so per-page counts and the crawl total remain
independent of page processing order.

**Visible prose** is the article text a reader sees in headings, paragraphs,
list items, blockquotes, table cells, figure captions and standalone bold
headlines in the article body. Hidden text, scripts, form fields and UI
controls such as "Subscribe to RSS" are not prose.

**Candidate** is the comparison one maintainer run produces, kept in its own
run folder with the run summary. A candidate becomes the **published
comparison** only when a maintainer promotes it. Each promoted comparison is
kept as a **release**, and a rollback promotes an older release.

## Satellite example

Synthetic satellite Scenes over an AOI become a Field-day table (one row per Field per date) with a real status and, when the Scene is usable, polygon-masked NDVI.

### Language

**AOI**:
A named geographic rectangle (bounding box and CRS) that bounds which imagery and fields belong together.
_Avoid_: Region

**NDVI**:
The vegetation index `(NIR - Red) / (NIR + Red)` computed over the Field's geometry, used as the observation when a Field-day is observed.
_Avoid_: stats, the report

**Field**:
A persistent agricultural plot with a stable identity, geometry, crop type, and planting date. The same Field is observed across many dates.
_Avoid_: generated farm, random field

**Field master**:
The versioned set of Fields the pipeline reads. It lives as a checked-in fixture.
_Avoid_: field config, generated fields

**Field-day**:
The grain of the data product: one row per Field per calendar date. Status is decided in this order: ineligible if the date is before planting; else missing-scene if the Scene is missing; else cloudy if the Scene is cloudy; else observed, with NDVI. Only observed rows have NDVI.
_Avoid_: daily report, field result, stats

**Eligible**:
A Field whose planting date is on or before the Field-day date. Ineligible beats Scene status: a Field that was not planted is ineligible even if the Scene is missing or cloudy.
_Avoid_: active, ready

**Scene**:
The imagery, or the explicit lack of imagery, for the AOI on a calendar date. A Scene is present, cloudy, or missing. Cloud is a property of the Scene, not of a Field.
_Avoid_: tile, satellite data, aoi_raster

**Scene catalog**:
The date-keyed record of whether each date's Scene is present, cloudy, or missing.
_Avoid_: availability API

**Landing**:
The layer that holds Scenes and the Field master as stored for a run.
_Avoid_: bronze, raw

**Product**:
The layer that holds the Field-day table, stored as Parquet for local query and loaded into Databricks SQL for the warehouse demo.
_Avoid_: gold, processed-data, silver
