"""Audio loading and level normalization tuned for quiet/whispered material."""

from __future__ import annotations

import numpy as np

SAMPLE_RATE = 16000


def load_audio(path: str) -> np.ndarray:
    """Decode any PyAV-readable file to mono float32 @ 16 kHz (no system ffmpeg needed).

    Uses PyAV directly rather than faster_whisper.audio.decode_audio, which breaks on newer PyAV.
    """
    import av

    chunks: list[np.ndarray] = []
    resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
    with av.open(path, mode="r") as container:
        if not container.streams.audio:
            raise ValueError(f"no audio stream in {path}")
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
    for out in resampler.resample(None):  # flush
        chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32, copy=False)


def normalize_for_asr(
    audio: np.ndarray,
    target_dbfs: float = -20.0,
    max_gain_db: float = 30.0,
    frame_ms: int = 30,
    active_percentile: float = 90.0,
) -> np.ndarray:
    """Gain-normalize so the *speech-active* level hits `target_dbfs`.

    ASMR whispers sit far below normal speech level; Whisper's accuracy and the VAD both degrade on
    them. We measure RMS per frame, take a high percentile of frames above a noise floor as the
    speech level, then apply a bounded gain and a soft clip. No denoising: it tends to hurt Whisper.
    """
    if audio.size == 0:
        return audio
    x = audio - float(np.mean(audio))
    frame = int(SAMPLE_RATE * frame_ms / 1000)
    n = (len(x) // frame) * frame
    if n == 0:
        return x
    rms = np.sqrt(np.mean(x[:n].reshape(-1, frame) ** 2, axis=1))
    floor = max(float(np.percentile(rms, 10)) * 1.5, 1e-5)
    active = rms[rms > floor]
    if active.size == 0:
        return x
    level = float(np.percentile(active, active_percentile))
    if level <= 1e-6:
        return x
    target = 10 ** (target_dbfs / 20)
    gain = min(target / level, 10 ** (max_gain_db / 20))
    y = x * gain
    # soft clip so a boosted breath/click can't hard-clip
    return np.tanh(y * 0.9) / 0.9 if np.max(np.abs(y)) > 0.95 else y.astype(np.float32)
