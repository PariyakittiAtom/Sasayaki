from sasayaki.db.repo import Repo
from sasayaki.models import Cue


def test_collection_and_track_lifecycle(tmp_path):
    r = Repo(tmp_path / "lib.db")
    cid = r.add_collection("Rainy Night Series", cover_path="c.png", description="d")
    other = r.add_collection("another")
    a = r.add_track(cid, "a.mp3", src_lang="ja")
    b = r.add_track(cid, "b.mp3", title="Custom")
    assert [t.title for t in r.tracks(cid)] == ["a", "Custom"]
    assert r.collection(cid).cover_path == "c.png"

    r.reorder_tracks(cid, [b, a])
    assert [t.id for t in r.tracks(cid)] == [b, a]
    r.move_track(a, other)
    assert [t.id for t in r.tracks(cid)] == [b] and [t.id for t in r.tracks(other)] == [a]

    r.update_collection(cid, name="Renamed", glossary=[{"source": "先輩", "english": "Senpai", "note": ""}])
    c = r.collection(cid)
    assert c.name == "Renamed" and c.glossary[0]["english"] == "Senpai"

    r.update_track(b, status="done", context_card={"summary": "x"})
    assert r.track(b).context_card == {"summary": "x"}


def test_cues_roundtrip_and_cascade_delete(tmp_path):
    r = Repo(tmp_path / "lib.db")
    cid = r.add_collection("c")
    t = r.add_track(cid, "a.mp3")
    cues = [Cue(0, 0, 1000, "こんにちは", "Hello", 0.9, ["x"]), Cue(1, 1200, 2000, "ねえ", "Hey", None, [], "fix", True)]
    r.replace_cues(t, cues)
    got = r.cues(t)
    assert got[0].en == "Hello" and got[0].flags == ["x"] and got[1].user_edited and got[1].asr_fix == "fix"

    got[0].en = "Hi there"
    got[0].user_edited = True
    r.update_cue(t, got[0])
    assert r.cues(t)[0].en == "Hi there"

    r.replace_cues(t, cues[:1])  # re-translation replaces, never duplicates
    assert len(r.cues(t)) == 1

    r.delete_collection(cid)
    assert r.tracks(cid) == [] and r.cues(t) == []


def test_reset_interrupted_requeues_inflight_jobs(tmp_path):
    r = Repo(tmp_path / "lib.db")
    cid = r.add_collection("c")
    a, b, c = (r.add_track(cid, f"{n}.mp3") for n in "abc")
    r.update_track(a, status="transcribing", stage_progress=0.5)
    r.update_track(b, status="done")
    r.reset_interrupted()
    assert r.track(a).status == "queued" and r.track(b).status == "done" and r.track(c).status == "queued"
