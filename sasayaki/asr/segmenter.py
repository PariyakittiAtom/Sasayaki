"""Turn raw ASR segments (with word timings) into subtitle-sized cues."""

from __future__ import annotations

import re

from ..models import Cue, Segment, Word

# ASCII "." / "?" matter: Whisper emits them for Korean (and English) rather than the CJK marks.
SENTENCE_END = re.compile(r"[。！？!?…\.]+[」』）)\"']*$")
CLAUSE_END = re.compile(r"[、,，]$")


def _join(words: list[Word]) -> str:
    return "".join(w.text for w in words).strip()


def _split_words(
    words: list[Word], max_chars: int, max_ms: int, gap_ms: int, min_chars: int
) -> list[list[Word]]:
    """Greedy split on long pauses, sentence ends, and size limits (preferring clause boundaries)."""
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for i, w in enumerate(words):
        cur.append(w)
        text = _join(cur)
        dur = cur[-1].end_ms - cur[0].start_ms
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt.start_ms - w.end_ms) if nxt else 0
        stripped = w.text.strip()
        too_big = len(text) >= max_chars or dur >= max_ms
        sentence_done = bool(SENTENCE_END.search(stripped)) and len(text) >= min_chars
        clause_done = bool(CLAUSE_END.search(stripped)) and (len(text) >= max_chars * 0.7 or dur >= max_ms * 0.7)
        pause = nxt is not None and gap >= gap_ms and len(text) >= min_chars
        if nxt is None or too_big or sentence_done or clause_done or pause:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def segments_to_cues(
    segments: list[Segment],
    language: str,
    max_chars: int | None = None,
    max_ms: int = 7000,
    gap_ms: int = 900,
    min_chars: int = 4,
) -> list[Cue]:
    if max_chars is None:
        max_chars = 36 if language in ("ja", "ko") else 80
    cues: list[Cue] = []
    for seg in segments:
        words = [w for w in seg.words if w.text.strip()]
        if not words:  # no word timings: keep the segment as one cue
            cues.append(Cue(0, seg.start_ms, seg.end_ms, seg.text, flags=list(seg.flags)))
            continue
        for grp in _split_words(words, max_chars, max_ms, gap_ms, min_chars):
            text = _join(grp)
            if text:
                cues.append(Cue(0, grp[0].start_ms, grp[-1].end_ms, text, flags=list(seg.flags)))

    cues = _merge_tiny(cues, min_chars=min_chars, max_chars=max_chars, max_ms=max_ms)
    cues = finalize_timing(cues)
    for i, c in enumerate(cues):
        c.idx = i
    return cues


def _merge_tiny(cues: list[Cue], min_chars: int, max_chars: int, max_ms: int) -> list[Cue]:
    """Fold fragments of < min_chars into a close neighbour when the result stays within limits."""
    out: list[Cue] = []
    for c in cues:
        if out and len(c.src) < min_chars:
            p = out[-1]
            if c.start_ms - p.end_ms < 500 and len(p.src) + len(c.src) <= max_chars and c.end_ms - p.start_ms <= max_ms:
                p.src += c.src
                p.end_ms = c.end_ms
                p.flags = sorted(set(p.flags) | set(c.flags))
                continue
        out.append(c)
    return out


def finalize_timing(cues: list[Cue], min_dur_ms: int = 900, tail_ms: int = 150, gap_ms: int = 40) -> list[Cue]:
    """Ensure cues stay on screen long enough to read without overlapping the next cue."""
    for i, c in enumerate(cues):
        limit = cues[i + 1].start_ms - gap_ms if i + 1 < len(cues) else c.end_ms + 10_000
        c.end_ms = min(max(c.end_ms + tail_ms, c.start_ms + min_dur_ms), max(limit, c.end_ms))
        if c.end_ms <= c.start_ms:
            c.end_ms = c.start_ms + 200
    return cues
