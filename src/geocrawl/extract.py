# HTML article and prose sentence extractor
"""Select article HTML from Wayback replay pages and extract normalized prose sentences."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser, LexborNode

# Content a reader never sees: never prose and never a place to look for the article.
HIDDEN_TAGS = frozenset(
    {"script", "style", "template", "noscript", "iframe", "textarea"}
)

# UI controls and site chrome around or inside the article.
UI_TAGS = frozenset(
    {"button", "label", "select", "option", "input", "form", "nav", "svg", "header", "footer", "aside"}
)

CHROME_TAGS = HIDDEN_TAGS | UI_TAGS

# ADR 0018: the only elements whose text counts as prose (plus a standalone <strong>
# directly inside the article body or a layout <div>/<section>).
PROSE_BLOCK_TAGS = frozenset(
    {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "th", "td", "figcaption"}
)

_STANDALONE_STRONG_PARENTS = frozenset(
    {"article", "main", "div", "section", "html", "body", "-undef", ""}
)

WAYBACK_CHROME_IDS = frozenset({"wm-ipp-base", "wm-ipp", "donato"})

BLOCK_BOUNDARY_TAGS = frozenset(
    {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "li",
        "ul",
        "ol",
        "dl",
        "dt",
        "dd",
        "blockquote",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "div",
        "section",
        "article",
        "figure",
        "figcaption",
        "hr",
        "pre",
    }
)

PROSE_SKIP_TAGS = CHROME_TAGS | frozenset({"pre"})

# Opening or closing any of these ends the current prose block, even when it is dropped:
# the blocks above plus every other element that closes an open <p> in HTML (<plaintext> is
# omitted because an empty <plaintext></plaintext> placeholder consumes trailing markup).
_SPLIT_TAGS = BLOCK_BOUNDARY_TAGS | frozenset(
    {
        "address", "aside", "center", "details", "dialog", "dir", "fieldset", "footer",
        "form", "header", "hgroup", "listing", "main", "menu", "nav", "search", "summary",
        "xmp",
    }
)

_TABLE_PART_TAGS = frozenset(
    {"caption", "col", "colgroup", "thead", "tbody", "tfoot", "tr", "th", "td"}
)

# HTML "in p button scope" barriers used when hoisting quirks-mode <table> elements out of <p>.
_P_SCOPE_BARRIERS = frozenset(
    {
        "applet", "button", "caption", "html", "marquee", "math", "object",
        "svg", "table", "td", "th", "template",
    }
)

SENTENCE_SPLIT_RE = re.compile(
    r"""[.!?](?<!\be\.g\.)(?<!\bi\.e\.)(?<!\betc\.)["'\u201d\u2019)\]}]*\s+"""
)

# Keeps contractions (don't), hyphenated words (AI-ready), and dotted/underscored identifiers (robots.txt).
TOKEN_RE = re.compile(r"[^\W_]+(?:['._-][^\W_]+)*", flags=re.UNICODE)


@dataclass(frozen=True)
class Sentence:
    normalized_text: str
    tokens: tuple[str, ...]


def _parse(html: str) -> LexborHTMLParser:
    """Build the element tree a browser builds (ADR 0018).

    Lexbor follows the WHATWG tree-building rules, so omitted end tags, stray end tags,
    self-closing tags, misnested markup and <template> content resolve as in a browser.
    Scripting is on, as in a browser that runs the page, so <noscript> content is raw text.
    """
    return LexborHTMLParser(html, scripting=True)


def _is_skipped(node: LexborNode, tag: str, skip_tags: frozenset[str]) -> bool:
    if tag in skip_tags:
        return True
    attrs = node.attributes
    if "hidden" in attrs:
        return True
    if (attrs.get("aria-hidden") or "").strip().lower() == "true":
        return True
    if attrs.get("id") in WAYBACK_CHROME_IDS:
        return True
    return "sr-only" in (attrs.get("class") or "").split()


def _children(node: LexborNode) -> list[LexborNode]:
    children = []
    child = node.first_child
    while child is not None:
        children.append(child)
        child = child.next
    return children


