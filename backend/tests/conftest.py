"""Shared test configuration.

The AI visual planner makes a live LLM call while a deck is assembled. The unit
tests are hermetic, so it is disabled globally here; tests that exercise the
planner enable it and monkeypatch the dispatcher themselves.
"""

from app.core.config import settings

settings.enable_ai_visual_planner = False
settings.enable_legacy_unsplash = False
