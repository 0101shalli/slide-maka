"""Task dispatcher that routes LLM work to any configured provider.

Callers never talk to a specific vendor. They name a *task* (``slides``,
``visual_plan``, ``outline``, ...) and the dispatcher picks the highest-priority
enabled provider that serves it, falling back through the rest and finally to
the built-in Gemini client. New providers are added as ``LLMProvider`` rows via
the admin API; no code change is needed.
"""

from __future__ import annotations

import logging
import threading
import time

from ...core.config import settings
from .base import LLMProviderError, ProviderConfig
from .providers import build_provider

logger = logging.getLogger(__name__)

_DB_CACHE_TTL = 5.0
_db_lock = threading.Lock()
_db_cache: tuple[float, list[ProviderConfig]] = (0.0, [])


def _builtin_config() -> ProviderConfig:
    return ProviderConfig(
        name="Gemini (built-in)",
        provider_type="gemini",
        model=settings.gemini_model,
        api_key=settings.gemini_api_key,
        priority=1000,
        is_default=True,
        extra={"builtin": True},
    )


def _row_to_config(row) -> ProviderConfig:
    return ProviderConfig(
        name=row.name,
        provider_type=(row.provider_type or "openai").lower(),
        model=row.model,
        api_key=row.api_key or "",
        base_url=row.base_url or "",
        priority=int(row.priority if row.priority is not None else 100),
        is_default=bool(row.is_default),
        extra=dict(row.extra_json or {}),
    )


def _load_db_configs() -> list[ProviderConfig]:
    """Read enabled providers from the DB, cached briefly.

    The table may not exist yet during startup or in hermetic tests, so any
    failure degrades to "no DB providers" instead of breaking the caller.
    """
    global _db_cache
    now = time.monotonic()
    with _db_lock:
        cached_at, cached = _db_cache
        if cached and now - cached_at < _DB_CACHE_TTL:
            return cached
    try:
        from ...db.session import SessionLocal
        from ...models.models import LLMProvider

        with SessionLocal() as db:
            rows = db.query(LLMProvider).filter(LLMProvider.enabled.is_(True)).all()
            configs = [_row_to_config(row) for row in rows]
    except Exception as exc:
        logger.debug("LLM provider table unavailable: %s", exc)
        configs = []
    with _db_lock:
        _db_cache = (now, configs)
    return configs


def invalidate_cache() -> None:
    """Drop the cached provider list (call after admin CRUD writes)."""
    global _db_cache
    with _db_lock:
        _db_cache = (0.0, [])


def _ordered(configs: list[ProviderConfig]) -> list[ProviderConfig]:
    active = [c for c in configs if not c.is_default]
    active.sort(key=lambda c: (c.priority, c.name))
    defaults = [c for c in configs if c.is_default]
    return active + defaults


def resolve_providers(task: str = "default") -> list:
    """The provider adapters to try for ``task``, in priority order."""
    configs = [c for c in _load_db_configs() if c.serves(task)]
    has_gemini = any(c.provider_type == "gemini" for c in configs)
    ordered = _ordered(configs)
    if not has_gemini:
        # The built-in Gemini client is always the last-resort fallback.
        ordered.append(_builtin_config())
    return [build_provider(config) for config in ordered]


def active_signature(task: str = "default") -> str:
    """A stable fingerprint of the provider chain, for cache keys."""
    providers = resolve_providers(task)
    return "|".join(f"{p.config.provider_type}:{p.config.name}:{p.config.model_for(task)}" for p in providers)


def generate_content(
    prompt: str,
    *,
    temperature: float = 0.3,
    response_mime_type: str = "text/plain",
    timeout: int = 120,
    max_attempts: int = 4,
    task: str = "default",
    model_override: str | None = None,
) -> str:
    """Run ``prompt`` through the provider chain for ``task``.

    The signature mirrors ``gemini_client.generate_content`` so callers can swap
    the import without changing anything else.
    """
    json_mode = response_mime_type == "application/json"
    errors: list[str] = []
    for provider in resolve_providers(task):
        model = model_override or provider.config.model_for(task)
        try:
            return provider.complete(
                prompt,
                temperature=temperature,
                json_mode=json_mode,
                timeout=timeout,
                model=model,
            )
        except Exception as exc:  # noqa: BLE001 - try the next provider
            logger.warning("LLM provider %s failed for task %s: %s", provider.name, task, exc)
            errors.append(f"{provider.name}: {exc}")
    raise LLMProviderError("All LLM providers failed: " + "; ".join(errors))
