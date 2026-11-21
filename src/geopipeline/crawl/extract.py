# HTML article and prose sentence extractor
"""Select article HTML from Wayback replay pages and extract normalized prose sentences."""

from __future__ import annotations

import re
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


def _pop_matching(stack: list[str], tag: str) -> None:
    for idx in range(len(stack) - 1, -1, -1):
        if stack[idx] == tag:
            del stack[idx:]
            return


class _SubtreeExtractor(HTMLParser):
    """Extract the first matching element's outer/inner HTML using tag-stack tracking."""

    def __init__(self, *, tag_name: str | None = None, class_name: str | None = None) -> None:
        super().__init__(convert_charrefs=False)
        self._tag_name = tag_name
        self._class_name = class_name
        self._stack: list[str] = []
        self._ignore_stack: list[str] = []
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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return
        raw = self.get_starttag_text() or f"<{tag}>"
        if not self._stack:
            if self._ignore_stack:
                if tag not in VOID_TAGS:
                    self._ignore_stack.append(tag)
                return
            # ADR 0018: the prose skip rules also decide where the article can be.
            if _is_skipped_element(tag, attrs, skip_tags=PROSE_SKIP_TAGS):
                if tag not in VOID_TAGS:
                    self._ignore_stack.append(tag)
                return
            if self._matches(tag, attrs):
                self._stack.append(tag)
                self._buf = [raw]
            return
        if tag not in VOID_TAGS:
            self._stack.append(tag)
        self._buf.append(raw)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done or not self._stack:
            return
        self._buf.append(self.get_starttag_text() or f"<{tag}/>")

    def handle_endtag(self, tag: str) -> None:
        if self._done or tag in VOID_TAGS:
            return
        if not self._stack:
            if self._ignore_stack:
                _pop_matching(self._ignore_stack, tag)
            return
        self._buf.append(f"</{tag}>")
        _pop_matching(self._stack, tag)
        if not self._stack:
            self._done = True
            self.outer_html = "".join(self._buf)
            self.inner_html = "".join(self._buf[1:-1])

    def handle_data(self, data: str) -> None:
        if not self._done and self._stack:
            self._buf.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._done and self._stack:
            self._buf.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._done and self._stack:
            self._buf.append(f"&#{name};")


class _ChromeStripper(HTMLParser):
    """Strip non-article chrome subtrees (Wayback toolbars, nav, scripts, buttons, sr-only)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._skip_stack: list[str] = []
        self._out: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_stack:
            if tag not in VOID_TAGS:
                self._skip_stack.append(tag)
            return
        if _is_skipped_element(tag, attrs, skip_tags=CHROME_TAGS):
            if tag not in VOID_TAGS:
                self._skip_stack.append(tag)
            return
        self._out.append(self.get_starttag_text() or f"<{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_stack or _is_skipped_element(tag, attrs, skip_tags=CHROME_TAGS):
            return
        self._out.append(self.get_starttag_text() or f"<{tag}/>")

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if self._skip_stack:
            _pop_matching(self._skip_stack, tag)
            return
        self._out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._skip_stack:
            self._out.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._skip_stack:
            self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._skip_stack:
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
        self._skip_stack: list[str] = []
        self._block_depth = 0
        self._headline_depth = 0
        self._current: list[str] = []
        self.blocks: list[str] = []

    def _collecting(self) -> bool:
        return self._block_depth > 0 or self._headline_depth > 0

    def _flush(self) -> None:
        if self._current:
            text = "".join(self._current).strip()
            if text:
                self.blocks.append(text)
            self._current.clear()

    def _open(self, tag: str) -> None:
        if tag == "br":
            if self._collecting():
                self._current.append(" ")
            return
        if tag in PROSE_BLOCK_TAGS:
            self._flush()
            self._block_depth += 1
        elif tag == "strong" and self._block_depth == 0:
            self._flush()
            self._headline_depth += 1
        elif tag in BLOCK_BOUNDARY_TAGS:
            self._flush()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_stack:
            if tag not in VOID_TAGS:
                self._skip_stack.append(tag)
            return
        if _is_skipped_element(tag, attrs, skip_tags=PROSE_SKIP_TAGS):
            if tag not in VOID_TAGS:
                self._skip_stack.append(tag)
            return
        self._open(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_stack or _is_skipped_element(tag, attrs, skip_tags=PROSE_SKIP_TAGS):
            return
        if tag == "br":
            self._open(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if self._skip_stack:
            _pop_matching(self._skip_stack, tag)
            return
        if tag in PROSE_BLOCK_TAGS and self._block_depth > 0:
            self._flush()
            self._block_depth -= 1
        elif tag == "strong" and self._headline_depth > 0 and self._block_depth == 0:
            self._flush()
            self._headline_depth -= 1
        elif tag in BLOCK_BOUNDARY_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip_stack and self._collecting():
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