def _walk(root: LexborNode, skip_tags: frozenset[str]) -> Iterator[tuple[str, LexborNode, str]]:
    """Yield ("start" | "end" | "skip", element, tag), ("text", node, text) and
    ("comment", node, "") in document order.

    A skipped element yields one "skip" event and none of its content. <template> content
    is not part of the tree, as in a browser. The walk keeps its own stack, so deeply
    nested pages never reach Python's recursion limit.
    """
    pending: list[tuple[str, LexborNode, str]] = [("node", root, "")]
    while pending:
        kind, node, value = pending.pop()
        if kind != "node":
            yield kind, node, value
            continue
        if node.is_text_node:
            yield "text", node, node.text_content or ""
            continue
        if not node.is_element_node:
            if node.is_comment_node:
                yield "comment", node, ""
            continue
        tag = node.tag or ""
        if _is_skipped(node, tag, skip_tags):
            yield "skip", node, tag
            continue
        yield "start", node, tag
        pending.append(("end", node, tag))
        pending.extend(("node", child, "") for child in reversed(_children(node)))


def _is_standalone_strong(node: LexborNode, container: LexborNode) -> bool:
    """Return True when every ancestor of ``node`` up to ``container`` is a layout container."""
    current = node.parent
    while current is not None and current != container:
        tag = current.tag or ""
        if tag != "strong" and tag not in _STANDALONE_STRONG_PARENTS:
            return False
        current = current.parent
    return True


def _prose_blocks(root: LexborNode) -> list[str]:
    """Collect visible prose blocks (ADR 0018).

    Text counts only inside a prose block or a <strong> outside any prose block when every
    open ancestor is a layout container (a <strong> nested inside a standalone <strong> stays
    part of that headline). Hidden content, UI controls, chrome and <pre> code blocks are
    skipped, and a skipped block still ends the text before it. A visible <br> is a space.
    """
    blocks: list[str] = []
    current: list[str] = []
    depth = 0
    collecting_depths: list[int] = []

    def flush() -> None:
        text = "".join(current).strip()
        if text:
            blocks.append(text)
        current.clear()

    for kind, node, value in _walk(root, PROSE_SKIP_TAGS):
        if kind == "text":
            if collecting_depths:
                current.append(value)
        elif kind == "skip":
            if value in _SPLIT_TAGS:
                flush()
        elif kind == "start":
            depth += 1
            collects = value in PROSE_BLOCK_TAGS or (
                value == "strong"
                and not collecting_depths
                and _is_standalone_strong(node, root)
            )
            if collects or value in _SPLIT_TAGS:
                flush()
            if value == "br" and collecting_depths:
                current.append(" ")
            if collects:
                collecting_depths.append(depth)
        elif kind == "end":
            collects = bool(collecting_depths and collecting_depths[-1] == depth)
            if collects:
                collecting_depths.pop()
            depth -= 1
            if collects or value in _SPLIT_TAGS:
                flush()
    flush()
    return blocks


def _find_first(root: LexborNode, predicate: Callable[[LexborNode, str], bool]) -> LexborNode | None:
    """First element inside ``root``, outside skipped content, that matches ``predicate``."""
    for kind, node, tag in _walk(root, PROSE_SKIP_TAGS):
        if kind == "start" and node is not root and predicate(node, tag):
            return node
    return None


def _is_or_contains(ancestor: LexborNode, node: LexborNode) -> bool:
    """Return True when ``node`` is ``ancestor`` or a descendant of ``ancestor``."""
    current: LexborNode | None = node
    while current is not None:
        if current == ancestor:
            return True
        current = current.parent
    return False


def _enclosing_prose_block(node: LexborNode, container: LexborNode) -> LexborNode | None:
    """Return the outermost prose-collecting ancestor of ``node`` inside ``container``,
    or the nearest non-layout wrapper when ``node`` sits inside one outside any prose block.
    """
    outermost_prose: LexborNode | None = None
    nearest_non_layout: LexborNode | None = None
    current = node.parent
    while current is not None and current != container:
        tag = current.tag or ""
        if tag in PROSE_BLOCK_TAGS or (
            tag == "strong" and _is_standalone_strong(current, container)
        ):
            outermost_prose = current
        elif nearest_non_layout is None and tag != "strong" and tag not in _STANDALONE_STRONG_PARENTS:
            nearest_non_layout = current
        current = current.parent
    return outermost_prose or nearest_non_layout


