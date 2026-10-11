from sasayaki.models import Cue
from sasayaki.subs.export import to_ass, to_srt, to_vtt


def cues():
    return [Cue(0, 1500, 3200, "おはよう", "Good morning"), Cue(1, 3_661_007, 3_663_000, "ねえ", ""), Cue(2, 4000, 5000, "うん", "Mm")]


def test_srt_format_skips_empty_and_renumbers():
    s = to_srt(cues())
    assert s.startswith("1\n00:00:01,500 --> 00:00:03,200\nGood morning\n")
    assert "2\n00:00:04,000 --> 00:00:05,000\nMm" in s
    assert "01:01:01" not in s


def test_srt_offset_and_bilingual():
    s = to_srt(cues(), mode="both", offset_ms=500)
    assert "00:00:02,000 --> 00:00:03,700\nGood morning\nおはよう" in s


def test_vtt_uses_dots_and_header():
    v = to_vtt(cues())
    assert v.startswith("WEBVTT") and "00:00:01.500 --> 00:00:03.200" in v


def test_ass_uses_centiseconds_and_escapes_newlines():
    a = to_ass(cues(), mode="both")
    assert "Dialogue: 0,0:00:01.50,0:00:03.20,Default,,0,0,0,,Good morning\\Nおはよう" in a
