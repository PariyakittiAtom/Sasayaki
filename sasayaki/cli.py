"""Command line entry point: `python -m sasayaki.cli run song.mp3 --lang ja`."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import Settings
from .engine import hotwords_from_glossary, transcribe_file, transcript_to_cues, translate_cues
from .models import Cue
from .subs.export import export


def _progress(stage: str, frac: float) -> None:
    print(f"\r[{stage:<9}] {frac * 100:5.1f}%", end="", file=sys.stderr, flush=True)
    if frac >= 1.0:
        print(file=sys.stderr)


def _load_glossary(path: str | None) -> list[dict]:
    if not path:
        return []
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_run(a: argparse.Namespace) -> int:
    settings = Settings.load()
    if a.quality:
        settings.quality = a.quality
    if a.model:
        settings.claude_model = a.model
    if a.engine:
        settings.translator = a.engine
    audio = Path(a.audio)
    out_dir = Path(a.out_dir) if a.out_dir else audio.parent
    work = out_dir / f"{audio.stem}.sasayaki"
    work.mkdir(parents=True, exist_ok=True)
    glossary = _load_glossary(a.glossary)

    t0 = time.time()
    tr = transcribe_file(
        str(audio),
        settings,
        cache_path=work / "asr.json",
        language=None if a.lang == "auto" else a.lang,
        hotwords=hotwords_from_glossary(glossary),
        progress=_progress,
        force=a.redo_asr,
    )
    t_asr = time.time() - t0
    cues = transcript_to_cues(tr)
    print(f"{len(cues)} cues, language={tr.language}, asr {t_asr:.0f}s", file=sys.stderr)
    (work / "cues_src.json").write_text(
        json.dumps([c.to_dict() for c in cues], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if a.asr_only:
        export(cues, work / "source.srt", mode="src")
        return 0

    card = json.loads(Path(a.card).read_text(encoding="utf-8")) if a.card else None
    t1 = time.time()
    card, pipe, backends = translate_cues(
        cues, tr.language, settings, hint=a.hint or "", glossary=glossary, card=card,
        progress=_progress, log=lambda m: print(m, file=sys.stderr),
    )
    (work / "scene_card.json").write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")
    (work / "cues.json").write_text(
        json.dumps([c.to_dict() for c in cues], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    srt = export(cues, out_dir / f"{audio.stem}.en.srt", mode="en")
    export(cues, work / "bilingual.srt", mode="both")

    s = pipe.stats
    print(f"\nwrote {srt}", file=sys.stderr)
    print(
        f"translate {time.time() - t1:.0f}s | chunks={s.chunks} fallback={s.fallback_chunks} "
        f"retried={s.retried_chunks} untranslated={s.untranslated} review_changes={s.review_changes}",
        file=sys.stderr,
    )
    for b in backends:
        u = b.usage
        if u.calls:
            print(
                f"{b.name}: calls={u.calls} in={u.input_tokens} out={u.output_tokens} "
                f"cache_read={u.cache_read_tokens} cache_write={u.cache_write_tokens}",
                file=sys.stderr,
            )
    low = [c for c in cues if (c.confidence or 1) < 0.5 or "asr_suspect" in c.flags]
    print(f"{len(low)} cues flagged for review (low confidence / suspected ASR error)", file=sys.stderr)
    return 0


def cmd_translate(a: argparse.Namespace) -> int:
    """Re-run translation from a cues_src.json (no GPU)."""
    settings = Settings.load()
    if a.quality:
        settings.quality = a.quality
    cues = [Cue.from_dict(d) for d in json.loads(Path(a.cues).read_text(encoding="utf-8"))]
    for c in cues:
        c.en, c.confidence, c.flags = "", None, [f for f in c.flags if f in ("repetitive", "low_confidence", "stock_phrase", "repeat_collapsed")]
    card = json.loads(Path(a.card).read_text(encoding="utf-8")) if a.card else None
    card, pipe, _ = translate_cues(
        cues, a.lang, settings, hint=a.hint or "", glossary=_load_glossary(a.glossary), card=card,
        progress=_progress, log=lambda m: print(m, file=sys.stderr),
    )
    out = Path(a.out)
    export(cues, out, mode="en")
    Path(a.cues).with_name("scene_card.json").write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    from .logging_setup import setup_logging

    setup_logging()
    p = argparse.ArgumentParser(prog="sasayaki")
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="audio -> English .srt")
    r.add_argument("audio")
    r.add_argument("--lang", choices=["auto", "ja", "ko"], default="auto")
    r.add_argument("--hint", help="free-text context about the track (roleplay setup, characters...)")
    r.add_argument("--glossary", help="JSON file: [{source, english, note}]")
    r.add_argument("--card", help="reuse/edit a scene_card.json instead of generating one")
    r.add_argument("--quality", choices=["fast", "balanced", "high"])
    r.add_argument("--model")
    r.add_argument("--engine", choices=["claude", "ollama"])
    r.add_argument("--out-dir")
    r.add_argument("--asr-only", action="store_true")
    r.add_argument("--redo-asr", action="store_true")
    r.set_defaults(fn=cmd_run)

    t = sub.add_parser("translate", help="re-translate from cues_src.json")
    t.add_argument("cues")
    t.add_argument("--lang", choices=["ja", "ko"], required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--hint")
    t.add_argument("--glossary")
    t.add_argument("--card")
    t.add_argument("--quality", choices=["fast", "balanced", "high"])
    t.set_defaults(fn=cmd_translate)

    y = sub.add_parser("sync", help="upload the library (audio + subtitles) to your Supabase project")
    y.set_defaults(fn=cmd_sync)

    g = sub.add_parser("gui", help="open the desktop app (default when no command is given)")
    g.set_defaults(fn=lambda _a: _gui())

    args = sys.argv[1:] if argv is None else argv
    if not args:
        return _gui()
    a = p.parse_args(args)
    return a.fn(a)


def cmd_sync(_a) -> int:
    from .config import data_dir
    from .sync.client import SyncError
    from .sync.service import sync_library

    settings = Settings.load()
    try:
        rep = sync_library(str(data_dir() / "library.db"), settings, lambda s, f: print(f"\r{s} {f:4.0%}   ", end="", flush=True))
    except SyncError as e:
        print(f"\nSync failed: {e}")
        return 1
    print(f"\n{rep.summary()}")
    return 1 if rep.failed else 0


def _gui() -> int:
    from .app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
