import json

import pytest

from sasayaki import engine
from sasayaki.config import Settings
from sasayaki.db.repo import Repo
from sasayaki.jobs.process import process_track
from sasayaki.models import Segment, Transcript, Word
from conftest import FakeBackend


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SASAYAKI_HOME", str(tmp_path / "home"))
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    repo = Repo(tmp_path / "lib.db")
    cid = repo.add_collection("c")
    repo.update_collection(cid, glossary=[{"source": "先輩", "english": "Senpai", "note": ""}])
    tid = repo.add_track(cid, str(audio), src_lang="auto")
    calls = {"asr": 0}

    def fake_asr(path, settings, cache_path=None, language=None, hotwords=None, progress=None, transcriber=None, force=False):
        if cache_path and cache_path.exists() and not force:
            return Transcript.from_dict(json.loads(cache_path.read_text(encoding="utf-8")))
        calls["asr"] += 1
        ws = [Word(0, 500, "先輩", 0.9), Word(600, 1200, "こんにちは。", 0.9), Word(3000, 3500, "ねえ。", 0.9)]
        tr = Transcript("ja", 5000, [Segment(0, 3500, "先輩こんにちは。ねえ。", ws)])
        cache_path.write_text(json.dumps(tr.to_dict(), ensure_ascii=False), encoding="utf-8")
        return tr

    backend = FakeBackend()
    monkeypatch.setattr(engine, "transcribe_file", fake_asr)
    monkeypatch.setattr(engine, "build_backends", lambda s: (backend, None))
    return repo, tid, calls, backend


def test_full_run_persists_cues_card_and_status(env):
    repo, tid, calls, backend = env
    stages = []
    process_track(repo, tid, Settings(), progress=lambda s, f: stages.append(s))
    t = repo.track(tid)
    assert t.status == "done" and t.src_lang == "ja" and t.duration_ms == 5000
    assert t.context_card["setting"] == "test"
    cues = repo.cues(tid)
    assert [c.src for c in cues] == ["先輩こんにちは。", "ねえ。"]
    assert all(c.en.startswith("EN") for c in cues)
    # the collection glossary reached the translator prompt
    assert any("先輩 => Senpai" in c["system"] for c in backend.calls)


def test_translate_only_rerun_keeps_user_edits_and_skips_asr(env):
    repo, tid, calls, _ = env
    process_track(repo, tid, Settings())
    cues = repo.cues(tid)
    cues[0].en, cues[0].user_edited = "My wording", True
    repo.update_cue(tid, cues[0])
    process_track(repo, tid, Settings(), from_stage="translate")
    after = repo.cues(tid)
    assert calls["asr"] == 1
    assert after[0].en == "My wording" and after[1].en.startswith("EN")


def test_missing_audio_sets_error_not_exception(env):
    repo, tid, *_ = env
    repo.update_track(tid, audio_path="C:/definitely/missing.mp3")
    process_track(repo, tid, Settings())
    t = repo.track(tid)
    assert t.status == "error" and "not found" in t.error.lower()


def test_cancel_sets_cancelled(env):
    repo, tid, *_ = env
    process_track(repo, tid, Settings(), cancel_check=lambda: True, progress=lambda s, f: None)
    assert repo.track(tid).status == "cancelled"


def test_missing_api_key_surfaces_clear_error(env, monkeypatch):
    repo, tid, *_ = env
    monkeypatch.setattr(engine, "build_backends", lambda s: (_ for _ in ()).throw(RuntimeError("No Anthropic API key found.")))
    process_track(repo, tid, Settings())
    t = repo.track(tid)
    assert t.status == "error" and "API key" in t.error


def test_total_translation_failure_is_an_error_with_the_real_reason_not_a_silent_done(env, monkeypatch):
    repo, tid, calls, _ = env
    from conftest import BackendError

    def boom(user, n):
        raise BackendError("Anthropic API error 400: key is not scoped to a workspace")

    primary, local = FakeBackend("claude", boom), FakeBackend("ollama", boom)
    monkeypatch.setattr(engine, "build_backends", lambda s: (primary, local))
    process_track(repo, tid, Settings())
    t = repo.track(tid)
    assert t.status == "error"
    assert "not scoped to a workspace" in t.error  # Claude's error, not the fallback's
    assert [c.src for c in repo.cues(tid)]  # source lines stay visible/retryable
