"""Batched AI visual planner.

A single LLM call per deck decides how each content slide should be illustrated:
a precise search query for a photo, a concept diagram, or -- when the slide
describes a process -- the ordered steps of a flow diagram that Pillow then
draws. Batching keeps a deck to one extra free-tier request, and the whole
module degrades to an empty plan (the keyword heuristic) on any failure.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from typing import Any, Optional

from ..core.config import settings
from .llm import generate_content

logger = logging.getLogger(__name__)

_VALID_KINDS = {"photo", "diagram", "flow", "none"}
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict[int, dict]]] = {}

_SYSTEM = (
    "You are a presentation art director. For each slide you decide the single "
    "best visual, if any, and give the designer a precise brief."
)


def _strip_code_fences(raw: str) -> str:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    return cleaned.strip()


def _slide_digest(slides: list[dict[str, Any]]) -> str:
    raw = "\n".join(
        f"{s.get('title', '')}|" + "; ".join(str(b) for b in (s.get("bullets") or [])[:4])
        for s in slides
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_prompt(slides: list[dict[str, Any]], audience_level: str) -> str:
    lines = [
        _SYSTEM,
        "",
        f"Audience level: {audience_level}.",
        "Decide the best visual for each slide below.",
        "",
        "Rules:",
        "- Use \"flow\" only when the slide describes a process, sequence, cycle or pipeline. Give 3-6 ordered steps.",
        "- Use \"diagram\" when the slide breaks down or compares a concept and a labelled diagram helps.",
        "- Use \"photo\" when a real-world image illustrates the topic best. Give a concrete 3-6 word search query.",
        "- Use \"none\" when the slide is better as text only.",
        "- \"query\" must be concrete nouns (things that can be photographed), never abstract verbs.",
        "",
        "Return ONLY JSON of this shape:",
        '{"slides":[{"index":0,"kind":"photo","query":"...","caption":"..."},'
        '{"index":1,"kind":"flow","query":"...","caption":"...","title":"...",'
        '"steps":["...","..."]},{"index":2,"kind":"diagram","query":"...","caption":"...",'
        '"points":["...","..."]}]}',
        "",
        "Slides:",
    ]
    for index, slide in enumerate(slides):
        bullets = [str(b) for b in (slide.get("bullets") or []) if str(b).strip()][:4]
        lines.append(f"[{index}] {slide.get('title', '')}")
        lines.extend(f"    - {b}" for b in bullets)
    return "\n".join(lines)


def _clean_query(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:80]


def _clean_steps(value: Any, limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    steps = [re.sub(r"\s+", " ", str(step)).strip() for step in value]
    return [step[:90] for step in steps if step][:limit]


def _clean_points(value: Any, limit: int = 4) -> list[str]:
    return _clean_steps(value, limit)


def _parse_visual_plan(raw: str, count: int) -> dict[int, dict]:
    payload: Any
    try:
        payload = json.loads(_strip_code_fences(raw))
    except (json.JSONDecodeError, TypeError):
        return {}
    entries = payload.get("slides") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return {}

    plan: dict[int, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("index"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= count:
            continue
        kind = str(entry.get("kind", "none")).strip().lower()
        if kind not in _VALID_KINDS or kind == "none":
            continue
        query = _clean_query(entry.get("query"))
        caption = _clean_query(entry.get("caption"))
        spec: dict[str, Any] = {"kind": kind, "query": query, "caption": caption}
        if kind == "flow":
            steps = _clean_steps(entry.get("steps"))
            if len(steps) < 2:
                continue
            spec["steps"] = steps
            spec["flow_title"] = _clean_query(entry.get("title")) or None
        elif kind == "diagram":
            points = _clean_points(entry.get("points"))
            if points:
                spec["points"] = points
        plan[index] = spec
    return plan


def _cache_ttl() -> int:
    return max(int(settings.gemini_slides_cache_ttl), 0)


def plan_visuals(
    slides: list[dict[str, Any]],
    audience_level: str = "Intermediate",
) -> dict[int, dict]:
    """Return ``{content_index: visual_spec}``; empty when disabled or on error."""
    if not settings.enable_ai_visual_planner or not slides:
        return {}

    digest = _slide_digest(slides)
    ttl = _cache_ttl()
    now = time.time()
    with _CACHE_LOCK:
        if ttl:
            _CACHE.setdefault(digest, (now, {}))
        hit = _CACHE.get(digest)
        if hit and ttl and now - hit[0] <= ttl and hit[1]:
            return dict(hit[1])

    try:
        raw = generate_content(
            _build_prompt(slides, audience_level),
            temperature=0.4,
            response_mime_type="application/json",
            timeout=90,
            task="visual_plan",
            model_override=settings.ai_visual_planner_model or None,
        )
        plan = _parse_visual_plan(raw, len(slides))
    except Exception as exc:  # noqa: BLE001 - visuals are best-effort
        logger.info("AI visual planner unavailable, using keyword heuristic: %s", exc)
        plan = {}

    with _CACHE_LOCK:
        _CACHE[digest] = (time.time(), plan)
    return dict(plan)


def invalidate_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
