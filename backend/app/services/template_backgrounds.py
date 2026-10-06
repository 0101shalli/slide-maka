"""Turn an uploaded 6-slide PPTX template into per-slide background images.

Mapping (as requested):
    slide 1 -> cover
    slide 2 -> outline
    slide 3 -> content (theory)
    slide 4 -> content (practical)
    slide 5 -> image
    slide 6 -> end

Pipeline: LibreOffice (headless) converts the PPTX to a PDF, then PyMuPDF
(fitz, already a dependency) renders each page to a PNG. If LibreOffice is
unavailable (e.g. outside Docker) the function returns {}. Results are cached
next to the template file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict

BACKGROUND_KEYS = ("cover", "outline", "content_theory", "content_practical", "image", "end")

_CACHE_SUBDIR = "_backgrounds"


def _render_pdf_to_png(pdf_path: Path, out_dir: Path) -> list[Path]:
    try:
        import fitz  # PyMuPDF
    except Exception:
        return []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return []
    rendered: list[Path] = []
    try:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
            out = out_dir / f"slide_{i + 1}.png"
            pix.save(str(out))
            rendered.append(out)
    finally:
        doc.close()
    return rendered


def extract_slide_backgrounds(pptx_path: Path, out_dir: Path) -> Dict[str, Path]:
    """Return {key: png_path} for the six mapped slides. Best effort."""
    if not pptx_path or not pptx_path.exists():
        return {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cached = {key: out_dir / f"{key}.png" for key in BACKGROUND_KEYS}
    if all(p.exists() for p in cached.values()):
        return dict(cached)

    work_dir = out_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = work_dir / "template.pdf"
    try:
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", str(work_dir), str(pptx_path)],
            check=True,
            timeout=180,
            capture_output=True,
        )
    except Exception:
        return {}

    pages = _render_pdf_to_png(pdf_path, work_dir)
    if len(pages) < 6:
        return {}

    mapping: Dict[str, Path] = {}
    for key, page in zip(BACKGROUND_KEYS, pages):
        dest = out_dir / f"{key}.png"
        try:
            if dest.exists():
                dest.unlink()
            page.replace(dest)
        except OSError:
            return {}
        mapping[key] = dest
    return mapping