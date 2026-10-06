from app.services.parameter_calculator import compute_distribution


def test_distribution_math():
    """The ratios apply to the content slides, which are what is left of the total.

    Four slides are spent on structure (cover, outline, recap, thank-you), so a
    10-slide deck has 6 content slides and 70% theory is 4 of them.
    """
    dist = compute_distribution(10, 70, 30, "word " * 200)
    assert dist.content_slides == 6
    assert dist.theory_slides == 4
    assert dist.practical_slides == 2
    assert dist.image_slides == 2
    assert dist.warning is None


def test_total_is_the_number_the_user_asked_for():
    for total in (5, 6, 8, 10, 14, 20, 50):
        dist = compute_distribution(total, 50, 35, "word " * 500)
        assert dist.total_slides + 0 == total
        # Cover, outline, recap and thank-you plus the content slides.
        assert 4 + dist.content_slides == total
        assert dist.theory_slides + dist.practical_slides == dist.content_slides


def test_ratios_are_respected():
    dist = compute_distribution(14, 50, 35, "word " * 500)
    assert dist.content_slides == 10
    assert dist.theory_slides == 5
    assert dist.practical_slides == 5
    assert dist.image_slides == 4  # 35% of 10, rounded

    dist = compute_distribution(14, 70, 50, "word " * 500)
    assert dist.theory_slides == 7
    assert dist.practical_slides == 3
    assert dist.image_slides == 5


def test_image_slides_never_exceed_content_slides():
    dist = compute_distribution(6, 50, 100, "word " * 500)
    assert dist.image_slides == dist.content_slides


def test_minimum_slide_count_still_yields_content():
    dist = compute_distribution(5, 50, 50, "word " * 500)
    assert dist.content_slides >= 1


def test_short_text_warning():
    dist = compute_distribution(20, 50, 50, "too short")
    assert dist.warning is not None
    # The warning must not promise filler the generator no longer inserts.
    assert "key-takeaway" not in dist.warning
