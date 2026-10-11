import threading
import time

import pytest

from sasayaki.asr.transcriber import Transcriber
from sasayaki.config import Settings
from sasayaki.db.repo import Repo


def test_detect_language_passes_vad_options_object_and_restricts_to_ja_ko():
    """Regression: detect_language() crashed with "'dict' object has no attribute 'threshold'"."""
    from faster_whisper.vad import VadOptions

    seen = {}

    class StubModel:
        def detect_language(self, **kw):
            seen.update(kw)
            return "en", 0.9, [("en", 0.9), ("ko", 0.06), ("ja", 0.03)]

    t = Transcriber(Settings())
    t._model = StubModel()
    lang, conf = t.detect_language(audio=None)
    assert isinstance(seen["vad_parameters"], VadOptions)
    assert lang == "ko" and 0.6 < conf < 0.7  # English is ignored; ko wins among ja/ko


@pytest.fixture
def qapp():
    from PySide6.QtCore import QCoreApplication

    return QCoreApplication.instance() or QCoreApplication([])


def pump(app, cond, timeout=5.0):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return cond()


def test_track_can_be_requeued_after_it_finished_and_duplicates_are_ignored(tmp_path, monkeypatch, qapp):
    """Regression: a finished track stayed in the 'queued' set, so Retry / Re-translate / Redo did nothing."""
    from sasayaki.jobs.queue import JobQueue

    calls, gate = [], threading.Event()

    def fake_process(repo, tid, settings, **kw):
        calls.append((tid, kw["from_stage"]))
        gate.wait(5)
        repo.update_track(tid, status="done")

    monkeypatch.setattr("sasayaki.jobs.queue.process_track", fake_process)
    db = str(tmp_path / "lib.db")
    repo = Repo(db)
    tid = repo.add_track(repo.add_collection("c"), "a.mp3")
    q = JobQueue(db, lambda: Settings())
    try:
        q.enqueue(tid, "auto")
        assert pump(qapp, lambda: len(calls) == 1)
        q.enqueue(tid, "translate")  # still running -> ignored
        gate.set()
        assert pump(qapp, lambda: tid not in q._pending)
        assert calls == [(tid, "auto")]

        q.enqueue(tid, "translate")  # finished -> accepted again
        assert pump(qapp, lambda: len(calls) == 2)
        assert calls[1] == (tid, "translate")
        assert pump(qapp, lambda: tid not in q._pending)

        q.enqueue(tid, "asr")  # and again, for "Redo everything"
        assert pump(qapp, lambda: len(calls) == 3)
    finally:
        gate.set()
        q.shutdown()
        repo.close()
