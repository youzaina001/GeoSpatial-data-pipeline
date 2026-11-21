# Crawl passage matching tests
"""Verify every settled GLOSSARY crawl freshness scenario and DuckDB aggregation."""

from __future__ import annotations

from geopipeline.crawl.extract import extract_sentences
from geopipeline.crawl.matching import match_pages
from geopipeline.crawl.metrics import compute_metrics


def _run(earlier: dict[str, str], later: dict[str, str]) -> tuple[dict[str, int | None], int]:
    earlier_s = {url: extract_sentences(html) for url, html in earlier.items()}
    later_s = {url: extract_sentences(html) for url, html in later.items()}
    matched = match_pages(earlier_s, later_s)
    metrics = compute_metrics(matched.pages, matched.passages)
    return (
        {page.url: page.new_words for page in metrics.pages},
        metrics.distinct_new_words,
    )


def test_single_word_replacement_deduplicates_across_two_pages() -> None:
    earlier = {
        "https://example.com/guide": "<article><p>The default timeout is ten seconds.</p></article>",
        "https://example.com/reference": "<article><p>The default timeout is ten seconds.</p></article>",
    }
    later = {
        "https://example.com/guide": "<article><p>The default timeout is thirty seconds.</p></article>",
        "https://example.com/reference": "<article><p>The default timeout is thirty seconds.</p></article>",
    }
    per_page, total = _run(earlier, later)
    assert per_page == {
        "https://example.com/guide": 1,
        "https://example.com/reference": 1,
    }
    assert total == 1


def test_surrounding_wording_distinguishes_same_new_word() -> None:
    earlier = {
        "https://example.com/a": "<article><p>The default timeout is ten seconds.</p></article>",
        "https://example.com/b": "<article><p>The default retention is ten days.</p></article>",
    }
    later = {
        "https://example.com/a": "<article><p>The default timeout is thirty seconds.</p></article>",
        "https://example.com/b": "<article><p>The default retention is thirty days.</p></article>",
    }
    per_page, total = _run(earlier, later)
    assert per_page == {"https://example.com/a": 1, "https://example.com/b": 1}
    assert total == 2


def test_revised_sentence_already_in_earlier_corpus_counts_zero() -> None:
    earlier = {
        "https://example.com/a": "<article><p>The default timeout is ten seconds.</p></article>",
        "https://example.com/other": "<article><p>The default timeout is thirty seconds.</p></article>",
    }
    later = {
        "https://example.com/a": "<article><p>The default timeout is thirty seconds.</p></article>",
    }
    per_page, total = _run(earlier, later)
    assert per_page == {"https://example.com/a": 0}
    assert total == 0


def test_cross_url_move_with_one_added_sentence_counts_only_added_sentence() -> None:
    earlier = {
        "https://example.com/setup": (
            "<article><p>Install the package first. Configure your token next.</p></article>"
        ),
    }
    later = {
        "https://example.com/install": (
            "<article><p>Install the package first. Configure your token next. "
            "Verify your local output immediately.</p></article>"
        ),
    }
    per_page, total = _run(earlier, later)
    assert per_page == {"https://example.com/install": 5}
    assert total == 5


def test_adding_twelve_word_sentence_to_existing_paragraph_counts_twelve() -> None:
    unchanged = " ".join(f"word{i}" for i in range(1, 81)) + "."
    added = "One two three four five six seven eight nine ten eleven twelve."
    earlier = {"https://example.com/p": f"<article><p>{unchanged}</p></article>"}
    later = {"https://example.com/p": f"<article><p>{unchanged} {added}</p></article>"}
    per_page, total = _run(earlier, later)
    assert per_page == {"https://example.com/p": 12}
    assert total == 12


def test_repeated_notice_across_ten_pages_counts_once_and_preserves_internal_repeats() -> None:
    # 100-word notice with repeated words ("notice") inside it.
    notice = " ".join(["notice" if i % 10 == 0 else f"term{i}" for i in range(1, 101)]) + "."
    earlier = {f"https://example.com/p{i}": "<article><p>Base intro text.</p></article>" for i in range(10)}
    later = {
        f"https://example.com/p{i}": f"<article><p>Base intro text. {notice}</p></article>"
        for i in range(10)
    }
    per_page, total = _run(earlier, later)
    assert all(count == 100 for count in per_page.values())
    assert total == 100

    # Order independence check: reverse input dict order gives identical counts.
    per_page_rev, total_rev = _run(
        dict(reversed(list(earlier.items()))),
        dict(reversed(list(later.items()))),
    )
    assert per_page_rev == per_page
    assert total_rev == total


def test_code_block_only_change_counts_zero() -> None:
    earlier = {
        "https://example.com/c": "<article><p>Use this rule.</p><pre><code>allow: /a</code></pre></article>"
    }
    later = {
        "https://example.com/c": "<article><p>Use this rule.</p><pre><code>disallow: /b/c/d</code></pre></article>"
    }
    per_page, total = _run(earlier, later)
    assert per_page == {"https://example.com/c": 0}
    assert total == 0


def _one(earlier_html: str, later_html: str) -> int:
    per_page, total = _run(
        {"https://example.com/a": f"<article>{earlier_html}</article>"},
        {"https://example.com/a": f"<article>{later_html}</article>"},
    )
    assert per_page["https://example.com/a"] == total
    count = per_page["https://example.com/a"]
    assert count is not None
    return count


