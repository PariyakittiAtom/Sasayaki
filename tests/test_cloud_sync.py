"""Cloud sync against a fake Supabase (httpx MockTransport): idempotency, resume, deletes, auth refresh."""

import json
import re

import httpx
import pytest

from sasayaki.db.repo import Repo
from sasayaki.models import Cue
from sasayaki.sync.client import SupabaseClient, SyncError
from sasayaki.sync.service import SyncService

UID = "user-1"


class FakeSupabase:
    def __init__(self):
        self.tables = {"collections": {}, "tracks": {}, "cues": {}}
        self.files: dict[tuple[str, str], int] = {}  # (bucket, path) -> size
        self.uploads = 0
        self.sign_ins = 0
        self.expire_next_request = False
        self.fail_upload = False

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    @staticmethod
    def _key(table: str, row: dict):
        return (row["track_id"], row["idx"]) if table == "cues" else row["id"]

    def _cascade(self, table: str, key) -> None:  # mirrors the schema's "on delete cascade"
        child = {"collections": ("tracks", "collection_id"), "tracks": ("cues", "track_id")}.get(table)
        if child:
            for ck in [ck for ck, r in self.tables[child[0]].items() if r[child[1]] == key]:
                del self.tables[child[0]][ck]
                self._cascade(child[0], ck)

    def snapshot(self) -> str:
        return repr({t: sorted(map(repr, rows.items())) for t, rows in self.tables.items()})

    def _matches(self, row: dict, params: dict) -> bool:
        for col, cond in params.items():
            if col in ("on_conflict", "select"):
                continue
            op, _, val = cond.partition(".")
            have = row.get(col)
            if op == "eq" and str(have) != val:
                return False
            if op == "gte" and not have >= int(val):
                return False
        return True

    def handle(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/auth/v1/token":
            self.sign_ins += 1
            return httpx.Response(200, json={"access_token": f"tok{self.sign_ins}", "user": {"id": UID}})
        if self.expire_next_request and req.headers["authorization"] == "Bearer tok1":
            self.expire_next_request = False
            return httpx.Response(401, json={"message": "JWT expired"})
        if m := re.fullmatch(r"/rest/v1/(\w+)", path):
            table, params = m.group(1), dict(req.url.params)
            if req.method == "POST":
                for row in json.loads(req.read()):
                    self.tables[table][self._key(table, row)] = row
                return httpx.Response(201)
            if req.method == "DELETE":
                for k in [k for k, r in self.tables[table].items() if self._matches(r, params)]:
                    del self.tables[table][k]
                    self._cascade(table, k)
                return httpx.Response(204)
            return httpx.Response(200, json=[r for r in self.tables[table].values() if self._matches(r, params)])
        if m := re.fullmatch(r"/storage/v1/object/(\w+)/(.+)", path):
            if self.fail_upload:
                return httpx.Response(413, json={"message": "The object exceeded the maximum allowed size"})
            self.uploads += 1
            self.files[(m.group(1), m.group(2))] = len(req.read())
            return httpx.Response(200, json={})
        if m := re.fullmatch(r"/storage/v1/object/(\w+)", path) and req.method == "DELETE":
            bucket = re.fullmatch(r"/storage/v1/object/(\w+)", path).group(1)
            for p in json.loads(req.read())["prefixes"]:
                self.files.pop((bucket, p), None)
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": f"no route {req.method} {path}"})


@pytest.fixture
def env(tmp_path):
    repo = Repo(tmp_path / "lib.db")
    server = FakeSupabase()
    client = SupabaseClient("https://x.supabase.co", "anon", transport=server.transport())
    client.sign_in("me@example.com", "pw")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x" * 5000)
    cover = tmp_path / "c.jpg"
    cover.write_bytes(b"jpg")
    cid = repo.add_collection("Series", cover_path=str(cover), description="d")
    tid = repo.add_track(cid, str(audio), title="Ep 1", duration_ms=9000)
    repo.replace_cues(tid, [Cue(0, 0, 1000, "こんにちは", "Hello"), Cue(1, 1000, 2000, "ね", "Hey")])
    repo.update_track(tid, status="done")
    yield repo, server, client, cid, tid
    repo.close()


def test_first_sync_uploads_everything(env):
    repo, server, client, cid, tid = env
    rep = SyncService(repo, client).sync_all()
    assert not rep.failed and rep.audio_uploaded == 1
    assert len(server.tables["collections"]) == 1 and len(server.tables["tracks"]) == 1 and len(server.tables["cues"]) == 2
    track = next(iter(server.tables["tracks"].values()))
    assert track["audio_path"].startswith(f"{UID}/") and ("audio", track["audio_path"]) in server.files
    assert server.files[("audio", track["audio_path"])] == 5000
    assert any(b == "covers" for b, _ in server.files)
    assert repo.track(tid).remote_id == track["id"]


def test_second_sync_sends_nothing(env):
    repo, server, client, *_ = env
    SyncService(repo, client).sync_all()
    uploads = server.uploads
    before = server.snapshot()
    rep = SyncService(repo, client).sync_all()
    assert rep.audio_uploaded == 0 and rep.tracks == 0
    assert server.uploads == uploads and server.snapshot() == before


def test_edited_lines_resync_without_reuploading_audio(env):
    repo, server, client, cid, tid = env
    SyncService(repo, client).sync_all()
    uploads = server.uploads
    cues = repo.cues(tid)[:1]  # one line removed, one edited
    cues[0].en = "Hi there"
    repo.replace_cues(tid, cues)
    rep = SyncService(repo, client).sync_all()
    assert rep.tracks == 1 and rep.audio_uploaded == 0 and server.uploads == uploads
    rows = list(server.tables["cues"].values())
    assert [r["en_text"] for r in rows] == ["Hi there"]  # the removed line is gone too


def test_changed_audio_is_uploaded_again(env, tmp_path):
    repo, server, client, cid, tid = env
    SyncService(repo, client).sync_all()
    (tmp_path / "a.mp3").write_bytes(b"y" * 7000)
    rep = SyncService(repo, client).sync_all()
    assert rep.audio_uploaded == 1
    assert list(server.files.values()).count(7000) == 1


def test_not_done_tracks_are_not_synced(env):
    repo, server, client, cid, tid = env
    repo.update_track(tid, status="translating")
    SyncService(repo, client).sync_all()
    assert not server.tables["tracks"] and not server.files.get(("audio", "x"))


def test_failed_upload_is_reported_and_retried(env):
    repo, server, client, cid, tid = env
    server.fail_upload = True
    rep = SyncService(repo, client).sync_all()
    assert rep.failed and "maximum allowed size" in rep.failed[0]
    assert not server.tables["tracks"]  # the track row must not point at audio that never arrived
    server.fail_upload = False
    rep = SyncService(repo, client).sync_all()
    assert not rep.failed and len(server.tables["tracks"]) == 1


def test_local_delete_removes_cloud_copy(env):
    repo, server, client, cid, tid = env
    SyncService(repo, client).sync_all()
    repo.delete_track(tid)
    rep = SyncService(repo, client).sync_all()
    assert rep.deleted == 1 and not server.tables["tracks"] and not server.tables["cues"]
    assert not any(b == "audio" for b, _ in server.files)
    assert repo.tombstones() == []


def test_deleting_collection_removes_files(env):
    repo, server, client, cid, tid = env
    SyncService(repo, client).sync_all()
    repo.delete_collection(cid)
    SyncService(repo, client).sync_all()
    assert not server.tables["collections"] and not server.tables["tracks"] and not server.files


def test_expired_token_signs_in_again(env):
    repo, server, client, *_ = env
    server.expire_next_request = True
    rep = SyncService(repo, client).sync_all()
    assert not rep.failed and server.sign_ins == 2


def test_bad_credentials():
    def deny(req):
        return httpx.Response(400, json={"error_description": "Invalid login credentials"})

    c = SupabaseClient("https://x.supabase.co", "anon", transport=httpx.MockTransport(deny))
    with pytest.raises(SyncError, match="Invalid login credentials"):
        c.sign_in("a@b.c", "wrong")


def test_old_database_is_migrated(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE collection(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, cover_path TEXT, description TEXT NOT NULL DEFAULT '', glossary_json TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL);"
        "INSERT INTO collection(name, created_at) VALUES ('Old', 1);"
    )
    con.commit()
    con.close()
    repo = Repo(db)
    c = repo.collections()[0]
    assert c.name == "Old" and c.remote_id is None and c.sync_state == {}
    repo.close()


@pytest.mark.parametrize("pasted", [
    "https://abcd1234.supabase.co",
    "https://abcd1234.supabase.co/",
    "https://abcd1234.supabase.co/rest/v1/",
    "  https://abcd1234.supabase.co/auth/v1/token?x=1 ",
    "abcd1234.supabase.co",
])
def test_url_is_reduced_to_the_project_address(pasted):
    from sasayaki.sync.client import normalize_url

    assert normalize_url(pasted) == "https://abcd1234.supabase.co"


def test_project_reference_alone_is_accepted():
    from sasayaki.sync.client import normalize_url

    assert normalize_url("abcdefghijklmnopqrst") == "https://abcdefghijklmnopqrst.supabase.co"


def test_dashboard_link_gets_a_helpful_error():
    from sasayaki.sync.client import normalize_url

    with pytest.raises(SyncError, match=r"dashboard.*https://qwerty123\.supabase\.co"):
        normalize_url("https://supabase.com/dashboard/project/qwerty123/settings/api")


def test_garbage_url_is_rejected():
    from sasayaki.sync.client import normalize_url

    with pytest.raises(SyncError, match="not a valid project URL"):
        normalize_url("hello")


def test_ready_track_with_untranslated_line_is_uploaded(env):
    repo, server, client, cid, tid = env
    cues = repo.cues(tid)
    cues[1].en, cues[1].flags = "", ["untranslated"]
    repo.replace_cues(tid, cues)
    repo.update_track(tid, status="done", error="1 lines could not be translated (see log).")  # shown as "Ready · 1 lines…"
    rep = SyncService(repo, client).sync_all()
    assert not rep.failed and len(server.tables["tracks"]) == 1
    assert sorted(r["en_text"] for r in server.tables["cues"].values()) == ["", "Hello"]


# ---- audio compression -------------------------------------------------------------------------------------------------
def _make_wav(path, seconds=3):
    import math
    import struct
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"".join(
            struct.pack("<hh", int(8000 * math.sin(i / 20)), int(8000 * math.sin(i / 23))) for i in range(44100 * seconds)
        ))


