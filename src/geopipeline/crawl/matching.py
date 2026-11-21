# Corpus-wide word-run matching
"""Find new words by three-word runs against the whole earlier corpus and emit ADR 0018 table rows."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from geopipeline.crawl.extract import Sentence, extract_sentences
from geopipeline.crawl.manifest import CaptureEntry, SampleManifest

RUN_LENGTH = 3
CONTEXT_WORDS = RUN_LENGTH - 1
PageStatus = Literal["compared", "comparison_incomplete"]


@dataclass(frozen=True)
class PageRow:
    page_url: str
    status: PageStatus
    earlier_capture_url: str | None
    later_capture_url: str | None


@dataclass(frozen=True)
class PassageRow:
    page_url: str
    passage_id: str
    word_count: int


@dataclass(frozen=True)
class ExcludedPageDiagnostic:
    url: str
    captured_at: str
    failed_step: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "url": self.url,
            "captured_at": self.captured_at,
            "failed_step": self.failed_step,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MatchResult:
    pages: tuple[PageRow, ...]
    passages: tuple[PassageRow, ...]
    excluded_diagnostics: tuple[ExcludedPageDiagnostic, ...]


def passage_id_for(words: tuple[str, ...], left: tuple[str, ...], right: tuple[str, ...]) -> str:
    """Identify a new passage by its words, plus its neighbours when it is shorter than a run."""
    if len(words) >= RUN_LENGTH:
        key = " ".join(words)
    else:
        key = f"{' '.join(left)} [{' '.join(words)}] {' '.join(right)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


Tokens = tuple[str, ...]


@dataclass(frozen=True)
class NewPassage:
    passage_id: str
    word_count: int


class _EarlierCorpus:
    """Every run of up to RUN_LENGTH consecutive words inside an earlier sentence."""

    def __init__(self, earlier_pages: dict[str, list[Sentence]]) -> None:
        self.sentences: tuple[Tokens, ...] = tuple(
            sorted({sentence.tokens for sentences in earlier_pages.values() for sentence in sentences})
        )
        runs: set[Tokens] = set()
        anchors: dict[Tokens, list[tuple[int, int]]] = {}
        for index, tokens in enumerate(self.sentences):
            for length in range(1, RUN_LENGTH + 1):
                for pos in range(len(tokens) - length + 1):
                    run = tokens[pos : pos + length]
                    runs.add(run)
                    if length <= CONTEXT_WORDS:
                        anchors.setdefault(run, []).append((index, pos))
        self.runs = frozenset(runs)
        self.two_word_sentences = frozenset(s for s in self.sentences if len(s) == CONTEXT_WORDS)
        self._anchors = anchors

    def one_word_changes(self, tokens: Tokens) -> set[int]:
        """Changed positions of every earlier sentence that differs from tokens in one word only."""
        size = len(tokens)
        candidates = {i for i, pos in self._anchors.get(tokens[:1], []) if pos == 0}
        candidates |= {
            i for i, pos in self._anchors.get(tokens[-1:], []) if pos == len(self.sentences[i]) - 1
        }
        changes: set[int] = set()
        for index in candidates:
            earlier = self.sentences[index]
            if len(earlier) != size:
                continue
            changed = [pos for pos in range(size) if earlier[pos] != tokens[pos]]
            if len(changed) == 1:
                changes.add(changed[0])
        return changes

    def tails_after(self, anchor: Tokens) -> list[Tokens]:
        return [self.sentences[i][pos + len(anchor) :] for i, pos in self._anchors.get(anchor, [])]

    def heads_before(self, anchor: Tokens) -> list[Tokens]:
        return [self.sentences[i][:pos] for i, pos in self._anchors.get(anchor, [])]


def _common_prefix(a: Tokens, b: Tokens) -> int:
    count = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        count += 1
    return count


def _common_suffix(a: Tokens, b: Tokens) -> int:
    return _common_prefix(a[::-1], b[::-1])


def _covered_words(tokens: Tokens, corpus: _EarlierCorpus) -> list[bool]:
    """Mark later words covered by an earlier run, then align uncovered sentence edges (ADR 0018)."""
    size = len(tokens)
    covered = [False] * size
    width = min(RUN_LENGTH, size)
    for pos in range(size - width + 1):
        if tokens[pos : pos + width] in corpus.runs:
            covered[pos : pos + width] = [True] * width
    if all(covered):
        return covered

    # One changed word in a copy of an earlier sentence adds one word (glossary), even when
    # the edit leaves no run, or another sentence's run reaches past the changed word. Each
    # near copy covers every word but its changed one, so the order of near copies never matters.
    changes = corpus.one_word_changes(tokens) if size >= 2 else set()
    if changes:
        return [flag or changes != {pos} for pos, flag in enumerate(covered)]
    if not any(covered):
        return _cover_merged_pairs(tokens, covered, corpus)

    # Uncovered end: align with earlier sentences that continue from the same covered words.
    if not covered[-1]:
        start = max(i for i, flag in enumerate(covered) if flag) + 1
        anchor = tokens[max(0, start - CONTEXT_WORDS) : start]
        gap = tokens[start:]
        keep = max((_common_suffix(gap, tail) for tail in corpus.tails_after(anchor)), default=0)
        for i in range(size - keep, size):
            covered[i] = True

    # Uncovered start: align with earlier sentences that lead into the same covered words.
    if not covered[0]:
        end = covered.index(True)
        anchor = tokens[end : end + CONTEXT_WORDS]
        gap = tokens[:end]
        keep = max((_common_prefix(gap, head) for head in corpus.heads_before(anchor)), default=0)
        for i in range(keep):
            covered[i] = True
    return _cover_merged_pairs(tokens, covered, corpus)


def _cover_merged_pairs(tokens: Tokens, covered: list[bool], corpus: _EarlierCorpus) -> list[bool]:
    """Merged sentences: a two-word earlier sentence at one edge counts as earlier wording when
    the rest of the sentence holds earlier wording too. One-word headings never cover this way."""
    pair = CONTEXT_WORDS
    if len(tokens) <= pair:
        return covered
    starts = tokens[:pair] in corpus.two_word_sentences
    ends = tokens[-pair:] in corpus.two_word_sentences
    rest_after = ends or any(covered[pair:])
    rest_before = starts or any(covered[:-pair])
    if starts and rest_after:
        covered[:pair] = [True] * pair
    if ends and rest_before:
        covered[-pair:] = [True] * pair
    return covered


def _new_passages(tokens: Tokens, corpus: _EarlierCorpus) -> list[NewPassage]:
    covered = _covered_words(tokens, corpus)
    passages: list[NewPassage] = []
    pos = 0
    size = len(tokens)
    while pos < size:
        if covered[pos]:
            pos += 1
            continue
        end = pos
        while end < size and not covered[end]:
            end += 1
        words = tokens[pos:end]
        left = ("^",) * max(0, CONTEXT_WORDS - pos) + tokens[max(0, pos - CONTEXT_WORDS) : pos]
        right = tokens[end : end + CONTEXT_WORDS] + ("$",) * max(0, end + CONTEXT_WORDS - size)
        passages.append(NewPassage(passage_id_for(words, left, right), len(words)))
        pos = end
    return passages


def match_pages(
    earlier_pages: dict[str, list[Sentence]],
    later_pages: dict[str, list[Sentence]],
    *,
    earlier_urls: dict[str, str | None] | None = None,
    later_urls: dict[str, str | None] | None = None,
    failed_pages: dict[str, ExcludedPageDiagnostic] | None = None,
) -> MatchResult:
    """Find words in later sentences that sit outside every earlier three-word run, corpus-wide."""
    earlier_urls = earlier_urls or {}
    later_urls = later_urls or {}
    failed_pages = failed_pages or {}

    corpus = _EarlierCorpus(earlier_pages)
    cache: dict[Tokens, list[NewPassage]] = {}
    page_rows: list[PageRow] = []
    passage_rows: list[PassageRow] = []
    excluded_diagnostics: list[ExcludedPageDiagnostic] = []

    all_later_urls = sorted(set(later_pages.keys()) | set(failed_pages.keys()))
    for page_url in all_later_urls:
        status: PageStatus = "comparison_incomplete" if page_url in failed_pages else "compared"
        page_rows.append(
            PageRow(
                page_url=page_url,
                status=status,
                earlier_capture_url=earlier_urls.get(page_url),
                later_capture_url=later_urls.get(page_url),
            )
        )
        if page_url in failed_pages:
            excluded_diagnostics.append(failed_pages[page_url])
            continue

        seen: set[str] = set()
        for sentence in later_pages[page_url]:
            if sentence.tokens not in cache:
                cache[sentence.tokens] = _new_passages(sentence.tokens, corpus)
            for passage in cache[sentence.tokens]:
                if passage.passage_id in seen:
                    continue
                seen.add(passage.passage_id)
                passage_rows.append(
                    PassageRow(
                        page_url=page_url,
                        passage_id=passage.passage_id,
                        word_count=passage.word_count,
                    )
                )

    return MatchResult(
        pages=tuple(page_rows),
        passages=tuple(passage_rows),
        excluded_diagnostics=tuple(excluded_diagnostics),
    )


def _verified_text(entry: CaptureEntry) -> str:
    if entry.text is None:
        raise ValueError(
            f"Capture entry for {entry.page_url} has neither verified content nor a load_error"
        )
    return entry.text


def match_crawl(manifest: SampleManifest) -> MatchResult:
    """Run corpus-wide matching on the verified fixture text held by the manifest."""
    earlier_by_url = {entry.page_url: entry for entry in manifest.earlier}
    earlier_urls: dict[str, str | None] = {
        entry.page_url: entry.replay_url for entry in manifest.earlier
    }
    later_urls: dict[str, str | None] = {
        entry.page_url: entry.replay_url for entry in manifest.later
    }

    earlier_pages: dict[str, list[Sentence]] = {}
    for entry in manifest.earlier:
        if entry.load_error is not None:
            continue
        earlier_pages[entry.page_url] = extract_sentences(_verified_text(entry))

    later_pages: dict[str, list[Sentence]] = {}
    failed_pages: dict[str, ExcludedPageDiagnostic] = {}

    for entry in manifest.later:
        earlier_entry = earlier_by_url.get(entry.page_url)
        if earlier_entry is not None and earlier_entry.load_error is not None:
            failed_pages[entry.page_url] = ExcludedPageDiagnostic(
                url=entry.page_url,
                captured_at=earlier_entry.captured_at,
                failed_step=earlier_entry.load_error.failed_step,
                reason=earlier_entry.load_error.reason,
            )
            continue
        if entry.load_error is not None:
            failed_pages[entry.page_url] = ExcludedPageDiagnostic(
                url=entry.page_url,
                captured_at=entry.captured_at,
                failed_step=entry.load_error.failed_step,
                reason=entry.load_error.reason,
            )
            continue
        later_pages[entry.page_url] = extract_sentences(_verified_text(entry))

    return match_pages(
        earlier_pages,
        later_pages,
        earlier_urls=earlier_urls,
        later_urls=later_urls,
        failed_pages=failed_pages,
    )