def _strip_chrome(root: LexborNode) -> bool:
    """Remove chrome (Wayback toolbars, nav, scripts, buttons, sr-only) and comments in place.

    A removed block leaves an empty element of the same tag without attributes, so the
    prose collector still splits the text around it as it does on the original page.
    Returns True when non-whitespace text remains inside ``root``.
    """
    removed: list[tuple[LexborNode, str]] = []
    for kind, node, tag in _walk(root, CHROME_TAGS):
        if kind in ("skip", "comment"):
            removed.append((node, tag))
    for node, tag in removed:
        if tag in _SPLIT_TAGS:
            node.inner_html = ""
            for name in list(node.attrs):
                del node.attrs[name]
        else:
            node.decompose()
    return bool(root.text(deep=True).strip())


_RAW_SHELL_SKIP_TAGS = frozenset(
    {
        "plaintext", "xmp", "script", "style", "textarea", "title", "iframe",
        "noscript", "noembed", "noframes", "frameset", "html", "head", "body",
    }
)


def _p_ancestor_in_scope(
    table: LexborNode,
    boundary: LexborNode | None,
    cache: dict[int, LexborNode | None] | None = None,
) -> LexborNode | None:
    path: list[int] = []
    result: LexborNode | None = None
    boundary_id = boundary.mem_id if boundary is not None else None
    current = table.parent
    while current is not None and current.mem_id != boundary_id:
        current_id = current.mem_id
        if cache is not None and current_id in cache:
            result = cache[current_id]
            break
        path.append(current_id)
        if current.tag == "p":
            result = current
            break
        if current.tag in _P_SCOPE_BARRIERS:
            result = None
            break
        current = current.parent
    if cache is not None:
        for node_id in path:
            cache[node_id] = result
    return result


def _build_shell_templates(tags: set[str]) -> tuple[LexborHTMLParser, dict[str, LexborNode]]:
    """Build reusable empty shell elements for wrapper tags in one parser call."""
    # Keep <span> first so a guaranteed fallback shell exists even if an unexpected tag drops.
    ordered_tags = ["span", *(sorted(t for t in tags if t != "span" and t not in _RAW_SHELL_SKIP_TAGS))]
    fragments = "".join(f"<div><{tag}></{tag}></div>" for tag in ordered_tags)
    shell_doc = LexborHTMLParser(f"<!doctype html>{fragments}")
    shells: dict[str, LexborNode] = {}
    body = shell_doc.body
    wrapper = body.first_child if body is not None else None
    for tag in ordered_tags:
        if wrapper is None:
            break
        child = wrapper.first_child
        if child is not None and child.tag == tag:
            shells[tag] = child
        wrapper = wrapper.next
    return shell_doc, shells


def _copy_non_id_attrs(
    source: LexborNode,
    target: LexborNode,
    attrs_cache: dict[int, tuple[tuple[str, str], ...]],
) -> None:
    source_id = source.mem_id
    attrs = attrs_cache.get(source_id)
    if attrs is None:
        attrs = tuple(
            (name, "" if value is None else value)
            for name, value in source.attributes.items()
            if name != "id"
        )
        attrs_cache[source_id] = attrs
    for name, value in attrs:
        target.attrs[name] = value


