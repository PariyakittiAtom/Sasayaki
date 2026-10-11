"""Run a blocking function off the GUI thread and deliver its result back on it."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal


class _Task(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn())
        except Exception as e:  # noqa: BLE001 - reported to the user
            self.failed.emit(str(e) or e.__class__.__name__)


_alive: set[_Task] = set()


def run_async(fn: Callable, on_done: Callable, on_error: Callable[[str], None], parent: QObject | None = None) -> None:
    t = _Task(fn, parent)
    _alive.add(t)  # keep a reference until finished

    def cleanup():
        _alive.discard(t)
        t.deleteLater()

    t.done.connect(on_done)
    t.failed.connect(on_error)
    t.finished.connect(cleanup)
    t.start()
