"""Tests for using visuals read out of an uploaded document on image slides."""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

from app.services.deck_builder import _attach_image_slots, _attach_document_figures, build_deck
from app.services.document_extractor import Figure
from app.services.parameter_calculator import compute_distribution


def _png(path: Path, color=(10, 20, 30)) -> str:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 300), color).save(path, format="PNG")
    return str(path)


def _image_slide(title: str, bullet: str, index: int = 0) -> dict:
    return {
        "slide_number": index + 3,
        "title": title,
        "bullets": [bullet],
        "type": "theory",
        "image_url": f"https://example.invalid/{index}.jpg",
        "image_keywords": [title.split()[0].lower()],
        "image_content": [bullet],
    }


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def test_matching_figure_is_attached_to_the_right_slide(tmp_path):
    figure = Figure(
        path=_png(tmp_path / "throughput.png"),
        caption="Figure 1. Throughput by model family",
        kind="chart",
        section="1. Throughput",
    )
    slides = [
        _image_slide("1. Throughput", "Throughput by model family", 0),
        _image_slide("2. Cost Analysis", "Budget review", 1),
    ]

    result = _attach_document_figures(slides, [figure], 2)

    assert result[0]["image_local_path"] == figure.path
    assert result[0]["image_source"] == "document:chart"
    assert result[0]["image_caption"] == "Figure 1. Throughput by model family"
    # The unrelated slide keeps its keyword image.
    assert "image_local_path" not in result[1]


def test_one_figure_is_never_reused_on_two_slides(tmp_path):
    figure = Figure(path=_png(tmp_path / "shared.png"), caption="Figure 1. Solar panels", section="Solar")
    slides = [
        _image_slide("Solar panels", "Solar output", 0),
        _image_slide("More on solar", "Solar arrays", 1),
    ]

    result = _attach_document_figures(slides, [figure], 2)

    attached = [s for s in result if s.get("image_local_path")]
    assert len(attached) == 1


def test_unrelated_figure_is_not_forced_onto_a_slide(tmp_path):
    figure = Figure(path=_png(tmp_path / "unrelated.png"), caption="Figure 9. Sediment transport", section="Geology")
    slides = [_image_slide("Neural Networks", "Activation functions", 0)]

    result = _attach_document_figures(slides, [figure], 1)

    assert "image_local_path" not in result[0]


def test_missing_file_does_not_mark_the_slide(tmp_path):
    figure = Figure(path=str(tmp_path / "gone.png"), caption="Figure 1. Throughput", section="Throughput")
    slides = [_image_slide("Throughput", "Throughput numbers", 0)]

    result = _attach_document_figures(slides, [figure], 1)

    assert "image_local_path" not in result[0]


def test_slide_without_an_image_slot_is_never_given_a_figure(tmp_path):
    figure = Figure(path=_png(tmp_path / "x.png"), caption="Figure 1. Throughput", section="Throughput")
    text_only = {"slide_number": 3, "title": "Throughput", "bullets": ["Numbers"], "type": "theory"}

    result = _attach_document_figures([text_only], [figure], 1)

    assert "image_local_path" not in result[0]


def test_empty_figure_list_is_a_no_op(tmp_path):
    slides = [_image_slide("Throughput", "Numbers", 0)]
    before = dict(slides[0])
    assert _attach_document_figures(slides, [], 1) == slides
    assert slides[0] == before


def test_attach_image_slots_forwards_figures(tmp_path):
    figure = Figure(path=_png(tmp_path / "y.png"), caption="Figure 1. Water cycle", section="Water cycle")
    slides = [_image_slide("The water cycle", "Evaporation and condensation", 0)]

    _attach_image_slots(slides, 1, [figure])

    assert slides[0].get("image_local_path") == figure.path


# ---------------------------------------------------------------------------
# End to end through build_deck
# ---------------------------------------------------------------------------


def test_build_deck_places_document_visuals_on_image_slides(tmp_path):
    figure = Figure(
        path=_png(tmp_path / "pipeline.png"),
        caption="Figure 2. Data pipeline architecture",
        kind="diagram",
        section="Architecture",
    )
    text = (
        "## Architecture\n"
        "The data pipeline architecture processes incoming records in batches.\n"
        "- Ingest stage validates every record before storage\n"
        "- Transform stage normalises columns and units\n"
        "## Results\n"
        "Pipeline latency improved by forty percent after the rewrite\n"
        "- Ingest throughput doubled\n"
        "- Storage cost fell by a fifth\n"
    )
    dist = compute_distribution(12, 50, 40, text)

    slides = build_deck("file", text, None, dist, "Intermediate", "Pipeline", "A", "a@b.c", [figure])

    with_visual = [s for s in slides if s.get("image_local_path")]
    assert with_visual, "the document visual must land on an image slide"
    assert with_visual[0]["image_local_path"] == figure.path
    assert with_visual[0]["image_source"] == "document:diagram"
    # Non-image slides are untouched.
    for slide in slides:
        if slide.get("type") in ("cover", "outline", "end", "takeaways"):
            assert "image_local_path" not in slide


