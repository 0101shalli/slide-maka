from app.services.gemini_structurer import _normalize_slides


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
