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
