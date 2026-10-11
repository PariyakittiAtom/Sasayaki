"""faster-whisper wrapper tuned for ASMR: VAD-gated, no cross-segment conditioning, word timestamps."""

from __future__ import annotations

from typing import Callable

import numpy as np

from ..config import Settings
from ..cuda_setup import ensure_cuda_dlls
from ..models import Segment, Transcript, Word
from .hallucination import clean_segments

SUPPORTED_LANGS = ("ja", "ko")

# Tuned for whispered speech: lower threshold than the 0.5 default so soft voiced speech isn't gated
# out, generous padding so word onsets/offsets aren't clipped.
VAD_PARAMS = dict(
    threshold=0.30,
    min_speech_duration_ms=120,
    min_silence_duration_ms=600,
    speech_pad_ms=400,
)

ProgressCb = Callable[[float], None]


class Transcriber:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        ensure_cuda_dlls()
        import ctranslate2
        from faster_whisper import WhisperModel

        device = self.settings.whisper_device
        if device == "auto":
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        compute = self.settings.whisper_compute_type
        if device == "cpu" and compute in ("float16", "int8_float16"):
            compute = "int8"
        self._model = WhisperModel(self.settings.whisper_model, device=device, compute_type=compute)
        self.device, self.compute_type = device, compute
        return self._model

    def unload(self) -> None:
        """Free VRAM so a local LLM (Ollama) can use the GPU afterwards."""
        self._model = None
        import gc

        gc.collect()

    def detect_language(self, audio: np.ndarray) -> tuple[str, float]:
        """Pick between Japanese and Korean using several speech windows (not just the first 30 s,
        which in ASMR is often silence or SFX)."""
        from faster_whisper.vad import VadOptions

        model = self._load()
        _, _, probs = model.detect_language(
            audio=audio,
            vad_filter=True,
            # must be a VadOptions here: unlike transcribe(), detect_language() does not accept a dict
            vad_parameters=VadOptions(**VAD_PARAMS),
            language_detection_segments=6,
            language_detection_threshold=1.01,  # never early-exit; always use all segments
        )
        scores = {lang: p for lang, p in probs if lang in SUPPORTED_LANGS}
        lang = max(scores, key=scores.get) if scores else "ja"
        total = sum(scores.values()) or 1.0
        return lang, scores.get(lang, 0.0) / total

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
        initial_prompt: str | None = None,
        progress: ProgressCb | None = None,
    ) -> Transcript:
        model = self._load()
        duration_ms = int(len(audio) / 16000 * 1000)
        if not language or language == "auto":
            language, _ = self.detect_language(audio)

        seg_iter, _info = model.transcribe(
            audio,
            language=language,
            task="transcribe",
            beam_size=5,
            temperature=(0.0, 0.2, 0.4),
            condition_on_previous_text=False,  # stops hallucination loops from propagating
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            word_timestamps=True,
            hallucination_silence_threshold=2.0,
            vad_filter=True,
            vad_parameters=VAD_PARAMS,
            hotwords=hotwords or None,
            initial_prompt=initial_prompt or None,
        )

        segments: list[Segment] = []
        for s in seg_iter:
            words = [
                Word(int(w.start * 1000), int(w.end * 1000), w.word, float(w.probability))
                for w in (s.words or [])
            ]
            segments.append(
                Segment(
                    start_ms=int(s.start * 1000),
                    end_ms=int(s.end * 1000),
                    text=s.text.strip(),
                    words=words,
                    avg_logprob=float(s.avg_logprob),
                    no_speech_prob=float(s.no_speech_prob),
                    compression_ratio=float(s.compression_ratio),
                )
            )
            if progress and duration_ms:
                progress(min(1.0, s.end * 1000 / duration_ms))

        segments = clean_segments(segments, language)
        if progress:
            progress(1.0)
        return Transcript(language=language, duration_ms=duration_ms, segments=segments)
