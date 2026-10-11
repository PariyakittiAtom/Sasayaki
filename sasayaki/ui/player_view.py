"""Audio player with synchronized subtitles, a click-to-seek transcript, and a cue editor."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter,
    QVBoxLayout, QWidget,
)

from ..config import Settings
from ..db.repo import Repo, Track
from ..jobs.process import sync_untranslated_note
from ..models import Cue
from ..player_sync import CueIndex, PositionClock
from ..subs.export import export
from ..translate.prompts import mmss
from . import theme
from .async_util import run_async
from .covers import cover_pixmap
from .dialogs import ContextCardDialog
from .flow import FlowLayout

REVIEW_FLAGS = {"asr_suspect", "low_confidence", "untranslated", "dropped_noise", "local_fallback", "repetitive"}
DISPLAY_MODES = [("English", "en"), ("English + original", "both"), ("Original", "src")]
FLAG_HELP = {
    "asr_suspect": "The translator suspects the speech recogniser misheard this line.",
    "low_confidence": "The speech recogniser was unsure about this line.",
    "untranslated": "This line could not be translated.",
    "dropped_noise": "Treated as noise/hallucination and left blank.",
    "local_fallback": "Translated by the local fallback model (lower quality).",
    "repetitive": "Possible repetition artefact from the speech recogniser.",
}


def needs_review(c: Cue) -> bool:
    return bool(REVIEW_FLAGS & set(c.flags)) or (c.confidence is not None and c.confidence < 0.5)


def fmt_clock(ms: int) -> str:
    s = max(0, ms) // 1000
    h, m, s = s // 3600, (s // 60) % 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class CueSlider(QSlider):
    """Seek bar that paints a density strip of cue start times."""

    def __init__(self, *a):
        super().__init__(Qt.Horizontal, *a)
        self.starts: list[int] = []
        self.setMinimumHeight(26)

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.starts or self.maximum() <= 0:
            return
        p = QPainter(self)
        p.setPen(QPen(QColor(theme.ACCENT), 1))
        w = self.width() - 14
        for s in self.starts:
            x = 7 + int(w * s / self.maximum())
            p.drawLine(x, 1, x, 5)
        p.end()


class PlayerView(QWidget):
    back = Signal()
    trackEnded = Signal()
    retranslateTrack = Signal(int)  # track id: re-run translation only

    def __init__(self, repo: Repo, settings: Settings, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.repo, self.settings = repo, settings
        self.track: Track | None = None
        self.index = CueIndex([])
        self.clock = PositionClock()
        self._active: int | None = None
        self._last: int | None = None
        self._dragging = False
        self._editing: Cue | None = None

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.audio.setVolume(0.8)
        self.player.durationChanged.connect(self._on_duration)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.errorOccurred.connect(lambda _e, msg: self._show_message(msg or "Playback error"))

        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)

        self._build_ui()
        self._bind_keys()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 14)

        top = FlowLayout(hspacing=10, vspacing=8)
        back = QPushButton("← Library")
        back.setObjectName("flat")
        back.clicked.connect(self._go_back)
        self.cover = QLabel()
        self.cover.setFixedSize(44, 44)
        self.title = QLabel("")
        self.title.setObjectName("h2")
        self.subtitle_info = QLabel("")
        self.subtitle_info.setObjectName("muted")
        titles = QWidget()
        tl = QVBoxLayout(titles)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self.title)
        tl.addWidget(self.subtitle_info)
        self.btn_brief = QPushButton("Scene brief…")
        self.btn_retrans = QPushButton("Re-translate")
        self.btn_export = QPushButton("Export…")
        self.btn_edit = QPushButton("Edit lines")
        self.btn_edit.setCheckable(True)
        self.btn_brief.clicked.connect(self._edit_brief)
        self.btn_retrans.clicked.connect(self._retranslate_track)
        self.btn_export.clicked.connect(self._export)
        self.btn_edit.toggled.connect(lambda on: self.editor.setVisible(on))
        for w in (back, self.cover, titles, self.btn_brief, self.btn_retrans, self.btn_export, self.btn_edit):
            top.addWidget(w)
        root.addLayout(top)

        left_w = QWidget()
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; border-radius: 12px; }}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 18, 24, 18)
        self.en_label = QLabel("")
        self.en_label.setAlignment(Qt.AlignCenter)
        self.en_label.setWordWrap(True)
        self.src_label = QLabel("")
        self.src_label.setAlignment(Qt.AlignCenter)
        self.src_label.setWordWrap(True)
        self.src_label.setStyleSheet(f"color: {theme.MUTED}; border: none; background: transparent;")
        self.en_label.setStyleSheet("border: none; background: transparent;")
        cl.addStretch()
        cl.addWidget(self.en_label)
        cl.addWidget(self.src_label)
        cl.addStretch()
        card.setMinimumHeight(110)
        left.addWidget(card)

        bar = FlowLayout(hspacing=14, vspacing=4)
        self.follow = QCheckBox("Follow playback")
        self.follow.setChecked(True)
        self.only_review = QCheckBox("Needs review only")
        self.only_review.toggled.connect(self._apply_filter)
        self.review_count = QLabel("")
        self.review_count.setObjectName("muted")
        bar.addWidget(self.follow)
        bar.addWidget(self.only_review)
        bar.addWidget(self.review_count)
        left.addLayout(bar)

        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.itemClicked.connect(self._on_item_clicked)
        left.addWidget(self.list, 1)

        self.editor = self._build_editor()
        self.editor.setVisible(False)
        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        body.addWidget(left_w)
        body.addWidget(self.editor)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 2)
        root.addWidget(body, 1)

        root.addLayout(self._build_transport())
        self._apply_font()

    def _build_editor(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(240)
        scroll.setWidget(self._build_editor_panel())
        return scroll

    def _build_editor_panel(self) -> QWidget:
        w = QFrame()
        w.setStyleSheet(f"QFrame#ed {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; border-radius: 10px; }}")
        w.setObjectName("ed")
        lay = QVBoxLayout(w)
        h = QLabel("Edit line")
        h.setObjectName("h2")
        lay.addWidget(h)
        self.ed_info = QLabel("Select a line in the transcript.")
        self.ed_info.setObjectName("muted")
        self.ed_info.setWordWrap(True)
        self.ed_info.setMinimumHeight(40)
        self.ed_info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(self.ed_info)
        lay.addWidget(QLabel("English"))
        self.ed_en = QPlainTextEdit()
        self.ed_en.setFixedHeight(80)
        lay.addWidget(self.ed_en)
        lay.addWidget(QLabel("Original"))
        src_hint = QLabel("If the speech was misheard, fix it here and use “Re-translate line”.")
        src_hint.setObjectName("muted")
        src_hint.setWordWrap(True)
        lay.addWidget(src_hint)
        self.ed_src = QPlainTextEdit()
        self.ed_src.setFixedHeight(70)
        lay.addWidget(self.ed_src)

        t = QHBoxLayout()
        self.ed_start = QDoubleSpinBox()
        self.ed_end = QDoubleSpinBox()
        for sb in (self.ed_start, self.ed_end):
            sb.setDecimals(2)
            sb.setSingleStep(0.1)
            sb.setRange(0, 100000)
            sb.setSuffix(" s")
        t.addWidget(QLabel("Start"))
        t.addWidget(self.ed_start)
        t.addWidget(QLabel("End"))
        t.addWidget(self.ed_end)
        lay.addLayout(t)
        t2 = QHBoxLayout()
        a = QPushButton("Start = now")
        b = QPushButton("End = now")
        a.clicked.connect(lambda: self.ed_start.setValue(self.player.position() / 1000))
        b.clicked.connect(lambda: self.ed_end.setValue(self.player.position() / 1000))
        t2.addWidget(a)
        t2.addWidget(b)
        lay.addLayout(t2)

        row = QHBoxLayout()
        self.ed_save = QPushButton("Save")
        self.ed_save.setObjectName("primary")
        self.ed_re = QPushButton("Re-translate line")
        self.ed_save.clicked.connect(self._save_cue)
        self.ed_re.clicked.connect(self._retranslate_line)
        row.addWidget(self.ed_save)
        row.addWidget(self.ed_re)
        lay.addLayout(row)
        lay.addStretch()
        return w

    def _build_transport(self) -> QVBoxLayout:
        v = QVBoxLayout()
        self.seek = CueSlider()
        self.seek.setRange(0, 0)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self.seek.sliderReleased.connect(self._seek_released)
        self.seek.sliderMoved.connect(lambda v_: self.time_label.setText(f"{fmt_clock(v_)} / {fmt_clock(self.seek.maximum())}"))
        v.addWidget(self.seek)

        r = FlowLayout(hspacing=6, vspacing=6)
        self.btn_prev = QPushButton("⏮")
        self.btn_back = QPushButton("−10s")
        self.btn_play = QPushButton("▶  Play")
        self.btn_play.setObjectName("primary")
        self.btn_play.setMinimumWidth(110)
        self.btn_fwd = QPushButton("+10s")
        self.btn_next = QPushButton("⏭")
        self.btn_prev.setToolTip("Previous line (↑)")
        self.btn_next.setToolTip("Next line (↓)")
        self.btn_prev.clicked.connect(lambda: self._jump_cue(-1))
        self.btn_next.clicked.connect(lambda: self._jump_cue(+1))
        self.btn_back.clicked.connect(lambda: self._seek_by(-10000))
        self.btn_fwd.clicked.connect(lambda: self._seek_by(+10000))
        self.btn_play.clicked.connect(self.toggle_play)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("muted")
        for w in (self.btn_prev, self.btn_back, self.btn_play, self.btn_fwd, self.btn_next):
            r.addWidget(w)
        r.addWidget(self.time_label)
        r2 = FlowLayout(hspacing=8, vspacing=6)

        self.speed = QComboBox()
        for s in (0.75, 0.9, 1.0, 1.1, 1.25, 1.5):
            self.speed.addItem(f"{s:g}×", s)
        self.speed.setCurrentIndex(2)
        self.speed.currentIndexChanged.connect(lambda: self.player.setPlaybackRate(self.speed.currentData()))
        self.display = QComboBox()
        for label, v_ in DISPLAY_MODES:
            self.display.addItem(label, v_)
        self.display.setCurrentIndex(1 if self.settings.show_source else 0)
        self.display.currentIndexChanged.connect(self._display_changed)
        self.offset = QSpinBox()
        self.offset.setRange(-10000, 10000)
        self.offset.setSingleStep(50)
        self.offset.setSuffix(" ms")
        self.offset.setValue(self.settings.subtitle_offset_ms)
        self.offset.setToolTip("Shift subtitles. Positive = show later, negative = show earlier  ( [ and ] keys )")
        self.offset.valueChanged.connect(self._offset_changed)
        self.font_size = QSpinBox()
        self.font_size.setRange(14, 64)
        self.font_size.setValue(self.settings.font_size)
        self.font_size.valueChanged.connect(self._font_changed)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setFixedWidth(90)
        self.volume.valueChanged.connect(lambda x: self.audio.setVolume(x / 100))
        for lbl, w in (("Speed", self.speed), ("Show", self.display), ("Sync", self.offset), ("Size", self.font_size), ("Vol", self.volume)):
            l = QLabel(lbl)
            l.setObjectName("muted")
            r2.addWidget(l)
            r2.addWidget(w)
        v.addLayout(r)
        v.addLayout(r2)
        return v

    def _bind_keys(self) -> None:
        def sc(seq, fn):
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(Qt.WidgetWithChildrenShortcut)
            s.activated.connect(fn)

        sc("Space", self.toggle_play)
        sc("Left", lambda: self._seek_by(-5000))
        sc("Right", lambda: self._seek_by(+5000))
        sc("Up", lambda: self._jump_cue(-1))
        sc("Down", lambda: self._jump_cue(+1))
        sc("[", lambda: self.offset.setValue(self.offset.value() - 50))
        sc("]", lambda: self.offset.setValue(self.offset.value() + 50))

    # ------------------------------------------------------------------ loading
    def load_track(self, track_id: int, collection_name: str = "", collection_cover: str | None = None) -> bool:
        track = self.repo.track(track_id)
        if track is None:
            return False
        self.stop()
        self.track = track
        cues = self.repo.cues(track_id)
        self.index = CueIndex(cues)
        self.title.setText(track.title)
        self.subtitle_info.setText(f"{collection_name}  ·  {len(cues)} lines" if collection_name else f"{len(cues)} lines")
        self.cover.setPixmap(cover_pixmap(collection_cover, collection_name or track.title, 44))
        self.seek.starts = [c.start_ms for c in self.index.cues]
        self._active = self._last = None
        self._editing = None
        self._fill_list()
        self._update_review_count()
        self._show_cue(None)
        if not Path(track.audio_path).exists():
            self._show_message(f"Audio file not found:\n{track.audio_path}")
            return True
        self.player.setSource(QUrl.fromLocalFile(track.audio_path))
        self.player.setPlaybackRate(self.speed.currentData() or 1.0)
        return True

    def stop(self) -> None:
        self.timer.stop()
        self.player.stop()
        self.btn_play.setText("▶  Play")

    # ------------------------------------------------------------------ transcript list
    def _item_text(self, c: Cue) -> str:
        en = c.en or ("—" if c.src else "")
        t = f"{mmss(c.start_ms)}   {en}"
        if self.display.currentData() != "en":
            t += f"\n          {c.src}"
        return t

    def _style_item(self, it: QListWidgetItem, c: Cue) -> None:
        review = needs_review(c)
        it.setForeground(QBrush(QColor(theme.WARN if review else theme.TEXT)))
        reasons = [FLAG_HELP[f] for f in c.flags if f in FLAG_HELP]
        if c.asr_fix:
            reasons.append(f"Suggested original: {c.asr_fix}")
        if c.user_edited:
            reasons.append("Edited by you.")
        it.setToolTip("\n".join(reasons))

    def _fill_list(self) -> None:
        self.list.clear()
        for pos, c in enumerate(self.index.cues):
            it = QListWidgetItem(self._item_text(c))
            it.setData(Qt.UserRole, pos)
            self._style_item(it, c)
            self.list.addItem(it)
        self._apply_filter()

    def _apply_filter(self) -> None:
        only = self.only_review.isChecked()
        for i in range(self.list.count()):
            self.list.item(i).setHidden(only and not needs_review(self.index.cues[i]))

    def _update_review_count(self) -> None:
        n = sum(1 for c in self.index.cues if needs_review(c))
        self.review_count.setText(f"{n} line{'s' if n != 1 else ''} flagged for review" if n else "")

    def _on_item_clicked(self, it: QListWidgetItem) -> None:
        pos = it.data(Qt.UserRole)
        c = self.index.cues[pos]
        self.player.setPosition(max(0, c.start_ms + self.offset.value()))
        self._load_editor(c)

    # ------------------------------------------------------------------ playback
    def toggle_play(self) -> None:
        if self.track is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.timer.stop()
            self.btn_play.setText("▶  Play")
        else:
            self.player.play()
            self.timer.start()
            self.btn_play.setText("⏸  Pause")

    def _seek_by(self, delta_ms: int) -> None:
        dur = self.player.duration() or 0
        self.player.setPosition(max(0, min(dur, self.player.position() + delta_ms)))
        self._tick()

    def _jump_cue(self, step: int) -> None:
        if not len(self.index):
            return
        t = self.player.position() - self.offset.value()
        cur = self.index.last_started(t)
        if step < 0:
            # if we're more than 1.5 s into the current line, "previous" restarts it first
            if cur is not None and t - self.index.cues[cur].start_ms > 1500:
                target = cur
            else:
                target = max(0, (cur if cur is not None else 0) - 1)
        else:
            target = 0 if cur is None else min(len(self.index) - 1, cur + 1)
        self.player.setPosition(max(0, self.index.cues[target].start_ms + self.offset.value()))
        self._tick()

    def _seek_released(self) -> None:
        self._dragging = False
        self.player.setPosition(self.seek.value())
        self._tick()

    def _on_duration(self, ms: int) -> None:
        self.seek.setRange(0, ms)

    def _on_status(self, status) -> None:
        if status == QMediaPlayer.EndOfMedia:
            self.timer.stop()
            self.btn_play.setText("▶  Play")
            self.trackEnded.emit()
        elif status == QMediaPlayer.InvalidMedia:
            self._show_message("This audio file could not be played.")

    def _tick(self) -> None:
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        est = self.clock.estimate(self.player.position(), playing, self.player.playbackRate() or 1.0)
        t = est - self.offset.value()  # positive offset delays subtitles
        active = self.index.active(t)
        if active != self._active:
            self._active = active
            self._show_cue(self.index.cues[active] if active is not None else None)
        last = self.index.last_started(t)
        if last != self._last:
            self._set_playing_row(last)
            self._last = last
        if not self._dragging:
            self.seek.setValue(est)
            self.time_label.setText(f"{fmt_clock(est)} / {fmt_clock(self.seek.maximum())}")

    def _show_cue(self, c: Cue | None) -> None:
        mode = self.display.currentData()
        if c is None:
            self.en_label.setText("")
            self.src_label.setText("")
            return
        self.en_label.setText(c.en if mode in ("en", "both") else c.src)
        self.src_label.setText(c.src if mode == "both" else "")

    def _show_message(self, text: str) -> None:
        self.en_label.setText(text)
        self.src_label.setText("")

    def _set_playing_row(self, pos: int | None) -> None:
        hi = QBrush(QColor(theme.ACCENT_DIM))
        none = QBrush(Qt.NoBrush)
        if self._last is not None and self._last < self.list.count():
            it = self.list.item(self._last)
            it.setBackground(none)
            f = it.font()
            f.setBold(False)
            it.setFont(f)
        if pos is not None:
            it = self.list.item(pos)
            it.setBackground(hi)
            f = it.font()
            f.setBold(True)
            it.setFont(f)
            if self.follow.isChecked() and not it.isHidden():
                self.list.scrollToItem(it, QListWidget.PositionAtCenter)

    # ------------------------------------------------------------------ display settings
    def _display_changed(self) -> None:
        self.settings.show_source = self.display.currentData() != "en"
        self.settings.save()
        for i in range(self.list.count()):
            self.list.item(i).setText(self._item_text(self.index.cues[i]))
        self._show_cue(self.index.cues[self._active] if self._active is not None else None)

    def _offset_changed(self, v: int) -> None:
        self.settings.subtitle_offset_ms = v
        self.settings.save()
        self._tick()

    def _font_changed(self, v: int) -> None:
        self.settings.font_size = v
        self.settings.save()
        self._apply_font()

    def _apply_font(self) -> None:
        sz = self.settings.font_size
        self.en_label.setStyleSheet(f"font-size: {sz}pt; font-weight: 600; border: none; background: transparent;")
        self.src_label.setStyleSheet(f"font-size: {max(10, int(sz * 0.55))}pt; color: {theme.MUTED}; border: none; background: transparent;")

    # ------------------------------------------------------------------ editing
    def _load_editor(self, c: Cue) -> None:
        self._editing = c
        self.ed_en.setPlainText(c.en)
        self.ed_src.setPlainText(c.src)
        self.ed_start.setValue(c.start_ms / 1000)
        self.ed_end.setValue(c.end_ms / 1000)
        bits = []
        if c.confidence is not None:
            bits.append(f"confidence {c.confidence:.0%}")
        bits += [FLAG_HELP.get(f, f) for f in c.flags if f in FLAG_HELP]
        if c.asr_fix:
            bits.append(f"suggested original: {c.asr_fix}")
        self.ed_info.setText(f"Line {c.idx + 1}. " + ("; ".join(bits) if bits else "No issues flagged."))

    def _pos_of(self, c: Cue) -> int:
        # identity, not equality: dataclass == would match a different cue with identical fields
        return next(i for i, x in enumerate(self.index.cues) if x is c)

    def _save_cue(self) -> None:
        c = self._editing
        if c is None or self.track is None:
            return
        start, end = round(self.ed_start.value() * 1000), round(self.ed_end.value() * 1000)
        if end <= start:
            QMessageBox.information(self, "Edit line", "The end time must be after the start time.")
            return
        timing_changed = (start, end) != (c.start_ms, c.end_ms)
        c.en, c.src, c.start_ms, c.end_ms = self.ed_en.toPlainText().strip(), self.ed_src.toPlainText().strip(), start, end
        c.user_edited = True
        if c.en and "untranslated" in c.flags:
            c.flags = [f for f in c.flags if f != "untranslated"]
        self.repo.update_cue(self.track.id, c)
        sync_untranslated_note(self.repo, self.track.id)
        if timing_changed:
            self.index = CueIndex(self.index.cues)  # re-sort
            self.seek.starts = [x.start_ms for x in self.index.cues]
            self._fill_list()
            self._active = self._last = None
        else:
            pos = self._pos_of(c)
            it = self.list.item(pos)
            it.setText(self._item_text(c))
            self._style_item(it, c)
        self._update_review_count()
        self._tick()

    def _retranslate_line(self) -> None:
        c = self._editing
        if c is None or self.track is None:
            return
        from ..jobs.process import retranslate_line

        tid, idx, new_src, db, settings = self.track.id, c.idx, self.ed_src.toPlainText().strip(), self.repo.path, self.settings
        self.ed_re.setEnabled(False)
        self.ed_re.setText("Translating…")

        def work():
            r = Repo(db)
            try:
                return retranslate_line(r, tid, idx, settings, new_src=new_src)
            finally:
                r.close()

        def done(updated: Cue):
            c.en, c.src, c.confidence, c.flags, c.asr_fix, c.user_edited = updated.en, updated.src, updated.confidence, updated.flags, updated.asr_fix, False
            self._reset_retranslate_button()
            self._load_editor(c)
            it = self.list.item(self._pos_of(c))
            it.setText(self._item_text(c))
            self._style_item(it, c)
            self._update_review_count()

        def failed(msg: str):
            self._reset_retranslate_button()
            QMessageBox.warning(self, "Re-translate", msg)

        run_async(work, done, failed, self)

    def _reset_retranslate_button(self) -> None:
        self.ed_re.setEnabled(True)
        self.ed_re.setText("Re-translate line")

    # ------------------------------------------------------------------ toolbar actions
    def _edit_brief(self) -> None:
        if self.track is None:
            return
        dlg = ContextCardDialog(self.track.context_card, self)
        if dlg.exec():
            self.repo.update_track(self.track.id, context_card=dlg.card)
            self.track.context_card = dlg.card
            if dlg.retranslate:
                self._confirm_retranslate()

    def _retranslate_track(self) -> None:
        self._confirm_retranslate()

    def _confirm_retranslate(self) -> None:
        if self.track is None:
            return
        edited = sum(1 for c in self.index.cues if c.user_edited)
        extra = f"\n\n{edited} line(s) you edited will be kept." if edited else ""
        if QMessageBox.question(self, "Re-translate", "Re-translate this track using the current scene brief?" + extra) == QMessageBox.Yes:
            self.retranslateTrack.emit(self.track.id)

    def _export(self) -> None:
        if self.track is None:
            return
        mode, ok = QInputDialog.getItem(self, "Export subtitles", "Contents", [m for m, _ in DISPLAY_MODES], 0, False)
        if not ok:
            return
        mode_v = dict(DISPLAY_MODES)[mode]
        path, sel = QFileDialog.getSaveFileName(
            self, "Export subtitles", f"{self.track.title}.srt", "SubRip (*.srt);;WebVTT (*.vtt);;Advanced SubStation (*.ass)"
        )
        if not path:
            return
        ext = {"SubRip": ".srt", "WebVTT": ".vtt", "Advanced": ".ass"}.get(sel.split(" ")[0], ".srt")
        if Path(path).suffix.lower() not in (".srt", ".vtt", ".ass"):
            path += ext
        try:
            export(self.index.cues, path, mode=mode_v, offset_ms=self.offset.value())
        except OSError as e:
            QMessageBox.warning(self, "Export", str(e))

    def _go_back(self) -> None:
        self.stop()
        self.back.emit()
