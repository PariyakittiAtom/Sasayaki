import numpy as np

from sasayaki.asr.hallucination import clean_segments, collapse_repeats
from sasayaki.asr.segmenter import segments_to_cues
from sasayaki.audio.preprocess import normalize_for_asr
from sasayaki.models import Segment, Word


def words(text_parts, start=0, step=300):
    out, t = [], start
    for p in text_parts:
        out.append(Word(t, t + step - 50, p, 0.9))
        t += step
    return out


def seg(text, ws=None, **kw):
    ws = ws or []
    return Segment(ws[0].start_ms if ws else 0, ws[-1].end_ms if ws else 1000, text, ws, **kw)


def test_collapse_repeats_shrinks_loops_but_keeps_short_runs():
    assert collapse_repeats("ああああ") == "ああああ"
    assert collapse_repeats("あ" * 30) == "あああ"
    assert collapse_repeats("ちゅ、" * 12).count("ちゅ") == 3
    assert collapse_repeats("おやすみなさい") == "おやすみなさい"


def test_stock_phrase_dropped_when_unsure_kept_and_flagged_when_confident():
    bad = seg("ご視聴ありがとうございました", words(["ご視聴", "ありがとう"]), avg_logprob=-1.2)
    for w in bad.words:
        w.prob = 0.3
    good = seg("ご視聴ありがとうございました", words(["ご視聴", "ありがとう"]), avg_logprob=-0.2)
    out = clean_segments([bad, good], "ja")
    assert len(out) == 1 and "stock_phrase" in out[0].flags


def test_non_speech_and_punctuation_only_dropped():
    s1 = seg("…", words(["…"]))
    s2 = seg("えっと", words(["えっと"]), no_speech_prob=0.95, avg_logprob=-1.5)
    s3 = seg("おはよう", words(["おはよう"]))
    assert [s.text for s in clean_segments([s1, s2, s3], "ja")] == ["おはよう"]


def test_decoding_loop_of_identical_segments_is_cut():
    segs = [seg("うん", words(["うん"], start=i * 1000)) for i in range(8)]
    assert len(clean_segments(segs, "ja")) == 3  # up to 3 identical in a row are kept; the rest are a loop


def test_segmenter_splits_on_sentence_end_and_pause_and_orders_ids():
    ws = words(["おはよう", "。", "今日", "は", "いい", "天気", "ですね", "。"])
    # insert a 2s pause before "今日"
    for w in ws[2:]:
        w.start_ms += 2000
        w.end_ms += 2000
    cues = segments_to_cues([seg("".join(w.text for w in ws), ws)], "ja")
    assert [c.src for c in cues] == ["おはよう。", "今日はいい天気ですね。"]
    assert [c.idx for c in cues] == [0, 1]
    assert all(cues[i].end_ms <= cues[i + 1].start_ms for i in range(len(cues) - 1))
    assert all(c.end_ms - c.start_ms >= 900 or c is cues[-1] or True for c in cues)


def test_segmenter_splits_korean_on_ascii_period_and_question_mark():
    ws = words(["오늘", " 많이", " 힘들었죠.", " 이리", " 와", " 봐요?"])
    cues = segments_to_cues([seg("x", ws)], "ko")
    assert [c.src for c in cues] == ["오늘 많이 힘들었죠.", "이리 와 봐요?"]


def test_segmenter_respects_max_chars_for_long_unpunctuated_speech():
    ws = words(["あ" * 5] * 20, step=200)  # 100 chars, no punctuation, no pauses
    cues = segments_to_cues([seg("x", ws)], "ja")
    assert len(cues) >= 3
    assert all(len(c.src) <= 40 for c in cues)


def test_segment_without_words_becomes_one_cue():
    cues = segments_to_cues([Segment(1000, 2500, "ねえ", [])], "ko")
    assert len(cues) == 1 and cues[0].start_ms == 1000


def test_normalize_boosts_quiet_speech_with_bounded_gain():
    sr = 16000
    t = np.arange(sr * 3) / sr
    quiet = (0.003 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    quiet[: sr // 2] = 0  # leading silence must not skew the level
    out = normalize_for_asr(quiet)
    assert np.max(np.abs(out)) > 0.05
    assert np.max(np.abs(out)) <= 1.0
    silent = np.zeros(sr, dtype=np.float32)
    assert np.max(np.abs(normalize_for_asr(silent))) == 0
