"""Small LLM clients: Ollama (default) and any OpenAI-compatible endpoint.

The engine only needs one method: ``complete(system, user, json_schema)``
which returns the raw text of the model's answer. Anything with that
method can be used, which makes it easy to pass a fake LLM in tests.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import httpx

from .config import Settings


class LLMError(RuntimeError):
    """The model endpoint answered, but not in a usable way."""


@runtime_checkable
class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str, json_schema: dict[str, Any] | None = None) -> str:
        """Return the raw text answer of the model."""
        ...


class OllamaClient:
    """Talks to Ollama's /api/chat endpoint."""

    def __init__(
        self,
        model: str = "llama3.1:8b",
        base_url: str = "http://localhost:11434",
        timeout_s: float = 60.0,
        json_mode: bool = True,
        transport: httpx.BaseTransport | None = None,
    ):
        self.model = model
        self.name = f"ollama:{model}"
        self.json_mode = json_mode
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s, transport=transport)

    def complete(self, system: str, user: str, json_schema: dict[str, Any] | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0},
        }
        if self.json_mode:
            # Ollama can force the answer to match a JSON schema.
            payload["format"] = json_schema or "json"
        response = self._http.post("/api/chat", json=payload)
        response.raise_for_status()
        content = (response.json().get("message") or {}).get("content")
        if not isinstance(content, str):
            raise LLMError("Ollama answer has no message content")
        return content


class OpenAICompatibleClient:
    """Talks to any OpenAI-compatible /chat/completions endpoint
    (OpenAI, Azure OpenAI proxies, vLLM, LM Studio, llama.cpp server, Groq, ...)."""

    def __init__(
        self,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        api_key: str | None = None,
        timeout_s: float = 60.0,
        json_mode: bool = True,
        transport: httpx.BaseTransport | None = None,
    ):
        self.model = model
        self.name = f"openai:{model}"
        self.json_mode = json_mode
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s, headers=headers, transport=transport)

    def complete(self, system: str, user: str, json_schema: dict[str, Any] | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = self._http.post("/chat/completions", json=payload)
        response.raise_for_status()
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("OpenAI-compatible answer has no choices[0].message.content") from exc
        if not isinstance(content, str):
            raise LLMError("OpenAI-compatible answer content is not text")
        return content


def client_from_settings(settings: Settings, model: str | None = None) -> LLMClient:
    model = model or settings.model
    if settings.provider == "openai":
        return OpenAICompatibleClient(
            model=model,
            base_url=settings.base_url,
            api_key=settings.api_key,
            timeout_s=settings.timeout_s,
            json_mode=settings.json_mode,
        )
    return OllamaClient(
        model=model,
        base_url=settings.base_url,
        timeout_s=settings.timeout_s,
        json_mode=settings.json_mode,
    )
