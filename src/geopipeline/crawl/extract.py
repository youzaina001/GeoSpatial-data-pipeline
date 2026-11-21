# HTML article and prose sentence extractor
"""Select article HTML from Wayback replay pages and extract normalized prose sentences."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser

VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

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

# Omitted end tags follow the HTML tree-building rules that matter for prose.
# Opening any of these closes an open <p>.
_P_CLOSERS = frozenset(
    {
        "address", "article", "aside", "blockquote", "center", "details", "dialog", "dir",
        "div", "dl", "dd", "dt", "fieldset", "figcaption", "figure", "footer", "form",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "li", "listing",
        "main", "menu", "nav", "ol", "p", "pre", "section", "summary", "table", "ul", "xmp",
    }
)
# Structural elements. An end tag for any other (inline) element stops at one of these
# and is ignored, so </span> never closes the <p> it wraps.
_SPECIAL_TAGS = _P_CLOSERS | HIDDEN_TAGS | frozenset(
    {
        "body", "button", "caption", "html", "select",
        "table", "tbody", "td", "tfoot", "th", "thead", "tr",
    }
)
# No implied or end-tag closing reaches past these. A <button> also stops an implied </p>.
_SCOPE_TAGS = frozenset({"caption", "html", "table", "td", "template", "th"})
_BUTTON_SCOPE = _SCOPE_TAGS | {"button"}
# Skipped content that is not page flow. Inside one of these no start tag closes an element
# outside it, and only a structural end tag other than </p> reaches past it.
_OPAQUE_TAGS = HIDDEN_TAGS | frozenset({"button", "label", "option", "select", "svg"})
# Opening or closing any of these ends the current prose block, even when it is dropped.
_SPLIT_TAGS = BLOCK_BOUNDARY_TAGS | _P_CLOSERS
_TABLE_SECTION = frozenset({"thead", "tbody", "tfoot"})
_TABLE_PARTS = _TABLE_SECTION | frozenset({"caption", "table", "td", "th", "tr"})
# Opening the key closes an open sibling. List items stop at a structural element other
# than address, div and p. Table parts stop at the element that holds them.
_LIST_SIBLINGS: dict[str, frozenset[str]] = {
    "li": frozenset({"li"}),
    "dt": frozenset({"dt", "dd"}),
    "dd": frozenset({"dt", "dd"}),
}
_TABLE_SIBLINGS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "td": (frozenset({"td", "th", "caption"}), frozenset({"tr", "table", "template"})),
    "th": (frozenset({"td", "th", "caption"}), frozenset({"tr", "table", "template"})),
    "tr": (frozenset({"tr", "td", "th", "caption"}), _TABLE_SECTION | {"table", "template"}),
    **{
        section: (_TABLE_SECTION | {"tr", "td", "th", "caption"}, frozenset({"table", "template"}))
        for section in _TABLE_SECTION
    },
}

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


def _has_class(attrs: list[tuple[str, str | None]], target: str) -> bool:
    for key, value in attrs:
        if key == "class" and value is not None and target in value.split():
            return True
    return False


def _get_attr(attrs: list[tuple[str, str | None]], name: str) -> str | None:
    for key, value in attrs:
        if key == name:
            return value
    return None


def _is_hidden(attrs: list[tuple[str, str | None]]) -> bool:
    if any(key == "hidden" for key, _ in attrs):
        return True
    aria_hidden = _get_attr(attrs, "aria-hidden")
    return aria_hidden is not None and aria_hidden.strip().lower() == "true"


def _is_skipped_element(
    tag: str,
    attrs: list[tuple[str, str | None]],
    *,
    skip_tags: frozenset[str],
) -> bool:
    if tag in skip_tags or _is_hidden(attrs):
        return True
    if _get_attr(attrs, "id") in WAYBACK_CHROME_IDS:
        return True
    return _has_class(attrs, "sr-only")


@dataclass(frozen=True, slots=True)
class _Open:
    """One open element. ``collects`` means its text is kept: prose, or the stripper's output."""

    tag: str
    skipped: bool = False
    collects: bool = False
    block: bool = False

    @property
    def opaque(self) -> bool:
        return self.skipped and self.tag in _OPAQUE_TAGS


