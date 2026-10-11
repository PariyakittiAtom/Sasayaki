"""Accuracy eval.

Gold layout:  eval/gold/<name>/gold.json
  {"language": "ja", "hint": "...", "audio": "clip.mp3" (optional, for e2e), "glossary": [...],
   "cues": [{"start_ms": 0, "end_ms": 2100, "src": "...", "en": "human reference translation"}]}

Modes
  translation  gold source lines -> translator -> judge   (isolates translation quality)
  e2e          audio -> ASR -> translator -> judge + CER   (what the user actually experiences)

Reports acceptable-rate (the ">90%" metric), CER, timing error, and writes a CSV for human spot checks.
Usage: python -m eval.run_eval eval/gold/clip1 --mode translation --quality high
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sasayaki.config import Settings, get_api_key  # noqa: E402
from sasayaki.engine import hotwords_from_glossary, transcribe_file, transcript_to_cues, translate_cues  # noqa: E402
from sasayaki.models import Cue  # noqa: E402
from sasayaki.translate.claude import ClaudeBackend  # noqa: E402

from eval.judge import judge  # noqa: E402
from eval.metrics import cer, hyp_for_gold, timing_error_ms  # noqa: E402


def run(gold_dir: Path, mode: str, quality: str, judge_model: str, model: str | None, out_dir: Path) -> dict:
    gold = json.loads((gold_dir / "gold.json").read_text(encoding="utf-8"))
    lang, gcues = gold["language"], gold["cues"]
    settings = Settings.load()
    settings.quality = quality
    if model:
        settings.claude_model = model
    report: dict = {"clip": gold_dir.name, "mode": mode, "quality": quality, "translator": settings.claude_model}

    if mode == "translation":
        cues = [Cue(i, g["start_ms"], g["end_ms"], g["src"]) for i, g in enumerate(gcues)]
    else:
        tr = transcribe_file(
            str(gold_dir / gold["audio"]), settings, cache_path=out_dir / "asr.json",
            language=lang, hotwords=hotwords_from_glossary(gold.get("glossary")),
        )
        cues = transcript_to_cues(tr)
        report["cer"] = round(cer(" ".join(g["src"] for g in gcues), " ".join(c.src for c in cues)), 4)
        report["timing"] = timing_error_ms(gcues, cues)

    card, pipe, backends = translate_cues(
        cues, lang, settings, hint=gold.get("hint", ""), glossary=gold.get("glossary"),
        log=lambda m: print(m, file=sys.stderr),
    )

    items = [
        {
            "id": i,
            "src": g["src"],
            "ref_en": g.get("en", ""),
            "hyp_en": (cues[i].en if mode == "translation" else hyp_for_gold(g, cues, "en")),
        }
        for i, g in enumerate(gcues)
    ]
    key = get_api_key()
    if not key:
        raise RuntimeError("judge needs ANTHROPIC_API_KEY")
    verdicts = judge(ClaudeBackend(key, judge_model), lang, items, summary=card.get("summary", ""), model=judge_model)

    ok = sum(1 for i in items if verdicts.get(i["id"], {}).get("acceptable"))
    report["lines"] = len(items)
    report["acceptable"] = ok
    report["acceptable_rate"] = round(ok / max(1, len(items)), 4)
    errs: dict[str, int] = {}
    for v in verdicts.values():
        if not v["acceptable"]:
            errs[v["error_type"]] = errs.get(v["error_type"], 0) + 1
    report["error_types"] = errs
    report["pipeline"] = vars(pipe.stats)
    report["usage"] = {b.name: vars(b.usage) for b in backends}

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"{mode}_{quality}.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "source", "reference_en", "candidate_en", "judge_ok", "error_type", "judge_note", "your_verdict"])
        for i in items:
            v = verdicts.get(i["id"], {})
            w.writerow([i["id"], i["src"], i["ref_en"], i["hyp_en"], v.get("acceptable"), v.get("error_type"), v.get("note"), ""])
    (out_dir / f"{mode}_{quality}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("gold_dir")
    p.add_argument("--mode", choices=["translation", "e2e"], default="translation")
    p.add_argument("--quality", choices=["fast", "balanced", "high"], default="balanced")
    p.add_argument("--judge-model", default="claude-opus-5-5")
    p.add_argument("--model", help="translator model override")
    p.add_argument("--out", default="eval/results")
    a = p.parse_args()
    gd = Path(a.gold_dir)
    rep = run(gd, a.mode, a.quality, a.judge_model, a.model, Path(a.out) / gd.name)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
