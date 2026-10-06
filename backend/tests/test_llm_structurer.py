import pytest
from app.services.llm_structurer import generate_slides, _redistribute_content
from app.services.parameter_calculator import Distribution, compute_distribution


def test_redistribute_content():
    """Test that content is properly redistributed across slides."""
    # Create test content with multiple sections
    single_slide = {
        "title": "Main Topic",
        "bullets": [
            "This is the first point with important information.",
            "This is the second point with detailed content.",
            "This is the third point with additional details.",
            "This is the fourth point with more information.",
            "This is the fifth point with final details."
        ]
    }

    # Create distribution for 3 slides
    distribution = Distribution(total_slides=4, theory_slides=2, practical_slides=1, image_slides=1)

    # Test redistribution for 3 slides
    redistributed = _redistribute_content(single_slide, 3, distribution)

    # Should have 3 slides
    assert len(redistributed) == 3

    # First slide should keep original title
    assert redistributed[0]["title"] == "Main Topic"

    # Check that content is distributed (not all in one slide)
    total_bullets = sum(len(slide["bullets"]) for slide in redistributed)
    assert total_bullets == len(single_slide["bullets"])  # All bullets distributed


def test_generate_slides_fallback():
    """Test that generate_slides works with fallback content distribution."""
    # Use the real calculator so content_slides agrees with total_slides: a
    # deck reserves cover, outline, takeaways and the closing slide, so
    # total_slides=6 leaves 2 content slides.
    distribution = compute_distribution(6, 50, 30, "Test content about widgets and refunds")
    assert distribution.total_slides == 6
    assert distribution.content_slides == 2

    # Test with minimal input that should trigger fallback
    result = generate_slides("Test content", distribution, "Intermediate", "Test Presentation")

    # Should return cover + outline + the content slides
    assert isinstance(result, list)
    assert len(result) == 2 + distribution.content_slides

    # Check that slides have different content (not all identical)
    slide_titles = [slide.get("title", "") for slide in result]
    assert len(set(slide_titles)) > 1  # Not all slides have identical titles

    # Check that content slides (exclude cover and outline) have bullets
    content_slides = [slide for slide in result if slide.get("slide_number", 0) > 2]
    assert len(content_slides) == distribution.content_slides
    for slide in content_slides:
        assert "bullets" in slide
        assert len(slide["bullets"]) >= 1