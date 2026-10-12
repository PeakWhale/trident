"""Settings, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

PROVIDERS = ("ollama", "openai")

DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434",
    "openai": "https://api.openai.com/v1",
}


def _flag(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _number(env: Mapping[str, str], key: str, default: float) -> float:
    value = env.get(key)
    if value is None or value.strip() == "":
        return default
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f"{key} must be a number, got {value!r}") from None
    if number <= 0:
        raise ValueError(f"{key} must be greater than 0, got {value!r}")
    return number


@dataclass(frozen=True)
class Settings:
    provider: str = "ollama"
    base_url: str = DEFAULT_BASE_URLS["ollama"]
    model: str = "llama3.1:8b"
    review_model: str | None = None
    api_key: str | None = None
    json_mode: bool = True
    timeout_s: float = 60.0
    max_input_chars: int = 8000
    audit_log: str | None = None
    packs_dir: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        provider = (env.get("TRIDENT_LLM_PROVIDER") or "ollama").strip().lower()
        if provider not in PROVIDERS:
            raise ValueError(f"TRIDENT_LLM_PROVIDER must be one of {', '.join(PROVIDERS)}, got {provider!r}")
        return cls(
            provider=provider,
            base_url=(env.get("TRIDENT_LLM_BASE_URL") or DEFAULT_BASE_URLS[provider]).rstrip("/"),
            model=env.get("TRIDENT_LLM_MODEL") or "llama3.1:8b",
            review_model=env.get("TRIDENT_REVIEW_MODEL") or None,
            api_key=env.get("TRIDENT_LLM_API_KEY") or env.get("OPENAI_API_KEY") or None,
            json_mode=_flag(env.get("TRIDENT_JSON_MODE"), True),
            timeout_s=_number(env, "TRIDENT_LLM_TIMEOUT", 60.0),
            max_input_chars=int(_number(env, "TRIDENT_MAX_INPUT_CHARS", 8000)),
            audit_log=env.get("TRIDENT_AUDIT_LOG") or None,
            packs_dir=env.get("TRIDENT_PACKS_DIR") or None,
        )


def load_dotenv_if_present() -> None:
    """Load a .env file from the current folder (or the nearest parent folder
    that has one). Variables that are already set win."""
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # pragma: no cover - optional
        return
    # usecwd=True: without it, python-dotenv searches from this file's folder
    # (site-packages when installed), not from where the user runs trident.
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)
