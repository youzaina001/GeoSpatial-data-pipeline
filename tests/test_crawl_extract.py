# Crawl prose extraction tests
"""Verify article selection, code-block exclusion, inline code retention, and tokenization."""

from __future__ import annotations

import pytest

from geocrawl import extract
from geocrawl.extract import extract_article_html, extract_sentences


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
    assert _texts('<article><p>First.”)] Second.</p></article>') == ["first", "second"]
    assert _texts('<article><p>First.")] Second.</p></article>') == ["first", "second"]
    assert _texts('<article><p>Read "etc." then stop.</p></article>') == ["read etc then stop"]
    assert _texts('<article><p>Use e.g. this (i.e.) that.</p></article>') == ["use e.g this i.e that"]


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


def test_markup_a_browser_moves_out_of_a_control_counts_where_the_browser_puts_it() -> None:
    # Round 7: a <p> inside <label> closes the paragraph and the label, and a <td> inside a
    # <button> starts a new cell, so a browser shows that text as page prose. The " end"
    # after the stray </button> is moved before the table, outside any prose block.
    assert _article_texts("<p>Note <label><p>Label leak</p></label> tail.</p>") == [
        "note",
        "label leak",
    ]
    assert _article_texts(
        "<table><tr><td>Cell <button><td>Button td</td></button> end</td></tr></table>"
    ) == ["cell", "button td"]


def test_closing_a_skipped_element_ends_everything_left_open_inside_it() -> None:
    # Round 5 AGY: an unclosed cell, button or block inside skipped content kept it open,
    # so every later paragraph was dropped.
    later = "<p>Visible prose.</p>"
    for skipped in (
        "<template><tr><td>Draft cell</template>",
        "<svg><div></svg>",
        "<nav><button>Menu</nav>",
        "<div hidden><button>Toggle</div>",
        "<noscript><table><tr><td>Off</noscript>",
    ):
        assert _article_texts(skipped + later) == ["visible prose"], skipped


def test_an_unclosed_paragraph_inside_an_svg_keeps_what_follows_inside_the_svg() -> None:
    # Round 7: </foreignObject> and </svg> cannot close an open <p> in a browser, so the next
    # paragraph is built inside the icon and is dropped with it.
    assert _article_texts("<svg><foreignObject><p>Icon</foreignObject></svg><p>Inside icon.</p>") == []


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


def _replay_texts(replay: str) -> list[str]:
    return [s.normalized_text for s in extract_sentences(extract_article_html(replay))]


def test_a_self_closing_svg_icon_closes_itself_as_in_a_browser() -> None:
    # Round 6 reviews: <svg/> stayed open and swallowed every later paragraph.
    assert _article_texts('<svg class="icon"/><p>Visible prose.</p>') == ["visible prose"]
    assert _article_texts("<p>Icon <svg/> text.</p><p>Next paragraph.</p>") == [
        "icon text",
        "next paragraph",
    ]
    assert _replay_texts('<main><svg class="icon"/><p>Visible prose.</p></main>') == ["visible prose"]
    assert _replay_texts('<svg class="icon"/><main><p>Visible prose.</p></main>') == ["visible prose"]


def test_end_tags_inside_a_template_never_close_anything_outside_it() -> None:
    # Round 6 AGY: </td>, </li> or </div> inside a <template> escaped it and leaked its text.
    assert _article_texts(
        "<table><tr><td>Cell <template></td><p>Template leak</p></template> tail.</td></tr></table>"
    ) == ["cell tail"]
    assert _article_texts("<ul><li>Item <template></li><p>Template leak</p></template> tail.</li></ul>") == [
        "item tail"
    ]
    assert _article_texts("<div><p>Before <template></div><p>Template leak</p></template> after.</p></div>") == [
        "before after"
    ]
    assert _replay_texts(
        "<div><template></div><main><p>Fake main.</p></main></template><main><p>Real main.</p></main></div>"
    ) == ["real main"]


def test_closing_a_dropped_container_ends_the_controls_left_open_inside_it() -> None:
    # Round 6 AGY: a second dropped element inside <label>, <template>, <noscript> or <select>
    # kept the outer one open, so every later paragraph was dropped.
    later = "<p>Visible prose.</p>"
    for skipped in (
        "<label><svg><g></label>",
        "<template><tr><td><button>Draft</template>",
        "<noscript><table><tr><td><button>Off</noscript>",
        "<select><td><option>One</select>",
    ):
        assert _article_texts(skipped + later) == ["visible prose"], skipped
    assert _replay_texts("<template><tr><td><button>Draft</template><main><p>Real.</p></main>") == ["real"]


