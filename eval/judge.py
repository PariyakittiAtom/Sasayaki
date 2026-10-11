"""LLM judge for translation acceptability. Use a *different, stronger* model than the translator."""

from __future__ import annotations

from sasayaki.translate.base import Backend

JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "acceptable", "error_type", "note"],
                "properties": {
                    "id": {"type": "integer"},
                    "acceptable": {"type": "boolean"},
                    "error_type": {
                        "type": "string",
                        "enum": ["none", "meaning", "pronoun_or_speaker", "tone_register", "term_inconsistency",
                                 "omission_or_addition", "unnatural_english", "censored_or_softened"],
                    },
                    "note": {"type": "string"},
                },
            },
        }
    },
}

JUDGE_SYSTEM = """\
You are a bilingual ({lang}/English) subtitle QA reviewer for ASMR / audio-drama roleplay. For each item you \
get the reference source line (human-verified), a human reference translation when available, and a candidate \
English subtitle. Judge the CANDIDATE against the source.

A candidate is acceptable (acceptable=true) when a bilingual reviewer would ship it: the meaning is conveyed, \
speaker/listener direction (I/you/he/she) is right, the tone and register match the moment, intimacy and \
explicitness are not softened or censored, nothing meaning-bearing is added or dropped, and the English reads \
naturally. Differences of wording from the reference are fine. A minor stylistic imperfection is still \
acceptable. It is NOT acceptable if it has a meaning-altering error, wrong pronoun/speaker, wrong tone that \
changes the feel of the line, censorship, or a real omission/addition. Set error_type to the main problem \
(or "none"). Items marked [context] are neighbours for reference; do not judge them.
Scene brief: {summary}"""


def judge(
    backend: Backend,
    lang: str,
    items: list[dict],
    summary: str = "",
    model: str | None = None,
    batch: int = 40,
    context: int = 2,
) -> dict[int, dict]:
    """items: [{'id', 'src', 'ref_en', 'hyp_en'}] in order. Returns {id: verdict}."""
    out: dict[int, dict] = {}
    system = JUDGE_SYSTEM.format(lang={"ja": "Japanese", "ko": "Korean"}.get(lang, lang), summary=summary or "n/a")
    for s in range(0, len(items), batch):
        chunk = items[s : s + batch]
        before = items[max(0, s - context) : s]
        after = items[s + batch : s + batch + context]
        lines = [f"[context] {i['id']}|{i['src']}|{i['hyp_en']}" for i in before]
        lines += [f"{i['id']}|SRC: {i['src']}|REF: {i.get('ref_en') or '-'}|CAND: {i['hyp_en'] or '(empty)'}" for i in chunk]
        lines += [f"[context] {i['id']}|{i['src']}|{i['hyp_en']}" for i in after]
        data = backend.complete_json(system, "\n".join(lines), JUDGE_SCHEMA, effort="high", model=model)
        for v in data.get("verdicts", []):
            out[v["id"]] = v
    return out
