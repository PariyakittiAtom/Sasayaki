"""Remove or flag typical Whisper hallucinations on quiet/ambient audio.

Policy: drop only when clearly bogus (empty, non-speech with poor confidence, stock phrases with low
confidence). Anything ambiguous is kept and *flagged* so the translator and the editor can see it.
"""

from __future__ import annotations

import re

from ..models import Segment

# Stock phrases Whisper emits over silence/noise (learned from YouTube subtitles). Matched after
# stripping spaces and punctuation. A creator may genuinely say some of these at the end of a track,
# hence "drop only if low confidence".
STOCK_PHRASES = {
    "ja": [
        "ご視聴ありがとうございました",
        "ご視聴ありがとうございます",
        "チャンネル登録",
        "高評価",
        "字幕",
        "最後までご視聴",
        "次回もお楽しみに",
    ],
    "ko": [
        "시청해주셔서감사합니다",
        "구독과좋아요",
        "자막제공",
        "자막제작",
        "다음영상에서만나요",
        "MBC뉴스",
    ],
}

_STRIP = re.compile(r"[\s　、。，．,.!！?？…~〜ー\-'\"「」『』()（）♪♡❤]+")
_ONLY_PUNCT = re.compile(r"^[\s　、。，．,.!！?？…~〜ー\-♪♡❤]*$")


def _norm(text: str) -> str:
    return _STRIP.sub("", text)


def collapse_repeats(text: str, min_repeats: int = 6, keep: int = 3) -> str:
    """'ああああ…' / 'ちゅ、ちゅ、ちゅ、…' runs beyond `min_repeats` shrink to `keep` repeats.

    Moans and kisses are real content in ASMR, so short runs are left alone.
    """
    # single character runs
    text = re.sub(r"(.)\1{%d,}" % (min_repeats - 1), lambda m: m.group(1) * keep, text)
    # short unit (1-8 chars, optional separator) repeated
    pat = re.compile(r"((?:[^\s、,。]{1,8})[\s、,。]*?)\1{%d,}" % (min_repeats - 1))
    return pat.sub(lambda m: m.group(1) * keep, text)


def clean_segments(segments: list[Segment], language: str) -> list[Segment]:
    out: list[Segment] = []
    stock = [_norm(p) for p in STOCK_PHRASES.get(language, [])]
    for seg in segments:
        text = collapse_repeats(seg.text.strip())
        if text != seg.text.strip():
            seg.flags.append("repeat_collapsed")
        seg.text = text

        if not text or _ONLY_PUNCT.match(text):
            continue
        # hard non-speech: Whisper itself says no speech and is unsure of what it wrote
        if seg.no_speech_prob > 0.8 and seg.avg_logprob < -1.0:
            continue

        n = _norm(text)
        if any(p and p in n and len(n) <= len(p) + 6 for p in stock):
            if seg.mean_word_prob < 0.6 or seg.avg_logprob < -0.7 or seg.no_speech_prob > 0.4:
                continue
            seg.flags.append("stock_phrase")

        if seg.compression_ratio > 2.4:
            seg.flags.append("repetitive")
        if seg.avg_logprob < -1.0 or seg.mean_word_prob < 0.45:
            seg.flags.append("low_confidence")

        # identical consecutive segments beyond 3 are almost always a decoding loop
        if len(out) >= 3 and all(_norm(o.text) == n for o in out[-3:]):
            continue
        out.append(seg)
    return out