class _OpenElements:
    """Every open element, closed by the HTML rules for omitted end tags that matter here.

    The prose collector, the article selector and the chrome stripper share these rules,
    so the three steps agree on where each element ends. Counters keep each tag linear
    in the page size outside the bounded scope walks.
    """

    def __init__(self, on_close: Callable[[list[_Open], int], None]) -> None:
        self._stack: list[_Open] = []
        self._tag_counts: dict[str, int] = {}
        self._opaque: list[int] = []
        self._on_close = on_close
        self.collecting = 0
        self.skipping = 0
        self.blocks = 0

    def __len__(self) -> int:
        return len(self._stack)

    def _count(self, entry: _Open, step: int) -> None:
        self._tag_counts[entry.tag] = self._tag_counts.get(entry.tag, 0) + step
        self.collecting += step * entry.collects
        self.skipping += step * entry.skipped
        self.blocks += step * entry.block

    def push(self, entry: _Open) -> None:
        if entry.opaque:
            self._opaque.append(len(self._stack))
        self._stack.append(entry)
        self._count(entry, 1)

    def _close_to(self, index: int) -> None:
        popped = self._stack[index:]
        del self._stack[index:]
        while self._opaque and self._opaque[-1] >= index:
            self._opaque.pop()
        for entry in popped:
            self._count(entry, -1)
        self._on_close(popped, index)

    def _floor(self) -> int:
        """Lowest index a start tag may close: nothing at or below opaque skipped content."""
        return self._opaque[-1] + 1 if self._opaque else 0

    def _is_open(self, tags: frozenset[str]) -> bool:
        return any(self._tag_counts.get(tag, 0) for tag in tags)

    def close_implied(self, tag: str) -> None:
        """Apply the HTML rules for omitted end tags before ``tag`` opens."""
        floor = self._floor()
        if tag in _P_CLOSERS and self._tag_counts.get("p"):
            for idx in range(len(self._stack) - 1, floor - 1, -1):
                open_tag = self._stack[idx].tag
                if open_tag == "p":
                    self._close_to(idx)
                    break
                if open_tag in _BUTTON_SCOPE:
                    break
        siblings = _LIST_SIBLINGS.get(tag)
        if siblings is not None and self._is_open(siblings):
            for idx in range(len(self._stack) - 1, floor - 1, -1):
                open_tag = self._stack[idx].tag
                if open_tag in siblings:
                    self._close_to(idx)
                    return
                if open_tag in _SPECIAL_TAGS and open_tag not in {"address", "div", "p"}:
                    return
        table = _TABLE_SIBLINGS.get(tag)
        if table is not None and self._is_open(table[0]):
            table_siblings, scope = table
            target = None
            for idx in range(len(self._stack) - 1, floor - 1, -1):
                open_tag = self._stack[idx].tag
                if open_tag in scope:
                    break
                if open_tag in table_siblings:
                    target = idx
            if target is not None:
                self._close_to(target)

    def close_end(self, tag: str) -> None:
        """Close the element an end tag names, or ignore the tag as HTML would."""
        if not self._tag_counts.get(tag):
            return
        start = len(self._stack) - 1
        if self._opaque:
            # Inside opaque skipped content, an end tag closes what opened inside it.
            barrier = self._opaque[-1]
            for idx in range(start, barrier - 1, -1):
                if self._stack[idx].tag == tag:
                    self._close_to(idx)
                    return
            if tag == "p" or tag not in _SPECIAL_TAGS:
                return
            start = barrier - 1
        if tag not in _SPECIAL_TAGS:
            stop = _SPECIAL_TAGS
        elif tag in _TABLE_PARTS:
            stop = frozenset({"html", "table", "template"})
        else:
            stop = _SCOPE_TAGS
        for idx in range(start, -1, -1):
            entry = self._stack[idx]
            if entry.tag == tag:
                self._close_to(idx)
                return
            if entry.tag in stop and not entry.opaque:
                return


