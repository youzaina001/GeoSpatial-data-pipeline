# HTML article and prose sentence extractor
"""Select article HTML from Wayback replay pages and extract normalized prose sentences."""

from __future__ import annotations

import html
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

CHROME_TAGS = frozenset(
    {
        "script",
        "style",
        "template",
        "noscript",
        "svg",
        "nav",
        "header",
        "footer",
        "aside",
        "button",
        "form",
    }
)

WAYBACK_CHROME_IDS = frozenset({"wm-ipp-base", "wm-ipp", "donato"})

PROSE_BLOCK_TAGS = frozenset(
    {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "li",
        "blockquote",
        "th",
        "td",
        "dt",
        "dd",
    }
)

CONTAINER_BREAK_TAGS = frozenset({"ul", "ol", "dl", "table", "div", "section", "article", "hr"})

PROSE_SKIP_TAGS = CHROME_TAGS | frozenset({"pre"})

SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[.!?])(?<!\be\.g\.)(?<!\bi\.e\.)(?<!\betc\.)\s+"
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


class _SubtreeExtractor(HTMLParser):
    """Extract the first matching element's inner HTML using proper HTML5 void-tag depth tracking."""

    def __init__(self, *, tag_name: str | None = None, class_name: str | None = None) -> None:
        super().__init__(convert_charrefs=False)
        self._tag_name = tag_name
        self._class_name = class_name
        self._depth = 0
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
        if self._depth == 0:
            if self._matches(tag, attrs):
                self._depth = 1
                self._buf = [raw]
            return
        if tag not in VOID_TAGS:
            self._depth += 1
        self._buf.append(raw)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done or self._depth == 0:
            return
        self._buf.append(self.get_starttag_text() or f"<{tag}/>")

    def handle_endtag(self, tag: str) -> None:
        if self._done or self._depth == 0 or tag in VOID_TAGS:
            return
        self._buf.append(f"</{tag}>")
        self._depth -= 1
        if self._depth == 0:
            self._done = True
            self.outer_html = "".join(self._buf)
            self.inner_html = "".join(self._buf[1:-1])

    def handle_data(self, data: str) -> None:
        if not self._done and self._depth > 0:
            self._buf.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._done and self._depth > 0:
            self._buf.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._done and self._depth > 0:
            self._buf.append(f"&#{name};")


class _ChromeStripper(HTMLParser):
    """Strip non-article chrome subtrees (Wayback toolbars, nav, scripts, buttons, sr-only)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._skip_depth = 0
        self._out: list[str] = []

    def _is_skipped_element(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag in CHROME_TAGS:
            return True
        elem_id = _get_attr(attrs, "id")
        if elem_id in WAYBACK_CHROME_IDS:
            return True
        return _has_class(attrs, "sr-only")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth > 0:
            if tag not in VOID_TAGS:
                self._skip_depth += 1
            return
        if self._is_skipped_element(tag, attrs):
            if tag not in VOID_TAGS:
                self._skip_depth = 1
            return
        self._out.append(self.get_starttag_text() or f"<{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth > 0 or self._is_skipped_element(tag, attrs):
            return
        self._out.append(self.get_starttag_text() or f"<{tag}/>")

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return
        self._out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._out.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._skip_depth == 0:
            self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._skip_depth == 0:
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
        if h1_outer is not None:
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
    """Collect visible prose blocks while dropping <pre> code blocks and chrome tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._block_stack: list[tuple[str, list[str]]] = []
        self.blocks: list[str] = []

    def _is_skipped(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag in PROSE_SKIP_TAGS:
            return True
        elem_id = _get_attr(attrs, "id")
        if elem_id in WAYBACK_CHROME_IDS:
            return True
        return _has_class(attrs, "sr-only")

    def _flush_top_text(self) -> None:
        if not self._block_stack:
            return
        chunks = self._block_stack[-1][1]
        if chunks:
            text = "".join(chunks).strip()
            if text:
                self.blocks.append(text)
            chunks.clear()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth > 0:
            if tag not in VOID_TAGS:
                self._skip_depth += 1
            return
        if self._is_skipped(tag, attrs):
            if tag not in VOID_TAGS:
                self._skip_depth = 1
            return
        if tag == "br":
            if self._block_stack:
                self._block_stack[-1][1].append(" ")
            return
        if tag in PROSE_BLOCK_TAGS:
            self._flush_top_text()
            self._block_stack.append((tag, []))
        elif tag in CONTAINER_BREAK_TAGS:
            self._flush_top_text()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth > 0:
            return
        if tag == "br" and self._block_stack:
            self._block_stack[-1][1].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag in PROSE_BLOCK_TAGS and self._block_stack:
            for idx in range(len(self._block_stack) - 1, -1, -1):
                if self._block_stack[idx][0] == tag:
                    while len(self._block_stack) > idx:
                        self._flush_top_text()
                        self._block_stack.pop()
                    break

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and self._block_stack:
            self._block_stack[-1][1].append(data)


def _normalize_text(raw: str) -> str:
    unescaped = html.unescape(raw)
    normalized_quotes = unescaped.replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", normalized_quotes).strip()


def extract_sentences(article_html: str) -> list[Sentence]:
    """Extract normalized prose sentences from article HTML.

    Drops <pre> code blocks, keeps inline <code> tokens inside prose, folds case
    to lowercase, and preserves contractions, hyphenated words, and dotted tokens.
    """
    collector = _ProseBlockCollector()
    collector.feed(article_html)
    collector.close()

    sentences: list[Sentence] = []
    for raw_block in collector.blocks:
        collapsed = _normalize_text(raw_block)
        if not collapsed:
            continue
        for part in SENTENCE_SPLIT_RE.split(collapsed):
            tokens = tuple(TOKEN_RE.findall(part.lower()))
            if not tokens:
                continue
            sentences.append(Sentence(normalized_text=" ".join(tokens), tokens=tokens))
    return sentences
