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


def _texts(html: str) -> list[str]:
    return [s.normalized_text for s in extract_sentences(html)]


def test_hidden_content_is_not_prose() -> None:
    html = """<article>
      <p>Read <span hidden>draft</span> this <span aria-hidden="true">icon</span> text.</p>
      <template><p>Template words.</p></template>
      <script>var x = "script words";</script><style>p { color: red; }</style>
      <noscript><p>Noscript words.</p></noscript>
      <p>Frame <iframe src="https://example.invalid/">iframe words</iframe> here.</p>
      <p>Box <textarea>textarea words</textarea> here.</p>
      <div hidden><p>Hidden block words.</p></div>
    </article>"""
    assert _texts(html) == ["read this text", "frame here", "box here"]


def test_ui_controls_and_text_outside_prose_blocks_are_not_prose() -> None:
    html = """<article>
      <a class="inline-flex" href="/rss.xml">Subscribe to RSS</a>
      <div>Loose div text.</div>
      <p>Kept <button>Copy</button> sentence <label>Label</label> here.</p>
      <form><p>Form words.</p></form>
      <select><option>Option words</option></select><input value="Input words">
    </article>"""
    assert _texts(html) == ["kept sentence here"]


def test_standalone_strong_in_article_body_is_a_headline_but_inline_strong_is_not_split() -> None:
    html = """<article>
      <strong>Analytics enhancements</strong> <br>
      <p>Use the <strong>Patterns</strong> tab.</p>
    </article>"""
    assert _texts(html) == ["analytics enhancements", "use the patterns tab"]


def test_br_inside_any_block_is_a_space_not_a_sentence_break() -> None:
    for tag in ("li", "h2", "td", "blockquote"):
        html = f"<article><table><tr><{tag}>The default timeout value<br>is ten seconds.</{tag}></tr></table></article>"
        assert _texts(html) == ["the default timeout value is ten seconds"], tag


def test_character_references_are_decoded_once() -> None:
    sentences = extract_sentences("<article><p>Write &amp;nbsp; for a space.</p></article>")
    assert sentences[0].tokens == ("write", "nbsp", "for", "a", "space")


def test_sentence_ends_after_closing_quote() -> None:
    html = '<article><p>He said "Alpha beta gamma." Then one more line follows.</p></article>'
    assert _texts(html) == ["he said alpha beta gamma", "then one more line follows"]


def test_article_selection_ignores_main_inside_template_and_script() -> None:
    replay = (
        "<template><main><p>Fake</p></main></template>"
        "<script>var s = '<main><p>Script</p></main>';</script>"
        "<main><p>Real</p></main>"
    )
    article = extract_article_html(replay)
    assert "Real" in article
    assert "Fake" not in article
    assert "Script" not in article


def test_h1_inside_markdown_content_is_not_duplicated() -> None:
    replay = '<main><div class="sl-markdown-content"><h1>Title</h1><p>Body.</p></div></main>'
    assert extract_article_html(replay).count("Title") == 1


def test_article_selection_skips_hidden_main_and_main_inside_hidden_ancestors() -> None:
    replay = (
        "<main hidden><p>Hidden draft.</p></main>"
        '<div aria-hidden="true"><main><p>Ancestor hidden.</p></main></div>'
        "<main><p>Visible article.</p></main>"
    )
    sentences = [s.normalized_text for s in extract_sentences(extract_article_html(replay))]
    assert sentences == ["visible article"]


def test_article_selection_skips_screen_reader_only_and_wayback_chrome_containers() -> None:
    replay = (
        '<main class="sr-only"><p>Draft prose.</p></main>'
        '<div id="wm-ipp-base"><main><p>Toolbar prose.</p></main></div>'
        "<main><p>Visible article.</p></main>"
    )
    sentences = [s.normalized_text for s in extract_sentences(extract_article_html(replay))]
    assert sentences == ["visible article"]


def test_article_selection_skips_ui_chrome_and_code_block_containers() -> None:
    replay = (
        "<aside><article><p>Related item.</p></article></aside>"
        "<nav><article><p>Nav card.</p></article></nav>"
        "<pre><article><p>Code sample.</p></article></pre>"
        "<article><p>Visible article.</p></article>"
    )
    sentences = [s.normalized_text for s in extract_sentences(extract_article_html(replay))]
    assert sentences == ["visible article"]


