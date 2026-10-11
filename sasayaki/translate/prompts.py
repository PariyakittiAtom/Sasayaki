"""Prompts and JSON schemas. The scene card + glossary go in the (cached) system prompt; chunk text
goes in the user message."""

from __future__ import annotations

import json

LANG_NAMES = {"ja": "Japanese", "ko": "Korean"}

LANG_NOTES = {
    "ja": (
        "Japanese notes: subjects and pronouns are routinely dropped - work out who is speaking to whom "
        "from the scene card and neighbouring lines, and choose I/you/he/she/we accordingly. Register "
        "(desu/masu vs. casual vs. teasing/clingy speech), first-person (watashi/boku/ore/atashi/uchi) and "
        "second-person choices (anata/kimi/onii-chan/senpai/name+san) are character signals - reflect them "
        "through diction, not by adding romaji. Sentence-final particles (ne, yo, wa, no, kana, mon) carry "
        "tone: convey it naturally. Onomatopoeia and mimetics (fufu, mmm, chu, zawa-zawa) should become natural "
        "English sounds or phrasing."
    ),
    "ko": (
        "Korean notes: subjects and pronouns are routinely dropped - work out who is speaking to whom from the "
        "scene card and neighbouring lines. Speech level (jondaetmal vs. banmal, -yo / -ya / -ne endings) and "
        "address terms (oppa, noona, hyung, jagiya, name+ssi) are character and relationship signals - reflect "
        "them through diction and follow the card's policy for address terms. Onomatopoeia and mimetic words "
        "should become natural English sounds or phrasing."
    ),
}

SCENE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "setting", "summary", "listener", "characters", "tone", "address_terms",
        "glossary", "content_notes", "translation_guidelines",
    ],
    "properties": {
        "setting": {"type": "string"},
        "summary": {"type": "string"},
        "listener": {
            "type": "object",
            "additionalProperties": False,
            "required": ["role", "gender", "notes"],
            "properties": {"role": {"type": "string"}, "gender": {"type": "string"}, "notes": {"type": "string"}},
        },
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "gender", "personality", "speech_style", "calls_listener", "refers_to_self"],
                "properties": {
                    "name": {"type": "string"},
                    "gender": {"type": "string"},
                    "personality": {"type": "string"},
                    "speech_style": {"type": "string"},
                    "calls_listener": {"type": "string"},
                    "refers_to_self": {"type": "string"},
                },
            },
        },
        "tone": {"type": "string"},
        "address_terms": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source", "english", "note"],
                "properties": {"source": {"type": "string"}, "english": {"type": "string"}, "note": {"type": "string"}},
            },
        },
        "glossary": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source", "english", "note"],
                "properties": {"source": {"type": "string"}, "english": {"type": "string"}, "note": {"type": "string"}},
            },
        },
        "content_notes": {"type": "string"},
        "translation_guidelines": {"type": "array", "items": {"type": "string"}},
    },
}

TRANSLATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["lines"],
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "en", "confidence", "asr_suspect", "asr_fix"],
                "properties": {
                    "id": {"type": "integer"},
                    "en": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "asr_suspect": {"type": "boolean"},
                    "asr_fix": {"type": "string"},
                },
            },
        }
    },
}

REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["changes"],
    "properties": {
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "en", "reason", "confidence"],
                "properties": {
                    "id": {"type": "integer"},
                    "en": {"type": "string"},
                    "reason": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
            },
        }
    },
}

CONFIDENCE = {"high": 0.92, "medium": 0.65, "low": 0.3}

# ---------------------------------------------------------------------------------------------
# Scene brief
# ---------------------------------------------------------------------------------------------

SCENE_SYSTEM = """\
You are a senior subtitle translator and localisation editor specialising in {lang} ASMR / audio-drama \
roleplay. Before any line is translated you study the whole script and write a *scene brief* that the \
translators will rely on.

The script is an automatic speech-recognition transcript of a single audio track, so it contains errors: \
mis-heard words, homophones, and occasional hallucinated lines. Read past those errors and infer what was \
actually said. Lines are in chronological order; times are mm:ss.

Produce a concise, accurate brief:
- setting / summary: where and when, what happens, how it progresses.
- listener: who "you" (the listener) is to the speaker (role, gender if clear, how they are treated).
- characters: every voiced character. For each: name (or role if unnamed), gender, personality, speech \
style/register, what they call the listener, how they refer to themselves.
- tone: emotional register and delivery (whispered, teasing, tender, sleepy...).
- address_terms: kinship/role terms and honorifics that recur (e.g. onii-chan, senpai, oppa, -san) with a \
translation policy: either an English rendering or "keep" (leave as the romanised term), plus a note. Choose \
the policy that preserves the relationship best for an English-speaking listener and apply it consistently.
- glossary: names, places, in-world terms, and recurring phrases with fixed English renderings. Also list \
likely ASR misrecognitions of names/terms with the corrected form in the note.
- content_notes: anything translators must treat carefully (explicit/intimate content, dialect, wordplay).
- translation_guidelines: 3-8 short, concrete rules specific to this track (e.g. "speaker is female, \
addresses listener as 'you'; never use 'he'").

Be faithful to the script. If something is ambiguous, say so rather than inventing detail.\
{user_hint}
{collection_glossary}"""


def scene_system(lang: str, hint: str = "", glossary_text: str = "") -> str:
    return SCENE_SYSTEM.format(
        lang=LANG_NAMES.get(lang, lang),
        user_hint=(f"\n\nUser-provided context about this track:\n{hint.strip()}" if hint.strip() else ""),
        collection_glossary=(f"\n\nKnown glossary (authoritative):\n{glossary_text}" if glossary_text else ""),
    )


