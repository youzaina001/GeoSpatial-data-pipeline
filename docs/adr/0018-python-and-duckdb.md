# Compare prose in Python and calculate metrics in DuckDB

Python extracts prose from archived pages and identifies the words that are new to the later sample. DuckDB SQL uses those results to calculate page counts, count each distinct new passage once across the crawl, and report excluded pages.

The [crawl freshness glossary](../../GLOSSARY.md#crawl-freshness) defines new prose. This ADR describes how Python applies that definition. When the two disagree, the glossary governs and this ADR changes.

## Tables

Python supplies two tables for each comparison.

* `pages (page_url VARCHAR PRIMARY KEY, status VARCHAR, earlier_capture_url VARCHAR, later_capture_url VARCHAR)` has one row per page with its canonical URL, comparison status (`compared` or `comparison_incomplete`), and available capture links. A successfully compared page with no new passages has a word count of zero. An incomplete page has a null word count and contributes to the exclusion count.
* `passages (page_url VARCHAR, passage_id VARCHAR, word_count INTEGER, PRIMARY KEY (page_url, passage_id))` has one row per distinct new passage on a successfully compared page. Each row references its page and carries a deterministic `passage_id` and a positive `word_count`. The same passage on two pages has the same identifier, so SQL can credit both pages and count the passage once across the crawl.

## Visible article prose

Python reads the article HTML recorded in the manifest and keeps visible prose blocks:

* headings, paragraphs, list items, blockquotes, table cells and `<figcaption>` captions;
* a `<strong>` element outside any prose block when it sits directly inside the article body or inside a layout wrapper (`<div>` or `<section>`), not inside inline or control wrappers such as `<a>`, `<span>` or `<summary>`. Cloudflare's changelog writes each entry's headline this way, and its overview page wraps related-product titles inside card `<div>` containers.

Text outside those blocks, such as a bare link styled as a button, is not prose. Prose inside a `<details>` element (including an initially collapsed `<details>` without `open`) counts as visible article prose unless the `<details>` element or an ancestor is hidden. Python also drops:

* hidden content: elements with the `hidden` attribute or `aria-hidden="true"`, and `<template>`, `<script>`, `<style>`, `<noscript>`, `<iframe>` and `<textarea>`;
* UI controls: `<button>`, `<label>`, `<select>`, `<option>`, `<input>`, `<form>` and `<nav>`, plus screen reader only text;
* `<pre>` code blocks. Inline `<code>` inside a prose block stays.

Python reads the HTML as a browser does. It builds the element tree with Lexbor, through the `selectolax` package, which follows the WHATWG HTML parsing rules with scripting on. Omitted end tags, stray end tags, self-closing tags and misnested markup therefore resolve as in a browser: a new list item or table cell ends the previous one, a `<p>` inside a `<label>` ends the paragraph and the label, an end tag for an inline element such as `</span>` never closes a block inside it, `<svg/>` closes itself and `<div/>` opens a `<div>`. Text that a browser keeps inside a dropped element, such as a paragraph left open inside an `<svg>`, is dropped with it. `<template>` content is not part of the page, and `<noscript>` content is raw text, as in a browser that runs scripts. Any block, including a dropped one such as `<pre>`, `<nav>`, a hidden `<div>` or a hidden `<hr>`, ends the text before and after it, so a dropped block inside a list item, table cell or quote splits it. A `<br>` inside a block is a space, and a hidden `<br>` adds nothing. Character references are decoded once, so `&amp;nbsp;` stays the visible text `&nbsp;`. The same tree selects the `<main>` or `<article>` element from a full replay page, so a `<main>` inside a `<template>` is never chosen. Stripping that element's chrome leaves an empty element where it removes a block, so replay and direct extraction give the same blocks.

Saved article fragments use HTML standards mode for sentence extraction. Full replay pages use the document mode selected by their original doctype, including quirks mode when it is absent; replay extraction splits any quirks-mode `<p>` around a nested `<table>` so the saved fragment preserves the same prose blocks when re-parsed in standards mode.

Python splits each block into sentences at `.`, `!` or `?` followed by optional closing quotes or brackets and a space. Common abbreviations such as "e.g." do not end a sentence. Python lowercases each sentence and splits it into words. Contractions, hyphenated words and dotted or underscored technical identifiers (such as `robots.txt`) stay single words.

## New words are words outside earlier three-word runs

The earlier corpus is every three-word run of consecutive words inside any sentence of the earlier sample, regardless of URL. Runs never cross a sentence boundary.

1. A later word is covered when a three-word run that contains it, inside the same later sentence, appears anywhere in the earlier corpus. A later sentence shorter than three words is covered when its words appear consecutively in an earlier sentence.
2. A word next to an edit near the start or end of a sentence has fewer runs to check. Python then aligns those uncovered edge words with every earlier sentence that contains the neighbouring covered words: the two covered words before an uncovered end, or the two covered words after an uncovered start. Uncovered words that match the earlier sentence at the same distance from its edge are covered. Changing "ten" to "thirty" in "The default timeout is ten seconds." therefore leaves "seconds" covered and counts one new word.
   Before that alignment, when an earlier sentence of the same length differs from the later sentence in exactly one word, every other word is covered, and the alignment is skipped. Changing "fast" to "slow" in "We use fast requests now." therefore counts one new word, even though that edit leaves no three-word run. Each such earlier sentence covers its own other words, so the result never depends on which one is found first.
   After that alignment, a two-word earlier sentence at the start or end of a later sentence is covered when the rest of the later sentence holds earlier wording too. Merging "Bots stop." and "Users wait." into "Bots stop and users wait." therefore counts only "and", and merging "Bots stop." into an edited "the default timeout is thirty seconds" counts "and" and "thirty". The two edges of a three-word sentence share a word, so they never cover each other: "Bots stop." and "Stop now." leave all three words of "Bots stop now." new. A one-word earlier sentence, such as an "Analytics" heading, never covers a word this way.
3. Every word that is still uncovered is new. Consecutive new words in a sentence form a passage.

A passage of three or more words is identified by the `sha256` of its words. A shorter passage also includes up to two neighbouring words on each side, with sentence edges marked, so two edits that introduce the same word in different wording stay distinct. Identical passages on several pages share one identifier and one word count, and SQL counts them once in the crawl total. Repeated words inside a passage count toward its length.

This rule follows the glossary examples. An edit counts only the replaced or added words. Merging, splitting or reordering sentences whose three-word runs already appear earlier adds only the joining words. A sentence that copies an earlier sentence except for one word counts one word, wherever it appears on the page. A sentence whose three-word runs are all absent from the earlier sample counts every word.

## Validation and reproduction

Before writing any candidate output, DuckDB validates referential and arithmetic consistency: every passage references a `compared` page, every `passage_id` has a single word count across the crawl, every compared page total equals the sum of its passages, and excluded pages carry null word counts.

This split lets a reviewer inspect the SQL behind the published metrics and reproduce them locally. Performance on a full crawl has yet to be measured.