def _split_p_scope(
    p_ancestor: LexborNode,
    hoisted_tables: set[int],
    split_nodes: set[int],
    seen_p: set[int],
    shells: dict[str, LexborNode],
    attrs_cache: dict[int, tuple[tuple[str, str], ...]],
    capture_top_nodes: bool,
) -> list[LexborNode]:
    """Split one ``<p>`` scope in a single iterative walk around its hoisted tables."""
    ancestors: list[LexborNode] = []
    active: list[LexborNode | None] = []
    used: set[int] = set()
    last_top: LexborNode | None = None
    top_nodes: list[LexborNode] = []

    def ensure_active() -> LexborNode:
        nonlocal last_top
        assert active
        if (current := active[-1]) is not None:
            return current
        start = len(active)
        while start > 0 and active[start - 1] is None:
            start -= 1
        for i in range(start, len(ancestors)):
            anc = ancestors[i]
            anc_id = anc.mem_id
            if anc_id not in used:
                used.add(anc_id)
                if i == 0:
                    last_top = anc
                    if capture_top_nodes:
                        top_nodes.append(anc)
                else:
                    parent_out = active[i - 1]
                    assert parent_out is not None
                    anc_parent = anc.parent
                    if anc_parent is None or anc_parent.mem_id != parent_out.mem_id:
                        parent_out.insert_child(anc, move=True)
                active[i] = anc
            else:
                shell = shells.get(anc.tag or "span", shells["span"])
                if i == 0:
                    assert last_top is not None
                    last_top.insert_after(shell)
                    tail = last_top.next
                    assert tail is not None
                    last_top = tail
                    if capture_top_nodes:
                        top_nodes.append(tail)
                else:
                    parent_out = active[i - 1]
                    assert parent_out is not None
                    parent_out.insert_child(shell)
                    tail = parent_out.last_child
                    assert tail is not None
                _copy_non_id_attrs(anc, tail, attrs_cache)
                active[i] = tail
        assert active[-1] is not None
        return active[-1]

    stack: list[tuple[str, LexborNode]] = [("enter", p_ancestor)]
    while stack:
        kind, node = stack.pop()
        if kind == "exit":
            ancestors.pop()
            active.pop()
            if node.mem_id not in used:
                node.decompose()
            continue
        if kind == "enter":
            ancestors.append(node)
            active.append(None)
            stack.append(("exit", node))
            children = _children(node)
            stack.extend(("visit", child) for child in reversed(children))
            continue
        node_id = node.mem_id
        if node_id in hoisted_tables:
            if last_top is None:
                p_ancestor.insert_before(node, move=True)
            else:
                last_top.insert_after(node, move=True)
                last_top = node
            if capture_top_nodes:
                top_nodes.append(node)
            for i in range(len(active)):
                active[i] = None
        elif node_id in split_nodes and node_id not in seen_p:
            stack.append(("enter", node))
        else:
            target = ensure_active()
            node_parent = node.parent
            if node_parent is None or node_parent.mem_id != target.mem_id:
                target.insert_child(node, move=True)

    return top_nodes


def _split_quirks_tables(root: LexborNode) -> list[LexborNode]:
    """Hoist quirks-mode ``<table>`` elements out of enclosing ``<p>`` elements.

    In quirks mode a ``<table>`` does not close an open ``<p>``. Because ``extract_sentences``
    parses saved article fragments in standards mode, leaving ``<table>`` inside ``<p>`` would
    cause the standards-mode parser to implicitly close ``<p>`` at ``<table>`` and drop any
    trailing prose after it.
    """
    boundary = root.parent
    boundary_id = boundary.mem_id if boundary is not None else None
    root_id = root.mem_id
    tables: list[LexborNode] = []
    stack: list[LexborNode] = [root]
    while stack:
        node = stack.pop()
        if node.is_element_node:
            if node.tag == "table" and node.mem_id != root_id:
                tables.append(node)
            child = node.last_child
            while child is not None:
                stack.append(child)
                child = child.prev

    if not tables:
        return [root]

    p_scope_cache: dict[int, LexborNode | None] = {}
    hoisted_tables: set[int] = set()
    split_nodes: set[int] = set()
    p_ancestors: list[LexborNode] = []
    seen_p: set[int] = set()
    needed_tags: set[str] = set()

    for table in tables:
        p_ancestor = _p_ancestor_in_scope(table, boundary, p_scope_cache)
        if p_ancestor is None:
            continue
        hoisted_tables.add(table.mem_id)
        p_ancestor_id = p_ancestor.mem_id
        if p_ancestor_id not in seen_p:
            seen_p.add(p_ancestor_id)
            p_ancestors.append(p_ancestor)
        current: LexborNode | None = table.parent
        while current is not None and current.mem_id != boundary_id:
            current_id = current.mem_id
            if current_id in split_nodes:
                break
            split_nodes.add(current_id)
            needed_tags.add(current.tag or "span")
            if current_id == p_ancestor_id:
                break
            current = current.parent

    if not hoisted_tables:
        return [root]

    shell_doc, shells = _build_shell_templates(needed_tags)
    attrs_cache: dict[int, tuple[tuple[str, str], ...]] = {}
    top_nodes: list[LexborNode] = [root]
    for p_ancestor in p_ancestors:
        is_root_p = p_ancestor.mem_id == root_id
        split_out = _split_p_scope(
            p_ancestor,
            hoisted_tables,
            split_nodes,
            seen_p,
            shells,
            attrs_cache,
            capture_top_nodes=is_root_p,
        )
        if is_root_p:
            top_nodes = split_out
    del shell_doc
    return top_nodes