def test_title_selection_skips_a_heading_inside_navigation() -> None:
    replay = (
        "<main><nav><h1>Nav title</h1></nav><h1>Real title</h1>"
        '<div class="sl-markdown-content"><p>Body.</p></div></main>'
    )
    sentences = [s.normalized_text for s in extract_sentences(extract_article_html(replay))]
    assert sentences == ["real title", "body"]


def test_omitted_end_tags_close_blocks_like_html_does() -> None:
    # AGY round 3: an unclosed <li> or <p> kept collecting the link that followed the block.
    items = "<article><ul><li>First item<li>Second item</ul><a href='/rss.xml'>Subscribe</a></article>"
    paras = "<article><p>First para<p>Second para<div><a href='/rss.xml'>Subscribe</a></div></article>"
    rows = "<article><table><tr><td>One<td>Two</table><a href='/rss.xml'>Subscribe</a></article>"
    assert [s.normalized_text for s in extract_sentences(items)] == ["first item", "second item"]
    assert [s.normalized_text for s in extract_sentences(paras)] == ["first para", "second para"]
    assert [s.normalized_text for s in extract_sentences(rows)] == ["one", "two"]


def _article_texts(html: str) -> list[str]:
    return [s.normalized_text for s in extract_sentences(f"<article>{html}</article>")]


def test_an_inline_end_tag_never_closes_the_block_inside_it() -> None:
    # Round 4 reviews: </span> or </a> closed the <p> or <h2> it wrapped and dropped prose.
    assert _article_texts("<span><p>First </span>second.</p>") == ["first second"]
    assert _article_texts("<span><p>First sentence.</span> Second sentence.</p>") == [
        "first sentence",
        "second sentence",
    ]
    assert _article_texts("<a href='/guide'><h2>Title</a> suffix</h2>") == ["title suffix"]


def test_skipped_blocks_and_rules_close_an_open_paragraph() -> None:
    link = "<a href='/rss.xml'>Subscribe</a>"
    assert _article_texts(f"<p>Alpha<pre>code</pre>{link}") == ["alpha"]
    assert _article_texts(f"<p>Alpha<nav><a href='/'>Home</a></nav>{link}") == ["alpha"]
    assert _article_texts(f"<p>Alpha<div hidden>Draft</div>{link}") == ["alpha"]
    assert _article_texts(f"<p>Alpha<aside>Aside</aside>{link}") == ["alpha"]
    assert _article_texts(f"<p>Alpha<details>{link}</details>") == ["alpha"]
    assert _article_texts(f"<p>Alpha<hr/>{link}") == ["alpha"]
    assert _article_texts("<p>Alpha<pre>code</pre><strong>Changelog title</strong>") == [
        "alpha",
        "changelog title",
    ]


def test_a_hidden_list_item_without_an_end_tag_hides_only_itself() -> None:
    assert _article_texts("<ul><li hidden>Secret<li>Visible item</ul><p>Later prose</p>") == [
        "visible item",
        "later prose",
    ]


def test_a_new_table_section_closes_the_open_header_cell() -> None:
    html = "<table><thead><tr><th>Name<tbody><tr><td>Alice</td></tr></tbody><div>Loose</div></table>"
    assert _article_texts(html) == ["name", "alice"]
    footer = "<table><thead><tr><th>Head<tbody><tr><td>Cell</td></tr></tbody><tfoot><tr><a>Sub</a></tr></tfoot></table>"
    assert _article_texts(footer) == ["head", "cell"]


def test_many_images_in_one_paragraph_extract_in_linear_time() -> None:
    # Codex round 4: void elements stayed on the open-element stack, so this was quadratic.
    from time import perf_counter

    html = "<p>First " + '<img src="x">' * 20000 + "last.</p>"
    start = perf_counter()
    assert _article_texts(html) == ["first last"]
    assert perf_counter() - start < 1.0


def test_a_hidden_line_break_adds_no_space() -> None:
    # Codex round 5: a hidden <br> bypassed the hidden check and split the word.
    assert _article_texts("<p>co<br hidden>operate</p>") == ["cooperate"]
    assert _article_texts('<p>one<br aria-hidden="true"/>two</p>') == ["onetwo"]


