import copy
import hashlib
import json
import re
import threading
import time
from typing import Any


from ..core.config import settings
from .llm import active_signature, generate_content

_CACHE_LOCK = threading.Lock()
# prompt+count fingerprint -> (timestamp, slides). The frontend calls /preview
# and then /generate with the same form, so without this the same deck material
# was generated twice, paying the latency and the free-tier quota twice.
_SLIDES_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _strip_code_fences(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    return cleaned.strip()


def _slide_regions(raw_text: str) -> list[str]:
    """Split a raw LLM answer into per-slide regions.

    The requested ``<<<START_SLIDE>>>`` markers are used when present. When the
    model ignores them, a repeated ``SLIDE_NUMBER``/``TITLE`` header is used
    instead, so the generated text still reaches the deck instead of being
    replaced by placeholders.
    """
    blocks = re.findall(r'<<<START_SLIDE>>>(.*?)<<<END_SLIDE>>>', raw_text, re.S)
    if blocks:
        return blocks

    for anchor in (r'(?im)^[ \t]*(?:#{1,4}[ \t]*)?SLIDE[ _]?NUMBER\s*[:.)-]', r'(?im)^[ \t]*(?:#{1,4}[ \t]*)?TITLE\s*:'):
        starts = [m.start() for m in re.finditer(anchor, raw_text)]
        if len(starts) >= 2:
            starts.append(len(raw_text))
            return [raw_text[starts[i]:starts[i + 1]] for i in range(len(starts) - 1)]
    return []


def _parse_slide_blocks(raw_text: str, requested_count: int) -> list[dict[str, Any]]:
    blocks = _slide_regions(raw_text)
    slides: list[dict[str, Any]] = []

    for idx, block in enumerate(blocks, start=1):
        title_match = re.search(r'^TITLE:\s*(.+)$', block, re.M)
        type_match = re.search(r'^TYPE:\s*(theory|practical)$', block, re.M | re.I)
        image_desc_match = re.search(r'^IMAGE_DESCRIPTION:\s*(.+)$', block, re.M)
        bullets = re.findall(r'^\s*[-*]\s*(.+)$', block, re.M)

        title = title_match.group(1).strip() if title_match else f"Slide {idx}"
        slide_type = type_match.group(1).strip().lower() if type_match else "theory"
        image_description = image_desc_match.group(1).strip() if image_desc_match else ""

        if not bullets:
            bullets = [f"Key point for {title}"]

        slides.append({
            "title": title,
            "bullets": [str(b).strip() for b in bullets][:6],
            "type": slide_type,
            "image_description": image_description,
        })

    return slides[:requested_count]


def _rebalance_slides(slides: list[dict[str, Any]], requested_count: int) -> list[dict[str, Any]]:
    """Spread the model's own bullets across the requested number of slides.

    When the model returns fewer slides than requested, its bullets are
    re-chunked over the missing slides (at least two lines each) so the deck
    keeps the generated material instead of generic placeholders. Slides that
    already exist keep their leading title.
    """
    if len(slides) >= requested_count:
        return slides
    bullets = [str(b) for slide in slides for b in slide.get("bullets", []) if str(b).strip()]
    if len(bullets) < 2 * requested_count:
        return slides  # not enough material to give every slide real lines

    per_slide, extra = divmod(len(bullets), requested_count)
    result: list[dict[str, Any]] = []
    cursor = 0
    for idx in range(requested_count):
        take = per_slide + (1 if idx < extra else 0)
        chunk = bullets[cursor:cursor + take]
        cursor += take
        source = slides[min(idx, len(slides) - 1)]
        title = source.get("title") or f"Key Point {idx + 1}"
        if idx >= len(slides):
            title = f"{title} (part {idx + 1})"
        result.append({
            "title": title,
            "bullets": chunk,
            "type": source.get("type", "theory"),
            # Only the original slides keep their visual brief; derived ones
            # would otherwise all request the same image.
            "image_description": source.get("image_description", "") if idx < len(slides) else "",
        })
    return result


def _normalize_slides(slides: list[dict[str, Any]], requested_count: int) -> list[dict[str, Any]]:
    slides = _rebalance_slides(slides[:requested_count], requested_count)
    while len(slides) < requested_count:
        index = len(slides) + 1
        slides.append(
            {
                "title": f"Key Takeaway {index}",
                "bullets": ["Summary point", "Action item", "Recap"],
                "type": "theory",
            }
        )
    return slides


def _cache_key(prompt: str, requested_count: int) -> str:
    try:
        provider_sig = active_signature("slides")
    except Exception:
        provider_sig = settings.gemini_model
    raw = "|".join(
        [
            provider_sig,
            settings.gemini_thinking_level or "default",
            str(requested_count),
            prompt,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> list[dict[str, Any]] | None:
    ttl = max(int(settings.gemini_slides_cache_ttl), 0)
    if not ttl:
        return None
    now = time.time()
    with _CACHE_LOCK:
        expired = [k for k, (ts, _) in _SLIDES_CACHE.items() if now - ts > ttl]
        for stale in expired:
            _SLIDES_CACHE.pop(stale, None)
        hit = _SLIDES_CACHE.get(key)
        if hit is None:
            return None
        return copy.deepcopy(hit[1])


def _cache_put(key: str, slides: list[dict[str, Any]]) -> None:
    if not max(int(settings.gemini_slides_cache_ttl), 0):
        return
    with _CACHE_LOCK:
        _SLIDES_CACHE[key] = (time.time(), copy.deepcopy(slides))


def generate_slides_json(prompt: str, requested_count: int) -> list[dict[str, Any]]:
    cache_key = _cache_key(prompt, requested_count)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    raw = generate_content(prompt, temperature=0.3, response_mime_type="text/plain", task="slides")
    raw = _strip_code_fences(raw)

    slides: list[dict[str, Any]]
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("Parsed JSON is not a list")

        slides = []
        for idx, slide in enumerate(parsed, start=1):
            if not isinstance(slide, dict):
                continue
            title = str(slide.get("title", f"Slide {idx}"))
            bullets = slide.get("bullets", [])
            if not isinstance(bullets, list):
                bullets = [str(bullets)]
            bullets = [str(b) for b in bullets][:6]
            slide_type = str(slide.get("type", "theory")).lower()
            if slide_type not in {"theory", "practical"}:
                slide_type = "theory"
            slides.append({
                "title": title,
                "bullets": bullets,
                "type": slide_type,
                "image_description": str(slide.get("image_description", "")),
            })
    except (json.JSONDecodeError, ValueError):
        slides = _parse_slide_blocks(raw, requested_count)

    slides = _normalize_slides(slides, requested_count)
    _cache_put(cache_key, slides)
    return copy.deepcopy(slides)
