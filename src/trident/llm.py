"""Small LLM clients: Ollama (default) and any OpenAI-compatible endpoint.

The engine only needs one method: ``complete(system, user, json_schema)``
which returns the raw text of the model's answer. Anything with that
method can be used, which makes it easy to pass a fake LLM in tests.
"""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

import httpx

from .config import Settings

_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@")
ERROR_DETAIL_LIMIT = 200


class LLMError(RuntimeError):
    """The model endpoint failed or answered, but not in a usable way."""


def redact(text: str, secrets: tuple[str | None, ...] = ()) -> str:
    """Remove passwords in URLs (https://user:pass@host) and any known secret from a message."""
    text = _USERINFO.sub(r"\1***@", text)
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "***")
    return text


def _error_detail(response: httpx.Response) -> str:
    """The short error text in an error response, if there is one."""
    try:
        body = response.json()
    except Exception:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        error = error.get("message")
    if not isinstance(error, str):
        return ""
    error = " ".join(error.split())
    return error if len(error) <= ERROR_DETAIL_LIMIT else error[: ERROR_DETAIL_LIMIT - 3] + "..."


def _post(http: httpx.Client, path: str, payload: dict[str, Any], secrets: tuple[str | None, ...]) -> httpx.Response:
    """POST and raise LLMError on any HTTP problem.

    httpx error messages contain the full URL, with any user:password in it.
    These messages end up in results, the audit log and MCP answers, so the
    URL is never put into them.
    """
    try:
        response = http.post(path, json=payload)
    except httpx.TimeoutException as exc:
        raise LLMError(f"the model endpoint timed out ({type(exc).__name__})") from None
    except httpx.RequestError as exc:
        detail = redact(f"{type(exc).__name__}: {exc}", secrets)
        raise LLMError(f"could not reach the model endpoint: {detail}") from None
    if response.is_error:
        detail = redact(_error_detail(response), secrets)
        message = f"the model endpoint returned HTTP {response.status_code} {response.reason_phrase}".rstrip()
        raise LLMError(f"{message}: {detail}" if detail else message)
    return response


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
        self._secrets = (self._http.base_url.password,)

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
        response = _post(self._http, "/api/chat", payload, self._secrets)
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
        self._secrets = (self._http.base_url.password, api_key)

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
        response = _post(self._http, "/chat/completions", payload, self._secrets)
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