class _SubtreeExtractor(HTMLParser):
    """Extract the first matching element's outer and inner HTML outside skipped content."""

    def __init__(self, *, tag_name: str | None = None, class_name: str | None = None) -> None:
        super().__init__(convert_charrefs=False)
        self._tag_name = tag_name
        self._class_name = class_name
        self._open = _OpenElements(self._closed)
        self._target: int | None = None
        self._target_tag = ""
        self._closed_at: int | None = None
        self._done = False
        self._buf: list[str] = []
        self.outer_html: str | None = None
        self.inner_html: str | None = None

    def _matches(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if self._tag_name is not None and tag != self._tag_name:
            return False
        if self._class_name is not None and not _has_class(attrs, self._class_name):
            return False
        return True

    def _closed(self, popped: list[_Open], index: int) -> None:
        if self._target is not None and index <= self._target and self._closed_at is None:
            self._closed_at = index

    def _finish(self, *, by_own_end_tag: bool) -> None:
        self._done = True
        if by_own_end_tag:
            self.outer_html = "".join(self._buf)
            self.inner_html = "".join(self._buf[1:-1])
        else:
            # An omitted end tag: the token that closed it is not part of it.
            self.inner_html = "".join(self._buf[1:])
            self.outer_html = "".join(self._buf) + f"</{self._target_tag}>"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return
        raw = self.get_starttag_text() or f"<{tag}>"
        self._open.close_implied(tag)
        if self._closed_at is not None:
            self._finish(by_own_end_tag=False)
            return
        capturing = self._target is not None
        if tag in VOID_TAGS:
            if capturing:
                self._buf.append(raw)
            return
        # ADR 0018: the prose skip rules also decide where the article can be.
        skipped = _is_skipped_element(tag, attrs, skip_tags=PROSE_SKIP_TAGS)
        visible = not self._open.skipping and not skipped
        index = len(self._open)
        self._open.push(_Open(tag, skipped=skipped))
        if capturing:
            self._buf.append(raw)
        elif visible and self._matches(tag, attrs):
            self._target = index
            self._target_tag = tag
            self._buf = [raw]

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in VOID_TAGS and not self._open.skipping:
            # HTML ignores the slash on a non-void element: <div/> opens a <div>.
            self.handle_starttag(tag, attrs)
            return
        if not self._done and self._target is not None:
            self._buf.append(self.get_starttag_text() or f"<{tag}/>")

    def handle_endtag(self, tag: str) -> None:
        if self._done or tag in VOID_TAGS:
            return
        if self._target is not None:
            self._buf.append(f"</{tag}>")
        self._open.close_end(tag)
        if self._closed_at is not None:
            if self._closed_at == self._target:
                self._finish(by_own_end_tag=True)
            else:
                self._buf.pop()
                self._finish(by_own_end_tag=False)

    def handle_data(self, data: str) -> None:
        if not self._done and self._target is not None:
            self._buf.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._done and self._target is not None:
            self._buf.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._done and self._target is not None:
            self._buf.append(f"&#{name};")


class _ChromeStripper(HTMLParser):
    """Strip non-article chrome subtrees (Wayback toolbars, nav, scripts, buttons, sr-only).

    Every element it keeps gets an explicit end tag where HTML would close it, so the
    prose collector sees the same blocks without the dropped elements.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._open = _OpenElements(self._closed)
        self._out: list[str] = []

    def _closed(self, popped: list[_Open], index: int) -> None:
        for entry in reversed(popped):
            if entry.collects:
                self._out.append(f"</{entry.tag}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open.close_implied(tag)
        visible = not self._open.skipping
        skipped = _is_skipped_element(tag, attrs, skip_tags=CHROME_TAGS)
        if tag not in VOID_TAGS:
            self._open.push(_Open(tag, skipped=skipped, collects=visible and not skipped))
        if visible and not skipped:
            self._out.append(self.get_starttag_text() or f"<{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in VOID_TAGS or not self._open.skipping:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag not in VOID_TAGS:
            self._open.close_end(tag)

    def handle_data(self, data: str) -> None:
        if not self._open.skipping:
            self._out.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._open.skipping:
            self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._open.skipping:
            self._out.append(f"&#{name};")

    def result(self) -> str:
        return "".join(self._out).strip()


def _extract_first(
    source_html: str, *, tag_name: str | None = None, class_name: str | None = None
) -> tuple[str | None, str | None]:
    parser = _SubtreeExtractor(tag_name=tag_name, class_name=class_name)
    parser.feed(source_html)
    parser.close()
    return parser.outer_html, parser.inner_html


def _strip_chrome(fragment: str) -> str:
    stripper = _ChromeStripper()
    stripper.feed(fragment)
    stripper.close()
    return stripper.result()


def extract_article_html(full_replay_html: str) -> str:
    """Extract clean article HTML from a full Wayback replay page.

    Preserves headings, paragraphs, lists, links, inline <code>, and <pre> code blocks
    while omitting Wayback toolbars, site navigation, footers, buttons, and scripts.
    """
    _, main_inner = _extract_first(full_replay_html, tag_name="main")
    if main_inner is None:
        _, main_inner = _extract_first(full_replay_html, tag_name="article")
    if main_inner is None:
        raise ValueError("No <main> or <article> container found in replay HTML")

    _, markdown_inner = _extract_first(main_inner, class_name="sl-markdown-content")
    if markdown_inner is not None:
        h1_outer, _ = _extract_first(main_inner, tag_name="h1")
        parts: list[str] = []
        if h1_outer is not None and h1_outer not in markdown_inner:
            cleaned_h1 = _strip_chrome(h1_outer)
            if cleaned_h1:
                parts.append(cleaned_h1)
        cleaned_body = _strip_chrome(markdown_inner)
        if cleaned_body:
            parts.append(cleaned_body)
        content = "\n".join(parts)
    else:
        content = _strip_chrome(main_inner)

    if not content:
        raise ValueError("Extracted article HTML is empty")
    return f"<article>\n{content}\n</article>\n"


class _ProseBlockCollector(HTMLParser):
    """Collect visible prose blocks (ADR 0018).

    Text counts only inside a prose block or a <strong> outside any prose block.
    Hidden content, UI controls, chrome and <pre> code blocks are skipped. <br> is a
    space. convert_charrefs=True decodes character references exactly once.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._open = _OpenElements(self._closed)
        self._current: list[str] = []
        self.blocks: list[str] = []

    def _flush(self) -> None:
        if self._current:
            text = "".join(self._current).strip()
            if text:
                self.blocks.append(text)
            self._current.clear()

    def _closed(self, popped: list[_Open], index: int) -> None:
        if any(entry.collects for entry in popped):
            self._flush()

    def _void(self, tag: str, hidden: bool) -> None:
        self._open.close_implied(tag)
        if self._open.skipping or hidden:
            return
        if tag == "br":
            if self._open.collecting:
                self._current.append(" ")
        elif tag in _SPLIT_TAGS:
            self._flush()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        skipped = _is_skipped_element(tag, attrs, skip_tags=PROSE_SKIP_TAGS)
        if tag in VOID_TAGS:
            self._void(tag, skipped)
            return
        self._open.close_implied(tag)
        collects = False
        if not self._open.skipping:
            if not skipped and (
                tag in PROSE_BLOCK_TAGS or (tag == "strong" and not self._open.blocks)
            ):
                self._flush()
                collects = True
            elif tag in _SPLIT_TAGS:
                # A dropped block such as <pre> still ends the text before it.
                self._flush()
        self._open.push(_Open(tag, skipped, collects, collects and tag in PROSE_BLOCK_TAGS))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in VOID_TAGS or not self._open.skipping:
            # HTML ignores the slash on a non-void element: <div/> opens a <div>.
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if tag in _SPLIT_TAGS and not self._open.skipping:
            self._flush()
        self._open.close_end(tag)

    def handle_data(self, data: str) -> None:
        if not self._open.skipping and self._open.collecting:
            self._current.append(data)

    def finalize(self) -> list[str]:
        self._flush()
        return self.blocks


def _normalize_text(raw: str) -> str:
    normalized_quotes = raw.replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", normalized_quotes).strip()


def extract_sentences(article_html: str) -> list[Sentence]:
    """Extract normalized sentences from the visible prose blocks of article HTML (ADR 0018).

    Folds case to lowercase and keeps contractions, hyphenated words, and dotted
    technical tokens as single words.
    """
    collector = _ProseBlockCollector()
    collector.feed(article_html)
    collector.close()

    sentences: list[Sentence] = []
    for raw_block in collector.finalize():
        collapsed = _normalize_text(raw_block)
        if not collapsed:
            continue
        for part in SENTENCE_SPLIT_RE.split(collapsed):
            tokens = tuple(TOKEN_RE.findall(part.lower()))
            if not tokens:
                continue
            sentences.append(Sentence(normalized_text=" ".join(tokens), tokens=tokens))
    return sentences
