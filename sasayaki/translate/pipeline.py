"""Contextual translation pipeline: scene brief -> chunked translation -> optional review.

Engine-agnostic: talks to `Backend`s. Handles chunking, ID validation, retries, splitting on
truncation, and automatic fallback to a second backend (e.g. local Ollama) on refusals/failures.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from ..config import QUALITY_MODES
from ..models import Cue
from . import prompts
from .base import Backend, BackendError, Refusal, TranslationStats, Truncated, LineResult

ProgressCb = Callable[[str, float], None]
logger = logging.getLogger(__name__)

# A refusal that arrives as normal text instead of a stop_reason (mostly small local models).
_REFUSAL_TEXT = re.compile(
    r"^\s*(i'?m sorry|i am sorry|sorry,|i can(?:'|no)t|i cannot|i won'?t|i'm unable|as an ai)", re.I
)


class Cancelled(Exception):
    pass


def make_chunks(cues: list[Cue], size: int = 45, lookback: int = 12, min_gap_ms: int = 1500) -> list[list[Cue]]:
    """Split into ~`size` cue chunks, preferring to cut at the longest pause near the boundary so a
    chunk rarely ends mid-thought."""
    chunks: list[list[Cue]] = []
    i = 0
    while i < len(cues):
        end = min(i + size, len(cues))
        if end < len(cues):
            best, best_gap = None, min_gap_ms - 1
            for j in range(end - 1, max(i + size - lookback, i + 1) - 1, -1):
                gap = cues[j + 1].start_ms - cues[j].end_ms
                if gap > best_gap:
                    best, best_gap = j + 1, gap
            if best is not None:
                end = best
        chunks.append(cues[i:end])
        i = end
    return chunks


class TranslationPipeline:
    def __init__(
        self,
        primary: Backend,
        fallback: Backend | None = None,
        quality: str = "balanced",
        chunk_size: int = 45,
        context_prev: int = 15,
        lookahead: int = 5,
        review_model: str | None = None,
        progress: ProgressCb | None = None,
        log: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ):
        self.primary = primary
        self.fallback = fallback
        self.mode = QUALITY_MODES[quality]
        self.chunk_size = chunk_size
        self.context_prev = context_prev
        self.lookahead = lookahead
        self.review_model = review_model or None
        self._progress = progress or (lambda stage, f: None)
        self._log = log or (lambda m: None)
        self._cancel = cancel_check or (lambda: False)
        self.stats = TranslationStats()

    # ------------------------------------------------------------------ public

    def run(
        self,
        cues: list[Cue],
        lang: str,
        hint: str = "",
        glossary: list[dict] | None = None,
        card: dict | None = None,
    ) -> dict:
        """Translate `cues` in place. Returns the scene card used."""
        glossary_text = prompts.format_glossary(glossary or [])
        if card is None:
            card = self.build_card(cues, lang, hint, glossary_text)
        self.translate(cues, lang, card, glossary_text)
        if self.mode["review"]:
            self.review(cues, lang, card, glossary_text)
        self._progress("done", 1.0)
        return card

    def build_card(self, cues: list[Cue], lang: str, hint: str = "", glossary_text: str = "") -> dict:
        self._progress("scene", 0.0)
        system = prompts.scene_system(lang, hint, glossary_text)
        user = prompts.scene_user(cues)
        for backend in self._backends():
            try:
                card = backend.complete_json(system, user, prompts.SCENE_SCHEMA, effort=self.mode["scene_effort"])
                self._progress("scene", 1.0)
                return card
            except BackendError as e:
                self._fail(backend, "scene brief", e)
        self.stats.notes.append("scene brief unavailable; translated without it")
        return {"summary": hint} if hint else {}

    def translate(self, cues: list[Cue], lang: str, card: dict, glossary_text: str = "") -> None:
        system = prompts.translate_system(lang, card, glossary_text)
        chunks = make_chunks(cues, self.chunk_size)
        for n, chunk in enumerate(chunks):
            self._check_cancel()
            start = chunk[0].idx
            prev = [c for c in cues[max(0, start - self.context_prev) : start] if c.en]
            nxt = cues[chunk[-1].idx + 1 : chunk[-1].idx + 1 + self.lookahead]
            self._translate_chunk(system, chunk, prev, nxt)
            self.stats.chunks += 1
            self._progress("translate", (n + 1) / len(chunks))

    def review(self, cues: list[Cue], lang: str, card: dict, glossary_text: str = "") -> None:
        system = prompts.review_system(lang, card, glossary_text)
        chunks = make_chunks(cues, self.chunk_size + 15)
        for n, chunk in enumerate(chunks):
            self._check_cancel()
            start = chunk[0].idx
            prev = cues[max(0, start - self.context_prev) : start]
            nxt = cues[chunk[-1].idx + 1 : chunk[-1].idx + 1 + self.lookahead]
            try:
                data = self.primary.complete_json(
                    system,
                    prompts.review_user(prev, chunk, nxt),
                    prompts.REVIEW_SCHEMA,
                    effort=self.mode["translate_effort"],
                    model=self.review_model,
                )
            except BackendError as e:
                # review is an enhancement; never fail the track over it
                self._fail(self.primary, f"review chunk {n} (skipped)", e)
                self._progress("review", (n + 1) / len(chunks))
                continue
            by_id = {c.idx: c for c in chunk}
            for ch in data.get("changes", []):
                cue = by_id.get(ch.get("id"))
                new = (ch.get("en") or "").strip()
                if cue is None or not new or new == cue.en or cue.user_edited:
                    continue
                cue.en = new
                cue.confidence = prompts.CONFIDENCE.get(ch.get("confidence"), cue.confidence)
                if "reviewed" not in cue.flags:
                    cue.flags.append("reviewed")
                self.stats.review_changes += 1
            self._progress("review", (n + 1) / len(chunks))

    # ------------------------------------------------------------------ internals

    def _backends(self) -> list[Backend]:
        return [self.primary] + ([self.fallback] if self.fallback else [])

    def _fail(self, backend: Backend, where: str, err: Exception) -> None:
        msg = f"{backend.name}: {err}"
        logger.warning("translation failure (%s): %s", where, msg)
        self._log(f"{where} failed on {msg}")
        # report the primary engine's error to the user; a missing local fallback shouldn't mask it
        if backend is self.primary or not self.stats.last_error:
            self.stats.last_error = msg

    def _check_cancel(self) -> None:
        if self._cancel():
            raise Cancelled()

    def _translate_chunk(self, system: str, chunk: list[Cue], prev: list[Cue], nxt: list[Cue]) -> None:
        pending = {c.idx: c for c in chunk}
        backends = self._backends()
        for bi, backend in enumerate(backends):
            if not pending:
                break
            lines = [pending[i] for i in sorted(pending)]
            try:
                got = self._call(backend, system, lines, prev, nxt)
            except Truncated:
                if len(lines) > 1:  # too much output for one call: translate each half
                    mid = len(lines) // 2
                    self._translate_chunk(system, lines[:mid], prev, lines[mid : mid + self.lookahead])
                    self._translate_chunk(system, lines[mid:], prev + [c for c in lines[:mid] if c.en][-self.context_prev :], nxt)
                    return
                continue
            except Refusal as e:
                self._fail(backend, f"refusal on chunk at line {lines[0].idx}", e)
                continue
            except BackendError as e:
                self._fail(backend, f"chunk at line {lines[0].idx}", e)
                continue

            applied = 0
            for idx, res in got.items():
                if idx not in pending:
                    continue
                if _REFUSAL_TEXT.match(res.en) and not _REFUSAL_TEXT.match(pending[idx].src):
                    continue  # treat as refusal; leave pending for the next backend
                self._apply(pending.pop(idx), res, used_fallback=bi > 0)
                applied += 1
            if bi > 0 and applied:
                self.stats.fallback_chunks += 1
            if pending and bi == 0 and len(pending) < len(lines):
                # got a partial answer from the primary: one targeted retry for just the gaps
                self.stats.retried_chunks += 1
                try:
                    again = self._call(backend, system, [pending[i] for i in sorted(pending)], prev, nxt)
                    for idx, res in again.items():
                        if idx in pending and not _REFUSAL_TEXT.match(res.en):
                            self._apply(pending.pop(idx), res, used_fallback=False)
                except BackendError:
                    pass

        for cue in pending.values():  # nobody could translate these
            cue.en = ""
            if "untranslated" not in cue.flags:
                cue.flags.append("untranslated")
            self.stats.untranslated += 1

    def _call(self, backend: Backend, system: str, lines: list[Cue], prev: list[Cue], nxt: list[Cue]) -> dict[int, LineResult]:
        data = backend.complete_json(
            system,
            prompts.translate_user(prev, lines, nxt),
            prompts.TRANSLATE_SCHEMA,
            effort=self.mode["translate_effort"],
        )
        wanted = {c.idx for c in lines}
        out: dict[int, LineResult] = {}
        for item in data.get("lines", []):
            idx = item.get("id")
            if idx in wanted and idx not in out:
                out[idx] = LineResult(
                    idx=idx,
                    en=(item.get("en") or "").strip(),
                    confidence=prompts.CONFIDENCE.get(item.get("confidence"), 0.65),
                    asr_suspect=bool(item.get("asr_suspect")),
                    asr_fix=(item.get("asr_fix") or "").strip(),
                )
        return out

    @staticmethod
    def _apply(cue: Cue, res: LineResult, used_fallback: bool) -> None:
        if cue.user_edited:
            return
        cue.en = res.en
        cue.confidence = res.confidence
        cue.asr_fix = res.asr_fix
        flags = set(cue.flags)
        if res.asr_suspect:
            flags.add("asr_suspect")
        if used_fallback:
            flags.add("local_fallback")
        if not res.en:
            flags.add("dropped_noise")
        cue.flags = sorted(flags)
