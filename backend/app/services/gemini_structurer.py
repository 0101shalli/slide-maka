import json
from typing import Any


from app.core.config import settings


def _strip_code_fences(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    return cleaned.strip()


def _normalize_slides(slides: list[dict[str, Any]], requested_count: int) -> list[dict[str, Any]]:
    slides = slides[:requested_count]
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


def generate_slides_json(prompt: str, requested_count: int) -> list[dict[str, Any]]:
    if not settings.gemini_api_key:
        raise RuntimeError("Missing GEMINI_API_KEY. Add it to your .env file.")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
        f"?key={settings.gemini_api_key}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "response_mime_type": "application/json",
        },
    }

    import requests

    response = requests.post(url, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()

    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts or "text" not in parts[0]:
        raise RuntimeError("Gemini returned no text payload")

    raw = _strip_code_fences(parts[0]["text"])
    slides = json.loads(raw)
    if not isinstance(slides, list):
        raise RuntimeError("Gemini response is not a JSON array")

    sanitized: list[dict[str, Any]] = []
    for idx, slide in enumerate(slides, start=1):
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
        sanitized.append({"title": title, "bullets": bullets, "type": slide_type})

    return _normalize_slides(sanitized, requested_count)
