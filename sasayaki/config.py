"""App paths, persisted settings and secret lookup."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "Sasayaki"
KEYRING_SERVICE = "Sasayaki"
KEYRING_USER = "anthropic_api_key"
KEYRING_SUPABASE_USER = "supabase_password"


def data_dir() -> Path:
    override = os.environ.get("SASAYAKI_HOME")
    p = Path(override) if override else Path(user_data_dir(APP_NAME, appauthor=False))
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir(track_key: str | int) -> Path:
    p = data_dir() / "cache" / str(track_key)
    p.mkdir(parents=True, exist_ok=True)
    return p


def covers_dir() -> Path:
    p = data_dir() / "covers"
    p.mkdir(parents=True, exist_ok=True)
    return p


# Effort per quality mode (Claude output_config.effort). "high" also enables the review pass.
QUALITY_MODES = {
    "fast": {"scene_effort": "medium", "translate_effort": "low", "review": False},
    "balanced": {"scene_effort": "high", "translate_effort": "medium", "review": False},
    "high": {"scene_effort": "high", "translate_effort": "high", "review": True},
}


@dataclass
class Settings:
    # ASR
    whisper_model: str = "large-v3"
    whisper_device: str = "auto"  # auto | cuda | cpu
    whisper_compute_type: str = "int8_float16"  # int8 on CPU is chosen automatically
    # translation
    translator: str = "claude"  # claude | ollama
    claude_model: str = "claude-sonnet-5-5"
    claude_review_model: str = ""  # empty = same as claude_model
    # Only needed when the API key is not scoped to a workspace (API otherwise answers 400).
    anthropic_workspace_id: str = ""
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    use_local_fallback: bool = True
    quality: str = "balanced"
    # playback
    subtitle_offset_ms: int = 0
    show_source: bool = True
    font_size: int = 28
    # cloud sync (Supabase). The anon key is public by design; access is limited by row-level security.
    sync_enabled: bool = False
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_email: str = ""
    sync_audio: str = "auto"  # auto = compress files over the free-plan size limit | compressed | original
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        path = data_dir() / "settings.json"
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
                return cls(**known)
            except (OSError, ValueError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        (data_dir() / "settings.json").write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )


def get_api_key() -> str | None:
    """Env var first, then Windows Credential Manager. Never stored in settings.json."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        return None


def set_api_key(key: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)


def get_supabase_password() -> str | None:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEYRING_SUPABASE_USER)
    except Exception:
        return None


def set_supabase_password(password: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_SUPABASE_USER, password)
