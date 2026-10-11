import re

import pytest

from sasayaki.models import Cue
from sasayaki.translate.base import BackendError, Refusal, Truncated, Usage


def make_cues(n: int, gap_every: int = 0) -> list[Cue]:
    cues, t = [], 0
    for i in range(n):
        cues.append(Cue(i, t, t + 1500, f"src{i}"))
        t += 1600 + (3000 if gap_every and (i + 1) % gap_every == 0 else 0)
    return cues


class FakeBackend:
    """Scripted backend. `behaviour(user_text, call_no)` may return a dict, or raise a BackendError."""

    def __init__(self, name="fake", behaviour=None):
        self.name = name
        self.usage = Usage()
        self.calls: list[dict] = []
        self.behaviour = behaviour or self.echo

    @staticmethod
    def ids_in(user: str) -> list[int]:
        section = re.split(r"Translate these lines \(id\|text\):\n", user)[-1].split("\n\n")[0]
        return [int(m.group(1)) for m in re.finditer(r"^(\d+)\|", section, re.M)]

    def echo(self, user, n, system=""):
        return {
            "lines": [
                {"id": i, "en": f"EN{i}", "confidence": "high", "asr_suspect": False, "asr_fix": ""}
                for i in self.ids_in(user)
            ]
        }

    def complete_json(self, system, user, schema, *, effort="medium", max_tokens=16000, model=None):
        self.calls.append({"system": system, "user": user, "schema": schema, "effort": effort, "model": model})
        self.usage.calls += 1
        if "changes" in schema.get("properties", {}):
            return {"changes": []}
        if "setting" in schema.get("properties", {}):
            return {"setting": "test", "summary": "s"}
        return self.behaviour(user, len(self.calls))


__all__ = ["FakeBackend", "make_cues", "BackendError", "Refusal", "Truncated"]


@pytest.fixture
def fake():
    return FakeBackend