def test_noscript_content_is_raw_text_as_in_a_browser_with_scripts_on() -> None:
    # Round 6 AGY: </div> inside <noscript> closed the outer block and leaked the fallback text.
    assert _article_texts(
        "<div><p>Before <noscript></div><p>Noscript leak</p></noscript> after.</p></div>"
    ) == ["before after"]


def test_a_self_closing_block_closes_an_open_hidden_element() -> None:
    # Round 6 AGY: <h2/>, <li/> and <div/> were ignored while hidden content was open.
    assert _article_texts("<p hidden>Draft<h2/>Visible heading</h2>") == ["visible heading"]
    assert _article_texts("<ul><li hidden>Secret<li/>Visible item</ul>") == ["visible item"]
    assert _article_texts("<p hidden>Draft<div/><strong>Visible headline</strong>") == ["visible headline"]
    assert _replay_texts(
        '<main><p hidden>Draft<hr/><span class="sl-markdown-content"><p>Body.</p></span>'
        "<p>Sidebar noise.</p></main>"
    ) == ["body"]


def test_a_hidden_rule_still_splits_the_block_around_it() -> None:
    # Codex and AGY round 6: <hr hidden> inside a list item fused the sentences on each side.
    assert _article_texts("<ul><li>Run this command.<hr hidden>Then check the status.</li></ul>") == [
        "run this command",
        "then check the status",
    ]
    assert _article_texts('<blockquote>One<hr aria-hidden="true">Two.</blockquote>') == ["one", "two"]


def test_replay_cleanup_keeps_the_split_where_it_removes_a_block() -> None:
    # Codex and AGY round 6: stripping a dropped block from a list item, cell or quote
    # joined the text on each side, so replay and direct extraction disagreed.
    for html in (
        "<ul><li>Run this command.<div hidden>Draft</div>Then check the status.</li></ul>",
        "<ul><li>Run this command.<nav><a href='/'>Home</a></nav>Then check the status.</li></ul>",
        "<blockquote>Run this command.<aside>Skip</aside>Then check the status.</blockquote>",
        "<table><tr><td>Run this command.<aside>Skip</aside>Then check the status.</td></tr></table>",
    ):
        assert _replay_texts(f"<main>{html}</main>") == _article_texts(html), html
        assert _article_texts(html) == ["run this command", "then check the status"], html


def test_replay_extraction_handles_unclosed_cells_and_titles() -> None:
    # Round 6 AGY: an unclosed <td> left <main> unfinished, and an unclosed <h1> inside the
    # markdown body was repeated.
    assert _replay_texts("<main><table><tr><td>cell") == ["cell"]
    replay = '<main><div class="sl-markdown-content"><h1>Title<p>Body.</p></div></main>'
    assert _replay_texts(replay) == ["title", "body"]


def test_an_optional_colgroup_end_tag_is_implied_before_the_rows() -> None:
    assert _article_texts("<table><colgroup hidden><col><tr><td>Visible</td></tr></table>") == ["visible"]


def test_stray_end_tags_after_deeply_nested_dropped_content_extract_without_error() -> None:
    # Codex round 6 / Round 8: iterative walk handles deeply nested dropped subtrees without recursion errors.
    html = "<p>First</p><span><svg>" + "<div>" * 8000 + "</span>" * 8000
    assert _article_texts(html) == ["first"]


def test_saved_article_fragment_uses_standards_mode() -> None:
    for table, expected in [("<table>", ["alpha", "cell"]), ("<table hidden>", ["alpha"])]:
        fragment = f"<article><p>Alpha{table}<tr><td>Cell</td></tr></table><a>Subscribe</a></article>"
        assert _texts(fragment) == expected


