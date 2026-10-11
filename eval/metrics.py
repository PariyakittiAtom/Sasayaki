"""Accuracy metrics for the eval harness."""

from __future__ import annotations

import re
import unicodedata

_DROP = re.compile(r"[\s　、。，．,.!！?？…~〜ー\-'\"「」『』()（）♪♡❤♥]+")


def normalize_for_cer(text: str) -> str:
    return _DROP.sub("", unicodedata.normalize("NFKC", text)).lower()


def edit_distance(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(reference: str, hypothesis: str) -> float:
    """Character error rate after NFKC + punctuation/space stripping (standard for ja/ko ASR)."""
    ref, hyp = normalize_for_cer(reference), normalize_for_cer(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)


def overlap_ms(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def hyp_for_gold(gold_cue: dict, hyp_cues: list, field: str = "en", min_frac: float = 0.4) -> str:
    """Join the hypothesis cues that substantially overlap a gold cue in time."""
    g0, g1 = gold_cue["start_ms"], gold_cue["end_ms"]
    dur = max(1, g1 - g0)
    parts = []
    for h in hyp_cues:
        ov = overlap_ms(g0, g1, h.start_ms, h.end_ms)
        hdur = max(1, h.end_ms - h.start_ms)
        if ov / dur >= min_frac or ov / hdur >= 0.6:
            t = getattr(h, field)
            if t:
                parts.append(t)
    return " ".join(parts)


def timing_error_ms(gold: list[dict], hyp: list) -> dict:
    """Median/p90 absolute start-time error between each gold cue and its best-overlapping hyp cue."""
    errs = []
    for g in gold:
        best = max(hyp, key=lambda h: overlap_ms(g["start_ms"], g["end_ms"], h.start_ms, h.end_ms), default=None)
        if best and overlap_ms(g["start_ms"], g["end_ms"], best.start_ms, best.end_ms) > 0:
            errs.append(abs(best.start_ms - g["start_ms"]))
    if not errs:
        return {"median_ms": None, "p90_ms": None, "matched": 0}
    errs.sort()
    return {"median_ms": errs[len(errs) // 2], "p90_ms": errs[int(len(errs) * 0.9)], "matched": len(errs)}
