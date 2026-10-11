"""Local backend: Ollama's native /api/chat with a JSON-schema `format` constraint."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import BackendError, Truncated, Usage


class OllamaBackend:
    name = "ollama"

    def __init__(self, url: str = "http://localhost:11434", model: str = "qwen2.5:7b-instruct", timeout: float = 600.0):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.usage = Usage()

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict,
        *,
        effort: str = "medium",
        max_tokens: int = 16000,
        model: str | None = None,
    ) -> dict:
        body = {
            "model": model or self.model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0.2, "num_predict": min(max_tokens, 8192), "num_ctx": 16384},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        req = urllib.request.Request(
            f"{self.url}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise BackendError(f"Could not reach Ollama at {self.url}: {e}") from e

        self.usage.add(
            Usage(
                input_tokens=data.get("prompt_eval_count", 0) or 0,
                output_tokens=data.get("eval_count", 0) or 0,
                calls=1,
            )
        )
        if data.get("done_reason") == "length":
            raise Truncated("local model hit its token limit")
        try:
            return json.loads(data["message"]["content"])
        except (KeyError, json.JSONDecodeError) as e:
            raise BackendError(f"local model returned invalid JSON: {e}") from e
