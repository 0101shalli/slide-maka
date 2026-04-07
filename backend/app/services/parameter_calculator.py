from dataclasses import dataclass


@dataclass
class Distribution:
    total_slides: int
    theory_slides: int
    practical_slides: int
    image_slides: int
    warning: str | None = None


def compute_distribution(slide_count: int, theory_percent: int, image_percent: int, text: str) -> Distribution:
    theory_slides = round(slide_count * (theory_percent / 100))
    practical_slides = slide_count - theory_slides
    image_slides = round(slide_count * (image_percent / 100))

    words = len(text.split())
    warning = None
    min_words_per_slide = 18
    if words < slide_count * min_words_per_slide:
        warning = (
            f"Input may be too short ({words} words) for {slide_count} slides. "
            "Generator will add key-takeaway/divider slides to satisfy count."
        )

    return Distribution(
        total_slides=slide_count,
        theory_slides=theory_slides,
        practical_slides=practical_slides,
        image_slides=image_slides,
        warning=warning,
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
