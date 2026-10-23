"""Collection detail page: header (cover, name, actions) and the track table."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMenu, QMessageBox,
    QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..config import cache_dir
from ..db.repo import Repo, Track
from . import theme
from .flow import FlowLayout
from .covers import cover_pixmap
from .dialogs import AUDIO_FILTER

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"}
LANG_LABEL = {"ja": "Japanese", "ko": "Korean", "auto": "Auto"}
STAGE_LABEL = {"decode": "Reading audio", "asr": "Transcribing", "scene": "Analyzing scene", "translate": "Translating", "review": "Reviewing"}
STATUS_COLOR = {
    "done": theme.OK, "error": theme.ERROR, "cancelled": theme.MUTED, "queued": theme.MUTED,
    "transcribing": theme.ACCENT, "translating": theme.ACCENT,
}


def fmt_len(ms: int) -> str:
    s = ms // 1000
    return f"{s // 3600}:{(s // 60) % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}" if ms else "—"


def audio_files(paths: list[str]) -> list[str]:
    return [p for p in paths if Path(p).suffix.lower() in AUDIO_EXTS]


class CollectionPage(QWidget):
    playRequested = Signal(int)
    addFiles = Signal(list)
    editCollection = Signal()
    deleteCollection = Signal()
    libraryChanged = Signal()  # counts etc. changed -> sidebar should refresh

    def __init__(self, repo: Repo, queue, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.setAcceptDrops(True)
        self.repo, self.queue = repo, queue
        self.cid: int | None = None
        self._rows: dict[int, int] = {}  # track id -> row

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 18)
        head = QHBoxLayout()
        head.setSpacing(18)
        self.cover = QLabel()
        self.cover.setFixedSize(132, 132)
        head.addWidget(self.cover)
        info = QVBoxLayout()
        self.name = QLabel("")
        self.name.setObjectName("h1")
        self.meta = QLabel("")
        self.meta.setObjectName("muted")
        self.desc = QLabel("")
        self.desc.setWordWrap(True)
        self.desc.setObjectName("muted")
        self.name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # long names clip instead of widening the window
        self.meta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        info.addStretch()
        info.addWidget(self.name)
        info.addWidget(self.meta)
        info.addWidget(self.desc)
        row = FlowLayout(hspacing=8, vspacing=6)
        self.btn_add = QPushButton("＋  Add audio")
        self.btn_add.setObjectName("primary")
        self.btn_edit = QPushButton("Edit collection")
        self.btn_del = QPushButton("Delete")
        self.btn_add.clicked.connect(self._pick_files)
        self.btn_edit.clicked.connect(self.editCollection)
        self.btn_del.clicked.connect(self.deleteCollection)
        for b in (self.btn_add, self.btn_edit, self.btn_del):
            row.addWidget(b)
        info.addLayout(row)
        info.addStretch()
        head.addLayout(info, 1)
        root.addLayout(head)
        root.addSpacing(14)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Title", "Language", "Length", "Status"])
        h = self.table.horizontalHeader()
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.Interactive)
        self.table.setColumnWidth(4, 260)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.cellDoubleClicked.connect(lambda r, _c: self._play_row(r))
        root.addWidget(self.table, 1)

        self.empty = QLabel("Drop audio files here, or click “Add audio”.\nSubtitles are generated automatically.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setObjectName("muted")
        root.addWidget(self.empty)

    # ------------------------------------------------------------------ data
    def show_collection(self, cid: int) -> None:
        self.cid = cid
        self.refresh()

    def refresh(self) -> None:
        c = self.repo.collection(self.cid) if self.cid is not None else None
        if c is None:
            return
        self.cover.setPixmap(cover_pixmap(c.cover_path, c.name, 132))
        self.name.setText(c.name)
        tracks = self.repo.tracks(c.id)
        total = sum(t.duration_ms for t in tracks)
        self.meta.setText(f"{len(tracks)} track{'s' if len(tracks) != 1 else ''}" + (f"  ·  {fmt_len(total)}" if total else ""))
        self.desc.setText(c.description)
        self.desc.setVisible(bool(c.description))
        self.table.setRowCount(len(tracks))
        self._rows = {}
        for r, t in enumerate(tracks):
            self._rows[t.id] = r
            self._fill_row(r, t)
        self.empty.setVisible(not tracks)
        self.table.setVisible(bool(tracks))

    def _fill_row(self, r: int, t: Track) -> None:
        vals = [str(r + 1), t.title, LANG_LABEL.get(t.src_lang, t.src_lang), fmt_len(t.duration_ms), self._status_text(t)]
        for c, v in enumerate(vals):
            it = QTableWidgetItem(v)
            it.setData(Qt.UserRole, t.id)
            if c == 4:
                it.setForeground(QBrush(QColor(STATUS_COLOR.get(t.status, theme.TEXT))))
                if t.error:
                    it.setToolTip(t.error)
            if c == 1 and not t.audio_exists:
                it.setForeground(QBrush(QColor(theme.WARN)))
                it.setToolTip("The audio file is missing. Right-click → Locate audio file…")
            self.table.setItem(r, c, it)
        self.table.setRowHeight(r, 38)

    @staticmethod
    def _status_text(t: Track) -> str:
        if t.status == "done":
            cloud = "☁ " if t.remote_id and t.sync_state.get("cues_hash") else ""
            return cloud + "Ready" + (f" · {t.error}" if t.error else "")
        if t.status == "error":
            return f"Failed: {t.error}"[:90]
        if t.status in ("transcribing", "translating"):
            return f"{'Transcribing' if t.status == 'transcribing' else 'Translating'}… {int(t.stage_progress * 100)}%"
        return {"queued": "Waiting in queue", "cancelled": "Cancelled"}.get(t.status, t.status)

    def update_track_row(self, tid: int) -> None:
        r = self._rows.get(tid)
        t = self.repo.track(tid)
        if r is None or t is None or t.collection_id != self.cid:
            return
        self._fill_row(r, t)

    def update_progress(self, tid: int, stage: str, frac: float) -> None:
        r = self._rows.get(tid)
        if r is None:
            return
        it = self.table.item(r, 4)
        if it:
            it.setText(f"{STAGE_LABEL.get(stage, stage)}… {int(frac * 100)}%")
            it.setForeground(QBrush(QColor(theme.ACCENT)))

    # ------------------------------------------------------------------ add / drop
    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add audio", "", AUDIO_FILTER)
        if files:
            self.addFiles.emit(files)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and audio_files([u.toLocalFile() for u in e.mimeData().urls()]):
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = audio_files([u.toLocalFile() for u in e.mimeData().urls()])
        if files:
            self.addFiles.emit(files)
            e.acceptProposedAction()

    # ------------------------------------------------------------------ per-track actions
    def _tid(self, row: int) -> int | None:
        it = self.table.item(row, 0)
        return it.data(Qt.UserRole) if it else None

    def _play_row(self, row: int) -> None:
        tid = self._tid(row)
        t = self.repo.track(tid) if tid else None
        if not t:
            return
        if t.status == "done" or self.repo.cues(t.id):
            self.playRequested.emit(t.id)
        else:
            QMessageBox.information(self, "Not ready", "Subtitles for this track are still being generated.")

    def _menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        tid = self._tid(row)
        t = self.repo.track(tid)
        if t is None:
            return
        m = QMenu(self)
        busy = t.status in ("queued", "transcribing", "translating")
        act = {}
        if t.status == "done":
            act[m.addAction("Play")] = lambda: self.playRequested.emit(tid)
            m.addSeparator()
        if busy:
            act[m.addAction("Cancel")] = lambda: self.queue.cancel(tid)
        else:
            if t.status == "done":
                act[m.addAction("Re-translate (keep transcript)")] = lambda: self.queue.enqueue(tid, "translate")
                act[m.addAction("Redo everything from the audio")] = lambda: self._redo_all(tid)
            else:
                act[m.addAction("Retry")] = lambda: self.queue.enqueue(tid, "auto")
        m.addSeparator()
        act[m.addAction("Rename…")] = lambda: self._rename(t)
        act[m.addAction("Move up")] = lambda: self._move(row, -1)
        act[m.addAction("Move down")] = lambda: self._move(row, +1)
        others = [c for c in self.repo.collections() if c.id != self.cid]
        if others:
            sub = m.addMenu("Move to collection")
            for c in others:
                act[sub.addAction(c.name)] = (lambda cid=c.id: self._move_to(tid, cid))
        m.addSeparator()
        if not t.audio_exists:
            act[m.addAction("Locate audio file…")] = lambda: self._relink(t)
        else:
            act[m.addAction("Show in folder")] = lambda: self._reveal(t.audio_path)
        act[m.addAction("Remove from library")] = lambda: self._remove(t)
        chosen = m.exec(self.table.viewport().mapToGlobal(pos))
        if chosen in act:
            act[chosen]()

    def _redo_all(self, tid: int) -> None:
        if QMessageBox.question(self, "Redo", "Transcribe again from the audio?\nLines you edited will be lost.") == QMessageBox.Yes:
            self.repo.update_track(tid, context_card=None)
            self.repo.replace_cues(tid, [])
            self.queue.enqueue(tid, "asr")

    def _rename(self, t: Track) -> None:
        name, ok = QInputDialog.getText(self, "Rename track", "Title", text=t.title)
        if ok and name.strip():
            self.repo.update_track(t.id, title=name.strip())
            self.refresh()

    def _move(self, row: int, delta: int) -> None:
        ids = [self._tid(r) for r in range(self.table.rowCount())]
        j = row + delta
        if 0 <= j < len(ids):
            ids[row], ids[j] = ids[j], ids[row]
            self.repo.reorder_tracks(self.cid, ids)
            self.refresh()
            self.table.selectRow(j)

    def _move_to(self, tid: int, cid: int) -> None:
        self.repo.move_track(tid, cid)
        self.refresh()
        self.libraryChanged.emit()

    def _relink(self, t: Track) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Locate audio file", "", AUDIO_FILTER)
        if path:
            self.repo.update_track(t.id, audio_path=path)
            self.refresh()

    @staticmethod
    def _reveal(path: str) -> None:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    def _remove(self, t: Track) -> None:
        if QMessageBox.question(
            self, "Remove track", f"Remove “{t.title}” from the library?\nThe audio file on disk is not deleted."
        ) != QMessageBox.Yes:
            return
        self.queue.cancel(t.id)
        self.repo.delete_track(t.id)
        shutil.rmtree(cache_dir(t.id), ignore_errors=True)
        self.refresh()
        self.libraryChanged.emit()
