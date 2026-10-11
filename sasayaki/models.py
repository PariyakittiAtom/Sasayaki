"""Plain data types shared by the ASR, translation and UI layers. Times are integer milliseconds."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Word:
    start_ms: int
    end_ms: int
    text: str
    prob: float = 1.0


@dataclass
class Segment:
    """One raw ASR segment (before subtitle segmentation)."""

    start_ms: int
    end_ms: int
    text: str
    words: list[Word] = field(default_factory=list)
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    compression_ratio: float = 1.0
    flags: list[str] = field(default_factory=list)

    @property
    def mean_word_prob(self) -> float:
        if not self.words:
            return 1.0
        return sum(w.prob for w in self.words) / len(self.words)


@dataclass
class Cue:
    """One subtitle line. `idx` is stable and is the translation key."""

    idx: int
    start_ms: int
    end_ms: int
    src: str
    en: str = ""
    confidence: float | None = None
    flags: list[str] = field(default_factory=list)
    asr_fix: str = ""  # translator's suggested corrected source text when it suspects an ASR error
    user_edited: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Cue":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Transcript:
    language: str
    duration_ms: int
    segments: list[Segment]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        segs = []
        for s in d["segments"]:
            words = [Word(**w) for w in s.get("words", [])]
            segs.append(Segment(**{**s, "words": words}))
        return cls(language=d["language"], duration_ms=d["duration_ms"], segments=segs)
