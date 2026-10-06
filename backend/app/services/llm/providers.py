"""Built-in provider implementations for the LLM dispatcher.

Three adapters cover essentially any model a user has an endpoint for:

* ``gemini``  -- Google Generative Language REST (delegates to gemini_client so
  it keeps the shared throttle/backoff/quota handling).
* ``openai``  -- any OpenAI-compatible ``/chat/completions`` server: OpenAI,
  OpenRouter, Groq, Together, Ollama, vLLM, LM Studio, ...
* ``anthropic`` -- the Claude ``/v1/messages`` API.
"""

from __future__ import annotations

import requests

from .base import BaseProvider, ProviderConfig

_HEADERS = {"User-Agent": "SlideMaka/1.0 (presentation generator)"}
DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_BASE = "https://api.anthropic.com"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"


def _join(base: str, path: str) -> str:
    base = (base or "").strip().rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _raise_for_status(response: requests.Response, provider: str) -> None:
    if response.status_code >= 400:
        detail = response.text[:300]
        raise RuntimeError(f"{provider} API error {response.status_code}: {detail}")


class GeminiProvider(BaseProvider):
    provider_type = "gemini"

    def complete(self, prompt, *, temperature=0.3, json_mode=False, timeout=120, model=None):
        from ..gemini_client import generate_content

        return generate_content(
            prompt,
            temperature=temperature,
            response_mime_type="application/json" if json_mode else "text/plain",
            timeout=timeout,
            model=model or self.config.model,
            api_key=self.config.api_key or None,
        )


class OpenAICompatibleProvider(BaseProvider):
    provider_type = "openai"

    def complete(self, prompt, *, temperature=0.3, json_mode=False, timeout=120, model=None):
        base = self.config.base_url or DEFAULT_OPENAI_BASE
        url = _join(base, "chat/completions")
        payload = {
            "model": model or self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {self.config.api_key}", **_HEADERS},
            timeout=timeout,
        )
        _raise_for_status(response, self.name)
        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"{self.name} returned no choices")
        message = choices[0].get("message") or {}
        return message.get("content") or ""


class AnthropicProvider(BaseProvider):
    provider_type = "anthropic"

    def complete(self, prompt, *, temperature=0.3, json_mode=False, timeout=120, model=None):
        base = self.config.base_url or DEFAULT_ANTHROPIC_BASE
        url = _join(base, "v1/messages")
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": self.config.extra.get("anthropic_version") or DEFAULT_ANTHROPIC_VERSION,
            "content-type": "application/json",
            **_HEADERS,
        }
        payload = {
            "model": model or self.config.model,
            "max_tokens": int(self.config.extra.get("max_tokens") or 4096),
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if json_mode:
            # Claude has no JSON mode; asking inside the prompt is the portable way.
            payload["messages"][0]["content"] = prompt + "\n\nRespond with a single valid JSON object and nothing else."
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        _raise_for_status(response, self.name)
        body = response.json()
        parts = body.get("content") or []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not text:
            raise RuntimeError(f"{self.name} returned no text payload")
        return text


PROVIDER_TYPES = {
    "gemini": GeminiProvider,
    "openai": OpenAICompatibleProvider,
    "anthropic": AnthropicProvider,
}

_PROVIDER_TYPES = PROVIDER_TYPES


def build_provider(config: ProviderConfig) -> BaseProvider:
    """Instantiate the adapter for ``config.provider_type`` (defaults to OpenAI)."""
    provider_cls = PROVIDER_TYPES.get((config.provider_type or "").lower(), OpenAICompatibleProvider)
    return provider_cls(config)