def test_tags_inside_skipped_controls_never_close_the_visible_block_around_them() -> None:
    # Round 5 reviews: a block or cell inside <svg>, <select>, <noscript>, <label> or <button>
    # closed the outer paragraph or cell, leaked the hidden text and dropped the rest.
    assert _article_texts(
        "<p>before <select><option>one</option><hr><option>two</option></select>after.</p>"
    ) == ["before after"]
    assert _article_texts(
        "<p>First <svg><foreignObject><div>Label</div></foreignObject></svg> last.</p>"
    ) == ["first last"]
    assert _article_texts(
        "<p>Icon <svg><foreignObject><p>Svg leak</p></foreignObject></svg> text.</p>"
    ) == ["icon text"]
    assert _article_texts("<p>Note <noscript><p>Enable JS</p></noscript> tail.</p>") == ["note tail"]
    assert _article_texts("<p>Edit <noscript></p><p>Hidden leak</p></noscript> after.</p>") == [
        "edit after"
    ]
    assert _article_texts("<p>Note <label><p>Label leak</p></label> tail.</p>") == ["note tail"]
    assert _article_texts(
        "<table><tr><td>Cell <button><td>Button td</td></button> end</td></tr></table>"
    ) == ["cell end"]


def test_closing_a_skipped_element_ends_everything_left_open_inside_it() -> None:
    # Round 5 AGY: an unclosed cell, button or block inside skipped content kept it open,
    # so every later paragraph was dropped.
    later = "<p>Visible prose.</p>"
    for skipped in (
        "<template><tr><td>Draft cell</template>",
        "<svg><foreignObject><p>Icon</foreignObject></svg>",
        "<svg><div></svg>",
        "<nav><button>Menu</nav>",
        "<div hidden><button>Toggle</div>",
        "<noscript><table><tr><td>Off</noscript>",
    ):
        assert _article_texts(skipped + later) == ["visible prose"], skipped


def test_an_unclosed_control_inside_a_list_or_cell_ends_with_it() -> None:
    assert _article_texts("<ul><li>Item <button>Menu</ul><p>Later prose.</p>") == [
        "item",
        "later prose",
    ]
    assert _article_texts("<table><tr><td>Cell <button>Go</td><td>Next</td></tr></table>") == [
        "cell",
        "next",
    ]


def test_a_dropped_block_inside_a_list_item_splits_it_like_any_block() -> None:
    # Round 5 AGY: the text on both sides of a <pre> fused into "command.then".
    assert _article_texts(
        "<ul><li>Run this command.<pre><code>curl /</code></pre>Then check the status.</li></ul>"
    ) == ["run this command", "then check the status"]
    assert _article_texts("<ul><li>Alpha<pre>code</pre>Beta</li></ul>") == ["alpha", "beta"]
    assert _article_texts("<ul><li>Alpha<div hidden>x</div>Beta</li></ul>") == ["alpha", "beta"]


def test_a_new_row_or_cell_closes_an_open_caption() -> None:
    assert _article_texts("<table><caption hidden>Hidden<tr><td>Visible</td></tr></table>") == [
        "visible"
    ]


def test_a_self_closing_block_tag_opens_the_block_as_html_does() -> None:
    link = "<a href='/rss.xml'>Subscribe</a>"
    assert _article_texts(f"<p>Alpha<div/>{link}") == ["alpha"]
    assert _article_texts("<p>Alpha<pre/><strong>Headline</strong>") == ["alpha"]


def test_replay_extraction_closes_omitted_end_tags_like_prose_extraction() -> None:
    # Round 5 AGY: the replay steps used plain tag stacks without HTML closing rules.
    article = extract_article_html(
        "<main><ul><li hidden>Secret<li>Visible item</ul><p>Later prose</p></main>"
    )
    assert [s.normalized_text for s in extract_sentences(article)] == ["visible item", "later prose"]
    draft = extract_article_html("<main><p hidden>Draft<p>Visible article.</p></main>")
    assert [s.normalized_text for s in extract_sentences(draft)] == ["visible article"]
    banner = extract_article_html("<p hidden>Banner<main><p>Real article.</p></main>")
    assert [s.normalized_text for s in extract_sentences(banner)] == ["real article"]
    nav = extract_article_html(
        "<main><p>Alpha<nav><a href='/'>Home</a></nav><a href='/rss.xml'>Subscribe</a></main>"
    )
    assert [s.normalized_text for s in extract_sentences(nav)] == ["alpha"]
