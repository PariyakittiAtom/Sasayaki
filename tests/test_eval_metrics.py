import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.metrics import cer, hyp_for_gold, timing_error_ms  # noqa: E402
from sasayaki.models import Cue  # noqa: E402


def test_cer_ignores_punctuation_and_width():
    assert cer("おはよう、今日は！", "おはよう今日は") == 0.0
    assert cer("ＡＢＣ", "abc") == 0.0


def test_cer_counts_substitutions():
    assert abs(cer("おはようございます", "おはようござります") - 1 / 9) < 1e-9
    assert cer("", "") == 0.0 and cer("", "x") == 1.0


def test_hyp_alignment_and_timing():
    gold = [{"start_ms": 0, "end_ms": 2000, "src": "a"}, {"start_ms": 3000, "end_ms": 4000, "src": "b"}]
    hyp = [Cue(0, 100, 1900, "x", "one"), Cue(1, 3200, 3900, "y", "two"), Cue(2, 3900, 4300, "z", "three")]
    assert hyp_for_gold(gold[0], hyp) == "one"
    assert hyp_for_gold(gold[1], hyp).startswith("two")
    t = timing_error_ms(gold, hyp)
    assert t["matched"] == 2 and t["median_ms"] in (100, 200)
