"""Provider contract for the LLM task dispatcher.

Every backend task that needs a language model goes through the dispatcher,
which tries the configured providers in priority order and falls back to the
built-in Gemini client. A provider only has to implement ``complete``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

DEFAULT_TIMEOUT = 120


class LLMProviderError(RuntimeError):
    """Raised when every configured provider failed for a request."""


@dataclass
class ProviderConfig:
    """One row of provider configuration (built-in default or a DB record)."""

    name: str
    provider_type: str
    model: str
    api_key: str = ""
    base_url: str = ""
    priority: int = 100
    is_default: bool = False
    extra: dict = field(default_factory=dict)

    def serves(self, task: str) -> bool:
        """Whether this provider accepts ``task`` (empty list serves every task)."""
        tasks = self.extra.get("tasks") or []
        if not tasks:
            return True
        return task in tasks

    def model_for(self, task: str) -> str:
        """The model to use for ``task``, allowing a per-task override."""
        overrides = self.extra.get("task_models") or {}
        return overrides.get(task) or self.model

    @property
    def is_builtin(self) -> bool:
        return bool(self.extra.get("builtin"))


class BaseProvider(ABC):
    """A single LLM backend."""

    provider_type = "base"

    def __init__(self, config: ProviderConfig):
        self.config = config

    @property
    def name(self) -> str:
        return self.config.name

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.3,
        json_mode: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
        model: str | None = None,
    ) -> str:
        """Return the model's text answer for ``prompt``."""
