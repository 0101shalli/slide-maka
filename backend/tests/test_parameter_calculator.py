from app.services.parameter_calculator import compute_distribution


def test_distribution_math():
    dist = compute_distribution(10, 70, 30, "word " * 200)
    assert dist.theory_slides == 7
    assert dist.practical_slides == 3
    assert dist.image_slides == 3
    assert dist.warning is None


def test_short_text_warning():
    dist = compute_distribution(20, 50, 50, "too short")
    assert dist.warning is not None