def mmss(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


def scene_user(cues) -> str:
    lines = "\n".join(f"{c.idx}|{mmss(c.start_ms)}|{c.src}" for c in cues)
    return f"Full script (id|time|text):\n{lines}"


# ---------------------------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------------------------

TRANSLATE_SYSTEM = """\
You are an expert {lang}-to-English subtitle translator for ASMR and audio-drama roleplay. You translate \
in context: the meaning, speaker, listener, relationship, mood and register of each line come from the \
scene brief and the surrounding lines, never from the line alone.

Rules
1. Faithful: translate everything that is said, at the same intensity and explicitness as the original. \
Do not censor, soften, moralise, summarise or add commentary. Do not invent content that is not in the source.
2. Resolve dropped subjects/pronouns from context (who speaks, who is addressed). Keep pronoun direction and \
gender consistent with the scene brief.
3. Voice: keep the speaker's personality, register and intimacy (whispering, teasing, sleepy, flustered). \
Prefer natural spoken English a native speaker would say in that situation over literal wording.
4. Terms: follow the scene brief's address-term policy and glossary exactly and consistently.
5. Vocalisations and sounds (breaths, moans, kisses, laughs, hums, "ah", "n", "fufu") become natural English \
vocalisations in the same spirit (e.g. "Ah...", "Mm...", "Hehe~"). Never explain them.
6. Subtitle form: each id is one subtitle cue. Cue boundaries come from the speech recogniser and may cut \
mid-sentence: translate each cue so the sequence reads naturally across cues, and keep fragments as fragments. \
Never merge ids, split ids or move words between ids. Keep each translation compact (aim for at most ~84 \
characters; shorten wording rather than dropping meaning).
7. The source is an automatic transcript and can be wrong. If a line is nonsensical in context, infer the most \
likely intended phrase from sound-alike words and neighbouring lines, translate that, set asr_suspect=true and \
put your corrected source-language text in asr_fix. If a line is clearly a recogniser hallucination unrelated \
to the scene (stock phrases such as channel/subscribe/thanks-for-watching text in the middle of a roleplay), \
return an empty en, asr_suspect=true. Otherwise asr_suspect=false and asr_fix="".
8. confidence: "high" when you are sure of meaning and tone; "medium" when a word, referent or nuance is \
uncertain; "low" when you are guessing.
9. Return every requested id exactly once, in order. Lines marked context are for reference only: do not \
translate them.

{lang_notes}

Scene brief
{card}
{glossary}"""


def translate_system(lang: str, card: dict | None, glossary_text: str = "") -> str:
    return TRANSLATE_SYSTEM.format(
        lang=LANG_NAMES.get(lang, lang),
        lang_notes=LANG_NOTES.get(lang, ""),
        card=json.dumps(card or {}, ensure_ascii=False, indent=1),
        glossary=(f"\nAuthoritative glossary (always use these renderings):\n{glossary_text}" if glossary_text else ""),
    )


def translate_user(prev: list, lines: list, nxt: list) -> str:
    parts = []
    if prev:
        parts.append(
            "Earlier lines (context only; already translated):\n"
            + "\n".join(f"{c.idx}|{c.src}|{c.en}" for c in prev)
        )
    parts.append("Translate these lines (id|text):\n" + "\n".join(f"{c.idx}|{c.src}" for c in lines))
    if nxt:
        parts.append("Upcoming lines (context only; do not translate):\n" + "\n".join(f"{c.idx}|{c.src}" for c in nxt))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------------------------

REVIEW_SYSTEM = """\
You are the final editor of {lang}-to-English subtitles for ASMR / audio-drama roleplay. You receive source \
lines with a draft translation and the scene brief. Find and fix real problems only:
- wrong meaning, or a misheard source word the draft translated literally;
- wrong pronoun direction (I/you/he/she), wrong gender, or wrong speaker/listener relationship;
- address terms or glossary items rendered inconsistently with the scene brief or earlier lines;
- tone/register that does not match the character or moment (too stiff, too crude, flat);
- lines that are unnatural English, or over ~84 characters when they could be tighter;
- censorship, softening, omissions or invented content.

Do NOT change a line for style preference alone. Return only the lines you change, with the corrected English, \
a short reason, and your confidence. If everything is fine, return an empty list. Never change ids.

{lang_notes}

Scene brief
{card}
{glossary}"""


def review_system(lang: str, card: dict | None, glossary_text: str = "") -> str:
    return REVIEW_SYSTEM.format(
        lang=LANG_NAMES.get(lang, lang),
        lang_notes=LANG_NOTES.get(lang, ""),
        card=json.dumps(card or {}, ensure_ascii=False, indent=1),
        glossary=(f"\nAuthoritative glossary:\n{glossary_text}" if glossary_text else ""),
    )


def review_user(prev: list, lines: list, nxt: list) -> str:
    parts = []
    if prev:
        parts.append("Earlier lines (context only):\n" + "\n".join(f"{c.idx}|{c.src}|{c.en}" for c in prev))
    parts.append("Lines to review (id|source|draft):\n" + "\n".join(f"{c.idx}|{c.src}|{c.en}" for c in lines))
    if nxt:
        parts.append("Upcoming lines (context only):\n" + "\n".join(f"{c.idx}|{c.src}" for c in nxt))
    return "\n\n".join(parts)


def format_glossary(entries: list[dict]) -> str:
    """entries: [{'source','english','note'}] -> one line each."""
    out = []
    for e in entries:
        note = f"  ({e['note']})" if e.get("note") else ""
        out.append(f"- {e['source']} => {e['english']}{note}")
    return "\n".join(out)
