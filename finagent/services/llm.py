"""Thin, dependency-free LLM clients: Ollama (local, free), OpenAI, Anthropic Claude."""

from __future__ import annotations

import json
import logging
import re
from typing import Protocol

import httpx

from ..config import Settings, get_settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str: ...


class OllamaClient:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0},
        }
        if json_mode:
            payload["format"] = "json"
        data = _post(f"{self.base_url}/api/chat", payload, {}, self.timeout)
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise LLMError(f"Unexpected Ollama response: {data!r:.200}") from exc


class OpenAIClient:
    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        payload: dict = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        data = _post(f"{self.base_url}/chat/completions", payload, headers, self.timeout)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected OpenAI response: {data!r:.200}") from exc


class AnthropicClient:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        if json_mode:
            system += "\nRespond with a single valid JSON object and nothing else."
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        data = _post("https://api.anthropic.com/v1/messages", payload, headers, self.timeout)
        try:
            return "".join(b["text"] for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise LLMError(f"Unexpected Anthropic response: {data!r:.200}") from exc


def _post(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"LLM HTTP {exc.response.status_code}: {exc.response.text[:200]}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc


def get_llm(settings: Settings | None = None) -> LLMClient | None:
    """Return the configured LLM client, or None when AI features are disabled."""
    s = settings or get_settings()
    if s.llm_provider == "ollama":
        return OllamaClient(s.ollama_base_url, s.ollama_model, s.llm_timeout_seconds)
    if s.llm_provider == "openai":
        if not s.openai_api_key:
            log.warning("LLM_PROVIDER=openai but OPENAI_API_KEY is empty; AI disabled")
            return None
        return OpenAIClient(
            s.openai_api_key, s.openai_model, s.openai_base_url, s.llm_timeout_seconds
        )
    if s.llm_provider == "anthropic":
        if not s.anthropic_api_key:
            log.warning("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is empty; AI disabled")
            return None
        return AnthropicClient(s.anthropic_api_key, s.anthropic_model, s.llm_timeout_seconds)
    return None


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(text: str) -> dict | list:
    """Parse JSON from an LLM reply, tolerating code fences and surrounding prose."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(open_ch), cleaned.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"Could not parse JSON from LLM output: {text[:200]!r}")
