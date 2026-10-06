"""Detailed reading of uploaded documents (PDF / DOCX) into text + visuals.

The pipeline is:

    upload -> _read_pdf / _read_docx -> ExtractedDocument
                                              |- .text              body text (deck material)
                                              |- .front_matter_text preliminary pages (read, not used)
                                              |- .load_figures()   diagrams / charts / photos / tables

Everything is read in document order with positions, so the reader can:

* classify pages as *preliminary* (cover, table of contents, list of figures,
  abstract, foreword, preface, acknowledgements, dedication, roman-numeral
  front matter) and keep their text out of ``.text``;
* detect headings from font size relative to the document's body size (not the
  per-page maximum), keeping wrapped lines and hyphenated words together so a
  sentence is not split into several points;
* pull tables out of the page layout and turn them into bullets plus a rendered
  table image;
* lift every raster image, cluster vector drawings into a rendered figure, and
  attach the nearest "Figure 2. ..." caption and enclosing section heading to
  it, so the deck can decide which slide each visual belongs on.

PyMuPDF is optional: without it the PDF still yields text via pdfminer.six, just
without visuals.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# A line that looks like a heading. The text structurer treats "## " as a
# strong header, so the reader emits it for every detected heading.
HEADER_MARKER = "## "

# Marks a figure/table caption. The text structurer demotes these to trailing
# bullets so a caption never becomes a slide heading or a section's first point.
CAPTION_MARKER = "! "

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# A line is a heading when its font is this much larger than the body text.
HEADER_SIZE_RATIO = 1.18
# ...or when it is bold and at least this large.
HEADER_BOLD_RATIO = 1.02
HEADER_MAX_CHARS = 120

# A vector cluster must be at least this fraction of the page to count as a
# figure (charts and diagrams are big; rules, underlines and boxes are not).
MIN_VECTOR_AREA_RATIO = 0.012
MIN_VECTOR_ITEMS = 3
MAX_VECTOR_FIGURES_PER_PAGE = 3
# Vector rects closer than this (points) are merged into the same cluster.
CLUSTER_GAP = 16.0
# Charts routinely fill the page; only near-full-page art (scans, wallpapers) is
# rejected, because a 16:9 slide would have to crop it.
MAX_FIGURE_AREA_RATIO = 0.86

# Raster images below these pixel dimensions are logos, bullets or rules.
MIN_RASTER_PX = (140, 100)
MIN_RASTER_AREA_RATIO = 0.008

# Caption proximity (points) above / below a figure.
CAPTION_BAND = 46.0
NEAR_TEXT_BAND = 30.0

# Hard caps so a pathological document cannot stall a request.
MAX_FIGURES = 60
MAX_VECTOR_ITEMS_PER_PAGE = 4000
MAX_PAGES_FOR_TABLE_SCAN = 400
# Diagrams and tables are more useful as PNG; large photos as JPEG.
PNG_MAX_BYTES = 2_500_000

CAPTION_RE = re.compile(
    r"^\s*(figure|fig\.?|abbildung|tabelle|table|chart|diagram|exhibit|graph|"
    r"scheme|plate|image|listing|schaubild|diagrama|figura)\s*"
    r"[\d]+(?:[.\-][\d]+)*\s*[.:)\-–—]?\s+",
    re.IGNORECASE,
)

BULLET_LINE_RE = re.compile(r"^\s*(?:[-*•‣·◦▪●■□➢►–—]|[a-z][.)]|\d+[.)])\s+")
# "1.", "2.3", "Chapter 4", "Section 2.1:" -> a numbered heading.
NUMBERED_HEADING_RE = re.compile(r"^\s*(?:chapter|section|part|module|unit|annex)\s+[\dIVXivx]+", re.IGNORECASE)
NUMBERED_ITEM_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})*)[.)]?\s+(\S.*)$")
ROMAN_RE = re.compile(r"^\s*[ivxlcdm]{1,7}\s*$", re.IGNORECASE)

# Headings that mark a preliminary page.
PRELIM_HEADINGS = (
    "table of contents", "contents", "index", "índice", "sommaire", "inhaltsverzeichnis",
    "indice", "indice general", "sumário", "sumario", "inhoud", "содержание", "目次",
    "list of figures", "list of tables", "list of illustrations", "figure list",
    "abstract", "summary", "resumo", "resumé", "resume", "zusammenfassung", "riassunto",
    "foreword", "preface", "preliminary", "introduction to", "acknowledgement",
    "acknowledgment", "acknowledgements", "acknowledgments", "agradecimientos",
    "dedication", "about the author", "about the authors", "contributors",
    "revision history", "document history", "version history", "change log",
    "changelog", "glossary of terms", "copyright", "disclaimer", "legal notice",
    "imprint", "colophon", "how to use this document", "reading guide",
    "note to the reader", "executive summary", "course outline", "seminar outline",
)

# A table-of-contents entry: "Introduction ......... 12" or "2.1 Methods  45".
TOC_ENTRY_RE = re.compile(r"^\s*.+?(?:\.{2,}|\s{2,}|\s·\s{2,}).*?(?:\d{1,4})\s*$")

PPTX_SAFE_EXTS = {"jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "emf", "wmf"}

_PARA_END = tuple(".!?:;\u2026\"')]}")

# The PyMuPDF module object, captured at import time (new wheels expose
# "pymupdf", older ones only "fitz"). ``None`` when neither is installed.
_FITZ: Any = None
try:  # pragma: no cover - depends on the environment
    import pymupdf as _FITZ  # type: ignore
except Exception:  # pragma: no cover
    try:
        import fitz as _FITZ  # type: ignore
    except Exception:
        _FITZ = None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class Figure:
    """One visual lifted out of the document, ready to be placed on a slide."""

    path: str
    caption: str = ""
    kind: str = "figure"  # photo | diagram | chart | table | figure
    page: int = 0
    section: str = ""
    width: int = 0
    height: int = 0

    @property
    def search_text(self) -> str:
        return " ".join(part for part in (self.section, self.caption) if part).strip()

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "caption": self.caption,
            "kind": self.kind,
            "page": self.page,
            "section": self.section,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class ExtractedDocument:
    """Everything the reader learned about an uploaded document."""

    text: str = ""
    front_matter_text: str = ""
    page_count: int = 0
    figures: List[Figure] = field(default_factory=list)
    title_hint: str = ""
    _figure_loader: Optional[Callable[[], List[Figure]]] = None

    def load_figures(self) -> List[Figure]:
        """Materialize (once) the visuals; reading text never pays for them."""
        if not self.figures and self._figure_loader is not None:
            loader, self._figure_loader = self._figure_loader, None
            try:
                self.figures = loader()
            except Exception:
                logger.exception("figure extraction failed")
                self.figures = []
        return self.figures


def _norm_space(text: str) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", (text or "").replace("\u00ad", "")).strip()


def _point_in_rect(point: Tuple[float, float], rect: Sequence[float]) -> bool:
    x, y = point
    x0, y0, x1, y1 = rect
    return x0 <= x <= x1 and y0 <= y <= y1


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _weighted_median_size(samples: Sequence[Tuple[float, int]]) -> float:
    """Body font size: the size covering the most characters, not the largest."""
    if not samples:
        return 11.0
    buckets: dict[float, int] = {}
    for size, chars in samples:
        if size <= 0:
            continue
        key = round(size * 2) / 2
        buckets[key] = buckets.get(key, 0) + chars
    return max(buckets.items(), key=lambda kv: (kv[1], -kv[0]))[0]


def _is_numbered_heading(text: str) -> bool:
    if NUMBERED_HEADING_RE.match(text):
        return True
    match = NUMBERED_ITEM_RE.match(text)
    if not match:
        return False
    rest = match.group(2)
    # "2.1 Design goals" is a heading; "2. The system was deployed in 2019" is not.
    return len(rest.split()) <= 9 and not rest.endswith(".")


def _touches_front_matter(text: str) -> bool:
    lowered = _norm_space(text).lower().rstrip(".:")
    if not lowered:
        return False
    return any(
        lowered == phrase or lowered.startswith(phrase + " ") or lowered.endswith(phrase)
        for phrase in PRELIM_HEADINGS
    )


def _toc_ratio(lines: Sequence[str]) -> float:
    """Fraction of lines that look like table-of-contents entries."""
    if not lines:
        return 0.0
    hits = 0
    for line in lines:
        if TOC_ENTRY_RE.match(line) or ROMAN_RE.match(line.strip()):
            hits += 1
    return hits / len(lines)


def _page_number_label(page) -> str:
    """The page label in the bottom margin, if the document prints one."""
    try:
        height = float(page.rect.height)
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = _norm_space("".join(s.get("text", "") for s in line.get("spans", [])))
                if not text or len(text) > 8:
                    continue
                y1 = float(line.get("bbox", (0, 0, 0, 0))[3])
                if y1 > height * 0.9 and (text.isdigit() or ROMAN_RE.match(text)):
                    return text
    except Exception:
        pass
    return ""


def _rect_area(rect) -> float:
    try:
        return max(0.0, float(rect[2] - rect[0])) * max(0.0, float(rect[3] - rect[1]))
    except Exception:
        return 0.0


def _cluster_rects(rects: Sequence[Sequence[float]], gap: float = CLUSTER_GAP) -> List[List[float]]:
    """Group rects that sit within ``gap`` points of each other.

    A single merge pass is not enough: a bar chart's bars are wider than the gap
    but the cluster grows as each is absorbed, so the passes are repeated until
    the grouping stops changing. This is what turns 6 loose marks into one
    "this is a figure" region.
    """
    clusters: List[List[float]] = [[float(v) for v in rect] for rect in rects]
    for _pass in range(8):
        merged_any = False
        result: List[List[float]] = []
        for cluster in clusters:
            target = None
            for other in result:
                if (
                    cluster[0] <= other[2] + gap
                    and other[0] - gap <= cluster[2]
                    and cluster[1] <= other[3] + gap
                    and other[1] - gap <= cluster[3]
                ):
                    target = other
                    break
            if target is None:
                result.append(list(cluster))
                continue
            target[0] = min(target[0], cluster[0])
            target[1] = min(target[1], cluster[1])
            target[2] = max(target[2], cluster[2])
            target[3] = max(target[3], cluster[3])
            merged_any = True
        clusters = result
        if not merged_any:
            break
    return clusters


def _overlaps(a: Sequence[float], b: Sequence[float], tolerance: float = 0.0) -> bool:
    return not (
        a[2] + tolerance < b[0]
        or b[2] + tolerance < a[0]
        or a[3] + tolerance < b[1]
        or b[3] + tolerance < a[1]
    )


def _grow_cluster(
    cluster: Sequence[float],
    lines: Sequence[Tuple[str, float, float]],
    band: float = 34.0,
) -> List[float]:
    """Widen a vector cluster to swallow the text labels drawn around it.

    Charts put their axis labels and legend beside the marks; clipping to the
    drawing rects alone would cut those labels off. Only labels horizontally
    close to the cluster (or inside it) are absorbed, and a caption is never
    swallowed.
    """
    x0, y0, x1, y1 = cluster
    for text, ly0, ly1 in lines:
        if ly1 < y0 - band or ly0 > y1 + band:
            continue
        if CAPTION_RE.match(text):
            continue
        # A label counts when it is within the horizontal span of the cluster
        # or just beside it.
        if max(ly0, x0) > min(ly1, x1) and not (x0 - band <= ly0 and ly1 <= x1 + band):
            continue
        if ly0 > x0 - band and ly1 < x1 + band:
            x0 = min(x0, ly0)
            x1 = max(x1, ly1)
    return [x0, y0, x1, y1]


def _pad(rect: Sequence[float], amount: float, page_rect) -> List[float]:
    x0 = max(float(page_rect.x0), rect[0] - amount)
    y0 = max(float(page_rect.y0), rect[1] - amount)
    x1 = min(float(page_rect.x1), rect[2] + amount)
    y1 = min(float(page_rect.y1), rect[3] + amount)
    return [x0, y0, x1, y1]


# ---------------------------------------------------------------------------
# Image persistence
# ---------------------------------------------------------------------------


def _save_image(data: bytes, ext: str, dest: Path) -> Optional[Tuple[Path, int, int]]:
    """Normalise image bytes to something PowerPoint can embed, and save them."""
    try:
        from PIL import Image
    except Exception:
        return None

    ext = (ext or "").lower().lstrip(".")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None

    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")
    width, height = img.size
    if width < 8 or height < 8:
        return None

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Charts and diagrams stay lossless; a big photo would bloat the deck.
    try:
        buffer = io.BytesIO()
        if width * height > 1_500_000 and img.mode == "RGB":
            img.save(buffer, format="JPEG", quality=88, optimize=True)
            out_ext = "jpg"
        else:
            img.save(buffer, format="PNG", optimize=True)
            out_ext = "png"
        payload = buffer.getvalue()
        if len(payload) > 8_000_000:
            return None
        if out_ext == "png" and len(payload) > PNG_MAX_BYTES and img.mode == "RGB":
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=88, optimize=True)
            payload, out_ext = buffer.getvalue(), "jpg"
        final = dest.with_suffix("." + out_ext)
        final.write_bytes(payload)
        return final, width, height
    except Exception:
        logger.debug("could not persist figure", exc_info=True)
        return None


def _render_table_image(rows: Sequence[Sequence[str]], caption: str, dest: Path) -> Optional[Tuple[Path, int, int]]:
    """Draw a table as a clean image so it can be shown on an image slide."""
    try:
        from PIL import Image, ImageDraw

        from .image_fetcher import _load_font, _wrap_text
    except Exception:
        return None

    rows = [row for row in rows if any(str(cell).strip() for cell in row)]
    if not rows:
        return None
    max_rows, max_cols = 8, 5
    rows = rows[:max_rows]
    rows = [list(row)[:max_cols] for row in rows]
    cols = max(len(row) for row in rows)

    title_font = _load_font(30, bold=True)
    head_font = _load_font(23, bold=True)
    cell_font = _load_font(22, bold=False)

    width = 1280
    pad = 28
    col_w = (width - pad * 2) // max(cols, 1)
    line_h = 46
    title_h = 52 if caption else 0
    height = pad * 2 + title_h + line_h * len(rows)

    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    y = pad
    if caption:
        for line in _wrap_text(caption, title_font, width - pad * 2)[:2]:
            draw.text((pad, y), line, font=title_font, fill=(23, 42, 66))
            y += 34
        y += 8

    for row_index, row in enumerate(rows):
        header = row_index == 0
        fill = (233, 240, 248) if header else (255, 255, 255) if row_index % 2 else (246, 248, 251)
        draw.rectangle([pad, y, pad + col_w * cols, y + line_h], fill=fill, outline=(198, 210, 224))
        for col in range(cols):
            cell = str(row[col]).strip() if col < len(row) else ""
            if not cell:
                continue
            font = head_font if header else cell_font
            for line in _wrap_text(cell, font, col_w - 16)[:2]:
                if y + 14 >= height:
                    break
                draw.text((pad + col * col_w + 10, y + 10), line, font=font,
                          fill=(23, 42, 66) if header else (48, 60, 75))
            y += 0  # rows are drawn at a fixed height
        draw.line([pad, y + line_h, pad + col_w * cols, y + line_h], fill=(198, 210, 224))
        y += line_h

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        dest.write_bytes(buffer.getvalue())
    except Exception:
        return None
    return dest, width, height


# ---------------------------------------------------------------------------
# PDF reading
# ---------------------------------------------------------------------------


@dataclass
class _PageText:
    lines: List[str] = field(default_factory=list)      # document-order text lines
    headers: List[Tuple[str, float]] = field(default_factory=list)  # (text, y0)
    word_count: int = 0


@dataclass
class _PageVisual:
    rect: List[float]
    data: bytes
    ext: str = "png"
    kind: str = "figure"


def _line_is_header(text: str, line: dict, body_size: float) -> bool:
    spans = [s for s in line.get("spans", []) if _norm_space(s.get("text", ""))]
    if not spans:
        return False
    if len(text) > HEADER_MAX_CHARS:
        return False
    size = max(float(s.get("size", body_size) or body_size) for s in spans)
    bold = any(int(s.get("flags", 0) or 0) & 16 for s in spans)
    return size >= body_size * HEADER_SIZE_RATIO or (
        bold and size >= body_size * HEADER_BOLD_RATIO and size > body_size * 0.98
    )


def _raw_line_info(
    block_lines: Sequence[dict], body_size: float
) -> List[Tuple[str, float, float, bool]]:
    """(text, y0, y1, is_header) per physical line, for geometry-based matching."""
    out: List[Tuple[str, float, float, bool]] = []
    for line in block_lines:
        text = _norm_space("".join(s.get("text", "") for s in line.get("spans", [])))
        if not text:
            continue
        bbox = line.get("bbox") or (0, 0, 0, 0)
        out.append((text, float(bbox[1]), float(bbox[3]), _line_is_header(text, line, body_size)))
    return out


def _assemble_lines(block_lines: Sequence[dict], body_size: float) -> List[str]:
    """Turn one text block into lines, joining wrapped/hyphenated continuations."""
    out: List[str] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer:
            out.append(buffer)
            buffer = ""

    for text, _y0, _y1, is_header in _raw_line_info(block_lines, body_size):
        is_bullet = bool(BULLET_LINE_RE.match(text))

        if is_header or _is_numbered_heading(text):
            flush()
            out.append(f"{HEADER_MARKER}{text}")
            continue
        if CAPTION_RE.match(text):
            # A caption is kept as material but never as a heading, and never as
            # a leading bullet: it is carried by the figure itself, so repeating
            # it as the first bullet of the section it sits in is noise. It is
            # still emitted when the section has no other text to show.
            flush()
            out.append(CAPTION_MARKER + text)
            continue
        if is_bullet:
            flush()
            out.append(f"- {BULLET_LINE_RE.sub('', text).strip()}")
            continue

        if buffer:
            # Join a wrapped line back onto the previous one.
            if buffer.endswith("-") and not buffer.endswith(" -"):
                buffer = buffer[:-1] + text
            elif buffer[-1] not in _PARA_END and text[:1].islower():
                buffer = f"{buffer} {text}"
            else:
                flush()
                buffer = text
        else:
            buffer = text
    flush()
    return out


def _opens_a_numbered_body(page_text: _PageText) -> bool:
    """True when a sparse first page is really the start of the body.

    A title page is short and unnumbered, but so is the first page of a short
    report or an article. A page that opens with a numbered heading is
    content, and treating it as a cover silently deletes the opening lines of
    the document the slides are built from.
    """
    headings = [l[len(HEADER_MARKER):] for l in page_text.lines if l.startswith(HEADER_MARKER)]
    return any(_is_numbered_heading(h) for h in headings)


def _page_is_preliminary(page_text: _PageText, page_number: str, index: int, total: int) -> bool:
    lines = [l for l in page_text.lines if not l.startswith(HEADER_MARKER)]
    headings = [l[len(HEADER_MARKER):] for l in page_text.lines if l.startswith(HEADER_MARKER)]
    early = index < max(2, int(total * 0.4))

    if any(_touches_front_matter(h) for h in headings):
        # "Abstract" only counts up front; a mid-document chapter with that name
        # is real content.
        if early or _toc_ratio(lines) > 0.3:
            return True
    if _toc_ratio(lines) >= 0.4 and len(lines) >= 3:
        return True
    if early and any(_touches_front_matter(line) for line in lines[:6]):
        return True
    if index == 0 and page_text.word_count < 90 and not _opens_a_numbered_body(page_text):
        return True
    if early and page_number and ROMAN_RE.match(page_number.strip()):
        return True
    return False


def _nearest_caption(lines: Sequence[Tuple[str, float, float]], rect: Sequence[float]) -> str:
    """Caption for a figure: the nearest 'Figure n.' line above or below it."""
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) / 2
    best: Optional[Tuple[float, str]] = None
    for text, ly0, ly1 in lines:
        vertical = 0.0 if y0 - CAPTION_BAND <= ly0 and ly1 <= y1 + CAPTION_BAND else None
        if vertical is None:
            if ly1 <= y0:
                distance = y0 - ly1
            elif ly0 >= y1:
                distance = ly0 - y1
            else:
                distance = 0.0
            if distance > CAPTION_BAND:
                continue
        else:
            distance = 0.0
        if not CAPTION_RE.match(text):
            continue
        key = distance
        if best is None or key < best[0]:
            best = (key, text)
    if best:
        return best[1]

    # No explicit caption: fall back to the closest short line above the figure.
    above: Optional[Tuple[float, str]] = None
    for text, ly0, ly1 in lines:
        if not (y0 - NEAR_TEXT_BAND - 12 <= ly1 <= y0):
            continue
        if len(text) > HEADER_MAX_CHARS or BULLET_LINE_RE.match(text):
            continue
        distance = y0 - ly1
        if above is None or distance < above[0]:
            above = (distance, text)
    return above[1] if above else ""


def _section_for(page_text: _PageText, top: float, running: str) -> str:
    """Nearest heading above the figure, else the last heading seen earlier."""
    candidates = [(h, y) for h, y in page_text.headers if y <= top + 6]
    if candidates:
        return max(candidates, key=lambda item: item[1])[0]
    return running


def _page_tables(page, drawings: Sequence[dict], scan: bool = True) -> List[Any]:
    """Tables found by the page-layout analyser (skipped on heavy vector pages).

    ``scan`` is False for pages past MAX_PAGES_FOR_TABLE_SCAN so that a very
    long document still has all of its *text* read while the expensive layout
    analysis stays bounded.
    """
    if not scan or not drawings or len(drawings) > MAX_VECTOR_ITEMS_PER_PAGE:
        return []
    try:
        found = page.find_tables()
    except Exception:
        return []
    tables = []
    for table in getattr(found, "tables", []) or []:
        try:
            if table.row_count >= 2 and table.col_count >= 2:
                tables.append(table)
        except Exception:
            continue
    return tables


def _read_pdf(path: Path, assets_dir: Path) -> Optional[ExtractedDocument]:
    if _FITZ is None:
        return None

    try:
        doc = _FITZ.open(str(path))
    except Exception:
        logger.warning("could not open PDF %s", path, exc_info=True)
        return None

    try:
        if doc.needs_pass:
            return None
        total = doc.page_count
        if total == 0:
            return None
        # Table detection is the only expensive step, so it is bounded per
        # page (see _page_tables' `scan`) rather than by restricting the
        # document: doc.select() used to drop every page after the fifth,
        # silently losing most of a long report.

        size_samples: List[Tuple[float, int]] = []
        for index in range(min(total, 12)):
            try:
                for block in doc[index].get_text("dict").get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            chars = len((span.get("text") or "").strip())
                            if chars:
                                size_samples.append((float(span.get("size", 0) or 0), chars))
            except Exception:
                continue
        body_size = _weighted_median_size(size_samples)

        # ---- pass 1: text + geometry -----------------------------------------
        pages: List[dict] = []
        for index in range(doc.page_count):
            page = doc[index]
            try:
                blocks = page.get_text("dict").get("blocks", [])
            except Exception:
                blocks = []
            try:
                drawings = page.get_drawings()
            except Exception:
                drawings = []
            tables = _page_tables(page, drawings, scan=index < MAX_PAGES_FOR_TABLE_SCAN)

            page_text = _PageText()
            page_lines: List[Tuple[str, float, float]] = []
            emitted: set[int] = set()
            for block in blocks:
                bbox = [float(v) for v in block.get("bbox", (0, 0, 0, 0))]
                center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
                table_index = next(
                    (
                        number
                        for number, table in enumerate(tables)
                        if _point_in_rect(center, table.bbox)
                    ),
                    None,
                )
                if block.get("type") != 0:
                    continue
                raw = _raw_line_info(block.get("lines", []), body_size)
                for text, y0, y1, _is_header in raw:
                    page_lines.append((text, y0, y1))
                if table_index is not None:
                    # Table cells are re-emitted as whole rows, not loose words.
                    if table_index not in emitted:
                        emitted.add(table_index)
                        for row in tables[table_index].extract():
                            cells = [_norm_space(str(cell)) for cell in row]
                            cells = [c for c in cells if c]
                            if not cells:
                                continue
                            page_text.word_count += sum(len(c.split()) for c in cells)
                            page_text.lines.append("- " + " — ".join(cells))
                    continue
                page_text.word_count += sum(len(t.split()) for t, _a, _b, _c in raw)
                for text, y0, _y1, is_header in raw:
                    if is_header:
                        page_text.headers.append((text, y0))
                page_text.lines.extend(_assemble_lines(block.get("lines", []), body_size))
            pages.append({
                "page": page,
                "text": page_text,
                "lines": page_lines,
                "page_number": _page_number_label(page),
                "tables": tables,
                "prelim": False,
            })

        for index, entry in enumerate(pages):
            entry["prelim"] = _page_is_preliminary(
                entry["text"], entry["page_number"], index, len(pages)
            )
        # A short document can trip the cover heuristic and classify every page
        # as preliminary; the content must never end up empty because of that.
        if not any(not entry["prelim"] for entry in pages):
            for entry in pages:
                entry["prelim"] = False

        body_lines: List[str] = []
        prelim_lines: List[str] = []
        title_hint = ""
        for index, entry in enumerate(pages):
            page_text: _PageText = entry["text"]
            if entry["prelim"]:
                prelim_lines.extend(page_text.lines)
                if index == 0:
                    for line in page_text.lines:
                        stripped = line[len(HEADER_MARKER):] if line.startswith(HEADER_MARKER) else line
                        if 2 <= len(stripped.split()) <= 14 and not BULLET_LINE_RE.match(stripped):
                            title_hint = stripped
                            break
            else:
                body_lines.extend(page_text.lines)
                if not title_hint and page_text.headers:
                    title_hint = page_text.headers[0][0]

        prelim_flags = [bool(entry["prelim"]) for entry in pages]
        document = ExtractedDocument(
            text="\n".join(l for l in body_lines if l.strip()),
            front_matter_text="\n".join(l for l in prelim_lines if l.strip()),
            page_count=total,
            title_hint=title_hint,
        )
        entries = list(enumerate(pages))

        def _load() -> List[Figure]:
            # The document is kept open until the visuals are taken, because
            # rendering vector figures needs the page it came from.
            try:
                return _pdf_figures(entries, assets_dir, prelim_flags)
            finally:
                try:
                    doc.close()
                except Exception:
                    pass

        document._figure_loader = _load
        return document
    except Exception:
        try:
            doc.close()
        except Exception:
            pass
        raise


def _pdf_figures(
    entries: Sequence[Tuple[int, dict]],
    assets_dir: Path,
    prelim_flags: Sequence[bool],
) -> List[Figure]:
    """Pass 2: lift rasters, render vector figures and tables, attach captions."""
    figures: List[Figure] = []
    seen_hashes: dict[str, int] = {}
    counter = 0
    running_heading = ""

    for index, entry in entries:
        if len(figures) >= MAX_FIGURES:
            break
        page = entry["page"]
        page_text: _PageText = entry["text"]
        page_rect = page.rect
        page_area = max(1.0, _rect_area([page_rect.x0, page_rect.y0, page_rect.x1, page_rect.y1]))
        if prelim_flags[index]:
            continue  # preliminary pages are read, never shown
        if page_text.headers:
            running_heading = page_text.headers[0][0]

        candidates: List[_PageVisual] = []
        table_boxes: List[List[float]] = []

        # ---- tables --------------------------------------------------------
        try:
            drawings = page.get_drawings()
        except Exception:
            drawings = []
        tables = _page_tables(page, drawings, scan=index < MAX_PAGES_FOR_TABLE_SCAN)
        for table in tables:
            rows = [list(row) for row in table.extract()]
            if len(rows) < 2:
                continue
            box = [float(v) for v in table.bbox]
            table_boxes.append(box)
            caption = _nearest_caption(entry["lines"], box)
            dest = assets_dir / f"table_{index + 1:03d}_{len(figures):02d}.png"
            saved = _render_table_image(rows, caption, dest)
            if saved:
                path, width, height = saved
                figures.append(Figure(
                    path=str(path), caption=caption, kind="table", page=index + 1,
                    section=_section_for(page_text, box[1], running_heading),
                    width=width, height=height,
                ))

        # ---- raster images --------------------------------------------------
        try:
            blocks = page.get_text("dict").get("blocks", [])
        except Exception:
            blocks = []
        for block in blocks:
            if block.get("type") != 1:
                continue
            data = block.get("image")
            if not data:
                continue
            try:
                width, height = int(block.get("width") or 0), int(block.get("height") or 0)
            except Exception:
                width = height = 0
            rect = [float(v) for v in block.get("bbox", (0, 0, 0, 0))]
            area_ratio = _rect_area(rect) / page_area
            if width and (width < MIN_RASTER_PX[0] or height < MIN_RASTER_PX[1]):
                continue
            if area_ratio < MIN_RASTER_AREA_RATIO or area_ratio > MAX_FIGURE_AREA_RATIO:
                continue
            if any(_overlaps(rect, box, 4.0) for box in table_boxes):
                continue
            digest = _sha1(data)
            seen_hashes[digest] = seen_hashes.get(digest, 0) + 1
            if seen_hashes[digest] > 2:
                continue  # running header/footer logo
            ext = str(block.get("ext") or "png")
            if ext == "jpx":
                ext = "jp2"
            candidates.append(_PageVisual(rect=rect, data=data, ext=ext, kind="photo"))

        # ---- vector figures (charts, diagrams, schematics) ------------------
        if drawings and len(drawings) <= MAX_VECTOR_ITEMS_PER_PAGE:
            rects: List[List[float]] = []
            item_count: List[int] = []
            for drawing in drawings:
                rect = drawing.get("rect")
                if rect is None:
                    continue
                items = drawing.get("items", [])
                box = [float(v) for v in rect]
                # Axis lines and connectors have no area but are exactly what
                # ties a chart together, so they are kept when they are long.
                thin = _rect_area(box) < 2.0
                if thin and max(box[2] - box[0], box[3] - box[1]) < 8.0:
                    continue
                rects.append(box)
                item_count.append(len(items))
            for cluster in _cluster_rects(rects):
                # Text labels are part of a chart: extend the clip over the
                # lines that sit close to it so axis labels are not cropped.
                cluster = _grow_cluster(cluster, entry["lines"])
                area_ratio = _rect_area(cluster) / page_area
                if area_ratio < MIN_VECTOR_AREA_RATIO or area_ratio > MAX_FIGURE_AREA_RATIO:
                    continue
                if any(_overlaps(cluster, box, 2.0) for box in table_boxes):
                    continue
                if any(_overlaps(cluster, c.rect, 6.0) for c in candidates):
                    continue
                items = sum(
                    item_count[order]
                    for order, box in enumerate(rects)
                    if _overlaps(cluster, box, 2.0)
                )
                if items < MIN_VECTOR_ITEMS:
                    continue
                if len(candidates) >= MAX_VECTOR_FIGURES_PER_PAGE:
                    break
                clip = _pad(cluster, 6.0, page_rect)
                try:
                    pixmap = page.get_pixmap(clip=_FITZ.Rect(*clip), dpi=200)
                    data = pixmap.tobytes("png")
                except Exception:
                    continue
                candidates.append(_PageVisual(rect=clip, data=data, ext="png", kind="chart"))

        # Reading order: a figure lower on the page comes later.
        for visual in sorted(candidates, key=lambda c: c.rect[1]):
            if len(figures) >= MAX_FIGURES:
                break
            caption = _nearest_caption(entry["lines"], visual.rect)
            section = _section_for(page_text, visual.rect[1], running_heading)
            dest = assets_dir / f"fig_{index + 1:03d}_{counter:02d}.{visual.ext}"
            saved = _save_image(visual.data, visual.ext, dest)
            counter += 1
            if not saved:
                continue
            path, width, height = saved
            figures.append(Figure(
                path=str(path), caption=caption, kind=visual.kind, page=index + 1,
                section=section, width=width, height=height,
            ))
    return figures



# ---------------------------------------------------------------------------
# DOCX reading
# ---------------------------------------------------------------------------

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_V_NS = "{urn:schemas-microsoft-com:vml}"

DOCX_HEADING_STYLES = {
    "Title", "Subtitle", "Heading 1", "Heading 2", "Heading 3", "Heading 4",
    "Heading 5", "Heading 6", "Heading 7", "Heading 8", "Heading 9",
}
DOCX_LIST_STYLES = {
    "List Bullet", "List Bullet 2", "List Bullet 3", "List Number",
    "List Number 2", "List Number 3", "List Paragraph",
}
_TOC_STYLE_RE = re.compile(r"^toc\s*\d*$", re.IGNORECASE)


def _docx_style_name(paragraph) -> str:
    try:
        return (paragraph.style.name or "") if paragraph.style is not None else ""
    except Exception:
        return ""


def _docx_image_blobs(element, part) -> List[Tuple[bytes, str]]:
    """Every image embedded in a paragraph, in document order."""
    out: List[Tuple[bytes, str]] = []
    rids: List[str] = []
    for blip in element.iter(f"{_A_NS}blip"):
        rid = blip.get(f"{_R_NS}embed") or blip.get(f"{_R_NS}link")
        if rid:
            rids.append(rid)
    for image_data in element.iter(f"{_V_NS}imagedata"):
        rid = image_data.get(f"{_R_NS}id")
        if rid:
            rids.append(rid)
    for rid in rids:
        try:
            related = part.related_parts[rid]
        except Exception:
            continue
        blob = getattr(related, "blob", None)
        if not blob:
            continue
        ext = "png"
        content_type = str(getattr(related, "content_type", "") or "")
        if "jpeg" in content_type or "jpg" in content_type:
            ext = "jpg"
        elif "gif" in content_type:
            ext = "gif"
        elif "bmp" in content_type:
            ext = "bmp"
        elif "tiff" in content_type:
            ext = "tiff"
        elif "x-emf" in content_type:
            ext = "emf"
        elif "x-wmf" in content_type:
            ext = "wmf"
        out.append((blob, ext))
    return out


def _redraw_table_with_caption(assets_dir: Path, figure: Figure, caption: str) -> None:
    """Redraw a pending table image once its trailing caption is known."""
    src = Path(figure.path)
    if not src.exists():
        return
    try:
        from PIL import Image

        with Image.open(src) as existing:
            base = existing.convert("RGB")
    except Exception:
        return
    # Draw the caption above the table, matching _render_table_image's layout.
    try:
        from .image_fetcher import _load_font, _wrap_text

        title_font = _load_font(30, bold=True)
        lines = _wrap_text(caption, title_font, base.width - 56)[:2]
        extra = len(lines) * 34 + 8
        canvas = Image.new("RGB", (base.width, base.height + extra), (255, 255, 255))
        canvas.paste(base, (0, extra))
        from PIL import ImageDraw

        draw = ImageDraw.Draw(canvas)
        y = 28
        for line in lines:
            draw.text((28, y), line, font=title_font, fill=(23, 42, 66))
            y += 34
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG", optimize=True)
        src.write_bytes(buffer.getvalue())
        figure.height = canvas.height
    except Exception:
        logger.debug("could not redraw table with caption", exc_info=True)


def _read_docx(path: Path, assets_dir: Path) -> Optional[ExtractedDocument]:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except Exception:
        return None

    try:
        doc = Document(str(path))
    except Exception:
        logger.warning("could not open DOCX %s", path, exc_info=True)
        return None

    part = doc.part
    body_lines: List[str] = []
    prelim_lines: List[str] = []
    figures: List[Figure] = []
    running_heading = ""
    in_front_matter = True
    counter = 0
    page_estimate = 1
    pending_figure: Optional[int] = None  # image awaiting its trailing caption

    def _plain(line: str) -> str:
        return line[len(HEADER_MARKER):] if line.startswith(HEADER_MARKER) else line

    claimed_captions: set[str] = set()

    def _caption_near(pool: Sequence[str], limit: int = 4) -> str:
        """The nearest caption line before a visual, if no other visual owns it."""
        for candidate in reversed(list(pool)[:limit] if limit else list(pool)):
            plain = _plain(candidate)
            if CAPTION_RE.match(plain) and plain != running_heading and plain not in claimed_captions:
                return plain
        return ""

    for child in doc.element.body.iterchildren():
        tag = child.tag
        if tag == f"{_W_NS}p":
            paragraph = Paragraph(child, doc._body)
            style = _docx_style_name(paragraph)
            text = _norm_space(paragraph.text)
            if len(text) > 2000:
                page_estimate += len(text) // 2000

            # A generated table of contents is a field: its entries are front
            # matter by definition, and Word's "TOC n" styles say so.
            if _TOC_STYLE_RE.match(style) or child.find(f".//{_W_NS}fldChar") is not None:
                if text:
                    prelim_lines.append(text)
                continue

            if text:
                is_heading = style in DOCX_HEADING_STYLES or _is_numbered_heading(text)
                is_caption = "caption" in style.lower() or bool(CAPTION_RE.match(text))
                is_toc_entry = bool(TOC_ENTRY_RE.match(text))
                labelled_prelim = _touches_front_matter(text)
                is_title = style in {"Title", "Subtitle"}

                # A TOC entry or a front-matter label never ends the front
                # matter, however it is styled. "Contents" written as Heading 1
                # is a table of contents; "Renewable Energy Systems" written as
                # Title is the cover.
                if in_front_matter and is_heading and not labelled_prelim and not is_toc_entry:
                    if not is_title:
                        in_front_matter = False
                prelim_now = in_front_matter

                if is_caption:
                    produced = text
                elif is_heading:
                    produced = f"{HEADER_MARKER}{text}"
                elif style in DOCX_LIST_STYLES or BULLET_LINE_RE.match(text):
                    produced = f"- {BULLET_LINE_RE.sub('', text).strip()}"
                else:
                    produced = text
                (prelim_lines if prelim_now else body_lines).append(produced)
                if is_heading and not prelim_now:
                    running_heading = text

                # Word puts a caption *after* the picture, so an image has no
                # caption yet at this point; keep it pending and let the next
                # caption claim it.
                if is_caption and pending_figure is not None and not figures[pending_figure].caption:
                    claimed = figures[pending_figure]
                    claimed.caption = text
                    claimed_captions.add(text)
                    pending_figure = None
                    if claimed.kind == "table":
                        _redraw_table_with_caption(assets_dir, claimed, text)
                elif is_heading and not is_caption:
                    pending_figure = None

            for blob, ext in _docx_image_blobs(child, part):
                if len(figures) >= MAX_FIGURES:
                    break
                if in_front_matter:
                    continue  # cover and front-matter artwork is not shown
                caption = _caption_near(body_lines[-4:])
                dest = assets_dir / f"fig_{counter:02d}.{ext}"
                saved = _save_image(blob, ext, dest)
                counter += 1
                if not saved:
                    continue
                saved_path, width, height = saved
                figures.append(Figure(
                    path=str(saved_path), caption=caption, kind="photo",
                    page=page_estimate, section=running_heading, width=width, height=height,
                ))
                pending_figure = len(figures) - 1

        elif tag == f"{_W_NS}tbl":
            try:
                table = Table(child, doc._body)
            except Exception:
                continue
            rows: List[List[str]] = []
            row_lines: List[str] = []
            for row in table.rows:
                cells = [_norm_space(cell.text) for cell in row.cells]
                if any(cells):
                    rows.append(cells)
                    row_lines.append("- " + " — ".join(c for c in cells if c))
            if not rows:
                continue
            if in_front_matter:
                prelim_lines.extend(row_lines)
                continue
            body_lines.extend(row_lines)
            dest = assets_dir / f"table_{counter:02d}.png"
            counter += 1
            if len(figures) >= MAX_FIGURES:
                continue
            # Word styles the caption *after* the table, so the visual is left
            # pending and a following "Table 1. ..." paragraph claims it (and
            # re-renders the image with the caption drawn on it).
            leading_caption = _caption_near(body_lines)
            saved = _render_table_image(rows, leading_caption, dest)
            if saved:
                saved_path, width, height = saved
                figures.append(Figure(
                    path=str(saved_path), caption=leading_caption, kind="table",
                    page=page_estimate, section=running_heading, width=width, height=height,
                ))
                if leading_caption:
                    pending_figure = None
                else:
                    pending_figure = len(figures) - 1

    # A document made only of preliminary matter still has to yield material.
    if not body_lines and prelim_lines:
        body_lines, prelim_lines = prelim_lines, []

    return ExtractedDocument(
        text="\n".join(l for l in body_lines if l.strip()),
        front_matter_text="\n".join(l for l in prelim_lines if l.strip()),
        page_count=max(1, page_estimate),
        figures=figures,
    )


# ---------------------------------------------------------------------------
# Fallback + entry points
# ---------------------------------------------------------------------------


def _pdfminer_text(path: Path) -> str:
    try:
        from pdfminer.high_level import extract_text
    except Exception:
        return ""
    try:
        return (extract_text(str(path)) or "").strip()
    except Exception:
        return ""


def extract_document(file_path: Path, assets_dir: Optional[Path] = None) -> ExtractedDocument:
    """Read a document in detail: body text, front matter and visuals."""
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()
    if assets_dir is None:
        assets_dir = Path("generated") / "assets"
    assets_dir = Path(assets_dir)

    if suffix == ".docx":
        document = _read_docx(file_path, assets_dir)
        if document is not None:
            return document
        raise RuntimeError("python-docx is required to extract .docx files")

    if suffix == ".pdf":
        document = _read_pdf(file_path, assets_dir)
        if document is not None:
            return document
        text = _pdfminer_text(file_path)
        if text:
            return ExtractedDocument(text=text, page_count=0)
        raise RuntimeError(
            "Unable to extract content from PDF. Install PyMuPDF (fitz) or pdfminer.six."
        )

    try:
        return ExtractedDocument(text=file_path.read_text(encoding="utf-8"))
    except Exception:
        return ExtractedDocument(text="")


def extract_document_from_upload(upload_file, assets_dir: Optional[Path] = None) -> ExtractedDocument:
    """Persist an upload and read it in detail.

    Assets are stored in a content-addressed directory so the ``/preview`` and
    ``/generate`` calls for the same file reuse the same extracted images.
    """
    from tempfile import NamedTemporaryFile

    payload = upload_file.file.read()
    suffix = Path(upload_file.filename or "upload").suffix.lower()
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)

    if assets_dir is None:
        digest_dir = Path("generated") / "assets" / _sha1(payload)[:16]
    else:
        digest_dir = Path(assets_dir) / _sha1(payload)[:16]

    try:
        return extract_document(tmp_path, digest_dir)
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass


def document_summary(document: ExtractedDocument) -> str:
    """One-line description of what was read, for logs and API responses."""
    figures = document.figures
    return (
        f"{document.page_count} pages, {len(document.text.split())} words of body text, "
        f"{len(document.front_matter_text.split())} words of front matter, "
        f"{len(figures)} visuals"
    )
