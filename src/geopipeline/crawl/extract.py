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

# ADR 0018: the only elements whose text counts as prose (plus a standalone <strong>).
PROSE_BLOCK_TAGS = frozenset(
    {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "th", "td", "figcaption"}
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
# the blocks above plus every other element that closes an open <p> in HTML.
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

SENTENCE_SPLIT_RE = re.compile(
    r"(?:(?<=[.!?])|(?<=[.!?][\"'\u201d\u2019)\]]))"
    r"(?<!\be\.g\.)(?<!\bi\.e\.)(?<!\betc\.)\s+"
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
    child = node.child
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


def _prose_blocks(root: LexborNode) -> list[str]:
    """Collect visible prose blocks (ADR 0018).

    Text counts only inside a prose block or a <strong> outside any prose block. Hidden
    content, UI controls, chrome and <pre> code blocks are skipped, and a skipped block
    still ends the text before it. A visible <br> is a space.
    """
    blocks: list[str] = []
    current: list[str] = []
    collecting = 0
    opened: list[bool] = []

    def flush() -> None:
        text = "".join(current).strip()
        if text:
            blocks.append(text)
        current.clear()

    for kind, _, value in _walk(root, PROSE_SKIP_TAGS):
        if kind == "text":
            if collecting:
                current.append(value)
        elif kind == "skip":
            if value in _SPLIT_TAGS:
                flush()
        elif kind == "start":
            collects = value in PROSE_BLOCK_TAGS or (value == "strong" and not collecting)
            opened.append(collects)
            if collects or value in _SPLIT_TAGS:
                flush()
            if value == "br" and collecting:
                current.append(" ")
            if collects:
                collecting += 1
        elif kind == "end":
            collects = opened.pop()
            if collects:
                collecting -= 1
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


def _contains(ancestor: LexborNode, node: LexborNode) -> bool:
    current: LexborNode | None = node
    while current is not None:
        if current == ancestor:
            return True
        current = current.parent
    return False


def _strip_chrome(root: LexborNode) -> int:
    """Remove chrome (Wayback toolbars, nav, scripts, buttons, sr-only) and comments in place.

    A removed block leaves an empty element of the same tag without attributes, so the
    prose collector still splits the text around it as it does on the original page.
    Returns how many elements were kept, not counting those empty placeholders.
    """
    kept = 0
    removed: list[tuple[LexborNode, str]] = []
    for kind, node, tag in _walk(root, CHROME_TAGS):
        if kind == "start" and node is not root:
            kept += 1
        elif kind in ("skip", "comment"):
            removed.append((node, tag))
    for node, tag in removed:
        if tag in _SPLIT_TAGS:
            node.inner_html = ""
            for name in list(node.attrs):
                del node.attrs[name]
        else:
            node.decompose()
    return kept


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
        title = _find_first(container, lambda _, tag: tag == "h1")
        if title is not None and _contains(title, markdown):
            body = title
        else:
            if title is not None and not _contains(markdown, title):
                if _strip_chrome(title) or title.text(deep=True).strip():
                    parts.append((title.html or "").strip())
            body = markdown
        emit_outer = True
    else:
        body = container
        emit_outer = False
    if _strip_chrome(body) or body.text(deep=True).strip():
        fragment = ((body.html if emit_outer else body.inner_html) or "").strip()
        if emit_outer and body.tag in _TABLE_PART_TAGS:
            fragment = f"<table>{fragment}</table>"
        if fragment:
            parts.append(fragment)
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
