"""Tests for rendering a document visual in the PPTX instead of a stock image."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.services import pptx_generator as pg


def _figure_bytes(width: int = 600, height: int = 400, color=(20, 80, 160)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture()
def figure_path(tmp_path) -> str:
    path = tmp_path / "fig.png"
    path.write_bytes(_figure_bytes())
    return str(path)


def test_local_image_bytes_reads_the_file(figure_path):
    assert pg._local_image_bytes({"image_local_path": figure_path})
    assert pg._local_image_bytes({}) is None
    assert pg._local_image_bytes({"image_local_path": "/nope/missing.png"}) is None


def test_image_slide_with_a_local_visual_is_not_prefetched(figure_path):
    """A slide with the user's own visual must not trigger a network fetch."""
    palette = {"primary": "#1F3A5F", "secondary": "#2E5E8C", "accent": "#E8A33D", "background": "#F7F9FC"}
    slide = {
        "title": "Throughput",
        "image_url": "https://example.invalid/a.jpg",
        "image_local_path": figure_path,
        "image_content": ["Throughput numbers"],
    }

    assert pg._slide_image_spec(slide, palette) is None
    # ...and without the local file the download path is still used.
    del slide["image_local_path"]
    assert pg._slide_image_spec(slide, palette) is not None


def test_document_visual_is_fitted_and_not_cropped(tmp_path):
    """A chart must not be cropped: _place_picture fits it inside the panel."""
    from PIL import Image

    # A wide-and-short image (a chart) would lose its edges under cover-crop.
    wide = io.BytesIO()
    Image.new("RGB", (1200, 300), (200, 30, 30)).save(wide, format="PNG")
    path = tmp_path / "wide.png"
    path.write_bytes(wide.getvalue())

    prs = pg.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    before = len(slide.shapes)

    pg._add_image_panel(
        prs, slide, dict(pg.PALETTES[1]), 4.0, 1.5, 3.3, 3.0, "chart",
        points=["Throughput"], slide_data={"image_local_path": str(path)},
    )

    added = list(slide.shapes)[before:]
    pictures = [s for s in added if s.shape_type == 13]
    assert pictures, "the document visual must be placed in the panel"
    # The picture keeps the source aspect ratio (4:1), so nothing is cut off.
    width_in = pictures[0].width / 914400
    height_in = pictures[0].height / 914400
    assert width_in / height_in == pytest.approx(4.0, rel=0.05)
    assert width_in <= 3.1 + 0.01


def test_panel_caption_uses_the_figure_caption(figure_path):
    prs = pg.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    pg._add_image_panel(
        prs, slide, dict(pg.PALETTES[1]), 4.0, 1.5, 3.3, 3.0, "throughput",
        points=["Numbers"],
        slide_data={"image_local_path": figure_path, "image_caption": "Figure 1. Throughput by family"},
    )

    texts = [s.text_frame.text for s in slide.shapes if s.has_text_frame]
    assert any("Throughput by family" in t for t in texts)


def test_fullscreen_slide_prefers_the_document_visual(figure_path, monkeypatch):
    """The full-bleed image slide must show the document's own visual."""

    def _boom(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("fetch_image must not run when a local visual exists")

    monkeypatch.setattr(pg, "fetch_image", _boom)

    prs = pg.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    pg._render_fullscreen_image(
        prs, slide, dict(pg.PALETTES[1]), {}, {"image_local_path": figure_path, "title": "T"}, "kw", ["b"]
    )

    assert [s for s in slide.shapes if s.shape_type == 13]


def test_fullscreen_slide_falls_back_to_a_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(pg, "fetch_image", lambda *a, **k: _figure_bytes(800, 600))
    prs = pg.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    pg._render_fullscreen_image(prs, slide, dict(pg.PALETTES[1]), {}, {"title": "T"}, "kw", ["b"])

    assert [s for s in slide.shapes if s.shape_type == 13]