def test_replay_document_honors_its_original_doctype() -> None:
    page = "<html><body><main><p>Alpha<table><tr><td>Cell</td></tr></table>Tail words here.</p></main></body></html>"
    assert _replay_texts(page) == ["alpha", "cell", "tail words here"]
    assert _replay_texts("<!doctype html>" + page) == ["alpha", "cell"]

    hidden_table = "<main><p>Alpha<table hidden><tr><td>Cell</td></tr></table><a>Beta</a></p></main>"
    assert _replay_texts(hidden_table) == ["alpha", "beta"]

    wrapped = "<main><p>Alpha <span>before <table><tr><td>Cell</td></tr></table> after</span> tail</p></main>"
    assert _replay_texts(wrapped) == ["alpha before", "cell", "after tail"]

    inline_markdown = '<main><p><span class="sl-markdown-content">Alpha<table><tr><td>Cell</td></tr></table>Tail</span></p></main>'
    assert _replay_texts(inline_markdown) == ["alpha", "cell", "tail"]


def test_many_quirks_tables_in_one_paragraph_hoist_with_constant_parser_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    real_parser = extract.LexborHTMLParser

    def counting_parser(html: str, *args: object, **kwargs: object) -> extract.LexborHTMLParser:
        nonlocal calls
        calls += 1
        return real_parser(html, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(extract, "LexborHTMLParser", counting_parser)
    n = 2000
    page = "<main><p>" + ("w<table><tr><td>c</td></tr></table>") * n + "end</p></main>"
    article = extract_article_html(page)
    # 1 initial parse of full replay HTML plus at most a tiny constant for shell cloning.
    assert calls <= 10
    expected = ["w", "c"] * n + ["end"]
    assert _texts(article) == expected


def test_quirks_table_hoisting_edge_wrappers_and_barriers() -> None:
    # Adjacent tables, leading/trailing tables, id stripping, and barrier isolation.
    html = (
        '<main><p id="p1">'
        '<table><tr><td>t1</td></tr></table>'
        '<span id="s1" class="hl">a<table><tr><td>t2</td></tr></table><table><tr><td>t3</td></tr></table>b</span>'
        '<button>ignore<table><tr><td>inner</td></tr></table></button>'
        '<table><tr><td>t4</td></tr></table>'
        "</p></main>"
    )
    article = extract_article_html(html)
    assert article.count('id="p1"') <= 1
    assert article.count('id="s1"') <= 1
    assert article.count('class="hl"') == 2
    assert _texts(article) == ["t1", "a", "t2", "t3", "b", "t4"]

    # Non-chrome _P_SCOPE_BARRIERS inside <p>: outer table hoists out of <p>, while inner table
    # stops at the <td>/<table> barrier and stays inside the outer <td>.
    nested_html = (
        '<main><p id="p2">before'
        "<table><tr><td>outer<table><tr><td>nested</td></tr></table>after_inner</td></tr></table>"
        "after_outer</p></main>"
    )
    nested_article = extract_article_html(nested_html)
    assert _texts(nested_article) == ["before", "outer", "nested", "after_inner", "after_outer"]
    nested_doc = extract.LexborHTMLParser("<!doctype html>" + nested_article)
    assert nested_doc.css_first("p table") is None
    assert nested_doc.css_first("td > table") is not None

    # Non-chrome <object> barrier stops hoisting inside <p> as well.
    object_html = (
        "<main><p>before<object>wrap<table><tr><td>inner</td></tr></table>tail</object>after</p></main>"
    )
    object_article = extract_article_html(object_html)
    assert _texts(object_article) == ["beforewrap", "inner", "tailafter"]
    object_doc = extract.LexborHTMLParser("<!doctype html>" + object_article)
    assert object_doc.css_first("p > object table") is not None

    # A nested <p> inside an outer hoisted table's <td> also hoists its own inner table inside <td>.
    nested_p_html = (
        '<main><p id="op">oa'
        '<table><tr><td><p id="ip">ia<table><tr><td>deep</td></tr></table>ib</p></td></tr></table>'
        "ob</p></main>"
    )
    nested_p_article = extract_article_html(nested_p_html)
    assert _texts(nested_p_article) == ["oa", "ia", "deep", "ib", "ob"]
    nested_p_doc = extract.LexborHTMLParser("<!doctype html>" + nested_p_article)
    assert nested_p_doc.css_first("p table") is None
    assert nested_p_doc.css_first("td > p#ip") is not None
    assert nested_p_doc.css_first("td > table") is not None


def test_quirks_table_hoisting_root_paragraph_and_whitespace_shells() -> None:
    # When sl-markdown-content is nested inside <p>, _serialize_element runs _split_quirks_tables
    # with root=<p> directly.
    root_p_html = (
        '<main><p id="p1" class="lead"><span class="sl-markdown-content">'
        "<table><tr><td>t0</td></tr></table>"
        "lead"
        "<table><tr><td>t1</td></tr></table>"
        "<table><tr><td>t2</td></tr></table>"
        "tail"
        "</span></p></main>"
    )
    root_p_article = extract_article_html(root_p_html)
    assert root_p_article.count('id="p1"') <= 1
    assert root_p_article.count('class="lead"') == 2
    assert root_p_article.count('class="sl-markdown-content"') == 2
    assert _texts(root_p_article) == ["t0", "lead", "t1", "t2", "tail"]

    root_p_doc = extract.LexborHTMLParser("<!doctype html>" + root_p_article)
    article_node = root_p_doc.css_first("article")
    assert article_node is not None
    top_tags = [
        child.tag
        for child in extract._children(article_node)
        if child.is_element_node
    ]
    assert top_tags == ["table", "p", "table", "table", "p"]

    # When root=<p> holds only hoisted tables, the empty <p> is decomposed completely.
    only_tables_html = (
        '<main><p id="p1" class="lead"><span class="sl-markdown-content">'
        "<table><tr><td>t1</td></tr></table><table><tr><td>t2</td></tr></table>"
        "</span></p></main>"
    )
    only_tables_article = extract_article_html(only_tables_html)
    assert 'id="p1"' not in only_tables_article
    assert "<p" not in only_tables_article
    assert _texts(only_tables_article) == ["t1", "t2"]

    # Whitespace-only sibling/split shells preserve spacing and document order around tables.
    spaced = "<main><p><span>a</span><span> </span><span>b</span><table><tr><td>x</td></tr></table></p></main>"
    assert _texts(spaced) == ["a b", "x"]

    ws_between = "<main><p><span>a</span><span> </span><table><tr><td>x</td></tr></table><span>b</span></p></main>"
    ws_between_article = extract_article_html(ws_between)
    assert _texts(ws_between_article) == ["a", "x", "b"]
    ws_doc = extract.LexborHTMLParser("<!doctype html>" + ws_between_article)
    ws_article_node = ws_doc.css_first("article")
    assert ws_article_node is not None
    assert [
        c.tag for c in extract._children(ws_article_node) if c.is_element_node
    ] == ["p", "table", "p"]

    ws_split_shell = (
        '<main><p><span>a</span><span class="sp"> <table><tr><td>x</td></tr></table> </span>'
        "<span>b</span></p></main>"
    )
    ws_split_article = extract_article_html(ws_split_shell)
    assert ws_split_article.count('class="sp"') == 2
    assert _texts(ws_split_article) == ["a", "x", "b"]


def test_hidden_html_root_drops_all_prose_and_replay_containers() -> None:
    for root_attrs in (
        "hidden",
        'aria-hidden="true"',
        'class="sr-only"',
        'id="wm-ipp-base"',
    ):
        assert extract_sentences(f"<html {root_attrs}><p>Hidden page.</p></html>") == [], root_attrs
        with pytest.raises(ValueError, match="No <main> or <article> container found"):
            extract_article_html(f"<html {root_attrs}><main><p>Hidden page.</p></main></html>")


def test_search_element_splits_prose_directly_and_through_replay() -> None:
    for html in (
        "<ul><li>Run this command.<search hidden>Find</search>Then check the status.</li></ul>",
        "<table><tr><td>Run this command.<search hidden>Find</search>Then check the status.</td></tr></table>",
        '<blockquote>Run this command.<search aria-hidden="true">Find</search>Then check the status.</blockquote>',
    ):
        assert _article_texts(html) == ["run this command", "then check the status"], html
        assert _replay_texts(f"<main>{html}</main>") == ["run this command", "then check the status"], html

    visible = "<ul><li>Run this command.<search>Find</search>Then check the status.</li></ul>"
    assert _article_texts(visible) == ["run this command", "find", "then check the status"]
    assert _replay_texts(f"<main>{visible}</main>") == ["run this command", "find", "then check the status"]

    closes_p = "<p>Alpha<search hidden>Find</search><a href='/rss.xml'>Subscribe</a>"
    assert _article_texts(closes_p) == ["alpha"]
    assert _replay_texts(f"<main>{closes_p}</main>") == ["alpha"]


def test_replay_preserves_markdown_wrapper_title_ancestry_and_rejects_chrome_only_titles() -> None:
    assert _replay_texts('<main><table class="sl-markdown-content"><tr><td>Cell text.</td></tr></table></main>') == [
        "cell text"
    ]
    assert _replay_texts('<main><table><tr><td class="sl-markdown-content">Cell text.</td></tr></table></main>') == [
        "cell text"
    ]
    assert _replay_texts('<main><p class="sl-markdown-content">Body <strong>bold</strong> text.</p></main>') == [
        "body bold text"
    ]
    assert _replay_texts('<main><strong class="sl-markdown-content">Headline</strong></main>') == ["headline"]
    assert _replay_texts('<main><h1 class="sl-markdown-content">Title <strong>Sub</strong></h1></main>') == [
        "title sub"
    ]
    assert _replay_texts('<main><h1>Title <div class="sl-markdown-content"><p>Body.</p></div></h1></main>') == [
        "title",
        "body",
    ]

    for empty_title in (
        '<main><h1><button>Copy</button></h1><div class="sl-markdown-content"><nav>Nav</nav></div></main>',
        '<main><h1><span class="sr-only">Hidden</span></h1><div class="sl-markdown-content"><nav>Nav</nav></div></main>',
        '<main><h1><div hidden>Draft</div></h1><div class="sl-markdown-content"><nav>Nav</nav></div></main>',
        '<main><h1 class="sl-markdown-content"><span><button>Copy</button></span></h1></main>',
        '<main><h1><a href="#"><span class="sr-only">Link</span></a></h1><div class="sl-markdown-content"><nav>Nav</nav></div></main>',
        '<main><h1><span class="icon"></span></h1><div class="sl-markdown-content"><nav>Nav</nav></div></main>',
    ):
        with pytest.raises(ValueError, match="Extracted article HTML is empty"):
            extract_article_html(empty_title)

    article = extract_article_html(
        '<main><h1><button>Copy</button></h1><div class="sl-markdown-content"><p>Body.</p></div></main>'
    )
    assert "<h1>" not in article
    assert _texts(article) == ["body"]

    empty_wrapper_title = extract_article_html(
        '<main><h1><span class="icon"></span></h1><div class="sl-markdown-content"><p>Body.</p></div></main>'
    )
    assert "<h1>" not in empty_wrapper_title
    assert _texts(empty_wrapper_title) == ["body"]

    code_article = extract_article_html("<main><pre><code>User-agent: GPTBot</code></pre></main>")
    assert "User-agent: GPTBot" in code_article
    assert _texts(code_article) == []


def test_inline_markdown_wrapper_inside_prose_block_keeps_enclosing_prose() -> None:
    cases = [
        ('<main><p><span class="sl-markdown-content">Body.</span></p></main>', ["body"]),
        ('<main><p>Before <span class="sl-markdown-content">Inside</span> after.</p></main>', ["before inside after"]),
        ('<main><ul><li><div class="sl-markdown-content">Body.</div></li></ul></main>', ["body"]),
        (
            '<main><table><tr><td>Before <span class="sl-markdown-content">Cell</span> after</td></tr></table></main>',
            ["before cell after"],
        ),
        ('<main><p>Before <strong class="sl-markdown-content">Bold</strong> after.</p></main>', ["before bold after"]),
        ('<main><strong><span class="sl-markdown-content">Headline</span></strong></main>', ["headline"]),
        ('<main><h1>Title</h1><p><span class="sl-markdown-content">Body.</span></p></main>', ["title", "body"]),
    ]
    for html, expected in cases:
        assert _replay_texts(html) == expected, html


def test_strong_outside_any_prose_block_and_closed_details_are_visible_prose() -> None:
    assert _article_texts("<div><strong>Card headline</strong><p>Card body.</p></div>") == [
        "card headline",
        "card body",
    ]
    assert _article_texts("<div><strong>Bold label</strong></div>") == ["bold label"]
    assert _article_texts(
        "<details><summary>More</summary><p>Expanded prose.</p></details><details hidden><p>Hidden prose.</p></details>"
    ) == ["expanded prose"]


def test_nested_strong_inside_standalone_strong_stays_one_headline() -> None:
    assert _article_texts("<strong>Use <strong>robots.txt</strong> rules</strong><a href='/rss.xml'>Subscribe</a>") == [
        "use robots.txt rules"
    ]
    assert (
        _article_texts(
            "<strong>Use <em><strong>robots.txt</strong></em> rules</strong><a href='/rss.xml'>Subscribe</a>"
        )
        == ["use robots.txt rules"]
    )
    assert _article_texts("<strong>First</strong><strong>Second</strong>") == ["first", "second"]
    assert (
        _article_texts("<strong>Headline <p>Para</p> tail</strong><a href='/rss.xml'>Subscribe</a>")
        == ["headline", "para", "tail"]
    )
    assert _article_texts("<p>Use <strong><strong>robots.txt</strong></strong> rules.</p>") == [
        "use robots.txt rules"
    ]


def test_strong_inside_link_span_or_summary_outside_prose_block_is_not_prose() -> None:
    from pathlib import Path

    # Outside any prose block, <strong> wrapped in <a>, <span>, or <summary> is not prose.
    assert _article_texts('<a class="button" href="#"><strong>Get started</strong></a><p>Body.</p>') == [
        "body"
    ]
    assert _article_texts("<span><strong>Badge</strong></span><p>Body.</p>") == ["body"]
    assert _article_texts(
        "<details><summary><strong>More</strong></summary><p>Expanded prose.</p></details>"
    ) == ["expanded prose"]
    assert _article_texts(
        '<div><a href="#"><strong>Link CTA</strong></a><span><strong>Tag</strong></span></div>'
    ) == []

    # Replay extraction agrees, including when sl-markdown-content is on an outer container
    # or on a wrapper around <strong>.
    assert _replay_texts(
        '<main><div class="sl-markdown-content">'
        '<a class="button" href="#"><strong>Get started</strong></a>'
        "<span><strong>Badge</strong></span>"
        "<details><summary><strong>More</strong></summary><p>Expanded prose.</p></details>"
        "</div></main>"
    ) == ["expanded prose"]
    assert _replay_texts(
        '<main><a href="#"><span class="sl-markdown-content"><strong>Link CTA</strong></span></a>'
        "<p>Body.</p></main>"
    ) == []
    assert _replay_texts(
        '<main><a href="#"><strong><span class="sl-markdown-content">Link CTA</span></strong></a>'
        "<p>Body.</p></main>"
    ) == []
    assert _replay_texts(
        '<main><span><strong><span class="sl-markdown-content">Badge</span></strong></span></main>'
    ) == []
    assert _replay_texts(
        '<main><details><summary><strong><span class="sl-markdown-content">More</span></strong></summary>'
        "<p>Expanded prose.</p></details></main>"
    ) == []

    # Inside a prose block (<p>, <li>, etc.), <strong> inside <a> or <span> still counts as prose.
    assert _article_texts('<p><a href="#"><strong>AI Audit</strong></a></p>') == ["ai audit"]
    assert _article_texts("<ul><li><span><strong>Item</strong></span></li></ul>") == ["item"]
    assert _replay_texts(
        '<main><div class="sl-markdown-content">'
        '<p><a href="#"><strong>AI Audit</strong></a></p>'
        "<ul><li><span><strong>Item</strong></span></li></ul>"
        "</div></main>"
    ) == ["ai audit", "item"]

    # Standalone <strong> directly inside <article>, <main>, or layout <div>/<section>
    # (including nested <strong><em><strong>...</strong></em></strong>) still counts.
    assert _article_texts("<section><div><strong>Section headline</strong></div></section>") == [
        "section headline"
    ]
    assert _article_texts("<div><strong><em><strong>Nested headline</strong></em></strong></div>") == [
        "nested headline"
    ]
    assert _replay_texts(
        '<main><strong><span class="sl-markdown-content">Headline</span></strong></main>'
    ) == ["headline"]

    # All 8 bundled HTML fixtures still extract 299 sentences across the 8 files.
    repo_root = Path(__file__).resolve().parents[1]
    fixture_files = sorted((repo_root / "fixtures").glob("*/*/*.html"))
    assert len(fixture_files) == 8
    total_sentences = sum(
        len(extract_sentences(path.read_text(encoding="utf-8"))) for path in fixture_files
    )
    assert total_sentences == 299

