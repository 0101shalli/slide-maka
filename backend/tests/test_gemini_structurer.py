import pytest

from app.services import gemini_structurer
from app.services.gemini_structurer import (
    _normalize_slides,
    _parse_slide_blocks,
    generate_slides_json,
)


def test_normalize_adds_missing_slides():
    slides = [{"title": "A", "bullets": ["x"], "type": "theory"}]
    result = _normalize_slides(slides, requested_count=3)
    assert len(result) == 3
    assert result[0]["title"] == "A"
    assert result[2]["title"].startswith("Key Takeaway")


def test_normalize_truncates_extra_slides():
    slides = [{"title": str(i), "bullets": [], "type": "theory"} for i in range(6)]
    result = _normalize_slides(slides, requested_count=4)
    assert len(result) == 4


def test_normalize_rebalances_instead_of_padding():
    """Too few slides: the model's own bullets fill the deck, not placeholders."""
    slides = [{
        "title": "Alpha",
        "type": "theory",
        "image_description": "alpha diagram",
        "bullets": [f"point {i}" for i in range(6)],
    }]
    result = _normalize_slides(slides, requested_count=3)
    assert len(result) == 3
    assert all(len(s["bullets"]) == 2 for s in result)
    assert [b for s in result for b in s["bullets"]] == [f"point {i}" for i in range(6)]
    assert not any(s["title"].startswith("Key Takeaway") for s in result)
    # Derived slides must not all request the same visual.
    assert [s["image_description"] for s in result] == ["alpha diagram", "", ""]


def test_parse_slide_blocks_without_markers():
    raw = (
        "SLIDE_NUMBER: 1\nTITLE: First Topic\nBULLETS:\n- one\n- two\n\n"
        "SLIDE_NUMBER: 2\nTITLE: Second Topic\nBULLETS:\n- three\n- four"
    )
    slides = _parse_slide_blocks(raw, 2)
    assert [s["title"] for s in slides] == ["First Topic", "Second Topic"]
    assert slides[1]["bullets"] == ["three", "four"]


def test_parse_slide_blocks_with_markers():
    raw = "<<<START_SLIDE>>>\nTITLE: Marked\nBULLETS:\n- only\n<<<END_SLIDE>>>"
    assert _parse_slide_blocks(raw, 1)[0]["title"] == "Marked"


def test_generate_slides_json_is_memoized(monkeypatch):
    """The /preview + /generate pair must spend one LLM call, not two."""
    calls = []

    def fake_generate_content(prompt, **kwargs):
        calls.append(prompt)
        return '<<<START_SLIDE>>>\nTITLE: One\nBULLETS:\n- a\n<<<END_SLIDE>>>'

    monkeypatch.setattr(gemini_structurer, "generate_content", fake_generate_content)
    with gemini_structurer._CACHE_LOCK:
        gemini_structurer._SLIDES_CACHE.clear()

    first = generate_slides_json("PROMPT-A", 1)
    second = generate_slides_json("PROMPT-A", 1)

    assert len(calls) == 1
    assert first == second
    # The cache must hand out copies so a caller cannot corrupt later requests.
    first[0]["title"] = "MUTATED"
    assert generate_slides_json("PROMPT-A", 1)[0]["title"] == "One"

    # A different slide count is a different prompt and must not be served stale.
    generate_slides_json("PROMPT-A", 2)
    assert len(calls) == 2
    with gemini_structurer._CACHE_LOCK:
        gemini_structurer._SLIDES_CACHE.clear()
