"""Cue lookup and playback-clock smoothing for subtitle sync (pure Python; no Qt)."""

from __future__ import annotations

import time
from bisect import bisect_right
from typing import Callable

from .models import Cue


class PositionClock:
    """QMediaPlayer.position() only advances in coarse steps (tens of ms, backend-dependent), which
    makes subtitles flip late/jittery. Between reported changes we extrapolate with a monotonic
    clock, capped so we never run far ahead of the audio (e.g. during buffering)."""

    def __init__(self, now: Callable[[], float] = time.monotonic, max_ahead_ms: int = 120):
        self._now = now
        self._max_ahead = max_ahead_ms
        self._reported = 0
        self._stamp = now()

    def estimate(self, reported_ms: int, playing: bool, rate: float = 1.0) -> int:
        t = self._now()
        if reported_ms != self._reported:
            self._reported, self._stamp = reported_ms, t  # fresh value from the backend
            return reported_ms
        if not playing:
            self._stamp = t
            return reported_ms
        ahead = min((t - self._stamp) * 1000 * rate, self._max_ahead)
        return reported_ms + round(ahead)


class CueIndex:
    """O(log n) "which cue is showing at playback position t?" over cues sorted by start time."""

    def __init__(self, cues: list[Cue]):
        self.cues = sorted(cues, key=lambda c: (c.start_ms, c.idx))
        self._starts = [c.start_ms for c in self.cues]

    def __len__(self) -> int:
        return len(self.cues)

    def last_started(self, pos_ms: int) -> int | None:
        """Position in `self.cues` of the latest cue that has started (None before the first)."""
        i = bisect_right(self._starts, pos_ms) - 1
        return i if i >= 0 else None

    def active(self, pos_ms: int) -> int | None:
        """Position of the cue visible at `pos_ms` (None in gaps). If edits made cues overlap, the
        most recently started still-visible cue wins."""
        i = self.last_started(pos_ms)
        if i is None:
            return None
        for j in range(i, max(i - 3, -1), -1):
            if pos_ms < self.cues[j].end_ms:
                return j
        return None

    def seek_target(self, position: int) -> int:
        return self.cues[position].start_ms