def test_duplicate_caption_bullet_is_dropped_when_the_visual_shows_it(tmp_path):
    """A split section pushes its caption to the next slide; the visual repeats it."""
    figure = Figure(
        path=_png(tmp_path / "loss.png"),
        caption="Figure 2. Loss per training step",
        kind="chart",
        section="2. Model Training",
    )
    slides = [{
        "slide_number": 6,
        "title": "2. Model Training (continued)",
        "type": "theory",
        "bullets": ["Figure 2. Loss per training step.", "Gradient descent updates weights."],
        "image_url": "https://example.invalid/x.jpg",
    }]

    result = _attach_document_figures(slides, [figure], 1)

    assert result[0]["bullets"] == ["Gradient descent updates weights."]


def test_caption_bullet_is_kept_when_it_is_the_only_content(tmp_path):
    """Dropping it would leave the slide with no text at all."""
    figure = Figure(path=_png(tmp_path / "only.png"), caption="Figure 1. Pipeline", section="Intro")
    slides = [{
        "slide_number": 3,
        "title": "Overview",
        "type": "theory",
        "bullets": ["Figure 1. Pipeline."],
        "image_url": "https://example.invalid/x.jpg",
    }]

    result = _attach_document_figures(slides, [figure], 1)

    assert result[0]["bullets"] == ["Figure 1. Pipeline."]


def test_caption_matching_ignores_label_and_punctuation(tmp_path):
    figure = Figure(path=_png(tmp_path / "m.png"), caption="Table 1. Accuracy comparison", section="Results")
    slides = [{
        "slide_number": 3,
        "title": "Accuracy comparison",
        "type": "theory",
        "bullets": ["Accuracy comparison.", "The CNN scored highest."],
        "image_url": "https://example.invalid/x.jpg",
    }]

    result = _attach_document_figures(slides, [figure], 1)

    assert result[0]["bullets"] == ["The CNN scored highest."]


def test_bullet_without_a_figure_match_is_untouched(tmp_path):
    """No local visual on this slide, so the caption text is the only source."""
    figure = Figure(path=_png(tmp_path / "other.png"), caption="Figure 1. Sediment", section="Geology")
    slides = [{
        "slide_number": 3,
        "title": "Neural Networks",
        "type": "theory",
        "bullets": ["Figure 1. Sediment."],
        "image_url": "https://example.invalid/x.jpg",
    }]

    result = _attach_document_figures(slides, [figure], 1)

    assert result[0]["bullets"] == ["Figure 1. Sediment."]


# ---------------------------------------------------------------------------
# Correlation: the visual must come from the slide's own section
# ---------------------------------------------------------------------------


def test_section_match_outranks_a_coincidental_shared_word(tmp_path):
    """A chart from '2. Model Training' must not jump to a slide that says 'model'."""
    from app.services.deck_builder import _figure_tokens, _score_figure, _section_affinity

    own = Figure(path=_png(tmp_path / "own.png"), caption="Figure 1. Loss per step", section="2. Model Training")
    # Shares the word "model" with the slide, but belongs to another section.
    other = Figure(path=_png(tmp_path / "other.png"), caption="Figure 2. Model accuracy", section="3. Results")
    slide = {"title": "2. Model Training", "type": "theory", "bullets": ["Model accuracy improved."]}
    tokens = {"model", "accuracy", "training", "improved"}

    own_overlap = _score_figure(own, tokens, _figure_tokens(own))
    other_overlap = _score_figure(other, tokens, _figure_tokens(other))
    own_total = own_overlap + _section_affinity(own, slide)
    other_total = other_overlap + _section_affinity(other, slide)

    assert own_total > other_total
    assert _section_affinity(own, slide) > 0
    assert _section_affinity(other, slide) == 0


def test_heading_variants_still_match_their_section():
    from app.services.deck_builder import _section_affinity, _normalise_heading

    figure = Figure(path="/tmp/does-not-need-to-exist.png", caption="Figure 1. Accuracy", section="3. Results")
    for title in ("3. Results", "3. Results (part 2)", "3. Results: In Focus", "Results"):
        assert _section_affinity(figure, {"title": title}) > 0, title


def test_heading_normalisation_keeps_meaningful_words():
    from app.services.deck_builder import _normalise_heading

    # "introduction" must survive: it is what a section is matched on.
    assert _normalise_heading("1. Introduction") == "introduction"
    assert _normalise_heading("2. Model Training (continued)") == "model training"
    assert _normalise_heading("2. Model Training: In Focus") == "model training"
    assert _normalise_heading("3. Results (part 2)") == "results"
    assert _normalise_heading("4. Solar Panels") == "solar panels"


