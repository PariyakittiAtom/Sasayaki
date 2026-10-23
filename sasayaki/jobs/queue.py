"""Qt job queue: one background thread processes tracks one at a time (the GPU is the bottleneck)."""

from __future__ import annotations

import queue
import threading

from PySide6.QtCore import QObject, QThread, Signal

from ..asr.transcriber import Transcriber
from ..config import Settings
from ..db.repo import Repo
from .process import process_track


class _Worker(QThread):
    progress = Signal(int, str, float)  # track id, stage, fraction
    changed = Signal(int)  # track row updated in DB (status etc.)
    finished_track = Signal(int)  # job for this track is over (done/error/cancelled): it may be queued again
    message = Signal(str)
    idle = Signal()

    def __init__(self, db_path: str, get_settings):
        super().__init__()
        self.db_path = db_path
        self.get_settings = get_settings
        self.q: "queue.Queue[tuple[int, str] | None]" = queue.Queue()
        self.cancelled: set[int] = set()
        self.lock = threading.Lock()
        self.current: int | None = None

    def run(self) -> None:
        repo = Repo(self.db_path)
        transcriber: Transcriber | None = None
        while True:
            item = self.q.get()
            if item is None:
                break
            tid, stage = item
            with self.lock:
                if tid in self.cancelled:
                    self.cancelled.discard(tid)
                    repo.update_track(tid, status="cancelled")
                    self.changed.emit(tid)
                    self.finished_track.emit(tid)
                    continue
                self.current = tid
            settings = self.get_settings()
            if transcriber is None:
                transcriber = Transcriber(settings)
            transcriber.settings = settings
            process_track(
                repo, tid, settings,
                progress=lambda s, f, tid=tid: self.progress.emit(tid, s, f),
                cancel_check=lambda tid=tid: tid in self.cancelled,
                from_stage=stage,
                transcriber=transcriber,
                log=self.message.emit,
            )
            with self.lock:
                self.cancelled.discard(tid)
                self.current = None
            self.changed.emit(tid)
            self.finished_track.emit(tid)
            if self.q.empty():
                transcriber.unload()  # free VRAM when idle (a local LLM may want it)
                transcriber = None
                self.idle.emit()
        repo.close()


class JobQueue(QObject):
    progress = Signal(int, str, float)
    changed = Signal(int)
    message = Signal(str)
    idle = Signal()

    def __init__(self, db_path: str, get_settings, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._w = _Worker(db_path, get_settings)
        self._w.progress.connect(self.progress)
        self._w.changed.connect(self.changed)
        self._w.finished_track.connect(self._on_finished)
        self._w.message.connect(self.message)
        self._w.idle.connect(self.idle)
        self._repo = Repo(db_path)
        self._pending: set[int] = set()  # tracks that are waiting or running right now (GUI thread only)
        self._w.start()

    def _on_finished(self, track_id: int) -> None:
        self._pending.discard(track_id)

    def enqueue(self, track_id: int, from_stage: str = "auto") -> None:
        if track_id in self._pending:
            return  # already waiting or running; a duplicate would just redo the work
        self._pending.add(track_id)
        with self._w.lock:
            self._w.cancelled.discard(track_id)
        self._repo.update_track(track_id, status="queued", stage_progress=0, error="")
        self.changed.emit(track_id)
        self._w.q.put((track_id, from_stage))

    def cancel(self, track_id: int) -> None:
        with self._w.lock:
            self._w.cancelled.add(track_id)

    def shutdown(self) -> None:
        with self._w.lock:
            if self._w.current is not None:
                self._w.cancelled.add(self._w.current)
        self._w.q.put(None)
        self._w.wait(15000)
        self._repo.close()
