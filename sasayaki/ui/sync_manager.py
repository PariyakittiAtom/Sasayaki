"""Runs cloud syncs on a background thread; coalesces bursts of requests into one run."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from ..config import Settings, get_supabase_password
from ..sync.service import sync_library
from .async_util import run_async


class SyncManager(QObject):
    status = Signal(str, bool)  # message, is_error
    busy = Signal(bool)
    finished = Signal()  # a run ended (rows' sync state changed)
    _progress = Signal(str)

    def __init__(self, db_path: str, get_settings, parent=None):
        super().__init__(parent)
        self.db_path, self.get_settings = db_path, get_settings
        self.running = False
        self._again = False
        self._cancel = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(2500)
        self._timer.timeout.connect(self._start)
        self._progress.connect(lambda m: self.status.emit(m, False))
        self._last = (None, -1)

    def missing(self) -> list[str]:
        """What still has to be filled in under Settings → Cloud sync (empty when ready)."""
        s: Settings = self.get_settings()
        out = []
        if not s.supabase_url:
            out.append("project URL")
        if not s.supabase_anon_key:
            out.append("anon key")
        if not s.supabase_email:
            out.append("account email")
        if not get_supabase_password():
            out.append("account password")
        return out

    def configured(self) -> bool:
        return not self.missing()

    def enabled(self) -> bool:
        """Automatic syncing: set up AND switched on. The Sync now button only needs it to be set up."""
        return bool(self.get_settings().sync_enabled and self.configured())

    def request(self, now: bool = False) -> None:
        """Ask for a sync. Automatic requests are delayed a moment so several changes in a row become one run."""
        if not (self.configured() if now else self.enabled()):
            return
        if now:
            self._timer.stop()
            self._start()
        else:
            self._timer.start()

    def shutdown(self) -> None:
        self._cancel = True
        self._timer.stop()

    # ------------------------------------------------------------------
    def _report(self, label: str, frac: float) -> None:
        key = (label, int(frac * 100))
        if key != self._last:  # one signal per percent, not per megabyte chunk
            self._last = key
            self._progress.emit(f"Cloud sync: {label} {key[1]}%" if frac < 1 else f"Cloud sync: {label}")

    def _start(self) -> None:
        if self.running:
            self._again = True
            return
        if not self.configured():
            return
        self.running, self._cancel = True, False
        self.busy.emit(True)
        settings = self.get_settings()
        run_async(
            lambda: sync_library(self.db_path, settings, self._report, lambda: self._cancel),
            self._done, self._failed, self,
        )

    def _finish(self) -> None:
        self.running = False
        self.busy.emit(False)
        self.finished.emit()
        if self._again and not self._cancel:
            self._again = False
            self._timer.start()

    def _done(self, rep) -> None:
        self.status.emit(f"Cloud sync done: {rep.summary()}", bool(rep.failed))
        self._finish()

    def _failed(self, msg: str) -> None:
        self.status.emit(("Cloud sync stopped." if "SyncCancelled" in msg else f"Cloud sync failed: {msg}"), "SyncCancelled" not in msg)
        self._finish()
