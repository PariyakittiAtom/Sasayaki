"""Backend contract: a backend turns (system, user, JSON schema) into a parsed JSON object.

All translation logic (prompting, chunking, validation, fallback) lives in the pipeline, so engines
are interchangeable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class BackendError(Exception):
    """Transient or configuration failure (network, auth, bad JSON)."""


class Refusal(BackendError):
    """The model declined to produce the translation (policy refusal)."""


class Truncated(BackendError):
    """Output hit the token limit before the JSON was complete."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.calls += other.calls


class Backend(Protocol):
    name: str
    usage: Usage

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict,
        *,
        effort: str = "medium",
        max_tokens: int = 16000,
        model: str | None = None,
    ) -> dict: ...


@dataclass
class ChunkLine:
    idx: int
    src: str
    en: str = ""


@dataclass
class LineResult:
    idx: int
    en: str
    confidence: float = 0.8
    asr_suspect: bool = False
    asr_fix: str = ""


@dataclass
class TranslationStats:
    chunks: int = 0
    fallback_chunks: int = 0
    retried_chunks: int = 0
    untranslated: int = 0
    review_changes: int = 0
    last_error: str = ""  # most recent backend failure, so a total failure can be explained to the user
    notes: list[str] = field(default_factory=list)
