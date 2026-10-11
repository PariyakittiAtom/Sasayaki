"""Claude backend (Anthropic SDK, structured JSON output, prompt-cached system prompt)."""

from __future__ import annotations

import json

import anthropic

from .base import BackendError, Refusal, Truncated, Usage


class ClaudeBackend:
    name = "claude"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-5-5",
        client: anthropic.Anthropic | None = None,
        workspace_id: str = "",
    ):
        self.model = model
        headers = {"anthropic-workspace-id": workspace_id.strip()} if workspace_id.strip() else None
        self.client = client or anthropic.Anthropic(api_key=api_key, default_headers=headers)
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
        try:
            resp = self.client.messages.create(
                model=model or self.model,
                max_tokens=max_tokens,
                # The system prompt carries the (stable) rules + scene card + glossary, so it is
                # cached across all chunks of a track.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.AuthenticationError as e:
            raise BackendError("Anthropic API key was rejected. Check it in Settings.") from e
        except anthropic.RateLimitError as e:
            raise BackendError("Anthropic rate limit hit; try again shortly.") from e
        except anthropic.APIConnectionError as e:
            raise BackendError(f"Could not reach the Anthropic API: {e}") from e
        except anthropic.APIStatusError as e:
            raise BackendError(f"Anthropic API error {e.status_code}: {e.message}") from e

        u = resp.usage
        self.usage.add(
            Usage(
                input_tokens=u.input_tokens or 0,
                output_tokens=u.output_tokens or 0,
                cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
                calls=1,
            )
        )

        if resp.stop_reason == "refusal":
            raise Refusal(getattr(getattr(resp, "stop_details", None), "explanation", None) or "refused")
        if resp.stop_reason == "max_tokens":
            raise Truncated("response hit max_tokens")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise BackendError(f"model returned invalid JSON: {e}") from e