def test_merging_two_earlier_sentences_counts_only_the_joining_word() -> None:
    # Reproduced at 16b27d6: the closest-sentence matcher gave 5.
    assert _one(
        "<p>Bots must obey robots.txt. Operators can block crawlers.</p>",
        "<p>Bots must obey robots.txt and operators can block crawlers.</p>",
    ) == 1


def test_reordering_earlier_sentences_counts_zero() -> None:
    # Reproduced at 16b27d6: the closest-sentence matcher gave 3.
    assert _one(
        "<p>Bots must obey robots.txt. Operators can block crawlers.</p>",
        "<p>Operators can block crawlers. Bots must obey robots.txt.</p>",
    ) == 0


def test_near_copy_of_an_earlier_sentence_counts_the_changed_word_wherever_it_appears() -> None:
    earlier = {
        "https://example.com/a": "<article><p>Crawlers must respect the crawl delay set in robots.txt.</p></article>",
        "https://example.com/b": "<article><p>Operators can block crawlers. Logs show each request.</p></article>",
    }
    later = {
        "https://example.com/b": (
            "<article><p>Operators can block crawlers. "
            "Crawlers must respect the crawl delay defined in robots.txt. "
            "Logs show each request.</p></article>"
        ),
    }
    per_page, total = _run(earlier, later)
    assert per_page == {"https://example.com/b": 1}
    assert total == 1


def test_inserting_an_unseen_twelve_word_sentence_mid_paragraph_counts_twelve() -> None:
    first = " ".join(f"alpha{i}" for i in range(1, 41)) + "."
    second = " ".join(f"omega{i}" for i in range(1, 41)) + "."
    added = "One two three four five six seven eight nine ten eleven twelve."
    assert _one(f"<p>{first} {second}</p>", f"<p>{first} {added} {second}</p>") == 12


def test_one_word_edits_at_sentence_start_and_near_the_end_count_one_each() -> None:
    assert _one(
        "<p>Set ten seconds as the default.</p>",
        "<p>Set thirty seconds as the default.</p>",
    ) == 1
    assert _one(
        "<p>The default timeout is ten seconds now.</p>",
        "<p>The default timeout is thirty seconds now.</p>",
    ) == 1


def test_extending_a_sentence_counts_only_the_added_words() -> None:
    assert _one(
        "<p>The default timeout is ten seconds.</p>",
        "<p>The default timeout is ten seconds for every upload.</p>",
    ) == 3


def test_formatting_capitalization_and_heading_changes_count_zero() -> None:
    assert _one(
        "<p>Bots must obey robots.txt. Operators can block crawlers.</p>",
        "<h2>BOTS must <strong>obey</strong> Robots.txt</h2><p>Operators can <em>block</em> crawlers.</p>",
    ) == 0


def test_added_sentence_explaining_a_code_block_counts_like_other_prose() -> None:
    assert _one(
        "<p>Use this rule.</p><pre><code>allow: /a</code></pre>",
        "<p>Use this rule.</p><pre><code>allow: /a</code></pre><p>The rule allows <code>/a</code> paths.</p>",
    ) == 5


def test_unseen_sentence_with_common_edge_words_still_counts_every_word() -> None:
    # Edge alignment needs covered neighbours; a sentence with none keeps all its words.
    assert _one(
        "<p>The crawler reads the page.</p>",
        "<p>The crawler reads the page. The new header changes how bots read the page.</p>",
    ) == 9


def test_reordering_clauses_of_an_earlier_sentence_counts_only_the_rejoined_word() -> None:
    # The closest-sentence matcher at 16b27d6 gave 9 here. Only "and" sits in new wording.
    assert _one(
        "<p>Bots must obey robots.txt and operators can block crawlers.</p>",
        "<p>Operators can block crawlers and bots must obey robots.txt.</p>",
    ) == 1


def test_one_changed_word_in_a_short_sentence_counts_one() -> None:
    # Glossary: one changed word adds one word, even when no three-word run survives.
    assert _one("<p>We use fast requests now.</p>", "<p>We use slow requests now.</p>") == 1
    assert _one("<p>Fast crawlers read pages.</p>", "<p>Slow crawlers read pages.</p>") == 1
    assert _one("<p>Bots read pages fast.</p>", "<p>Bots read pages slowly.</p>") == 1


def test_one_changed_word_already_in_earlier_wording_does_not_inflate_the_count() -> None:
    # Spec review 2026-11-21 saw 2 here. "We use slow" is earlier wording, so the three-word
    # rule covers "slow" and the copied rest is covered too: builder reading 0, owner to confirm.
    assert _one(
        "<p>We use fast requests now.</p><p>We use slow.</p>",
        "<p>We use slow requests now.</p>",
    ) == 0


def test_merging_two_short_earlier_sentences_counts_only_the_joining_word() -> None:
    assert _one("<p>Bots stop. Users wait.</p>", "<p>Bots stop and users wait.</p>") == 1


def test_merging_a_short_sentence_into_a_long_one_counts_only_the_joining_word() -> None:
    assert _one(
        "<p>Bots stop. Users must wait for the crawler.</p>",
        "<p>Bots stop and users must wait for the crawler.</p>",
    ) == 1


def test_a_one_word_earlier_heading_does_not_cover_words_in_new_headings() -> None:
    assert _one("<h2>Analytics</h2>", "<h2>Analytics</h2><h2>Referral analytics</h2>") == 2
