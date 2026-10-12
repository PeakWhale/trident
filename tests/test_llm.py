"""LLM clients and settings. HTTP is faked with httpx.MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from trident.config import Settings
# Kept before the autouse fixture in conftest.py swaps it for a no-op.
from trident.config import load_dotenv_if_present as REAL_LOAD_DOTENV
from trident.engine import TriageEngine
from trident.llm import LLMError, OllamaClient, OpenAICompatibleClient, client_from_settings

SCHEMA = {"type": "object"}


def transport(handler):
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.MockTransport(wrapped), seen


def test_ollama_request_and_answer():
    mock, seen = transport(lambda r: httpx.Response(200, json={"message": {"content": '{"ok": true}'}}))
    client = OllamaClient(model="llama3.1:8b", base_url="http://ollama:11434", transport=mock)
    assert client.complete("sys", "user", SCHEMA) == '{"ok": true}'
    assert client.name == "ollama:llama3.1:8b"
    request = seen[0]
    assert str(request.url) == "http://ollama:11434/api/chat"
    body = json.loads(request.content)
    assert body["model"] == "llama3.1:8b"
    assert body["stream"] is False
    assert body["format"] == SCHEMA
    assert body["options"]["temperature"] == 0
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}]


def test_ollama_errors():
    mock, _ = transport(lambda r: httpx.Response(500, json={"error": "model not found"}))
    with pytest.raises(httpx.HTTPStatusError):
        OllamaClient(transport=mock).complete("s", "u")
    mock, _ = transport(lambda r: httpx.Response(200, json={"done": True}))
    with pytest.raises(LLMError):
        OllamaClient(transport=mock).complete("s", "u")


def test_openai_compatible_request_and_answer():
    answer = {"choices": [{"message": {"role": "assistant", "content": '{"ok": 1}'}}]}
    mock, seen = transport(lambda r: httpx.Response(200, json=answer))
    client = OpenAICompatibleClient(model="gpt-x", base_url="http://llm.local/v1", api_key="sk-test", transport=mock)
    assert client.complete("sys", "user", SCHEMA) == '{"ok": 1}'
    request = seen[0]
    assert str(request.url) == "http://llm.local/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert body["model"] == "gpt-x"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0


def test_openai_compatible_without_json_mode_or_key():
    answer = {"choices": [{"message": {"content": "{}"}}]}
    mock, seen = transport(lambda r: httpx.Response(200, json=answer))
    OpenAICompatibleClient(model="m", base_url="http://x/v1", json_mode=False, transport=mock).complete("s", "u")
    assert "response_format" not in json.loads(seen[0].content)
    assert "Authorization" not in seen[0].headers


def test_openai_compatible_bad_answer():
    mock, _ = transport(lambda r: httpx.Response(200, json={"choices": []}))
    with pytest.raises(LLMError):
        OpenAICompatibleClient(model="m", transport=mock).complete("s", "u")


def test_settings_defaults():
    settings = Settings.from_env({})
    assert settings.provider == "ollama"
    assert settings.base_url == "http://localhost:11434"
    assert settings.model == "llama3.1:8b"
    assert settings.review_model is None
    assert settings.timeout_s == 60
    assert settings.json_mode is True
    assert isinstance(client_from_settings(settings), OllamaClient)


def test_settings_openai_compatible():
    settings = Settings.from_env(
        {
            "TRIDENT_LLM_PROVIDER": "OpenAI",
            "TRIDENT_LLM_MODEL": "gpt-4o-mini",
            "OPENAI_API_KEY": "sk-from-openai-var",
            "TRIDENT_LLM_TIMEOUT": "12.5",
            "TRIDENT_JSON_MODE": "off",
        }
    )
    assert settings.provider == "openai"
    assert settings.base_url == "https://api.openai.com/v1"
    assert settings.api_key == "sk-from-openai-var"
    assert settings.timeout_s == 12.5
    assert settings.json_mode is False
    client = client_from_settings(settings)
    assert isinstance(client, OpenAICompatibleClient)
    assert client.name == "openai:gpt-4o-mini"


@pytest.mark.parametrize(
    "env",
    [
        {"TRIDENT_LLM_PROVIDER": "bard"},
        {"TRIDENT_LLM_TIMEOUT": "soon"},
        {"TRIDENT_LLM_TIMEOUT": "-1"},
        {"TRIDENT_MAX_INPUT_CHARS": "0"},
        {"TRIDENT_LLM_TIMEOUT": "nan"},
        {"TRIDENT_LLM_TIMEOUT": "inf"},
        {"TRIDENT_LLM_TIMEOUT": "1e400"},
        {"TRIDENT_MAX_INPUT_CHARS": "0.5"},
        {"TRIDENT_MAX_INPUT_CHARS": "8000.5"},
        {"TRIDENT_MAX_INPUT_CHARS": "inf"},
        {"TRIDENT_MAX_INPUT_CHARS": "nan"},
        {"TRIDENT_MAX_INPUT_CHARS": "-5"},
    ],
)
def test_bad_settings_fail_loudly(env):
    with pytest.raises(ValueError, match="TRIDENT_"):
        Settings.from_env(env)


def test_max_input_chars_setting():
    assert Settings.from_env({"TRIDENT_MAX_INPUT_CHARS": " 12000 "}).max_input_chars == 12000
    assert Settings.from_env({}).max_input_chars == 8000


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), 0, -1])
def test_engine_rejects_a_bad_timeout(registry, timeout):
    with pytest.raises(ValueError):
        TriageEngine(registry, object(), timeout_s=timeout)  # type: ignore[arg-type]


def test_dotenv_is_read_from_the_current_folder(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("TRIDENT_LLM_MODEL=from-cwd-dotenv\nTRIDENT_REVIEW_MODEL=from-cwd-review\n")
    monkeypatch.chdir(tmp_path)
    # Make monkeypatch restore (remove) these after the test.
    for key in ("TRIDENT_LLM_MODEL", "TRIDENT_REVIEW_MODEL"):
        monkeypatch.setenv(key, "placeholder")
        monkeypatch.delenv(key)
    monkeypatch.setenv("TRIDENT_REVIEW_MODEL", "already-set")

    REAL_LOAD_DOTENV()
    settings = Settings.from_env()
    assert settings.model == "from-cwd-dotenv"
    assert settings.review_model == "already-set"  # the environment wins over .env


def test_separate_review_model():
    settings = Settings.from_env({"TRIDENT_LLM_MODEL": "small", "TRIDENT_REVIEW_MODEL": "big"})
    engine = TriageEngine.from_settings(settings)
    try:
        assert engine.model_names == {"classifier": "ollama:small", "reviewer": "ollama:big"}
    finally:
        engine.close()


def test_custom_packs_dir_from_settings(tmp_path):
    from test_packs import pack_with

    (tmp_path / "mine.yaml").write_text(pack_with())
    engine = TriageEngine.from_settings(Settings.from_env({"TRIDENT_PACKS_DIR": str(tmp_path)}))
    try:
        assert "test-pack" in engine.packs
    finally:
        engine.close()
