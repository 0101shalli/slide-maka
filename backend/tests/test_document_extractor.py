"""Tests for the detailed document reader (PDF / DOCX).

Everything is hermetic: the fixtures are generated in-process with PyMuPDF and
python-docx, so no network and no checked-in binaries.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.services import document_extractor as de


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _png_bytes(width: int, height: int, color=(30, 90, 160)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory) -> Path:
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path_factory.mktemp("docs") / "sample.pdf"
    doc = pymupdf.open()

    page = doc.new_page()
    page.insert_text((72, 120), "Machine Learning Systems", fontsize=26)
    page.insert_text((72, 160), "A Practical Handbook", fontsize=14)
    page.insert_text((72, 700), "Dr. Ada Lovelace, 2024", fontsize=10)

    page = doc.new_page()
    page.insert_text((72, 90), "Table of Contents", fontsize=20)
    for i, (title, number) in enumerate([("Introduction", 3), ("Model Training", 5), ("Results", 9)]):
        page.insert_text((72, 130 + i * 22), f"{title} " + "." * 40 + f" {number}", fontsize=11)

    page = doc.new_page()
    page.insert_text((72, 80), "1. Introduction", fontsize=16)
    page.insert_text((72, 110), "Machine learning systems are complex and require careful design", fontsize=11)
    page.insert_text((72, 126), "decisions that span data collection and model selection.", fontsize=11)
    page.insert_text((72, 150), "Figure 1. Training loss curves", fontsize=9)
    page.insert_image(pymupdf.Rect(72, 170, 472, 370), stream=_png_bytes(400, 200))

    page = doc.new_page()
    page.insert_text((72, 80), "2. Results", fontsize=16)
    page.insert_text((72, 110), "Table 1. Accuracy comparison", fontsize=9)
    rows = [["Model", "Accuracy"], ["LogReg", "0.81"], ["SVM", "0.86"], ["CNN", "0.93"]]
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            page.draw_rect(
                pymupdf.Rect(72 + c * 150, 130 + r * 24, 72 + (c + 1) * 150, 130 + (r + 1) * 24),
                color=(0.6, 0.6, 0.6), width=0.7,
            )
            page.insert_text((78 + c * 150, 130 + r * 24 + 16), cell, fontsize=10)

    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture(scope="module")
def vector_chart_pdf(tmp_path_factory) -> Path:
    """A page whose chart is drawn as vectors, not embedded as a bitmap."""
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path_factory.mktemp("docs") / "chart.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "1. Throughput", fontsize=16)
    page.insert_text((72, 110), "Throughput comparison across model families", fontsize=11)
    base = 560
    page.draw_line(pymupdf.Point(80, base), pymupdf.Point(480, base), width=1)
    page.draw_line(pymupdf.Point(80, base), pymupdf.Point(80, 400), width=1)
    for i, height in enumerate([60, 120, 90, 160]):
        page.draw_rect(
            pymupdf.Rect(100 + i * 90, base - height, 160 + i * 90, base),
            color=None, fill=(0.2, 0.5, 0.9),
        )
    page.insert_text((72, 585), "Figure 1. Throughput by model family", fontsize=9)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture(scope="module")
def sample_docx(tmp_path_factory) -> Path:
    docx = pytest.importorskip("docx")
    path = tmp_path_factory.mktemp("docs") / "sample.docx"
    doc = docx.Document()

    doc.add_heading("Renewable Energy Systems", 0)
    doc.add_paragraph("A seminar handbook")
    doc.add_page_break()
    doc.add_heading("Table of Contents", 1)
    doc.add_paragraph("Introduction ................................ 3")
    doc.add_paragraph("Solar panels ................................ 5")
    doc.add_page_break()

    doc.add_heading("1. Introduction", 1)
    doc.add_paragraph("Renewable energy systems convert natural sources into electricity.")
    doc.add_picture(io.BytesIO(_png_bytes(600, 400, (200, 120, 40))), width=docx.shared.Inches(4))
    doc.add_paragraph("Figure 1. Solar panel array on a rooftop", style="Caption")

    doc.add_heading("2. Solar Panels", 1)
    doc.add_paragraph("Solar panels convert sunlight directly into electrical energy.")
    table = doc.add_table(rows=3, cols=3)
    for r, row in enumerate([["Panel", "Output", "Cost"], ["Poly", "340W", "$200"], ["Mono", "410W", "$260"]]):
        for c, value in enumerate(row):
            table.rows[r].cells[c].text = value
    doc.add_paragraph("Table 1. Panel comparison", style="Caption")

    doc.save(str(path))
    return path


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------


def test_pdf_cover_and_toc_are_excluded_from_body_text(sample_pdf, tmp_path):
    document = de.extract_document(sample_pdf, tmp_path / "assets")

    assert "Table of Contents" not in document.text
    assert "A Practical Handbook" not in document.text
    assert "Introduction ...." not in document.text
    # They were still read.
    assert "Table of Contents" in document.front_matter_text
    assert "Machine Learning Systems" in document.front_matter_text


def test_pdf_body_sections_are_kept(sample_pdf, tmp_path):
    document = de.extract_document(sample_pdf, tmp_path / "assets")

    assert "1. Introduction" in document.text
    assert "2. Results" in document.text
    assert "0.81" in document.text


def test_docx_title_and_toc_are_excluded(sample_docx, tmp_path):
    document = de.extract_document(sample_docx, tmp_path / "assets")

    assert "Renewable Energy Systems" not in document.text
    assert "Table of Contents" not in document.text
    assert "Solar panels ...." not in document.text
    assert "Renewable Energy Systems" in document.front_matter_text
    assert "1. Introduction" in document.text


def test_front_matter_only_document_still_yields_text(tmp_path):
    """A one-page cover must not produce an empty deck."""
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "cover.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 120), "Quarterly Business Review", fontsize=28)
    doc.save(str(path))
    doc.close()

    document = de.extract_document(path, tmp_path / "assets")

    assert document.text.strip()


# ---------------------------------------------------------------------------
# Visuals
# ---------------------------------------------------------------------------


def test_pdf_embedded_photo_is_lifted_with_its_caption(sample_pdf, tmp_path):
    document = de.extract_document(sample_pdf, tmp_path / "assets")
    figures = document.load_figures()

    photo = [f for f in figures if f.kind == "photo"]
    assert len(photo) == 1
    assert Path(photo[0].path).exists()
    assert photo[0].width > 0 and photo[0].height > 0
    assert "Training loss curves" in photo[0].caption
    assert photo[0].section == "1. Introduction"


def test_pdf_table_becomes_rows_and_an_image(sample_pdf, tmp_path):
    document = de.extract_document(sample_pdf, tmp_path / "assets")
    figures = document.load_figures()

    table = [f for f in figures if f.kind == "table"]
    assert len(table) == 1
    assert Path(table[0].path).exists()
    assert "Accuracy comparison" in table[0].caption
    # The rows are also readable as text material.
    assert "LogReg" in document.text
    assert "0.93" in document.text


def test_pdf_vector_chart_is_rendered(vector_chart_pdf, tmp_path):
    document = de.extract_document(vector_chart_pdf, tmp_path / "assets")
    figures = document.load_figures()

    assert figures, "a vector-drawn chart must be picked up"
    chart = figures[0]
    assert chart.kind == "chart"
    assert Path(chart.path).exists()
    assert "Throughput" in chart.caption


def test_docx_image_and_table_are_lifted(sample_docx, tmp_path):
    document = de.extract_document(sample_docx, tmp_path / "assets")
    figures = document.load_figures()

    kinds = {f.kind for f in figures}
    assert "photo" in kinds
    assert "table" in kinds
    photo = next(f for f in figures if f.kind == "photo")
    # Word puts the caption after the picture; it must still be attached.
    assert "Solar panel array" in photo.caption
    assert photo.section == "1. Introduction"
    table = next(f for f in figures if f.kind == "table")
    assert "Panel comparison" in table.caption


def test_front_matter_artwork_is_not_used(sample_docx, tmp_path):
    document = de.extract_document(sample_docx, tmp_path / "assets")
    for figure in document.load_figures():
        assert figure.page >= 1
        assert "Table of Contents" not in figure.search_text


def test_figures_are_lazy(sample_pdf, tmp_path):
    """Reading text must not pay for image extraction."""
    document = de.extract_document(sample_pdf, tmp_path / "lazy")
    assert document.figures == []
    assert document.text.strip()

    document.load_figures()
    assert document.load_figures() is document.figures


# ---------------------------------------------------------------------------
# Structure helpers
# ---------------------------------------------------------------------------


def test_wrapped_lines_are_joined_not_split(sample_pdf, tmp_path):
    document = de.extract_document(sample_pdf, tmp_path / "assets")
    # The two printed lines are one sentence and must survive as one point.
    assert "design decisions that span data collection" in document.text


def test_numbered_heading_is_marked(sample_pdf, tmp_path):
    document = de.extract_document(sample_pdf, tmp_path / "assets")
    assert "## 1. Introduction" in document.text
    assert "## 2. Results" in document.text


def test_toc_entry_regex_detects_dot_leaders():
    assert de.TOC_ENTRY_RE.match("Introduction ............ 3")
    assert de.TOC_ENTRY_RE.match("2.1 Methods          45")
    assert not de.TOC_ENTRY_RE.match("Machine learning systems are complex and require care")


def test_prelim_headings_are_recognised():
    assert de._touches_front_matter("Table of Contents")
    assert de._touches_front_matter("Acknowledgements")
    assert de._touches_front_matter("List of Figures")
    assert not de._touches_front_matter("Model Training Pipeline")


def test_table_image_renderer_draws_rows(tmp_path):
    dest = tmp_path / "table.png"
    saved = de._render_table_image(
        [["Panel", "Output"], ["Poly", "340W"], ["Mono", "410W"]], "Table 1. Panel comparison", dest
    )
    assert saved is not None
    path, width, height = saved
    assert path.exists() and width > 0 and height > 0


def test_captions_are_marked_and_never_become_headings(sample_pdf, tmp_path):
    """Captions are subordinate material, so the structurer can demote them."""
    from app.services.text_structurer import structure_text

    document = de.extract_document(sample_pdf, tmp_path / "assets")
    caption_lines = [l for l in document.text.splitlines() if l.startswith(de.CAPTION_MARKER)]
    assert caption_lines, "captions must be emitted with the caption marker"
    assert not any(l.startswith(de.HEADER_MARKER) for l in caption_lines)

    data = structure_text(document.text)
    headings = [s["heading"] for s in data["sections"]]
    assert "1. Introduction" in headings and "2. Results" in headings
    for section in data["sections"]:
        assert not section["heading"].startswith(("Figure", "Table"))
    # A caption trails its section instead of leading it.
    intro = next(s for s in data["sections"] if s["heading"] == "1. Introduction")
    assert not intro["points"][0].startswith("Figure")
    assert any("Training loss curves" in p for p in intro["points"])


def test_section_survives_when_only_a_caption_follows_a_heading():
    from app.services.text_structurer import structure_text

    data = structure_text("## Overview\n" + de.CAPTION_MARKER + "Figure 1. Pipeline")
    assert [s["heading"] for s in data["sections"]] == ["Overview"]
    assert data["sections"][0]["points"] == ["Figure 1. Pipeline"]


def test_a_long_pdf_keeps_the_text_of_every_page(tmp_path):
    """A long report must not be truncated to its first few pages.

    Bounding the table scan (the expensive step) is fine; dropping pages is
    not, because the missing text is the material the slides are built from.
    """
    pymupdf = pytest.importorskip("pymupdf")

    path = tmp_path / "long.pdf"
    doc = pymupdf.open()
    for page_no in range(9):
        page = doc.new_page()
        page.insert_text((72, 80), f"{page_no + 1}. Chapter {page_no + 1}", fontsize=16)
        page.insert_text((72, 110), f"Unique sentence from page {page_no + 1}.", fontsize=11)
    doc.save(str(path))
    doc.close()

    data = de.extract_document(path, tmp_path / "assets")
    for page_no in range(9):
        assert f"Unique sentence from page {page_no + 1}." in data.text, (
            f"page {page_no + 1} was dropped from the extracted text"
        )
