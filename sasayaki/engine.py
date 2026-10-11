"""High-level engine: file -> transcript -> cues -> translated cues. Shared by the CLI, the job queue
and the eval harness. Each stage is cached on disk so it can be re-run independently."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .asr.segmenter import segments_to_cues
from .asr.transcriber import Transcriber
from .audio.preprocess import load_audio, normalize_for_asr
from .config import Settings, get_api_key
from .models import Cue, Transcript
from .translate.base import Backend
from .translate.claude import ClaudeBackend
from .translate.ollama import OllamaBackend
from .translate.pipeline import TranslationPipeline

ProgressCb = Callable[[str, float], None]


def build_backends(settings: Settings) -> tuple[Backend, Backend | None]:
    """Primary + optional fallback according to settings. Raises RuntimeError if Claude is selected
    but no API key is configured."""
    ollama = OllamaBackend(settings.ollama_url, settings.ollama_model)
    if settings.translator == "ollama":
        return ollama, None
    key = get_api_key()
    if not key:
        raise RuntimeError("No Anthropic API key found. Set ANTHROPIC_API_KEY or add it in Settings.")
    claude = ClaudeBackend(key, settings.claude_model, workspace_id=settings.anthropic_workspace_id)
    return claude, (ollama if settings.use_local_fallback else None)


def test_claude_connection(settings: Settings, api_key: str | None = None) -> str:
    """One tiny request through the real backend; returns a human-readable success line or raises."""
    key = api_key or get_api_key()
    if not key:
        raise RuntimeError("No Anthropic API key is set.")
    b = ClaudeBackend(key, settings.claude_model, workspace_id=settings.anthropic_workspace_id)
    schema = {"type": "object", "additionalProperties": False, "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
    b.complete_json("Reply with JSON only.", "Return ok=true.", schema, effort="low", max_tokens=200)
    return f"Connected. Model {settings.claude_model} responded."


def transcribe_file(
    audio_path: str,
    settings: Settings,
    cache_path: Path | None = None,
    language: str | None = None,
    hotwords: str | None = None,
    progress: ProgressCb | None = None,
    transcriber: Transcriber | None = None,
    force: bool = False,
) -> Transcript:
    if cache_path and cache_path.exists() and not force:
        return Transcript.from_dict(json.loads(cache_path.read_text(encoding="utf-8")))
    if progress:
        progress("decode", 0.0)
    audio = normalize_for_asr(load_audio(audio_path))
    t = transcriber or Transcriber(settings)
    tr = t.transcribe(
        audio,
        language=language,
        hotwords=hotwords,
        progress=(lambda f: progress("asr", f)) if progress else None,
    )
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(tr.to_dict(), ensure_ascii=False), encoding="utf-8")
    return tr


def translate_cues(
    cues: list[Cue],
    language: str,
    settings: Settings,
    hint: str = "",
    glossary: list[dict] | None = None,
    card: dict | None = None,
    progress: ProgressCb | None = None,
    log: Callable[[str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[dict, TranslationPipeline, list[Backend]]:
    primary, fallback = build_backends(settings)
    pipe = TranslationPipeline(
        primary,
        fallback,
        quality=settings.quality,
        review_model=settings.claude_review_model or None,
        progress=progress,
        log=log,
        cancel_check=cancel_check,
    )
    card = pipe.run(cues, language, hint=hint, glossary=glossary, card=card)
    return card, pipe, [b for b in (primary, fallback) if b]


def hotwords_from_glossary(glossary: list[dict] | None) -> str | None:
    """Source-language glossary terms bias Whisper toward correct names/terms."""
    if not glossary:
        return None
    terms = [g["source"] for g in glossary if g.get("source")]
    return ", ".join(terms)[:400] or None


def transcript_to_cues(tr: Transcript) -> list[Cue]:
    return segments_to_cues(tr.segments, tr.language)
