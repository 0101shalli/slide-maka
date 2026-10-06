from dataclasses import dataclass


@dataclass
class Distribution:
    total_slides: int
    theory_slides: int
    practical_slides: int
    image_slides: int
    warning: str | None = None
    content_slides: int = 1


# Slides the deck spends on structure rather than source material: the cover,
# the outline, the closing recap and the thank-you. The user's ``slide_count``
# is the total they see, so the content slides are whatever is left over.
STRUCTURAL_SLIDES = 4


def compute_distribution(slide_count: int, theory_percent: int, image_percent: int, text: str) -> Distribution:
    # `slide_count` is the total number of slides the user gets, cover and
    # outline included. Reserving only two of them made every deck come out two
    # slides longer than the number the user chose, because the closing recap
    # and the thank-you slide are added afterwards.
    content_slides = max(slide_count - STRUCTURAL_SLIDES, 1)
    theory_slides = round(content_slides * (theory_percent / 100))
    practical_slides = content_slides - theory_slides
    image_slides = min(content_slides, round(content_slides * (image_percent / 100)))

    words = len(text.split())
    warning = None
    min_words_per_slide = 18
    # Use content slides when estimating minimum word requirements.
    if words < content_slides * min_words_per_slide:
        warning = (
            f"Input may be too short ({words} words) for {slide_count} slides. "
            "Slides will carry fewer lines each so nothing has to be repeated."
        )

    return Distribution(
        total_slides=slide_count,
        theory_slides=theory_slides,
        practical_slides=practical_slides,
        image_slides=image_slides,
        warning=warning,
        content_slides=content_slides,
    )


def theory_slide_indices(total_slides: int, theory_slides: int) -> list[int]:
    if theory_slides <= 0:
        return []
    step = total_slides / theory_slides
    return sorted({min(total_slides - 1, round(i * step)) for i in range(theory_slides)})


def image_slide_indices(total_slides: int, image_slides: int) -> list[int]:
    if image_slides <= 0:
        return []
    step = total_slides / image_slides
    return sorted({min(total_slides - 1, round(i * step)) for i in range(image_slides)})
