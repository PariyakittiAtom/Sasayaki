"""SQLite library: collections, tracks, cues. Single connection, used from the GUI thread; worker
threads open their own `Repo` on the same file (SQLite WAL handles the concurrency)."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from ..models import Cue

SCHEMA = """
CREATE TABLE IF NOT EXISTS collection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    cover_path TEXT,
    description TEXT NOT NULL DEFAULT '',
    glossary_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS track (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER NOT NULL REFERENCES collection(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    audio_path TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    src_lang TEXT NOT NULL DEFAULT 'auto',
    sort_order INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued|transcribing|translating|done|error|cancelled
    stage_progress REAL NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    hint TEXT NOT NULL DEFAULT '',
    quality TEXT NOT NULL DEFAULT 'balanced',
    context_card_json TEXT NOT NULL DEFAULT '',
    audio_hash TEXT NOT NULL DEFAULT '',
    added_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_track_collection ON track(collection_id, sort_order);
CREATE TABLE IF NOT EXISTS cue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL REFERENCES track(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    src_text TEXT NOT NULL,
    en_text TEXT NOT NULL DEFAULT '',
    confidence REAL,
    flags TEXT NOT NULL DEFAULT '[]',
    asr_fix TEXT NOT NULL DEFAULT '',
    user_edited INTEGER NOT NULL DEFAULT 0,
    UNIQUE(track_id, idx)
);
"""

STATUS_DONE = "done"


@dataclass
class Collection:
    id: int
    name: str
    cover_path: str | None
    description: str
    glossary: list[dict]
    created_at: float


@dataclass
class Track:
    id: int
    collection_id: int
    title: str
    audio_path: str
    duration_ms: int
    src_lang: str
    sort_order: int
    status: str
    stage_progress: float
    error: str
    hint: str
    quality: str
    context_card: dict | None
    added_at: float

    @property
    def audio_exists(self) -> bool:
        return Path(self.audio_path).exists()


def _col(r: sqlite3.Row) -> Collection:
    return Collection(r["id"], r["name"], r["cover_path"], r["description"], json.loads(r["glossary_json"] or "[]"), r["created_at"])


def _track(r: sqlite3.Row) -> Track:
    card = json.loads(r["context_card_json"]) if r["context_card_json"] else None
    return Track(
        r["id"], r["collection_id"], r["title"], r["audio_path"], r["duration_ms"], r["src_lang"], r["sort_order"],
        r["status"], r["stage_progress"], r["error"], r["hint"], r["quality"], card, r["added_at"],
    )


class Repo:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # ---- collections
    def add_collection(self, name: str, cover_path: str | None = None, description: str = "") -> int:
        cur = self.db.execute(
            "INSERT INTO collection(name, cover_path, description, created_at) VALUES (?,?,?,?)",
            (name.strip(), cover_path, description, time.time()),
        )
        self.db.commit()
        return cur.lastrowid

    def update_collection(self, cid: int, **fields) -> None:
        allowed = {"name", "cover_path", "description"}
        sets, vals = [], []
        for k, v in fields.items():
            if k == "glossary":
                sets.append("glossary_json=?")
                vals.append(json.dumps(v, ensure_ascii=False))
            elif k in allowed:
                sets.append(f"{k}=?")
                vals.append(v)
        if sets:
            self.db.execute(f"UPDATE collection SET {', '.join(sets)} WHERE id=?", (*vals, cid))
            self.db.commit()

    def delete_collection(self, cid: int) -> None:
        self.db.execute("DELETE FROM collection WHERE id=?", (cid,))
        self.db.commit()

    def collections(self) -> list[Collection]:
        return [_col(r) for r in self.db.execute("SELECT * FROM collection ORDER BY name COLLATE NOCASE")]

    def collection(self, cid: int) -> Collection | None:
        r = self.db.execute("SELECT * FROM collection WHERE id=?", (cid,)).fetchone()
        return _col(r) if r else None

    def collection_track_count(self, cid: int) -> int:
        return self.db.execute("SELECT COUNT(*) FROM track WHERE collection_id=?", (cid,)).fetchone()[0]

    # ---- tracks
    def add_track(self, collection_id: int, audio_path: str, title: str | None = None, src_lang: str = "auto",
                  hint: str = "", quality: str = "balanced", duration_ms: int = 0) -> int:
        order = self.db.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM track WHERE collection_id=?", (collection_id,)).fetchone()[0]
        cur = self.db.execute(
            "INSERT INTO track(collection_id,title,audio_path,duration_ms,src_lang,sort_order,hint,quality,added_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (collection_id, title or Path(audio_path).stem, audio_path, duration_ms, src_lang, order, hint, quality, time.time()),
        )
        self.db.commit()
        return cur.lastrowid

    def track(self, tid: int) -> Track | None:
        r = self.db.execute("SELECT * FROM track WHERE id=?", (tid,)).fetchone()
        return _track(r) if r else None

    def tracks(self, collection_id: int) -> list[Track]:
        return [_track(r) for r in self.db.execute("SELECT * FROM track WHERE collection_id=? ORDER BY sort_order, id", (collection_id,))]

    def update_track(self, tid: int, **fields) -> None:
        allowed = {"title", "audio_path", "duration_ms", "src_lang", "status", "stage_progress", "error", "hint", "quality", "collection_id"}
        sets, vals = [], []
        for k, v in fields.items():
            if k == "context_card":
                sets.append("context_card_json=?")
                vals.append(json.dumps(v, ensure_ascii=False) if v else "")
            elif k in allowed:
                sets.append(f"{k}=?")
                vals.append(v)
        if sets:
            self.db.execute(f"UPDATE track SET {', '.join(sets)} WHERE id=?", (*vals, tid))
            self.db.commit()

    def delete_track(self, tid: int) -> None:
        self.db.execute("DELETE FROM track WHERE id=?", (tid,))
        self.db.commit()

    def reorder_tracks(self, collection_id: int, ordered_ids: list[int]) -> None:
        for i, tid in enumerate(ordered_ids):
            self.db.execute("UPDATE track SET sort_order=? WHERE id=? AND collection_id=?", (i, tid, collection_id))
        self.db.commit()

    def move_track(self, tid: int, new_collection_id: int) -> None:
        order = self.db.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM track WHERE collection_id=?", (new_collection_id,)).fetchone()[0]
        self.db.execute("UPDATE track SET collection_id=?, sort_order=? WHERE id=?", (new_collection_id, order, tid))
        self.db.commit()

    def reset_interrupted(self) -> None:
        """Jobs left mid-flight by a crash/close go back to the queue (stages resume from cache)."""
        self.db.execute("UPDATE track SET status='queued', stage_progress=0 WHERE status IN ('transcribing','translating')")
        self.db.commit()

    # ---- cues
    def replace_cues(self, tid: int, cues: list[Cue]) -> None:
        with self.db:
            self.db.execute("DELETE FROM cue WHERE track_id=?", (tid,))
            self.db.executemany(
                "INSERT INTO cue(track_id,idx,start_ms,end_ms,src_text,en_text,confidence,flags,asr_fix,user_edited) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(tid, c.idx, c.start_ms, c.end_ms, c.src, c.en, c.confidence, json.dumps(c.flags), c.asr_fix, int(c.user_edited)) for c in cues],
            )

    def cues(self, tid: int) -> list[Cue]:
        rows = self.db.execute("SELECT * FROM cue WHERE track_id=? ORDER BY idx", (tid,))
        return [
            Cue(r["idx"], r["start_ms"], r["end_ms"], r["src_text"], r["en_text"], r["confidence"],
                json.loads(r["flags"]), r["asr_fix"], bool(r["user_edited"]))
            for r in rows
        ]

    def update_cue(self, tid: int, c: Cue) -> None:
        self.db.execute(
            "UPDATE cue SET start_ms=?,end_ms=?,src_text=?,en_text=?,confidence=?,flags=?,asr_fix=?,user_edited=? WHERE track_id=? AND idx=?",
            (c.start_ms, c.end_ms, c.src, c.en, c.confidence, json.dumps(c.flags), c.asr_fix, int(c.user_edited), tid, c.idx),
        )
        self.db.commit()