def _serialize_element(node: LexborNode) -> str | None:
    if not _strip_chrome(node):
        return None
    nodes = _split_quirks_tables(node)
    rendered = "\n".join(fragment for item in nodes if (fragment := (item.html or "").strip()))
    if not rendered:
        return None
    if len(nodes) == 1 and nodes[0].tag in _TABLE_PART_TAGS:
        return f"<table>{rendered}</table>"
    return rendered


def _serialize_contents(container: LexborNode) -> str | None:
    if not _strip_chrome(container):
        return None
    _split_quirks_tables(container)
    return (container.inner_html or "").strip() or None


def extract_article_html(full_replay_html: str) -> str:
    """Extract clean article HTML from a full Wayback replay page.

    Preserves headings, paragraphs, lists, links, inline <code>, and <pre> code blocks
    while omitting Wayback toolbars, site navigation, footers, buttons, and scripts.
    """
    document = _parse(full_replay_html)
    root = document.root
    if root is None:
        raise ValueError("No <main> or <article> container found in replay HTML")
    container = _find_first(root, lambda _, tag: tag == "main")
    if container is None:
        container = _find_first(root, lambda _, tag: tag == "article")
    if container is None:
        raise ValueError("No <main> or <article> container found in replay HTML")

    parts: list[str] = []
    markdown = _find_first(
        container,
        lambda node, _: "sl-markdown-content" in (node.attributes.get("class") or "").split(),
    )
    if markdown is not None:
        body = _enclosing_prose_block(markdown, container) or markdown
        title = _find_first(container, lambda _, tag: tag == "h1")
        if title is not None and not _is_or_contains(body, title):
            if rendered_title := _serialize_element(title):
                parts.append(rendered_title)
        if rendered_body := _serialize_element(body):
            parts.append(rendered_body)
    else:
        if rendered_container := _serialize_contents(container):
            parts.append(rendered_container)
    if not parts:
        raise ValueError("Extracted article HTML is empty")
    content = "\n".join(parts)
    return f"<article>\n{content}\n</article>\n"


def _normalize_text(raw: str) -> str:
    normalized_quotes = raw.replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", normalized_quotes).strip()


def extract_sentences(article_html: str) -> list[Sentence]:
    """Extract normalized sentences from the visible prose blocks of article HTML (ADR 0018).

    Folds case to lowercase and keeps contractions, hyphenated words, and dotted
    technical tokens as single words.
    """
    sentences: list[Sentence] = []
    # Saved fragments have no document mode of their own (ADR 0018).
    document = _parse("<!doctype html>" + article_html)
    root = document.root
    for raw_block in _prose_blocks(root) if root is not None else []:
        collapsed = _normalize_text(raw_block)
        if not collapsed:
            continue
        for part in SENTENCE_SPLIT_RE.split(collapsed):
            tokens = tuple(TOKEN_RE.findall(part.lower()))
            if not tokens:
                continue
            sentences.append(Sentence(normalized_text=" ".join(tokens), tokens=tokens))
    return sentences
