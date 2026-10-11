"""Cover image import (center-crop to a square thumbnail) and generated placeholders."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPixmap

from ..config import covers_dir

THUMB = 512


def import_cover(src_path: str) -> str:
    """Copy `src_path` into the library as a 512x512 PNG (center-cropped). Returns the new path."""
    img = QImage(src_path)
    if img.isNull():
        raise ValueError("That file could not be read as an image.")
    side = min(img.width(), img.height())
    img = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
    img = img.scaled(THUMB, THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    name = hashlib.sha1(f"{src_path}{time.time()}".encode()).hexdigest()[:16] + ".png"
    dest = covers_dir() / name
    if not img.save(str(dest), "PNG"):
        raise OSError("Could not save the cover image into the library.")
    return str(dest)


def remove_cover(path: str | None) -> None:
    """Delete a library-owned cover file (never touches files outside the covers folder)."""
    if not path:
        return
    p = Path(path)
    try:
        if p.exists() and p.resolve().parent == covers_dir().resolve():
            p.unlink()
    except OSError:
        pass


def placeholder(name: str, size: int = 256) -> QPixmap:
    """Deterministic gradient tile with the collection's initial."""
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:6], 16)
    c1 = QColor.fromHsv(h % 360, 110, 140)
    c2 = QColor.fromHsv((h // 7 + 50) % 360, 140, 90)
    pm = QPixmap(size, size)
    p = QPainter(pm)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, c1)
    g.setColorAt(1, c2)
    p.fillRect(0, 0, size, size, g)
    p.setPen(QColor(255, 255, 255, 220))
    f = QFont("Segoe UI", int(size * 0.28), QFont.Bold)
    p.setFont(f)
    p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, (name.strip()[:1] or "?").upper())
    p.end()
    return pm


def cover_pixmap(path: str | None, name: str, size: int) -> QPixmap:
    if path and Path(path).exists():
        pm = QPixmap(path)
        if not pm.isNull():
            return pm.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    return placeholder(name, size).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
