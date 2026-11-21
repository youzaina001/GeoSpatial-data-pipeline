# Corpus-wide prose sentence matching
"""Match later crawl sentences against the entire earlier corpus and emit ADR 0018 table rows."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from geopipeline.crawl.extract import Sentence, extract_sentences
from geopipeline.crawl.manifest import CaptureEntry, SampleManifest

SIMILARITY_THRESHOLD = 0.5
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


def passage_id_for(normalized_sentence: str) -> str:
    return hashlib.sha256(normalized_sentence.encode("utf-8")).hexdigest()


def _new_word_count(
    later_sentence: Sentence,
    earlier_exact: frozenset[str],
    earlier_corpus: tuple[Sentence, ...],
) -> int:
    if later_sentence.normalized_text in earlier_exact:
        return 0

    best_ratio = 0.0
    best_earlier: Sentence | None = None
    later_tokens = later_sentence.tokens

    # earlier_corpus is sorted lexicographically by normalized_text, so strict '>'
    # deterministically breaks ties in favor of the lexicographically smallest baseline.
    for candidate in earlier_corpus:
        matcher = SequenceMatcher(None, candidate.tokens, later_tokens, autojunk=False)
        if matcher.quick_ratio() < SIMILARITY_THRESHOLD:
            continue
        ratio = matcher.ratio()
        if ratio >= SIMILARITY_THRESHOLD and ratio > best_ratio:
            best_ratio = ratio
            best_earlier = candidate

    if best_earlier is None:
        return len(later_tokens)

    diff = SequenceMatcher(None, best_earlier.tokens, later_tokens, autojunk=False)
    return sum(
        j2 - j1
        for tag, _i1, _i2, j1, j2 in diff.get_opcodes()
        if tag in {"insert", "replace"}
    )


def match_pages(
    earlier_pages: dict[str, list[Sentence]],
    later_pages: dict[str, list[Sentence]],
    *,
    earlier_urls: dict[str, str | None] | None = None,
    later_urls: dict[str, str | None] | None = None,
    failed_pages: dict[str, ExcludedPageDiagnostic] | None = None,
) -> MatchResult:
    """Compare extracted later sentences against all readable earlier sentences corpus-wide."""
    earlier_urls = earlier_urls or {}
    later_urls = later_urls or {}
    failed_pages = failed_pages or {}

    unique_earlier_by_text: dict[str, Sentence] = {}
    for sentences in earlier_pages.values():
        for sentence in sentences:
            unique_earlier_by_text.setdefault(sentence.normalized_text, sentence)
    earlier_corpus = tuple(
        unique_earlier_by_text[key] for key in sorted(unique_earlier_by_text)
    )
    earlier_exact = frozenset(unique_earlier_by_text.keys())

    score_cache: dict[str, int] = {}
    page_rows: list[PageRow] = []
    passage_rows: list[PassageRow] = []
    excluded_diagnostics: list[ExcludedPageDiagnostic] = []

    all_later_urls = sorted(set(later_pages.keys()) | set(failed_pages.keys()))
    for page_url in all_later_urls:
        if page_url in failed_pages:
            page_rows.append(
                PageRow(
                    page_url=page_url,
                    status="comparison_incomplete",
                    earlier_capture_url=earlier_urls.get(page_url),
                    later_capture_url=later_urls.get(page_url),
                )
            )
            excluded_diagnostics.append(failed_pages[page_url])
            continue

        page_rows.append(
            PageRow(
                page_url=page_url,
                status="compared",
                earlier_capture_url=earlier_urls.get(page_url),
                later_capture_url=later_urls.get(page_url),
            )
        )
        seen_passages: set[str] = set()
        for sentence in later_pages[page_url]:
            norm = sentence.normalized_text
            if norm in seen_passages:
                continue
            seen_passages.add(norm)
            if norm not in score_cache:
                score_cache[norm] = _new_word_count(sentence, earlier_exact, earlier_corpus)
            words = score_cache[norm]
            if words > 0:
                passage_rows.append(
                    PassageRow(
                        page_url=page_url,
                        passage_id=passage_id_for(norm),
                        word_count=words,
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