def test_figure_prefers_its_own_section_over_a_stock_keyword(tmp_path):
    """The section of the source document is the primary correlation signal."""
    section_figure = Figure(
        path=_png(tmp_path / "results.png"), caption="Figure 1. Accuracy comparison", section="3. Results"
    )
    unrelated = Figure(path=_png(tmp_path / "u.png"), caption="Figure 2. Solar array", section="1. Introduction")
    slides = [{
        "slide_number": 3,
        "title": "3. Results",
        "type": "theory",
        "bullets": ["The convolutional network achieved the highest accuracy."],
        "image_url": "https://example.invalid/a.jpg",
    }]

    result = _attach_document_figures(slides, [unrelated, section_figure], 1)

    assert result[0]["image_local_path"] == section_figure.path


# ---------------------------------------------------------------------------
# No generic filler: the slides must carry the document's own wording
# ---------------------------------------------------------------------------


def test_real_content_is_not_padded_with_generic_filler():
    """A slide with two real lines must not gain invented meta-commentary."""
    from app.services.deck_builder import _structured_content_slide

    slide = _structured_content_slide(
        slide_number=3,
        title="1. Introduction",
        bullets=[
            "Machine learning systems require careful design decisions.",
            "Site selection determines the annual yield.",
        ],
        slide_type="theory",
        audience_level="Intermediate",
    )

    assert slide["bullets"] == [
        "Machine learning systems require careful design decisions.",
        "Site selection determines the annual yield.",
    ]


def test_single_real_line_is_not_padded_when_a_visual_is_attached(tmp_path):
    """A section with one sentence keeps one sentence; the picture does the rest."""
    from app.services.deck_builder import _structured_content_slide

    figure = Figure(path=_png(tmp_path / "p.png"), caption="Figure 1. Solar array", section="1. Introduction")
    slide = _structured_content_slide(
        slide_number=3,
        title="1. Introduction",
        bullets=["Renewable systems convert natural sources into electricity."],
        slide_type="theory",
        audience_level="Intermediate",
    )
    slide["image_url"] = "https://example.invalid/a.jpg"
    _attach_document_figures([slide], [figure], 1)

    assert slide["bullets"] == ["Renewable systems convert natural sources into electricity."]


def test_a_genuinely_empty_slide_still_gets_something():
    from app.services.deck_builder import _structured_content_slide

    slide = _structured_content_slide(
        slide_number=3, title="Key Takeaway", bullets=[], slide_type="theory", audience_level="Intermediate"
    )
    assert len(slide["bullets"]) >= 2


def test_document_points_are_never_dropped_for_filler(tmp_path):
    """Every point the reader produced must appear somewhere in the deck."""
    import io

    pymupdf = pytest.importorskip("pymupdf")
    from PIL import Image

    from app.services.deck_builder import build_deck
    from app.services.document_extractor import CAPTION_MARKER, CAPTION_RE, extract_document
    from app.services.parameter_calculator import compute_distribution
    from app.services.text_structurer import structure_text

    source = tmp_path / "fidelity.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "1. Introduction", fontsize=16)
    for i, sentence in enumerate([
        "Machine learning systems require careful design decisions.",
        "Site selection determines the annual yield of every installation.",
        "Monocrystalline cells deliver higher efficiency per square metre.",
    ]):
        page.insert_text((72, 110 + i * 20), sentence, fontsize=11)
    buf = io.BytesIO()
    Image.new("RGB", (400, 200), (30, 90, 160)).save(buf, format="PNG")
    page.insert_image(pymupdf.Rect(72, 200, 472, 400), stream=buf.getvalue())
    page.insert_text((72, 420), "Figure 1. Cell layout", fontsize=9)
    page = doc.new_page()
    page.insert_text((72, 80), "2. Results", fontsize=16)
    page.insert_text((72, 110), "Accuracy improved by twelve percent.", fontsize=11)
    page.insert_text((72, 130), "Latency grew with model complexity.", fontsize=11)
    doc.save(str(source))
    doc.close()

    document = extract_document(source, tmp_path / "assets")
    data = structure_text(document.text)
    dist = compute_distribution(10, 50, 40, document.text)
    slides = build_deck("file", document.text, None, dist, "Intermediate",
                        "Fidelity", "A", "a@b.c", document.load_figures())

    def words(text):
        return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3}

    deck_words = set()
    for slide in slides:
        for bullet in slide.get("bullets", []):
            if bullet and not bullet.startswith("**"):
                deck_words |= words(bullet)

    missing = [
        point for point in (p for s in data["sections"] for p in s["points"])
        if not CAPTION_RE.match(point) and not (words(point) & deck_words)
    ]
    assert not missing, f"document text lost from the deck: {missing}"

    # A caption is not a bullet: it is drawn under its figure. That is only
    # acceptable while the caption really is attached to a figure.
    captions = {
        p[len(CAPTION_MARKER):].strip()
        for s in data["sections"] for p in s["points"] if p.startswith(CAPTION_MARKER)
    } or {p for s in data["sections"] for p in s["points"] if CAPTION_RE.match(p)}
    rendered = {f.caption for f in document.load_figures() if f.caption}
    for caption in captions:
        assert any(caption in c for c in rendered), f"caption dropped: {caption}"


