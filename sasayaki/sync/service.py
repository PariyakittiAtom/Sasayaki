"""Push the local library to Supabase. The PC is the source of truth; the phone only reads.

Idempotent: what was already uploaded is remembered in each row's `sync_state` (content hashes), so running
a sync again only sends what changed. Audio is uploaded once per file content.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..config import Settings, get_supabase_password
from ..db.repo import Repo
from .client import SupabaseClient, SyncError
from .transcode import to_opus

logger = logging.getLogger(__name__)

CUE_BATCH = 500
AUTO_COMPRESS_OVER = 50 * 1024 * 1024  # Supabase free plan: 50 MB per file
ProgressCb = Callable[[str, float], None]


@dataclass
class SyncReport:
    collections: int = 0
    tracks: int = 0
    audio_uploaded: int = 0
    deleted: int = 0
    failed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        bits = [f"{self.tracks} track(s) updated", f"{self.audio_uploaded} audio file(s) uploaded"]
        if self.deleted:
            bits.append(f"{self.deleted} removed")
        if self.failed:
            bits.append(f"{len(self.failed)} failed: {self.failed[0]}")
        return ", ".join(bits)


class SyncCancelled(Exception):
    pass


def _digest(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


class SyncService:
    def __init__(self, repo: Repo, client: SupabaseClient, progress: ProgressCb | None = None,
                 cancel_check: Callable[[], bool] | None = None, audio_mode: str = "auto"):
        self.repo, self.client, self.audio_mode = repo, client, audio_mode
        self.progress = progress or (lambda s, f: None)
        self.cancelled = cancel_check or (lambda: False)

    @property
    def uid(self) -> str:
        assert self.client.user_id, "sign in first"
        return self.client.user_id

    # ------------------------------------------------------------------ whole library
    def sync_all(self) -> SyncReport:
        rep = SyncReport()
        self._flush_tombstones(rep)
        for c in self.repo.collections():
            self._guard(rep, f"collection {c.name}", lambda c=c: self.sync_collection(c.id))
            rep.collections += 1
        todo = [t for c in self.repo.collections() for t in self.repo.tracks(c.id) if t.status == "done"]
        for n, t in enumerate(todo):
            if self.cancelled():
                raise SyncCancelled()
            self.progress(f"Syncing {t.title}", n / max(1, len(todo)))
            self._guard(rep, t.title, lambda t=t: self._count(rep, self.sync_track(t.id)))
        self.progress("Sync finished", 1.0)
        return rep

    @staticmethod
    def _guard(rep: SyncReport, what: str, fn) -> None:
        try:
            fn()
        except (SyncError, OSError) as e:
            logger.warning("sync failed for %s: %s", what, e)
            rep.failed.append(f"{what}: {e}")

    @staticmethod
    def _count(rep: SyncReport, result: dict) -> None:
        rep.tracks += bool(result["meta"] or result["cues"] or result["audio"])
        rep.audio_uploaded += result["audio"]

    # ------------------------------------------------------------------ collections
    def sync_collection(self, cid: int) -> str:
        c = self.repo.collection(cid)
        remote_id = c.remote_id or str(uuid.uuid4())
        state = dict(c.sync_state)

        if c.cover_path and Path(c.cover_path).is_file():
            cover_hash = file_sha256(Path(c.cover_path))
            if state.get("cover_hash") != cover_hash:
                path = f"{self.uid}/{remote_id}{Path(c.cover_path).suffix.lower() or '.jpg'}"
                self.client.upload("covers", path, c.cover_path)
                state.update(cover_hash=cover_hash, cover_path=path)
        else:
            state.pop("cover_hash", None)
            state["cover_path"] = None

        meta = _digest([c.name, c.description, c.glossary, state.get("cover_path")])
        if c.remote_id != remote_id or state.get("meta_hash") != meta:
            self.client.upsert("collections", [{
                "id": remote_id, "user_id": self.uid, "name": c.name, "description": c.description,
                "glossary": c.glossary, "cover_path": state.get("cover_path"),
            }], "id")
            state["meta_hash"] = meta
        self.repo.set_sync("collection", cid, remote_id=remote_id, state=state)
        return remote_id

    # ------------------------------------------------------------------ tracks
    def sync_track(self, tid: int) -> dict:
        """Returns what was sent: {"audio": 0/1, "meta": bool, "cues": bool}."""
        t = self.repo.track(tid)
        done = {"audio": 0, "meta": False, "cues": False}
        if t is None or t.status != "done":
            return done
        col = self.repo.collection(t.collection_id)
        coll_remote = col.remote_id or self.sync_collection(col.id)
        remote_id = t.remote_id or str(uuid.uuid4())
        state = dict(t.sync_state)

        # 1. audio (once per content; the row only points at it after the upload succeeded)
        audio = Path(t.audio_path)
        if audio.is_file():
            st = audio.stat()
            stamp = f"{st.st_size}:{st.st_mtime_ns}"
            if state.get("audio_stamp") != stamp:  # don't re-hash an unchanged multi-hundred-MB file
                state["audio_hash"], state["audio_stamp"] = file_sha256(audio), stamp
            compress = self.audio_mode == "compressed" or (self.audio_mode == "auto" and st.st_size > AUTO_COMPRESS_OVER)
            want = "opus" if compress else "original"
            stale_mode = self.audio_mode != "auto" and state.get("uploaded_mode", "original") != want
            if state.get("uploaded_hash") != state["audio_hash"] or stale_mode:
                old_path = state.get("audio_path")
                path, size = self._upload_audio(t.title, audio, remote_id, compress)
                state.update(uploaded_hash=state["audio_hash"], uploaded_mode=want, audio_path=path, audio_bytes=size)
                done["audio"] = 1
                if old_path and old_path != path:  # e.g. an earlier .mp3 replaced by the compressed .opus
                    try:
                        self.client.remove("audio", [old_path])
                    except SyncError:
                        pass
            self.repo.set_sync("track", tid, state=state)  # remember the hash/upload even if a later step fails

        # 2. track row
        meta = _digest([t.title, t.src_lang, t.duration_ms, t.sort_order, coll_remote, t.context_card,
                        state.get("audio_path"), state.get("audio_bytes")])
        if t.remote_id != remote_id or state.get("meta_hash") != meta:
            self.client.upsert("tracks", [{
                "id": remote_id, "user_id": self.uid, "collection_id": coll_remote, "title": t.title,
                "audio_path": state.get("audio_path"), "audio_bytes": state.get("audio_bytes"),
                "duration_ms": t.duration_ms, "src_lang": t.src_lang, "sort_order": t.sort_order,
                "context_card": t.context_card,
            }], "id")
            state["meta_hash"] = meta
            done["meta"] = True
        self.repo.set_sync("track", tid, remote_id=remote_id, state=state)

        # 3. cues
        cues = self.repo.cues(tid)
        digest = _digest([[c.idx, c.start_ms, c.end_ms, c.src, c.en] for c in cues])
        if state.get("cues_hash") != digest:
            rows = [{
                "track_id": remote_id, "idx": c.idx, "user_id": self.uid, "start_ms": c.start_ms, "end_ms": c.end_ms,
                "src_text": c.src, "en_text": c.en,
            } for c in cues]
            for i in range(0, len(rows), CUE_BATCH):
                self.client.upsert("cues", rows[i : i + CUE_BATCH], "track_id,idx")
            self.client.delete("cues", track_id=f"eq.{remote_id}", idx=f"gte.{len(cues)}")  # lines that no longer exist
            state["cues_hash"] = digest
            done["cues"] = True
            self.repo.set_sync("track", tid, state=state)
        return done

    def _upload_audio(self, title: str, audio: Path, remote_id: str, compress: bool) -> tuple[str, int]:
        """Upload one audio file (optionally shrunk to Opus first). Returns (storage path, bytes)."""
        with tempfile.TemporaryDirectory(prefix="sasayaki-up-") as tmp:
            src = audio
            if compress:
                self.progress(f"Compressing {title}", 0.0)
                src = to_opus(audio, Path(tmp) / "upload.opus", progress=lambda f: self._compressing(title, f))
            path = f"{self.uid}/{remote_id}{src.suffix.lower()}"
            self.progress(f"Uploading {title}", 0.0)
            self.client.upload("audio", path, src, progress=lambda s, n: self._uploading(title, s, n))
            return path, src.stat().st_size

    def _compressing(self, title: str, frac: float) -> None:
        if self.cancelled():
            raise SyncCancelled()
        self.progress(f"Compressing {title}", frac)

    def _uploading(self, title: str, sent: int, total: int) -> None:
        if self.cancelled():
            raise SyncCancelled()
        self.progress(f"Uploading {title}", sent / max(1, total))

    # ------------------------------------------------------------------ deletions made locally
    def _flush_tombstones(self, rep: SyncReport) -> None:
        for tomb_id, kind, remote_id, storage in self.repo.tombstones():
            try:
                for bucket in {b for b, _ in storage}:
                    self.client.remove(bucket, [p for b, p in storage if b == bucket])
                self.client.delete(kind, id=f"eq.{remote_id}")
            except SyncError as e:
                rep.failed.append(f"remove {kind[:-1]}: {e}")
                continue
            self.repo.clear_tombstone(tomb_id)
            rep.deleted += 1


def make_client(settings: Settings) -> SupabaseClient:
    client = SupabaseClient(settings.supabase_url, settings.supabase_anon_key)
    password = get_supabase_password()
    if not settings.supabase_email or not password:
        raise SyncError("Cloud sync needs the account email and password (Settings → Cloud sync).")
    client.sign_in(settings.supabase_email, password)
    return client


def sync_library(db_path: str, settings: Settings, progress: ProgressCb | None = None,
                 cancel_check: Callable[[], bool] | None = None) -> SyncReport:
    """Entry point for worker threads: opens its own Repo and client."""
    repo = Repo(db_path)
    try:
        client = make_client(settings)
        try:
            return SyncService(repo, client, progress, cancel_check, settings.sync_audio).sync_all()
        finally:
            client.close()
    finally:
        repo.close()


def check_connection(url: str, anon_key: str, email: str, password: str) -> str:
    """Sign in and confirm the schema exists. Returns a human-readable success message."""
    client = SupabaseClient(url, anon_key)
    try:
        client.sign_in(email, password)
        try:
            client.select("collections", select="id", limit="1")
        except SyncError as e:
            raise SyncError(f"Signed in, but the database tables are missing - run supabase/schema.sql ({e})") from e
        return f"Connected as {email}."
    finally:
        client.close()