@pytest.fixture
def wav_env(env, tmp_path):
    repo, server, client, cid, tid = env
    wav = tmp_path / "big.wav"
    _make_wav(wav)
    repo.update_track(tid, audio_path=str(wav))
    return repo, server, client, cid, tid, wav


def test_oversized_audio_is_compressed_in_auto_mode(wav_env, monkeypatch):
    import sasayaki.sync.service as svc

    repo, server, client, cid, tid, wav = wav_env
    monkeypatch.setattr(svc, "AUTO_COMPRESS_OVER", 100_000)  # the 3 s wav is ~530 KB
    rep = SyncService(repo, client).sync_all()
    assert not rep.failed and rep.audio_uploaded == 1
    (bucket, path), size = next((k, v) for k, v in server.files.items() if k[0] == "audio")
    assert path.endswith(".opus") and 0 < size < wav.stat().st_size / 3
    assert next(iter(server.tables["tracks"].values()))["audio_path"] == path
    assert SyncService(repo, client).sync_all().audio_uploaded == 0  # and it is not redone next time


def test_small_audio_stays_original_in_auto_mode(env):
    repo, server, client, *_ = env
    SyncService(repo, client).sync_all()
    assert all(p.endswith(".mp3") for b, p in server.files if b == "audio")


def test_always_compress_mode_and_old_file_is_removed(wav_env):
    repo, server, client, cid, tid, wav = wav_env
    SyncService(repo, client, audio_mode="original").sync_all()
    assert any(p.endswith(".wav") for b, p in server.files if b == "audio")
    rep = SyncService(repo, client, audio_mode="compressed").sync_all()
    assert rep.audio_uploaded == 1
    audio_files = [p for b, p in server.files if b == "audio"]
    assert len(audio_files) == 1 and audio_files[0].endswith(".opus")  # the old .wav was deleted from the cloud


def test_transcode_keeps_duration_and_shrinks(tmp_path):
    import av

    from sasayaki.sync.transcode import to_opus

    wav = tmp_path / "a.wav"
    _make_wav(wav, seconds=4)
    out = to_opus(wav, tmp_path / "a.opus")
    with av.open(str(out)) as c:
        assert c.streams.audio[0].codec_context.name == "opus"
        assert abs(c.duration / 1e6 - 4) < 0.2
    assert out.stat().st_size < wav.stat().st_size / 4


def test_original_text_is_uploaded_with_each_line(env):
    repo, server, client, *_ = env
    SyncService(repo, client).sync_all()
    rows = sorted(server.tables["cues"].values(), key=lambda r: r["idx"])
    assert [r["src_text"] for r in rows] == ["こんにちは", "ね"]
