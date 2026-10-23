"""Shrink audio for upload: any PyAV-readable file -> Opus in Ogg (plays on every Android version)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import av

BITRATE = 96_000  # stereo; transparent enough for whispered speech, ~0.7 MB per minute
RATE = 48_000  # Opus native rate
FRAME = 960  # 20 ms at 48 kHz


def to_opus(src: str | Path, dst: str | Path, bitrate: int = BITRATE,
            progress: Callable[[float], None] | None = None) -> Path:
    dst = Path(dst)
    with av.open(str(src)) as inp:
        stream = inp.streams.audio[0]
        channels = min(2, stream.codec_context.channels or 2)
        layout = "mono" if channels == 1 else "stereo"
        total = float(stream.duration * stream.time_base) if stream.duration else 0.0

        with av.open(str(dst), "w", format="ogg") as out:
            enc = out.add_stream("libopus", rate=RATE)
            enc.layout = layout
            enc.bit_rate = bitrate if channels == 2 else bitrate // 2
            resampler = av.AudioResampler(format="flt", layout=layout, rate=RATE, frame_size=FRAME)

            def emit(frames) -> None:
                for f in frames:
                    for packet in enc.encode(f):
                        out.mux(packet)

            for frame in inp.decode(stream):
                emit(resampler.resample(frame))
                if progress and total and frame.time is not None:
                    progress(min(1.0, frame.time / total))
            emit(resampler.resample(None))  # flush the resampler
            for packet in enc.encode(None):  # flush the encoder
                out.mux(packet)
    return dst
