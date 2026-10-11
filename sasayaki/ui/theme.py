"""Dark theme (Qt style sheet)."""

BG = "#14131a"
PANEL = "#1c1b24"
PANEL_HI = "#25242f"
BORDER = "#2e2d3a"
TEXT = "#e9e7f2"
MUTED = "#8d8aa3"
ACCENT = "#b79cff"
ACCENT_DIM = "#4a3d7a"
WARN = "#f0b866"
ERROR = "#ff7a8a"
OK = "#7fd8a6"

QSS = f"""
* {{ font-family: "Segoe UI", "Yu Gothic UI", "Malgun Gothic", sans-serif; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QDialog, QWidget#page {{ background: {BG}; }}
QWidget#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#h1 {{ font-size: 20pt; font-weight: 600; }}
QLabel#h2 {{ font-size: 12pt; font-weight: 600; }}
QPushButton {{ background: {PANEL_HI}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {ACCENT_DIM}; }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton#primary {{ background: {ACCENT}; color: #1a1030; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: #c7b0ff; }}
QPushButton#flat {{ background: transparent; border: none; padding: 4px 8px; }}
QPushButton#flat:hover {{ background: {PANEL_HI}; }}
QListWidget, QTableWidget, QTreeWidget, QPlainTextEdit, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; selection-background-color: {ACCENT_DIM};
}}
QListWidget::item {{ padding: 6px 8px; border-radius: 4px; }}
QListWidget::item:selected {{ background: {ACCENT_DIM}; }}
QListWidget::item:hover {{ background: {PANEL_HI}; }}
QTableWidget {{ gridline-color: {BORDER}; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER}; padding: 6px; }}
QTableWidget::item {{ padding: 4px; }}
QTableWidget::item:selected {{ background: {ACCENT_DIM}; }}
QSlider::groove:horizontal {{ height: 6px; background: {PANEL_HI}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -4px 0; background: {TEXT}; border-radius: 7px; }}
QProgressBar {{ background: {PANEL_HI}; border: none; border-radius: 3px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QToolTip {{ background: {PANEL_HI}; color: {TEXT}; border: 1px solid {BORDER}; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
"""
