# Crawl prose extraction tests
"""Verify article selection, code-block exclusion, inline code retention, and tokenization."""

from __future__ import annotations

from geopipeline.crawl.extract import extract_article_html, extract_sentences


def test_extract_article_html_strips_wayback_chrome_and_site_navigation() -> None:
    replay_html = """<!doctype html>
<html>
<head><title>AI Crawl Control</title><script>var wm = 1;</script></head>
<body>
  <div id="wm-ipp-base"><div>Wayback Machine Toolbar</div></div>
  <header><nav><a href="/">Docs Home</a></nav></header>
  <main data-pagefind-body>
    <nav aria-label="Breadcrumb"><a href="/">Home</a></nav>
    <button>Page options</button>
    <h1 id="_top">AI Crawl Control</h1>
    <div class="sl-markdown-content">
      <p>Monitor <code>robots.txt</code> directives.</p>
      <pre><code>User-agent: GPTBot
Disallow: /</code></pre>
    </div>
    <footer><p>Was this helpful?</p><p>Privacy Policy</p></footer>
  </main>
</body>
</html>
"""
    article = extract_article_html(replay_html)
    assert "AI Crawl Control" in article
    assert "Monitor <code>robots.txt</code> directives." in article
    assert "User-agent: GPTBot" in article
    assert "Wayback Machine Toolbar" not in article
    assert "Docs Home" not in article
    assert "Page options" not in article
    assert "Was this helpful?" not in article
    assert "Privacy Policy" not in article


def test_extract_sentences_excludes_pre_blocks_and_keeps_inline_code() -> None:
    html = """<article>
      <h2>Track <code>robots.txt</code></h2>
      <p>Monitor <code>robots.txt</code> directives for AI-ready sites that don't allow scraping.</p>
      <pre><code>User-agent: ExampleBot
Disallow: /private/</code></pre>
      <p>Added explanation for the code block.</p>
    </article>"""
    sentences = extract_sentences(html)
    texts = [s.normalized_text for s in sentences]
    assert texts == [
        "track robots.txt",
        "monitor robots.txt directives for ai-ready sites that don't allow scraping",
        "added explanation for the code block",
    ]
    assert sentences[1].tokens == (
        "monitor",
        "robots.txt",
        "directives",
        "for",
        "ai-ready",
        "sites",
        "that",
        "don't",
        "allow",
        "scraping",
    )


def test_formatting_and_capitalization_changes_produce_identical_sentences() -> None:
    before = "<article><p>The default timeout is ten seconds.</p></article>"
    after = "<article><h2>The <strong>DEFAULT</strong> Timeout Is <em>Ten</em> Seconds.</h2></article>"
    assert extract_sentences(before) == extract_sentences(after)


def test_curly_apostrophes_normalize_to_straight_apostrophes() -> None:
    html = "<article><p>Cloudflare\u2019s crawler rules don\u2019t block humans.</p></article>"
    sentences = extract_sentences(html)
    assert sentences[0].tokens == (
        "cloudflare's",
        "crawler",
        "rules",
        "don't",
        "block",
        "humans",
    )


def test_bare_changelog_titles_and_figcaptions_are_extracted_as_prose() -> None:
    html = """<article>
      <h2>2026-03-24</h2><br>
      <strong>Advanced WAF customization for AI Crawl Control blocks</strong><br>
      <p>AI Crawl Control supports custom modifications.</p>
      <figure><figcaption>Traffic overview chart caption.</figcaption></figure>
    </article>"""
    texts = [s.normalized_text for s in extract_sentences(html)]
    assert texts == [
        "2026-03-24",
        "advanced waf customization for ai crawl control blocks",
        "ai crawl control supports custom modifications",
        "traffic overview chart caption",
    ]
