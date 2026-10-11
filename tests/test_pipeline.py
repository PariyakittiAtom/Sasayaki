from conftest import BackendError, FakeBackend, Refusal, Truncated, make_cues

from sasayaki.translate.pipeline import TranslationPipeline, make_chunks


def test_chunks_cover_all_cues_in_order():
    cues = make_cues(130)
    chunks = make_chunks(cues, size=45)
    flat = [c.idx for ch in chunks for c in ch]
    assert flat == list(range(130))
    assert all(len(ch) <= 45 for ch in chunks)


def test_chunks_prefer_cut_at_long_pause():
    cues = make_cues(100, gap_every=40)  # 3s pause after cue 39, 79
    chunks = make_chunks(cues, size=45)
    assert chunks[0][-1].idx == 39


def test_happy_path_translates_everything_and_passes_context():
    cues = make_cues(100)
    b = FakeBackend()
    pipe = TranslationPipeline(b, quality="balanced")
    card = pipe.run(cues, "ja", hint="girlfriend roleplay")
    assert card["setting"] == "test"
    assert [c.en for c in cues] == [f"EN{i}" for i in range(100)]
    assert all(c.confidence == 0.92 for c in cues)
    # second chunk's prompt includes earlier translated lines and upcoming lookahead
    second = [c for c in b.calls if "Earlier lines" in c["user"]]
    assert second and "|EN" in second[0]["user"]
    # scene card is in the system prompt for translate calls
    assert any("Scene brief" in c["system"] and '"setting": "test"' in c["system"] for c in b.calls)


def test_missing_ids_are_retried_then_filled():
    cues = make_cues(10)

    def behaviour(user, n):
        ids = FakeBackend.ids_in(user)
        if n == 2:  # first translate call (call 1 = scene brief): drop two ids
            ids = [i for i in ids if i not in (3, 7)]
        return {"lines": [{"id": i, "en": f"EN{i}", "confidence": "high", "asr_suspect": False, "asr_fix": ""} for i in ids]}

    pipe = TranslationPipeline(FakeBackend(behaviour=behaviour))
    pipe.run(cues, "ja")
    assert all(c.en for c in cues)
    assert pipe.stats.retried_chunks == 1 and pipe.stats.untranslated == 0


def test_refusal_falls_back_and_flags_cues():
    cues = make_cues(10)

    def refuse(user, n):
        raise Refusal("policy")

    primary, local = FakeBackend("claude", refuse), FakeBackend("ollama")
    pipe = TranslationPipeline(primary, local)
    pipe.run(cues, "ja", card={"setting": "x"})
    assert all(c.en for c in cues)
    assert all("local_fallback" in c.flags for c in cues)
    assert pipe.stats.fallback_chunks == 1


def test_refusal_text_in_output_triggers_fallback():
    cues = make_cues(3)

    def softened(user, n):
        return {"lines": [{"id": i, "en": "I'm sorry, I can't help with that.", "confidence": "high", "asr_suspect": False, "asr_fix": ""} for i in FakeBackend.ids_in(user)]}

    pipe = TranslationPipeline(FakeBackend("claude", softened), FakeBackend("ollama"))
    pipe.run(cues, "ja", card={})
    assert [c.en for c in cues] == ["EN0", "EN1", "EN2"]


def test_no_fallback_leaves_untranslated_flagged():
    cues = make_cues(4)

    def fail(user, n):
        raise BackendError("down")

    pipe = TranslationPipeline(FakeBackend("claude", fail))
    pipe.run(cues, "ja", card={})
    assert all(c.en == "" and "untranslated" in c.flags for c in cues)
    assert pipe.stats.untranslated == 4


def test_truncation_splits_chunk_in_half():
    cues = make_cues(8)
    seen = []

    def behaviour(user, n):
        ids = FakeBackend.ids_in(user)
        seen.append(len(ids))
        if len(ids) > 4:
            raise Truncated("too long")
        return {"lines": [{"id": i, "en": f"EN{i}", "confidence": "high", "asr_suspect": False, "asr_fix": ""} for i in ids]}

    pipe = TranslationPipeline(FakeBackend(behaviour=behaviour))
    pipe.run(cues, "ja", card={})
    assert [c.en for c in cues] == [f"EN{i}" for i in range(8)]
    assert seen == [8, 4, 4]


def test_asr_suspect_and_empty_en_are_flagged_and_user_edits_survive():
    cues = make_cues(3)
    cues[2].en, cues[2].user_edited = "MINE", True

    def behaviour(user, n):
        return {"lines": [
            {"id": 0, "en": "Hi", "confidence": "low", "asr_suspect": True, "asr_fix": "fixed"},
            {"id": 1, "en": "", "confidence": "high", "asr_suspect": True, "asr_fix": ""},
            {"id": 2, "en": "OVERWRITE", "confidence": "high", "asr_suspect": False, "asr_fix": ""},
        ]}

    TranslationPipeline(FakeBackend(behaviour=behaviour)).run(cues, "ko", card={})
    assert cues[0].asr_fix == "fixed" and "asr_suspect" in cues[0].flags and cues[0].confidence == 0.3
    assert "dropped_noise" in cues[1].flags
    assert cues[2].en == "MINE"


def test_high_quality_runs_review_and_applies_changes():
    cues = make_cues(5)

    class Reviewer(FakeBackend):
        def complete_json(self, system, user, schema, **kw):
            if "changes" in schema.get("properties", {}):
                self.calls.append({"model": kw.get("model")})
                return {"changes": [{"id": 1, "en": "Better", "reason": "pronoun", "confidence": "high"}]}
            return super().complete_json(system, user, schema, **kw)

    b = Reviewer()
    pipe = TranslationPipeline(b, quality="high", review_model="claude-opus-5-5")
    pipe.run(cues, "ja", card={})
    assert cues[1].en == "Better" and "reviewed" in cues[1].flags
    assert pipe.stats.review_changes == 1
    assert {"model": "claude-opus-5-5"} in b.calls
