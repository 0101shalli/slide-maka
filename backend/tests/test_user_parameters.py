"""The deck must honour the parameters the user gave.

These are the guarantees checked here:
  * the deck is exactly the requested number of slides when the material allows
  * the theory / practice and image ratios are respected
  * no source wording is dropped, summarised or invented
  * no bullet is repeated across slides
"""
from __future__ import annotations

import io
import re

import pytest

from app.services import document_extractor as de
from app.services.deck_builder import build_deck
from app.services.parameter_calculator import STRUCTURAL_SLIDES, compute_distribution
from app.services.text_structurer import structure_text


SENTENCES = [
    "Machine learning systems require careful design decisions.",
    "Feature stores keep training and serving features consistent.",
    "Labeling workflows decide how much signal a dataset carries.",
    "Data versioning makes a model reproducible months later.",
    "Retrieval quality sets the ceiling for every downstream answer.",
    "Semantic caching removes repeated work on common questions.",
    "Batch and streaming paths need separate correctness tests.",
    "Idempotent writes keep retries from duplicating records.",
    "Backpressure protects a queue from a bursty producer.",
    "Dead letter queues hold the payloads a consumer cannot parse.",
    "Traces show where a slow request actually spent its time.",
    "Structured logs turn a failure into a queryable event.",
    "Canary releases limit the blast radius of a bad model.",
    "Feature flags separate a code change from a behaviour change.",
    "Gradient descent updates the weights to minimise the loss function.",
    "Learning rate and batch size dominate convergence behaviour.",
    "Momentum smooths the oscillation found near the optimum.",
    "Weight decay reduces overfitting on small tabular data sets.",
    "Adam adapts the step size per parameter and converges quickly.",
    "Gradient clipping keeps an outlier batch from destroying a run.",
    "Class imbalance biases accuracy towards the majority label.",
    "Calibration decides whether a 0.8 score is really 80 percent likely.",
    "Cross validation estimates generalisation before deployment.",
    "Hyperparameter search must not peek at the test set.",
    "Precision and recall must be chosen for the task at hand.",
    "A confusion matrix explains where a model actually fails.",
    "Latency percentiles matter more than the average response time.",
    "Model serving exposes the artefact behind a versioned endpoint.",
    "Shadow deployments compare a candidate against the live model.",
    "Rollback requires the previous artefact to stay retrievable.",
    "Drift monitoring compares live features to the training baseline.",
    "Latency alerts catch failures that accuracy metrics cannot see.",
    "Retraining triggers need a reason beyond a calendar date.",
    "Cost per thousand requests constrains the model choice.",
    "A champion challenger split measures a new model safely.",
    "Cache the answer, not the question, to stay correct.",
]

SENTENCES_PER_SECTION = 5

GENERIC = re.compile(
    r"(this section|the key principles|follow a clear|best practices|check the outcomes|"
    r"integrate this approach|evaluate the impact|refine the process|mastering these|"
    r"repeat the steps|a worked example|important definitions|everyday examples|"
    r"summary point|action item|^recap)",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def handbook(tmp_path_factory) -> de.ExtractedDocument:
    """A six-section handbook with a photo, a vector chart and a table."""
    pymupdf = pytest.importorskip("pymupdf")
    from PIL import Image

    path = tmp_path_factory.mktemp("params") / "handbook.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 120), "Machine Learning Systems", fontsize=26)
    page = doc.new_page()
    page.insert_text((72, 90), "Table of Contents", fontsize=20)
    page.insert_text((72, 130), "1. Introduction " + "." * 30 + " 3", fontsize=11)

    chunks = [
        SENTENCES[i:i + SENTENCES_PER_SECTION]
        for i in range(0, len(SENTENCES), SENTENCES_PER_SECTION)
    ]
    for index, group in enumerate(chunks):
        page = doc.new_page()
        page.insert_text((72, 80), f"{index + 1}. Section {index + 1}", fontsize=16)
        y = 110
        for sentence in group:
            page.insert_text((72, y), sentence, fontsize=11)
            y += 18
        if index == 0:
            page.insert_text((72, y + 8), "Figure 1. Training loss curves", fontsize=9)
            buf = io.BytesIO()
            Image.new("RGB", (400, 200), (30, 90, 160)).save(buf, format="PNG")
            page.insert_image(pymupdf.Rect(72, y + 16, 472, y + 216), stream=buf.getvalue())
    doc.save(str(path))
    doc.close()
    return de.extract_document(path, path.parent / "assets")


def _deck(handbook, slides=14, theory=50, images=35, audience="Intermediate"):
    dist = compute_distribution(slides, theory, images, handbook.text)
    return dist, build_deck("file", handbook.text, None, dist, audience,
                            "Handbook", "A", "a@b.c", handbook.load_figures())


def _content(deck):
    return [s for s in deck if s.get("type") in ("theory", "practical")]


# ---------------------------------------------------------------------------
# Slide count
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("total", [8, 10, 12, 14, 18])
def test_deck_is_exactly_the_requested_number_of_slides(handbook, total):
    _dist, deck = _deck(handbook, slides=total)
    assert len(deck) == total


def test_slide_numbering_is_contiguous_and_ends_at_the_total(handbook):
    _dist, deck = _deck(handbook, slides=14)
    assert [s["slide_number"] for s in deck] == list(range(1, len(deck) + 1))


def test_structural_slides_are_present_once_each(handbook):
    _dist, deck = _deck(handbook, slides=14)
    kinds = [s.get("type") for s in deck]
    assert kinds[0] == "cover"
    assert kinds[1] == "outline"
    assert kinds[-1] == "end"
    assert kinds.count("cover") == 1 and kinds.count("outline") == 1 and kinds.count("end") == 1


# ---------------------------------------------------------------------------
# Ratios
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slides,theory,images",
    [(10, 30, 20), (10, 70, 20), (14, 50, 35), (14, 20, 60), (18, 60, 40)],
)
def test_theory_and_image_ratios_are_respected(handbook, slides, theory, images):
    dist, deck = _deck(handbook, slides=slides, theory=theory, images=images)
    content = _content(deck)

    assert len(content) == slides - STRUCTURAL_SLIDES
    assert sum(1 for s in content if s["type"] == "theory") == dist.theory_slides
    assert sum(1 for s in content if s["type"] == "practical") == dist.practical_slides
    assert sum(1 for s in content if s.get("image_url")) == dist.image_slides


