"""Main window: collection sidebar + stacked pages (empty / collection / player)."""

from __future__ import annotations

import shutil

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget,
)

from ..config import Settings, cache_dir, get_api_key
from ..db.repo import Repo
from ..jobs.queue import JobQueue
from .covers import cover_pixmap, remove_cover
from .dialogs import AddTracksDialog, CollectionDialog, SettingsDialog
from .library_view import STAGE_LABEL, CollectionPage
from .player_view import PlayerView


class MainWindow(QMainWindow):
    def __init__(self, repo: Repo, queue: JobQueue, settings: Settings):
        super().__init__()
        self.repo, self.queue, self.settings = repo, queue, settings
        self.setWindowTitle("Sasayaki")
        self.resize(1280, 820)
        self._current_cid: int | None = None
        self._player_cid: int | None = None

        side = QWidget()
        side.setObjectName("sidebar")
        side.setMinimumWidth(150)
        side.setMaximumWidth(380)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 14)
        brand = QLabel("Sasayaki")
        brand.setObjectName("h1")
        sub = QLabel("囁き · subtitles for whispered audio")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        sl.addWidget(brand)
        sl.addWidget(sub)
        sl.addSpacing(14)
        lab = QLabel("COLLECTIONS")
        lab.setObjectName("muted")
        sl.addWidget(lab)
        self.coll_list = QListWidget()
        self.coll_list.setIconSize(QSize(44, 44))
        self.coll_list.setSpacing(2)
        self.coll_list.setFrameShape(QListWidget.NoFrame)
        self.coll_list.setStyleSheet("QListWidget { background: transparent; border: none; }")
        self.coll_list.currentItemChanged.connect(self._on_select)
        sl.addWidget(self.coll_list, 1)
        new = QPushButton("＋  New collection")
        new.setObjectName("primary")
        new.clicked.connect(self.new_collection)
        sl.addWidget(new)
        st = QPushButton("Settings")
        st.clicked.connect(self.open_settings)
        sl.addWidget(st)

        self.stack = QStackedWidget()
        self.empty = QLabel("Create a collection to get started.\nA collection is a named set of audio with its own cover image.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setObjectName("muted")
        self.page = CollectionPage(repo, queue)
        self.player = PlayerView(repo, settings)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.page)
        self.stack.addWidget(self.player)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(1)
        split.addWidget(side)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([270, 1010])
        self.setCentralWidget(split)

        self.page.playRequested.connect(self.play_track)
        self.page.addFiles.connect(self.add_files)
        self.page.editCollection.connect(self.edit_collection)
        self.page.deleteCollection.connect(self.delete_collection)
        self.page.libraryChanged.connect(self.refresh_sidebar)
        self.player.back.connect(self._leave_player)
        self.player.trackEnded.connect(self._play_next)
        self.player.retranslateTrack.connect(lambda tid: self.queue.enqueue(tid, "translate"))
        queue.changed.connect(self._on_job_changed)
        queue.progress.connect(self._on_job_progress)
        queue.message.connect(lambda m: self.statusBar().showMessage(m, 8000))
        queue.idle.connect(lambda: self.statusBar().showMessage("All subtitle jobs finished.", 6000))

        self.refresh_sidebar()

    # ------------------------------------------------------------------ sidebar
    def refresh_sidebar(self, select: int | None = None) -> None:
        keep = select if select is not None else self._current_cid
        self.coll_list.blockSignals(True)
        self.coll_list.clear()
        target = None
        for c in self.repo.collections():
            n = self.repo.collection_track_count(c.id)
            it = QListWidgetItem(f"{c.name}\n{n} track{'s' if n != 1 else ''}")
            it.setIcon(QIcon(cover_pixmap(c.cover_path, c.name, 44)))
            it.setData(Qt.UserRole, c.id)
            it.setSizeHint(QSize(0, 56))
            self.coll_list.addItem(it)
            if c.id == keep:
                target = it
        self.coll_list.blockSignals(False)
        if target is None and self.coll_list.count():
            target = self.coll_list.item(0)
        if target is not None:
            self.coll_list.setCurrentItem(target)
            self._show_collection(target.data(Qt.UserRole))
        else:
            self._current_cid = None
            self.stack.setCurrentWidget(self.empty)

    def _on_select(self, cur, _prev) -> None:
        if cur is not None:
            self.player.stop()
            self._show_collection(cur.data(Qt.UserRole))

    def _show_collection(self, cid: int) -> None:
        self._current_cid = cid
        self.page.show_collection(cid)
        self.stack.setCurrentWidget(self.page)

    # ------------------------------------------------------------------ collections
    def new_collection(self) -> None:
        dlg = CollectionDialog(self)
        if dlg.exec():
            d = dlg.result_data
            cid = self.repo.add_collection(d["name"], d["cover_path"], d["description"])
            self.repo.update_collection(cid, glossary=d["glossary"])
            self.refresh_sidebar(select=cid)

    def edit_collection(self) -> None:
        c = self.repo.collection(self._current_cid) if self._current_cid else None
        if c is None:
            return
        dlg = CollectionDialog(self, c.name, c.cover_path, c.description, c.glossary)
        if dlg.exec():
            d = dlg.result_data
            if c.cover_path and c.cover_path != d["cover_path"]:
                remove_cover(c.cover_path)
            self.repo.update_collection(c.id, name=d["name"], cover_path=d["cover_path"], description=d["description"], glossary=d["glossary"])
            self.refresh_sidebar(select=c.id)

    def delete_collection(self) -> None:
        c = self.repo.collection(self._current_cid) if self._current_cid else None
        if c is None:
            return
        n = self.repo.collection_track_count(c.id)
        if QMessageBox.question(
            self, "Delete collection",
            f"Delete “{c.name}” and its {n} track(s) from the library?\nSubtitles are deleted; the audio files on disk are not.",
        ) != QMessageBox.Yes:
            return
        for t in self.repo.tracks(c.id):
            self.queue.cancel(t.id)
            shutil.rmtree(cache_dir(t.id), ignore_errors=True)
        remove_cover(c.cover_path)
        self.repo.delete_collection(c.id)
        self._current_cid = None
        self.refresh_sidebar()

    # ------------------------------------------------------------------ tracks
    def add_files(self, files: list[str]) -> None:
        if self._current_cid is None:
            return
        if self.settings.translator == "claude" and not get_api_key():
            if QMessageBox.question(
                self, "API key needed",
                "Translation uses Claude, but no Anthropic API key is set.\nOpen Settings now? "
                "(Choose No to add the files anyway; they will wait with an error until a key is set.)",
            ) == QMessageBox.Yes:
                self.open_settings()
        dlg = AddTracksDialog(files, self, self.settings.quality)
        if not dlg.exec():
            return
        opts = dlg.result_data
        for f in files:
            tid = self.repo.add_track(self._current_cid, f, src_lang=opts["src_lang"], hint=opts["hint"], quality=opts["quality"])
            self.queue.enqueue(tid, "auto")
        self.page.refresh()
        self.refresh_sidebar()

    def _on_job_changed(self, tid: int) -> None:
        self.page.update_track_row(tid)
        t = self.repo.track(tid)
        if t and t.status == "done":
            self.statusBar().showMessage(f"Subtitles ready: {t.title}", 6000)
        elif t and t.status == "error":
            self.statusBar().showMessage(f"{t.title}: {t.error}", 12000)

    def _on_job_progress(self, tid: int, stage: str, frac: float) -> None:
        self.page.update_progress(tid, stage, frac)
        t = self.repo.track(tid)
        self.statusBar().showMessage(f"{t.title if t else ''}: {STAGE_LABEL.get(stage, stage)} {int(frac * 100)}%")

    # ------------------------------------------------------------------ player
    def play_track(self, tid: int) -> None:
        t = self.repo.track(tid)
        if t is None:
            return
        c = self.repo.collection(t.collection_id)
        self._player_cid = t.collection_id
        if self.player.load_track(tid, c.name if c else "", c.cover_path if c else None):
            self.stack.setCurrentWidget(self.player)
            self.player.setFocus()

    def _leave_player(self) -> None:
        self.stack.setCurrentWidget(self.page)
        self.page.refresh()

    def _play_next(self) -> None:
        """Autoplay the next finished track of the same collection."""
        cur = self.player.track
        if cur is None:
            return
        tracks = self.repo.tracks(cur.collection_id)
        ids = [t.id for t in tracks]
        if cur.id in ids:
            for t in tracks[ids.index(cur.id) + 1 :]:
                if t.status == "done" and t.audio_exists:
                    self.play_track(t.id)
                    self.player.toggle_play()
                    return

    # ------------------------------------------------------------------ settings / lifecycle
    def open_settings(self) -> None:
        SettingsDialog(self.settings, self).exec()

    def closeEvent(self, e) -> None:
        self.player.stop()
        self.queue.shutdown()
        e.accept()
