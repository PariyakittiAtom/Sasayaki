"""Subtitle file writers (SRT / WebVTT / ASS). Cues with empty text for the chosen mode are skipped."""

from __future__ import annotations

from pathlib import Path

from ..models import Cue


def _ts(ms: int, sep: str) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{milli:03d}"


def _text(c: Cue, mode: str) -> str:
    if mode == "en":
        return c.en.strip()
    if mode == "src":
        return c.src.strip()
    parts = [p for p in (c.en.strip(), c.src.strip()) if p]  # bilingual: English first
    return "\n".join(parts)


def to_srt(cues: list[Cue], mode: str = "en", offset_ms: int = 0) -> str:
    out, n = [], 1
    for c in cues:
        t = _text(c, mode)
        if not t:
            continue
        out.append(f"{n}\n{_ts(c.start_ms + offset_ms, ',')} --> {_ts(c.end_ms + offset_ms, ',')}\n{t}\n")
        n += 1
    return "\n".join(out)


def to_vtt(cues: list[Cue], mode: str = "en", offset_ms: int = 0) -> str:
    out = ["WEBVTT\n"]
    for c in cues:
        t = _text(c, mode)
        if t:
            out.append(f"{_ts(c.start_ms + offset_ms, '.')} --> {_ts(c.end_ms + offset_ms, '.')}\n{t}\n")
    return "\n".join(out)


def _ass_ts(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h}:{m:02d}:{s:02d}.{milli // 10:02d}"


def to_ass(cues: list[Cue], mode: str = "en", offset_ms: int = 0) -> str:
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
        "Alignment, MarginL, MarginR, MarginV, Outline, Shadow\n"
        "Style: Default,Arial,44,&H00FFFFFF,&H00000000,&H80000000,0,2,40,40,40,2,0\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for c in cues:
        t = _text(c, mode).replace("\n", "\\N")
        if t:
            lines.append(
                f"Dialogue: 0,{_ass_ts(c.start_ms + offset_ms)},{_ass_ts(c.end_ms + offset_ms)},Default,,0,0,0,,{t}"
            )
    return head + "\n".join(lines) + "\n"


WRITERS = {"srt": to_srt, "vtt": to_vtt, "ass": to_ass}


def export(cues: list[Cue], path: str | Path, mode: str = "en", offset_ms: int = 0) -> Path:
    path = Path(path)
    fmt = path.suffix.lstrip(".").lower()
    if fmt not in WRITERS:
        raise ValueError(f"unsupported subtitle format: .{fmt}")
    path.write_text(WRITERS[fmt](cues, mode, offset_ms), encoding="utf-8-sig" if fmt == "srt" else "utf-8")
    return path