def test_zero_percent_theory_and_hundred_percent_images(handbook):
    dist, deck = _deck(handbook, slides=12, theory=0, images=100)
    content = _content(deck)
    assert sum(1 for s in content if s["type"] == "theory") == 0
    assert sum(1 for s in content if s.get("image_url")) == dist.image_slides == len(content)


def test_zero_percent_images_leaves_no_image_slots(handbook):
    _dist, deck = _deck(handbook, slides=12, theory=50, images=0)
    content = _content(deck)
    assert not any(s.get("image_url") for s in content)


# ---------------------------------------------------------------------------
# Content fidelity
# ---------------------------------------------------------------------------


def test_no_source_wording_is_dropped(handbook):
    _dist, deck = _deck(handbook, slides=16)
    text = " ".join(
        b.lower() for s in _content(deck) for b in s.get("bullets", []) if b and not b.startswith("**")
    )
    for sentence in SENTENCES:
        words = {w for w in re.findall(r"[a-z]+", sentence.lower()) if len(w) > 3}
        assert words & set(re.findall(r"[a-z]+", text)), f"lost from the deck: {sentence}"


def test_no_invented_summary_lines(handbook):
    _dist, deck = _deck(handbook, slides=16)
    for slide in _content(deck):
        for bullet in slide.get("bullets", []):
            if not bullet or bullet.startswith("**"):
                continue
            assert not GENERIC.search(bullet), f"invented filler on slide {slide['slide_number']}: {bullet}"


def test_no_bullet_repeats_across_slides(handbook):
    _dist, deck = _deck(handbook, slides=16)
    seen = {}
    for slide in _content(deck):
        for bullet in slide.get("bullets", []):
            if bullet and not bullet.startswith("**"):
                seen.setdefault(bullet, []).append(slide["slide_number"])
    assert {t: p for t, p in seen.items() if len(p) > 1} == {}


def test_no_slide_is_left_empty(handbook):
    _dist, deck = _deck(handbook, slides=16)
    for slide in _content(deck):
        assert [b for b in slide.get("bullets", []) if b and not b.startswith("**")], (
            f"slide {slide['slide_number']} ({slide['title']}) has no content"
        )


def test_slides_are_balanced_rather_than_one_line_each(handbook):
    """More slides than sections should not mean one sentence per slide."""
    _dist, deck = _deck(handbook, slides=18)
    content = _content(deck)
    thin = [
        s for s in content
        if len([b for b in s.get("bullets", []) if b and not b.startswith("**")]) < 2
    ]
    assert len(thin) <= len(content) // 3, f"{len(thin)}/{len(content)} slides hold a single line"


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def test_document_figures_land_on_their_own_section(handbook):
    _dist, deck = _deck(handbook, slides=14)
    from app.services.deck_builder import _normalise_heading

    local = [s for s in _content(deck) if s.get("image_local_path")]
    assert local, "the photo must be used"
    for slide in local:
        figure = next(f for f in handbook.figures if str(f.path) == slide["image_local_path"])
        assert _normalise_heading(figure.section) in _normalise_heading(slide["title"]), (
            f"slide '{slide['title']}' got a figure from '{figure.section}'"
        )


def test_an_unrelated_figure_is_never_forced_onto_a_slide(handbook):
    from app.services.document_extractor import Figure

    _dist, deck = _deck(handbook, slides=14)
    stranger = Figure(path="/nonexistent/never-used.png", caption="Figure 9. Sediment transport",
                      section="Geology")
    for slide in _content(deck):
        if str(stranger.path) == str(slide.get("image_local_path")):
            pytest.fail("a figure from an unrelated section was used")
