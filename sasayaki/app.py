"""GUI entry point: `python -m sasayaki.app` (or `python -m sasayaki gui`)."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .config import Settings, data_dir
from .db.repo import Repo
from .jobs.queue import JobQueue
from .ui import theme
from .ui.main_window import MainWindow


def main() -> int:
    from .logging_setup import setup_logging

    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Sasayaki")
    app.setStyleSheet(theme.QSS)

    db_path = str(data_dir() / "library.db")
    repo = Repo(db_path)
    repo.reset_interrupted()  # jobs cut off by a crash/close restart from their cached stage
    settings = Settings.load()

    queue = JobQueue(db_path, lambda: Settings.load())
    win = MainWindow(repo, queue, settings)
    win.show()

    for c in repo.collections():
        for t in repo.tracks(c.id):
            if t.status == "queued":
                queue.enqueue(t.id, "auto")
    code = app.exec()
    repo.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
