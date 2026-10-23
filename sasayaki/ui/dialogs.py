"""Modal dialogs: collection editor, add-audio options, settings, scene-card editor."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
    QWidget,
)

from ..config import Settings, get_api_key, get_supabase_password, set_api_key, set_supabase_password
from .covers import cover_pixmap, import_cover, remove_cover

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
AUDIO_FILTER = "Audio (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus *.wma);;All files (*)"


class CollectionDialog(QDialog):
    """Create or edit a collection: name, cover image, description and a shared glossary."""

    def __init__(self, parent=None, name="", cover_path=None, description="", glossary=None):
        super().__init__(parent)
        self.setWindowTitle("Collection")
        self.setMinimumWidth(560)
        self._cover_path: str | None = cover_path
        self._imported: list[str] = []  # covers imported during this dialog (cleaned up if unused)

        tabs = QTabWidget()
        general = QWidget()
        form = QFormLayout(general)
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("e.g. Rainy Night Café series")
        form.addRow("Name", self.name)

        self.cover = QLabel()
        self.cover.setFixedSize(140, 140)
        self.cover.setAlignment(Qt.AlignCenter)
        pick = QPushButton("Choose image…")
        clear = QPushButton("Remove")
        pick.clicked.connect(self._pick)
        clear.clicked.connect(self._clear)
        row = QHBoxLayout()
        row.addWidget(self.cover)
        col = QVBoxLayout()
        col.addWidget(pick)
        col.addWidget(clear)
        col.addStretch()
        row.addLayout(col)
        row.addStretch()
        form.addRow("Cover", row)

        self.desc = QPlainTextEdit(description)
        self.desc.setPlaceholderText("Optional notes about this set")
        self.desc.setFixedHeight(80)
        form.addRow("Description", self.desc)
        tabs.addTab(general, "General")

        gl = QWidget()
        gv = QVBoxLayout(gl)
        hint = QLabel(
            "Names, places and fixed terms for every track in this collection. They are applied "
            "during translation and help the speech recogniser spell names correctly."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        gv.addWidget(hint)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Original (JA/KO)", "English", "Note"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for e in glossary or []:
            self._add_row(e.get("source", ""), e.get("english", ""), e.get("note", ""))
        gv.addWidget(self.table)
        btns = QHBoxLayout()
        add = QPushButton("Add term")
        rem = QPushButton("Remove selected")
        add.clicked.connect(lambda: self._add_row())
        rem.clicked.connect(self._remove_rows)
        btns.addWidget(add)
        btns.addWidget(rem)
        btns.addStretch()
        gv.addLayout(btns)
        tabs.addTab(gl, "Glossary")

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(bb)
        self._refresh_cover()

    def _refresh_cover(self) -> None:
        self.cover.setPixmap(cover_pixmap(self._cover_path, self.name.text() or "?", 140))

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose cover image", "", IMAGE_FILTER)
        if not path:
            return
        try:
            new = import_cover(path)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Cover image", str(e))
            return
        self._imported.append(new)
        self._cover_path = new
        self._refresh_cover()

    def _clear(self) -> None:
        self._cover_path = None
        self._refresh_cover()

    def _add_row(self, source="", english="", note="") -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, v in enumerate((source, english, note)):
            self.table.setItem(r, c, QTableWidgetItem(v))

    def _remove_rows(self) -> None:
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def _accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.information(self, "Collection", "Please give the collection a name.")
            return
        for p in self._imported:  # covers picked then replaced within this dialog
            if p != self._cover_path:
                remove_cover(p)
        self.accept()

    def reject(self) -> None:
        for p in self._imported:
            remove_cover(p)
        super().reject()

    @property
    def result_data(self) -> dict:
        glossary = []
        for r in range(self.table.rowCount()):
            cells = [(self.table.item(r, c).text() if self.table.item(r, c) else "").strip() for c in range(3)]
            if cells[0] and cells[1]:
                glossary.append({"source": cells[0], "english": cells[1], "note": cells[2]})
        return {
            "name": self.name.text().strip(),
            "cover_path": self._cover_path,
            "description": self.desc.toPlainText().strip(),
            "glossary": glossary,
        }


class AddTracksDialog(QDialog):
    """Options applied to the audio files being added."""

    def __init__(self, files: list[str], parent=None, default_quality="balanced"):
        super().__init__(parent)
        self.setWindowTitle(f"Add {len(files)} audio file{'s' if len(files) != 1 else ''}")
        self.setMinimumWidth(480)
        form = QFormLayout()
        self.lang = QComboBox()
        for label, v in (("Auto-detect (Japanese / Korean)", "auto"), ("Japanese", "ja"), ("Korean", "ko")):
            self.lang.addItem(label, v)
        form.addRow("Spoken language", self.lang)
        self.quality = QComboBox()
        for label, v in (
            ("Fast: cheaper, no review pass", "fast"),
            ("Balanced (recommended)", "balanced"),
            ("High accuracy: adds a review pass", "high"),
        ):
            self.quality.addItem(label, v)
        self.quality.setCurrentIndex(self.quality.findData(default_quality))
        form.addRow("Quality", self.quality)
        self.hint = QPlainTextEdit()
        self.hint.setPlaceholderText(
            "Optional but valuable: who is speaking and to whom, e.g. “Older-sister type girlfriend whispering to "
            "the listener at bedtime. She calls the listener ‘anata’. Character name: Mio.”"
        )
        self.hint.setFixedHeight(100)
        form.addRow("Context hint", self.hint)

        lst = QLabel("\n".join(f"• {f.replace(chr(92), '/').rsplit('/', 1)[-1]}" for f in files[:8]) + (f"\n… and {len(files) - 8} more" if len(files) > 8 else ""))
        lst.setObjectName("muted")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Add && generate subtitles")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(lst)
        lay.addLayout(form)
        lay.addWidget(bb)

    @property
    def result_data(self) -> dict:
        return {"src_lang": self.lang.currentData(), "quality": self.quality.currentData(), "hint": self.hint.toPlainText().strip()}


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        self.s = settings
        form = QFormLayout()

        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Stored in Windows Credential Manager" if get_api_key() else "sk-ant-…")
        form.addRow("Anthropic API key", self.key)

        self.workspace = QLineEdit(settings.anthropic_workspace_id)
        self.workspace.setPlaceholderText("Only if the API reports the key is not scoped to a workspace")
        form.addRow("Workspace ID", self.workspace)
        test_row = QHBoxLayout()
        self.btn_test = QPushButton("Test connection")
        self.btn_test.clicked.connect(self._test)
        self.btn_log = QPushButton("Open log folder")
        self.btn_log.clicked.connect(self._open_logs)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.btn_test)
        test_row.addWidget(self.btn_log)
        test_row.addStretch()
        form.addRow("", test_row)
        form.addRow("", self.test_result)

        self.translator = QComboBox()
        self.translator.addItem("Claude (recommended)", "claude")
        self.translator.addItem("Local only (Ollama)", "ollama")
        self.translator.setCurrentIndex(self.translator.findData(settings.translator))
        form.addRow("Translation engine", self.translator)

        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(["claude-sonnet-5-5", "claude-opus-5-5"])
        self.model.setCurrentText(settings.claude_model)
        form.addRow("Claude model", self.model)

        self.review_model = QComboBox()
        self.review_model.setEditable(True)
        self.review_model.addItems(["", "claude-opus-5-5", "claude-sonnet-5-5"])
        self.review_model.setCurrentText(settings.claude_review_model)
        form.addRow("Review-pass model", self.review_model)

        self.fallback = QCheckBox("Use local model when Claude refuses or fails")
        self.fallback.setChecked(settings.use_local_fallback)
        form.addRow("", self.fallback)
        self.ollama_url = QLineEdit(settings.ollama_url)
        self.ollama_model = QLineEdit(settings.ollama_model)
        form.addRow("Ollama URL", self.ollama_url)
        form.addRow("Ollama model", self.ollama_model)

        self.whisper = QComboBox()
        self.whisper.setEditable(True)
        self.whisper.addItems(["large-v3", "large-v3-turbo", "large-v2", "medium", "small"])
        self.whisper.setCurrentText(settings.whisper_model)
        form.addRow("Speech model", self.whisper)
        self.device = QComboBox()
        for v in ("auto", "cuda", "cpu"):
            self.device.addItem(v, v)
        self.device.setCurrentIndex(self.device.findData(settings.whisper_device))
        form.addRow("Device", self.device)

        head = QLabel("<b>Cloud sync</b> (Supabase): keeps your audio and subtitles online for the Android app")
        head.setWordWrap(True)
        form.addRow(head)
        self.sync_on = QCheckBox("Upload my library automatically")
        self.sync_on.setChecked(settings.sync_enabled)
        form.addRow("", self.sync_on)
        self.sb_url = QLineEdit(settings.supabase_url)
        self.sb_url.setPlaceholderText("https://xxxx.supabase.co")
        form.addRow("Project URL", self.sb_url)
        self.sb_key = QLineEdit(settings.supabase_anon_key)
        self.sb_key.setPlaceholderText("anon / publishable key")
        form.addRow("Anon key", self.sb_key)
        self.sb_email = QLineEdit(settings.supabase_email)
        form.addRow("Account email", self.sb_email)
        self.sb_pw = QLineEdit()
        self.sb_pw.setEchoMode(QLineEdit.Password)
        self.sb_pw.setPlaceholderText("Stored in Windows Credential Manager" if get_supabase_password() else "Account password")
        form.addRow("Account password", self.sb_pw)
        self.sync_audio = QComboBox()
        self.sync_audio.addItem("Auto: compress files over 50 MB", "auto")
        self.sync_audio.addItem("Always compress (smallest)", "compressed")
        self.sync_audio.addItem("Always original quality", "original")
        self.sync_audio.setCurrentIndex(max(0, self.sync_audio.findData(settings.sync_audio)))
        self.sync_audio.setToolTip("Compressed audio is Opus ~96 kbps: about a quarter of an MP3's size. The free Supabase plan "
                                   "allows 50 MB per file and 1 GB in total.")
        form.addRow("Upload audio", self.sync_audio)
        sb_row = QHBoxLayout()
        self.btn_sb_test = QPushButton("Test cloud connection")
        self.btn_sb_test.clicked.connect(self._test_cloud)
        sb_row.addWidget(self.btn_sb_test)
        sb_row.addStretch()
        form.addRow("", sb_row)
        self.sb_result = QLabel("")
        self.sb_result.setWordWrap(True)
        form.addRow("", self.sb_result)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(bb)

    def _test(self) -> None:
        """Try the key and model currently typed in the dialog (not yet saved)."""
        from dataclasses import replace

        from ..engine import test_claude_connection
        from .async_util import run_async

        s = replace(
            self.s,
            claude_model=self.model.currentText().strip() or self.s.claude_model,
            anthropic_workspace_id=self.workspace.text().strip(),
        )
        typed = self.key.text().strip() or None
        self.btn_test.setEnabled(False)
        self.test_result.setStyleSheet("")
        self.test_result.setText("Testing…")

        def done(msg: str) -> None:
            self.btn_test.setEnabled(True)
            self.test_result.setStyleSheet("color: #7fd8a6;")
            self.test_result.setText(msg)

        def failed(msg: str) -> None:
            self.btn_test.setEnabled(True)
            self.test_result.setStyleSheet("color: #ff7a8a;")
            self.test_result.setText(msg)

        run_async(lambda: test_claude_connection(s, typed), done, failed, self)

    def _test_cloud(self) -> None:
        from ..sync.service import check_connection
        from .async_util import run_async

        url, key, email = self.sb_url.text().strip().rstrip("/"), self.sb_key.text().strip(), self.sb_email.text().strip()
        pw = self.sb_pw.text() or get_supabase_password() or ""
        self.btn_sb_test.setEnabled(False)
        self.sb_result.setStyleSheet("")
        self.sb_result.setText("Testing…")

        def finish(msg: str, ok: bool) -> None:
            self.btn_sb_test.setEnabled(True)
            self.sb_result.setStyleSheet("color: #7fd8a6;" if ok else "color: #ff7a8a;")
            self.sb_result.setText(msg)

        run_async(lambda: check_connection(url, key, email, pw), lambda m: finish(m, True), lambda m: finish(m, False), self)

    def _open_logs(self) -> None:
        import os

        from ..logging_setup import log_path

        os.startfile(str(log_path().parent))  # noqa: S606 - opens the user's own log folder

    def _save(self) -> None:
        if self.key.text().strip():
            try:
                set_api_key(self.key.text().strip())
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "API key", f"Could not store the key securely:\n{e}")
                return
        s = self.s
        s.anthropic_workspace_id = self.workspace.text().strip()
        s.translator = self.translator.currentData()
        s.claude_model = self.model.currentText().strip() or s.claude_model
        s.claude_review_model = self.review_model.currentText().strip()
        s.use_local_fallback = self.fallback.isChecked()
        s.ollama_url = self.ollama_url.text().strip() or s.ollama_url
        s.ollama_model = self.ollama_model.text().strip() or s.ollama_model
        s.whisper_model = self.whisper.currentText().strip() or s.whisper_model
        s.whisper_device = self.device.currentData()
        if self.sb_pw.text():
            try:
                set_supabase_password(self.sb_pw.text())
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "Cloud sync", f"Could not store the password securely:\n{e}")
                return
        s.sync_enabled = self.sync_on.isChecked()
        s.supabase_url = self.sb_url.text().strip().rstrip("/")
        s.supabase_anon_key = self.sb_key.text().strip()
        s.supabase_email = self.sb_email.text().strip()
        s.sync_audio = self.sync_audio.currentData()
        s.save()
        self.accept()


class ContextCardDialog(QDialog):
    """Edit the scene brief (JSON) that guides translation. Optionally re-translate afterwards."""

    def __init__(self, card: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scene brief")
        self.resize(720, 640)
        self.retranslate = False
        info = QLabel(
            "This brief tells the translator who is speaking to whom, how characters address each other, and "
            "which terms to keep. Correcting it is the most effective way to improve a whole track."
        )
        info.setObjectName("muted")
        info.setWordWrap(True)
        self.edit = QPlainTextEdit(json.dumps(card or {}, ensure_ascii=False, indent=2))
        self.edit.setStyleSheet("font-family: Consolas, monospace;")
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        save = bb.addButton("Save", QDialogButtonBox.AcceptRole)
        save_re = bb.addButton("Save && re-translate", QDialogButtonBox.AcceptRole)
        save_re.setObjectName("primary")
        save.clicked.connect(lambda: self._done(False))
        save_re.clicked.connect(lambda: self._done(True))
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(self.edit)
        lay.addWidget(bb)

    def _done(self, retranslate: bool) -> None:
        try:
            self._card = json.loads(self.edit.toPlainText() or "{}")
            if not isinstance(self._card, dict):
                raise ValueError("The brief must be a JSON object.")
        except ValueError as e:
            QMessageBox.warning(self, "Scene brief", f"That isn't valid JSON:\n{e}")
            return
        self.retranslate = retranslate
        self.accept()

    @property
    def card(self) -> dict:
        return self._card
