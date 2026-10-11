"""Process one library track end-to-end and persist results. Qt-free so it can be tested directly.

Stages are resumable: the ASR result is cached on disk, the scene card and cues live in the DB, and
`from_stage="translate"` re-runs only translation (keeping any cues the user edited).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable

from .. import engine
from ..asr.transcriber import Transcriber
from ..config import Settings, cache_dir
from ..db.repo import Repo
from ..models import Cue
from ..translate.pipeline import Cancelled

ProgressCb = Callable[[str, float], None]
logger = logging.getLogger(__name__)


def process_track(
    repo: Repo,
    track_id: int,
    settings: Settings,
    progress: ProgressCb | None = None,
    cancel_check: Callable[[], bool] | None = None,
    from_stage: str = "auto",  # auto = resume from cache | asr = redo transcription | translate = redo translation only
    transcriber: Transcriber | None = None,
    log: Callable[[str], None] | None = None,
) -> None:
    progress = progress or (lambda s, f: None)
    cancelled = cancel_check or (lambda: False)
    track = repo.track(track_id)
    if track is None:
        return
    try:
        if not Path(track.audio_path).exists():
            raise FileNotFoundError(f"Audio file not found: {track.audio_path}")
        col = repo.collection(track.collection_id)
        glossary = col.glossary if col else []
        settings = _with_quality(settings, track.quality)
        asr_cache = cache_dir(track_id) / "asr.json"

        # ---- ASR (cached; skipped on translate-only re-runs)
        repo.update_track(track_id, status="transcribing", stage_progress=0, error="")
        tr = engine.transcribe_file(
            track.audio_path,
            settings,
            cache_path=asr_cache,
            language=None if track.src_lang == "auto" else track.src_lang,
            hotwords=engine.hotwords_from_glossary(glossary),
            progress=lambda s, f: (_check(cancelled), progress(s, f)),
            transcriber=transcriber,
            force=(from_stage == "asr"),  # "auto"/"translate" reuse the cached ASR result
        )
        _check(cancelled)

        # ---- cues: reuse existing (keeps user edits) when only re-translating
        existing = repo.cues(track_id)
        if from_stage == "translate" and existing:
            cues = existing
            for c in cues:
                if not c.user_edited:
                    c.en, c.confidence, c.asr_fix = "", None, ""
                    c.flags = [f for f in c.flags if f in ("repetitive", "low_confidence", "stock_phrase", "repeat_collapsed")]
        else:
            cues = engine.transcript_to_cues(tr)
        repo.update_track(track_id, duration_ms=tr.duration_ms, src_lang=tr.language)
        repo.replace_cues(track_id, cues)  # source text visible immediately, even before translation

        # ---- translation
        repo.update_track(track_id, status="translating", stage_progress=0)
        card, pipe, backends = engine.translate_cues(
            cues, tr.language, settings,
            hint=track.hint, glossary=glossary, card=track.context_card,
            progress=lambda s, f: (_check(cancelled), progress(s, f)),
            log=log, cancel_check=cancelled,
        )
        repo.update_track(track_id, context_card=card)
        repo.replace_cues(track_id, cues)
        stats = pipe.stats
        for b in backends:  # exact usage, to compare against the provider's billing page
            u = b.usage
            if u.calls:
                logger.info(
                    "track %s %s usage: model=%s calls=%d input=%d output=%d cache_read=%d cache_write=%d",
                    track_id, b.name, getattr(b, "model", "?"), u.calls, u.input_tokens, u.output_tokens,
                    u.cache_read_tokens, u.cache_write_tokens,
                )
        if stats.untranslated and stats.untranslated >= len(cues):
            # nothing got translated: a configuration/service problem, not a content problem
            raise RuntimeError(f"Translation failed - {stats.last_error or 'no engine produced output'}")
        note = ""
        if stats.untranslated:
            note = f"{stats.untranslated} lines could not be translated ({stats.last_error or 'see log'})."
        logger.info("track %s done: %d cues, %d untranslated, %d fallback chunks", track_id, len(cues), stats.untranslated, stats.fallback_chunks)
        repo.update_track(track_id, status="done", stage_progress=1.0, error=note)
    except Cancelled:
        repo.update_track(track_id, status="cancelled", stage_progress=0)
    except Exception as e:  # surfaced in the UI; never crash the worker thread
        logger.exception("track %s failed", track_id)
        repo.update_track(track_id, status="error", error=str(e) or e.__class__.__name__)


def _check(cancelled: Callable[[], bool]) -> None:
    if cancelled():
        raise Cancelled()


def _with_quality(settings: Settings, quality: str) -> Settings:
    from dataclasses import replace

    return replace(settings, quality=quality or settings.quality)


def retranslate_line(
    repo: Repo, track_id: int, cue_idx: int, settings: Settings, new_src: str | None = None
) -> Cue:
    """Re-translate a single line with its neighbours as context (editor button)."""
    from ..translate import prompts
    from ..translate.pipeline import TranslationPipeline

    track = repo.track(track_id)
    cues = repo.cues(track_id)
    target = cues[cue_idx]
    if new_src is not None:
        target.src = new_src
    target.en, target.user_edited = "", False
    target.flags = [f for f in target.flags if f != "untranslated"]  # re-added by the pipeline if it fails again
    col = repo.collection(track.collection_id)
    primary, fallback = engine.build_backends(settings)
    pipe = TranslationPipeline(primary, fallback, quality=settings.quality)
    system = prompts.translate_system(track.src_lang, track.context_card, prompts.format_glossary(col.glossary if col else []))
    prev = [c for c in cues[max(0, cue_idx - pipe.context_prev) : cue_idx] if c.en]
    nxt = cues[cue_idx + 1 : cue_idx + 1 + pipe.lookahead]
    pipe._translate_chunk(system, [target], prev, nxt)
    repo.update_cue(track_id, target)
    sync_untranslated_note(repo, track_id)
    return target


def sync_untranslated_note(repo: Repo, track_id: int) -> None:
    """Keep the track's "N lines could not be translated" note in step with single-line edits/re-translations."""
    track = repo.track(track_id)
    if track is None or track.status != "done":
        return
    remaining = sum(1 for c in repo.cues(track_id) if "untranslated" in c.flags and not c.en)
    if remaining:
        reason = re.search(r"\((.*)\)\.?$", track.error)
        note = f"{remaining} lines could not be translated ({reason.group(1) if reason else 'see log'})."
    else:
        note = ""
    if note != track.error:
        repo.update_track(track_id, error=note)
