"""
Shared Gemini API client with global rate-limiting and resilient retries.

All Gemini callers go through this module so that calls are throttled to
respect free-tier per-minute quotas and transient 429/5xx/timeouts are retried
with a backoff that honors the server-provided retry delay.
"""
import json
import random
import re
import threading
import time
from typing import Any

import requests

from ..core.config import settings

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# gemini-3.x flash models on the free tier allow ~20 requests/day (per model).
MIN_REQUEST_INTERVAL = 3.5  # minimum seconds between API calls (~17/min)
MAX_BACKOFF = 30.0
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_TIMEOUT = 120

_lock = threading.Lock()
_last_request_ms = 0.0
_daily_quota_exhausted = False
_thinking_config_supported = True


def _throttle() -> None:
    """Space out consecutive calls so we do not overrun the per-minute quota."""
    global _last_request_ms
    with _lock:
        now = time.monotonic()
        delay = MIN_REQUEST_INTERVAL - (now - _last_request_ms)
        if delay > 0:
            time.sleep(delay)
        _last_request_ms = time.monotonic()


def _parse_duration(duration: str) -> float:
    """Parse an ISO-8601-ish duration such as '1.5s', '500ms', '1m30s'."""
    if not duration:
        return 0.0
    total = 0.0
    for value, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|s|m)", duration):
        number = float(value)
        if unit == "ms":
            total += number / 1000.0
        elif unit == "s":
            total += number
        elif unit == "m":
            total += number * 60.0
    return total


def _error_details(response_body: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the `details` array from a Gemini error response body."""
    if not isinstance(response_body, dict):
        return []
    error = response_body.get("error")
    if not isinstance(error, dict):
        return []
    details = error.get("details", [])
    return details if isinstance(details, list) else []


def _wait_seconds(response_body: dict[str, Any] | None, retry_after: str | None, attempt: int) -> float:
    wait = 0.0
    for detail in _error_details(response_body):
        delay = detail.get("retryDelay")
        if delay:
            wait = max(wait, _parse_duration(str(delay)))
    if wait <= 0.0:
        wait = _parse_duration(str(retry_after or ""))
    wait = min(max(wait, 0.0), MAX_BACKOFF)
    if wait <= 0.0:
        wait = min(MAX_BACKOFF, 2.0 ** attempt)
    return wait + random.uniform(0, 0.5 * wait)


def _is_daily_quota(response_body: dict[str, Any] | None) -> bool:
    """True if the 429 is a daily free-tier quota exhaustion (retrying is futile)."""
    try:
        for detail in _error_details(response_body):
            for violation in detail.get("violations", []):
                if "PerDay" in violation.get("quotaId", "") or "Daily" in violation.get("quotaId", ""):
                    return True
    except (AttributeError, TypeError):
        return False
    return False


def _generation_config(temperature: float, response_mime_type: str) -> dict[str, Any]:
    """Build ``generationConfig``, including the thinking level when supported."""
    config: dict[str, Any] = {
        "temperature": temperature,
        "response_mime_type": response_mime_type,
    }
    level = (settings.gemini_thinking_level or "").strip()
    if level and _thinking_config_supported:
        config["thinkingConfig"] = {"thinkingLevel": level}
    return config


def _thinking_rejected(response_body: dict[str, Any] | None, had_thinking: bool) -> bool:
    """True when a 400 says the thinking knob itself is the problem."""
    if not had_thinking or not isinstance(response_body, dict):
        return False
    message = str(response_body.get("error", {}).get("message", "")).lower()
    return "thinking" in message or "invalid argument" in message


def generate_content(
    prompt: str,
    *,
    temperature: float = 0.3,
    response_mime_type: str = "text/plain",
    timeout: int = DEFAULT_TIMEOUT,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    model: str | None = None,
    api_key: str | None = None,
) -> str:
    """Call Gemini generateContent and return the first text part.

    ``model``/``api_key`` let a stored ``LLMProvider`` row target a different
    Gemini model or key than the built-in one in settings.
    """
    global _daily_quota_exhausted, _thinking_config_supported

    model = (model or settings.gemini_model).strip()
    api_key = api_key or settings.gemini_api_key

    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY")

    if _daily_quota_exhausted:
        raise RuntimeError(
            f"Gemini daily free-tier quota for model '{model}' is exhausted. "
            "Switch to a paid API key or try again after the quota resets."
        )

    url = (
        f"{_ENDPOINT.format(model=model)}?key={api_key}"
    )
    payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": _generation_config(temperature, response_mime_type),
    }
    had_thinking = "thinkingConfig" in payload["generationConfig"]

    last_error: Exception | None = None

    for attempt in range(max_attempts):
        _throttle()
        try:
            response = requests.post(url, json=payload, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            last_error = exc
            time.sleep(_wait_seconds(None, None, attempt))
            continue

        try:
            body = response.json()
        except ValueError:
            body = None

        if response.status_code == 400 and _thinking_rejected(body, had_thinking):
            # The deployed model does not accept the thinking knob: drop it for
            # the rest of the process and replay the request instead of failing.
            _thinking_config_supported = False
            payload["generationConfig"] = _generation_config(temperature, response_mime_type)
            had_thinking = "thinkingConfig" in payload["generationConfig"]
            last_error = requests.exceptions.HTTPError(
                f"400 Bad Request: {str((body or {}).get('error', {}).get('message', ''))[:200]}"
            )
            continue

        if response.status_code == 429:
            message = (body or {}).get("error", {}).get("message", response.text)
            if _is_daily_quota(body):
                _daily_quota_exhausted = True
                raise RuntimeError(
                    f"Gemini daily free-tier quota for model '{model}' is exhausted "
                    f"({message[:200]}). Switch to a paid API key or try again after the quota resets."
                )
            last_error = requests.exceptions.HTTPError(f"429 Too Many Requests: {message[:200]}")
            time.sleep(_wait_seconds(body, response.headers.get("Retry-After"), attempt))
            continue

        if 500 <= response.status_code < 600:
            last_error = requests.exceptions.HTTPError(
                f"{response.status_code} Server Error: {response.text[:200]}"
            )
            time.sleep(_wait_seconds(body, response.headers.get("Retry-After"), attempt))
            continue

        if response.status_code != 200:
            response.raise_for_status()

        candidates = (body or {}).get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts or "text" not in parts[0]:
            raise RuntimeError("Gemini returned no text payload")
        return parts[0]["text"]

    raise RuntimeError(
        f"Failed to call Gemini API after {max_attempts} attempts: {last_error}"
    )