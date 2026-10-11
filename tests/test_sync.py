from sasayaki.models import Cue
from sasayaki.player_sync import CueIndex


def idx():
    return CueIndex([Cue(0, 1000, 2000, "a"), Cue(1, 2500, 4000, "b"), Cue(2, 4000, 5000, "c")])


def test_active_boundaries_are_start_inclusive_end_exclusive():
    x = idx()
    assert x.active(0) is None and x.active(999) is None
    assert x.active(1000) == 0 and x.active(1999) == 0
    assert x.active(2000) is None and x.active(2499) is None  # gap between cues
    assert x.active(2500) == 1 and x.active(3999) == 1
    assert x.active(4000) == 2  # back-to-back cues: the new one wins at the boundary
    assert x.active(5000) is None


def test_last_started_holds_through_gaps_for_transcript_highlight():
    x = idx()
    assert x.last_started(500) is None
    assert x.last_started(2200) == 0
    assert x.last_started(9999) == 2


def test_unsorted_input_and_overlap_after_manual_edit():
    x = CueIndex([Cue(1, 3000, 6000, "late"), Cue(0, 1000, 4000, "early")])
    assert [c.src for c in x.cues] == ["early", "late"]
    assert x.active(3500) == 1  # both visible: newest started cue wins
    assert x.active(5000) == 1
    assert x.active(3999) == 1


def test_empty_index():
    x = CueIndex([])
    assert x.active(100) is None and x.last_started(100) is None


def test_position_clock_extrapolates_between_updates_but_never_runs_away():
    from sasayaki.player_sync import PositionClock

    t = [100.0]
    c = PositionClock(now=lambda: t[0], max_ahead_ms=120)
    assert c.estimate(5000, playing=True) == 5000  # fresh backend value
    t[0] += 0.05
    assert c.estimate(5000, playing=True) == 5050  # same reported value: extrapolate 50 ms
    t[0] += 1.0
    assert c.estimate(5000, playing=True) == 5120  # stalled backend: capped at +120 ms
    assert c.estimate(5000, playing=False) == 5000  # paused: no extrapolation
    t[0] += 0.04
    assert c.estimate(5000, playing=True, rate=2.0) == 5080  # playback rate respected
    assert c.estimate(5100, playing=True) == 5100  # new value (e.g. after seek) wins immediately