# ---------------------------------------------------------------------------
# The deck must not repeat or pad itself when the source is short
# ---------------------------------------------------------------------------


def _short_source_deck(tmp_path, slide_count=14):
    """A 99-word document asked for 14 slides: the case that used to duplicate."""
    import io

    pymupdf = pytest.importorskip("pymupdf")
    from PIL import Image

    from app.services.deck_builder import build_deck
    from app.services.document_extractor import extract_document
    from app.services.parameter_calculator import compute_distribution

    source = tmp_path / "short.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "1. Introduction", fontsize=16)
    for i, sentence in enumerate([
        "Machine learning systems require careful design decisions.",
        "Gradient descent updates weights to minimise the loss function.",
        "Learning rate and batch size dominate convergence behaviour.",
    ]):
        page.insert_text((72, 110 + i * 20), sentence, fontsize=11)
    buf = io.BytesIO()
    Image.new("RGB", (400, 200), (30, 90, 160)).save(buf, format="PNG")
    page.insert_image(pymupdf.Rect(72, 200, 472, 400), stream=buf.getvalue())
    page.insert_text((72, 420), "Figure 1. Training loss curves", fontsize=9)
    doc.save(str(source))
    doc.close()

    document = extract_document(source, tmp_path / "assets")
    dist = compute_distribution(slide_count, 50, 35, document.text)
    return build_deck("file", document.text, None, dist, "Intermediate",
                      "Short", "A", "a@b.c", document.load_figures())


def test_no_bullet_appears_on_two_slides(tmp_path):
    slides = _short_source_deck(tmp_path)

    seen = {}
    for slide in slides:
        # The cover and the closing slide repeat the author details by design.
        if slide.get("type") not in ("theory", "practical"):
            continue
        for bullet in slide.get("bullets", []):
            if bullet and not bullet.startswith("**"):
                seen.setdefault(bullet, []).append(slide["slide_number"])

    duplicated = {text: pages for text, pages in seen.items() if len(pages) > 1}
    assert not duplicated, f"the same sentence is repeated: {duplicated}"


def test_a_short_source_produces_a_shorter_deck_instead_of_filler(tmp_path):
    """Capping the deck is honest; duplicating or inventing lines is not."""
    slides = _short_source_deck(tmp_path, slide_count=14)

    assert len(slides) < 16
    assert all(
        slide.get("title") != "Key Takeaway" for slide in slides
    ), "no placeholder slides for material the document does not contain"
    content = [s for s in slides if s.get("type") in ("theory", "practical")]
    assert 0 < len(content) < 14


def test_no_slide_contains_only_a_figure_caption(tmp_path):
    """A slide whose sole line is 'Figure 2. Loss.' says nothing."""
    from app.services.content_planner import _is_caption

    slides = _short_source_deck(tmp_path)
    for slide in slides:
        bullets = [b for b in slide.get("bullets", []) if b and not b.startswith("**")]
        if not bullets:
            continue
        own = [b for b in bullets if not _is_caption(b)]
        assert own, f"slide {slide['slide_number']} is nothing but a caption: {bullets}"


def test_split_keeps_captions_with_their_own_section():
    from app.services.content_planner import _chunks

    points = [
        "Gradient descent updates weights to minimise the loss function.",
        "Learning rate and batch size dominate convergence behaviour.",
        "Momentum smooths the oscillation near the optimum.",
        "Figure 2. Loss per training step.",
    ]

    chunks = _chunks(points, 2)

    assert len(chunks) == 2
    # The caption rides with the first half, not alone on the second.
    assert any("Figure 2." in p for p in chunks[0])
    assert all(not p.startswith("Figure") for p in chunks[1])


def test_no_chunk_ever_ends_up_holding_only_captions():
    """Splitting must not leave a run whose every line is a caption."""
    from app.services.content_planner import _chunks, _is_caption

    points = [
        "Gradient descent updates weights to minimise the loss function.",
        "Learning rate and batch size dominate convergence.",
        "Momentum smooths the oscillation near the optimum.",
        "Figure 1. Loss per step.",
        "Table 2. Accuracy comparison.",
    ]

    for parts in range(1, 6):
        for chunk in _chunks(points, parts):
            assert any(not _is_caption(point) for point in chunk), (parts, chunk)
