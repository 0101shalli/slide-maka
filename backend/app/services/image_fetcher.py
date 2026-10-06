"""Deterministic Image Fetcher.

Best effort: search several keyless internet sources (Wikimedia Commons,
Openverse and DuckDuckGo Images) for the photo that best matches the slide's
keyword, ranking candidates by how many of the query's words their title/tags
actually contain before breaking ties on aspect ratio. If every network call
fails or nothing relevant is found, fall back to a locally generated Pillow
infographic so the pipeline never blocks or fails on missing images.
"""

from __future__ import annotations

import io
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, NamedTuple, Optional, Tuple
from urllib.parse import quote_plus

import requests
from PIL import Image, ImageDraw, ImageFont

from ..core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_WIDTH = 960
DEFAULT_HEIGHT = 720
# Images are always fetched at this canonical size and cover-cropped per panel,
# so a single cached download can serve every layout of the same slide.
DEFAULT_FETCH_WIDTH = 1600
DEFAULT_FETCH_HEIGHT = 900

_HEADERS = {"User-Agent": "SlideMaka/1.0 (presentation generator)"}

# The sandbox proxies HTTPS (MITM), so certificate verification can fail with
# SSLCertVerificationError. We swallow it gracefully and short-circuit further
# network attempts for the rest of the process; the image pipeline then uses the
# deterministic Pillow diagrams instead of a real photo.
_NETWORK_BLOCKED = False
_SSL_VERIFY = os.getenv("SLIDEMAKA_SSL_VERIFY", "1") != "0"

# Fetched images are reused for the rest of the process. Rendering a deck asks
# for the same keyword more than once (image panel + fullscreen variants) and a
# repeated keyword across slides would otherwise be downloaded again.
_CACHE_LOCK = threading.Lock()
_IMAGE_CACHE: Dict[tuple, bytes] = {}
_IMAGE_CACHE_MAX = 64

# Cache keys whose bytes came from ``generate_infographic`` rather than a real
# photo. A generated infographic is a text-dense diagram, so the deck gives it a
# full slide of its own instead of a small side panel.
_GENERATED_KEYS: set = set()


class ImageSpec(NamedTuple):
    """What one slide needs from the image pipeline.

    ``diagram`` is set by the AI visual planner when the slide should be drawn
    as a concept diagram or a flow rather than filled with a photo. Its presence
    skips the photo search entirely.
    """

    keyword: str
    primary: str
    secondary: str
    accent: str
    background: str
    points: Optional[list[str]] = None
    diagram: Optional[dict] = None

    @property
    def cache_key(self) -> tuple:
        return (
            self.keyword,
            self.primary,
            self.secondary,
            self.accent,
            self.background,
            _points_signature(self.points),
            _diagram_signature(self.diagram),
        )


def _points_signature(points: Optional[list[str]]) -> tuple:
    return tuple(p for p in (points or [])[:4])


def _diagram_signature(diagram: Optional[dict]) -> tuple:
    if not diagram:
        return ()
    steps = tuple(str(s) for s in (diagram.get("steps") or [])[:6])
    return (str(diagram.get("title") or ""), steps)


def _cache_get(key: tuple) -> Optional[bytes]:
    with _CACHE_LOCK:
        return _IMAGE_CACHE.get(key)


def _cache_put(key: tuple, data: bytes) -> None:
    with _CACHE_LOCK:
        if len(_IMAGE_CACHE) >= _IMAGE_CACHE_MAX:
            evicted = next(iter(_IMAGE_CACHE))
            _IMAGE_CACHE.pop(evicted)
            _GENERATED_KEYS.discard(evicted)
        _IMAGE_CACHE[key] = data


def _mark_generated(key: tuple, generated: bool) -> None:
    with _CACHE_LOCK:
        if generated:
            _GENERATED_KEYS.add(key)
        else:
            _GENERATED_KEYS.discard(key)


def _spec_key(
    keyword: str,
    primary: str,
    secondary: str,
    accent: str,
    background: str,
    points: Optional[list[str]] = None,
    diagram: Optional[dict] = None,
) -> tuple:
    return ImageSpec(keyword, primary, secondary, accent, background, points, diagram).cache_key



def _ca_bundle() -> object:
    if not _SSL_VERIFY:
        return False
    try:
        import certifi

        return certifi.where()
    except Exception:
        for candidate in ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
            if os.path.exists(candidate):
                return candidate
    return True


def _mark_network_blocked(reason: str) -> None:
    global _NETWORK_BLOCKED
    if not _NETWORK_BLOCKED:
        _NETWORK_BLOCKED = True
        logger.warning(
            "Network blocked for image fetching (%s). Falling back to local generated diagrams.", reason
        )


def _is_certificate_error(exc: Exception) -> bool:
    return isinstance(exc, requests.exceptions.SSLError) or "certificate" in str(exc).lower()


def _luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _contrast_color(hex_color: str) -> str:
    return "#FFFFFF" if _luminance(hex_color) < 140 else "#1A1A1A"


def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if bold:
        names = ("DejaVuSans-Bold.ttf", "Arial Bold", "DejaVuSans.ttf", "Arial")
    else:
        names = ("DejaVuSans.ttf", "Arial", "DejaVuSans-Bold.ttf", "Arial Bold")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default(size)


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getbbox(candidate)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _infographic_keyword(keyword: str) -> str:
    keyword = re.sub(r"[^a-zA-Z0-9 ]", " ", keyword or "").strip()
    words = keyword.split()[:4]
    return " ".join(words).title() or "SlideMaka"


def _clean_point(point: str) -> str:
    point = re.sub(r"\*\*(.*?)\*\*", r"\1", point or "")
    point = re.sub(r"[_\-]{2,}", " ", point)
    point = point.strip()
    return point or "Key information point"


def _draw_pill(draw: ImageDraw.ImageDraw, cx: int, y: int, radius: int, fill: str) -> None:
    draw.ellipse([cx - radius, y - radius, cx + radius, y + radius], fill=fill)


def _render_point_rows(
    img: Image.Image,
    points: list[str],
    primary: str,
    secondary: str,
    accent: str,
    background: str,
    top_offset: int = 0,
) -> int:
    """Draw numbered concept rows; returns the y position after the last row."""
    base = ImageDraw.Draw(img, mode="RGBA")
    margin = int(img.width * 0.06)
    num_font = _load_font(30, bold=True)
    body_font = _load_font(26, bold=False)
    row_x = margin
    circle_r = 26
    circle_gap = 18
    max_width = img.width - 2 * margin - circle_r * 2 - circle_gap - 24

    max_lines = 3
    line_h = 30
    pad_y = 16

    rows = []
    for point in (points or [])[:4]:
        for segment in re.split(r"(?<=[.])\s+(?=[A-Za-z0-9\"'(])", _clean_point(point))[:4]:
            if segment.strip():
                rows.append(segment.strip())
            if len(rows) >= 4:
                break
        if len(rows) >= 4:
            break
    rows = rows[:4]
    short_mode = len(rows) >= 2 and all(len(p.split()) <= 7 for p in rows)
    y = top_offset
    # Text is drawn on row cards filled with `background`; pick the contrast
    # against that fill so the content stays readable on any palette.
    text_contrast = _contrast_color(background)
    numeral_color = _contrast_color(accent)
    circle_cys: list[int] = []

    for i, point in enumerate(rows):
        text = _clean_point(point)
        lines = _wrap_text(text, body_font, max_width)[:max_lines]
        block_h = max(len(lines), 1) * line_h + pad_y * 2
        circle_cy = y + round(block_h / 2) + 10
        circle_cys.append(circle_cy)

        # Row card so the text stays readable over the banded background.
        pad_x = 8
        card = Image.new("RGBA", (img.width - 2 * (margin - pad_x), block_h), (0, 0, 0, 0))
        card_draw = ImageDraw.Draw(card)
        card_draw.rounded_rectangle(
            [(0, 0), (card.width - 1, block_h - 1)],
            radius=16,
            fill=background + "C8",
        )
        card_draw.rounded_rectangle(
            [(margin - 2 * pad_x + 8, 6), (margin - 2 * pad_x + 13, block_h - 7)],
            radius=3,
            fill=accent + "FF",
        )
        img.paste(card, (margin - pad_x, y + 10), card)

        _draw_pill(base, row_x + circle_r, circle_cy, circle_r, accent)
        if short_mode:
            base.line(
                [(row_x + circle_r + circle_gap - 8, circle_cy), (row_x + circle_r + circle_gap + 12, circle_cy)],
                fill=secondary,
                width=3,
            )
        num = f"{i + 1}"
        nb = num_font.getbbox(num)
        base.text(
            (row_x + circle_r - (nb[2] - nb[0]) / 2, circle_cy - (nb[3] - nb[1]) / 2 - nb[1]),
            num,
            font=num_font,
            fill=numeral_color,
        )

        tx = row_x + circle_r * 2 + circle_gap
        ty = y + 10 + pad_y
        for j, line in enumerate(lines):
            base.text((tx, ty + j * line_h), line, font=body_font, fill=text_contrast)
            if short_mode and j == len(lines) - 1:
                underline_w = min(len(line) * 14, max_width - 8)
                base.line(
                    [(tx, ty + j * line_h + line_h - 6), (tx + underline_w, ty + j * line_h + line_h - 6)],
                    fill=accent + "AA",
                    width=2,
                )
        y += block_h + 18

    if len(circle_cys) > 1:
        # Vertical connector chains the numbered steps into a flow diagram.
        cx = row_x + circle_r
        for prev_cy, next_cy in zip(circle_cys, circle_cys[1:]):
            base.line(
                [(cx, prev_cy + circle_r), (cx, next_cy - circle_r)],
                fill=secondary + "99",
                width=3,
            )
    return y


def _paste_footer_chip(img: Image.Image, label: str, primary: str) -> None:
    """Small centered chip at the bottom, matching the infographic style."""
    tag_font = _load_font(22, bold=False)
    tag_bbox = tag_font.getbbox(label)
    chip_w = tag_bbox[2] + 36
    chip_h = 34
    chip_img = Image.new("RGBA", (chip_w, chip_h), primary + "CC")
    chip_draw = ImageDraw.Draw(chip_img)
    chip_draw.text((18, (chip_h - tag_bbox[3]) // 2 - tag_bbox[1] + 4), label, font=tag_font, fill=_contrast_color(primary))
    img.paste(chip_img, ((img.width - chip_w) // 2, img.height - chip_h - 28), chip_img)


def _encode_jpeg(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def _render_flow_body(
    img: Image.Image,
    steps: list[str],
    title: str,
    primary: str,
    secondary: str,
    accent: str,
    background: str,
) -> None:
    """Draw a vertical flow of numbered step boxes joined by arrows.

    A vertical chain keeps every box edge-to-edge inside the slide, so no label
    is cropped when the diagram fills a 16:9 slide.
    """
    base = ImageDraw.Draw(img, mode="RGBA")
    width, height = img.size
    margin = int(width * 0.09)
    content_w = width - 2 * margin
    content_color = _contrast_color(background)

    y = int(height * 0.06)
    if title:
        title_font = _load_font(52, bold=True)
        for line in _wrap_text(title, title_font, content_w)[:2]:
            base.text((margin, y), line, font=title_font, fill=content_color)
            y += 60
        bar = Image.new("RGBA", (int(width * 0.22), 8), accent)
        img.paste(bar, (margin, y + 8), bar)
        y += 40

    n = max(len(steps), 1)
    bottom = height - int(height * 0.11)
    gap = max(14, int((bottom - y) * 0.035))
    box_h = int((bottom - y - gap * (n - 1)) / n)
    box_h = max(66, min(box_h, 150))
    num_font = _load_font(max(20, int(box_h * 0.36)), bold=True)
    step_font = _load_font(max(20, int(box_h * 0.31)), bold=False)
    line_h = int(getattr(step_font, "size", int(box_h * 0.36)) * 1.22)

    for i, step in enumerate(steps):
        top = y + i * (box_h + gap)
        base.rounded_rectangle(
            [margin, top, margin + content_w, top + box_h],
            radius=20,
            fill=background + "F2",
            outline=accent,
            width=4,
        )
        badge_r = int(box_h * 0.30)
        cx = margin + badge_r + 18
        cy = top + box_h // 2
        base.ellipse([cx - badge_r, cy - badge_r, cx + badge_r, cy + badge_r], fill=accent)
        num = str(i + 1)
        nb = num_font.getbbox(num)
        base.text(
            (cx - (nb[2] - nb[0]) / 2 - nb[0], cy - (nb[3] - nb[1]) / 2 - nb[1]),
            num,
            font=num_font,
            fill=_contrast_color(accent),
        )
        tx = cx + badge_r + 22
        max_tw = (margin + content_w) - tx - 24
        lines = _wrap_text(_clean_point(step), step_font, max_tw)[:2]
        ty = cy - (len(lines) * line_h) // 2
        for line in lines:
            base.text((tx, ty), line, font=step_font, fill=content_color)
            ty += line_h
        if i < n - 1:
            ax = margin + content_w // 2
            ay0 = top + box_h + 1
            ay1 = top + box_h + gap
            base.line([(ax, ay0), (ax, ay1 - 4)], fill=secondary, width=5)
            base.polygon([(ax - 11, ay1 - 10), (ax + 11, ay1 - 10), (ax, ay1 + 4)], fill=secondary)


def generate_infographic(
    keyword: str,
    primary: str = "#0B3C5D",
    secondary: str = "#1D5C7C",
    accent: str = "#3A7CA5",
    background: str = "#F0F8FF",
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    points: Optional[list[str]] = None,
    diagram: Optional[dict] = None,
) -> bytes:
    """Generate a themed Pillow infographic for the given keyword.

    When ``points`` (the slide's key bullets) are supplied, the image renders a
    numbered concept/flow diagram depicting the actual content instead of a mere
    keyword poster. ``diagram`` (from the AI visual planner) renders either a
    labelled flow of its ``steps`` or a concept diagram from its ``points``.
    """
    img = Image.new("RGB", (width, height), background)
    base = ImageDraw.Draw(img, mode="RGBA")

    # Diagonal band using secondary/primary overlay.
    band = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    band_draw = ImageDraw.Draw(band)
    steps = 9
    step_w = (width + height) // steps
    for i in range(steps):
        x0 = -height // 2 + i * step_w
        alpha = 22 if i % 2 == 0 else 38
        band_draw.polygon(
            [(x0, height), (x0 + height // 2, 0), (x0 + step_w + height // 2, 0), (x0 + step_w, height)],
            fill=primary + f"{alpha:02X}",
        )
    img = Image.alpha_composite(img.convert("RGBA"), band)
    base = ImageDraw.Draw(img)

    # Accent circles in the corners.
    r = int(width * 0.22)
    base.ellipse([-r // 2, -r // 2, 3 * r // 2, 3 * r // 2], fill=secondary + "40")
    base.ellipse([width - r, height - r, width + r, height + r], fill=accent + "38")
    base.ellipse([width - r * 2.4, -r, width - r * 0.4, r * 1.4], fill=primary + "30")

    if diagram is not None:
        flow_steps = [str(step) for step in (diagram.get("steps") or []) if str(step).strip()][:6]
        if len(flow_steps) >= 2:
            flow_title = _infographic_keyword(diagram.get("title") or keyword)
            _render_flow_body(img, flow_steps, flow_title, primary, secondary, accent, background)
            _paste_footer_chip(img, f"Flow - {_infographic_keyword(keyword)[:28]}", primary)
            return _encode_jpeg(img)
        # A concept diagram: reuse the planner's own points when it gave any.
        points = diagram.get("points") or points

    margin = int(width * 0.06)
    headline = _infographic_keyword(keyword)
    content_mode = bool(points)

    # Headline.
    font_size = 76 if not content_mode else 46
    while font_size > 36:
        font = _load_font(font_size, bold=True)
        if max(font.getbbox(line)[2] for line in [headline]) <= int(width * 0.82):
            break
        font_size -= 4
        font = _load_font(font_size, bold=True)
    lines = _wrap_text(headline, font, int(width * 0.82))
    line_height = font_size + 10
    if content_mode:
        y = margin + 18
    else:
        total_h = len(lines) * line_height
        y = (height - total_h) // 2 - 24
    for line in lines:
        bbox = font.getbbox(line)
        x = margin if content_mode else (width - bbox[2]) // 2
        base.text((x + 3, y + 3), line, font=font, fill="#00000040")
        base.text((x, y), line, font=font, fill=_contrast_color(primary))
        y += line_height

    # Accent underline.
    bar_w = int(width * 0.28)
    if content_mode:
        label = "Concept overview"
        tag_font = _load_font(20, bold=False)
        tag_bbox = tag_font.getbbox(label)
        base.text((margin, y + 6), label, font=tag_font, fill=accent if _contrast_color(primary) == "#FFFFFF" else secondary)
        paste = Image.new("RGBA", (bar_w, 6), accent)
        img.paste(paste, (margin, y + 10), paste)
        y += 30
    else:
        paste = Image.new("RGBA", (bar_w, 10), accent)
        img.paste(paste, ((width - bar_w) // 2, y + 12), paste)
        y += 44

    if content_mode:
        y = _render_point_rows(img, points, primary, secondary, accent, background, top_offset=y)
    else:
        y += 44

    # Footer chip.
    label = f'Diagram - {_infographic_keyword(keyword)[:28]}' if content_mode else "SlideMaka Presentation"
    _paste_footer_chip(img, label, primary)
    return _encode_jpeg(img)


def try_unsplash_source(keyword: str, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT) -> Optional[bytes]:
    """Try to fetch a real photo. Returns JPEG bytes or None."""
    if _NETWORK_BLOCKED:
        return None
    keyword = keyword or "presentation"
    url = f"https://source.unsplash.com/{width}x{height}/?" + quote_plus(keyword)
    try:
        response = requests.get(url, timeout=10, headers=_HEADERS, verify=_ca_bundle())
        if response.status_code != 200:
            return None
        content_type = response.headers.get("Content-Type", "")
        if "image" not in content_type:
            return None
        data = response.content
        if not data or len(data) < 2048:
            return None
        # Validate it parses as an image.
        Image.open(io.BytesIO(data)).verify()
        return data
    except requests.exceptions.SSLError as exc:
        _mark_network_blocked(f"SSL certificate verification failed: {exc.__class__.__name__}")
        return None
    except Exception as exc:
        if _is_certificate_error(exc):
            _mark_network_blocked(f"certificate error: {exc}")
        else:
            logger.debug("Unsplash fetch failed: %s", exc)
        return None


_WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
_OPENVERSE_API = "https://api.openverse.org/v1/images/"
_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

# Words that carry no topical meaning in an image search; they must not inflate
# a candidate's relevance score or steer the query.
_SEARCH_STOPWORDS = {
    "the", "and", "of", "for", "with", "from", "that", "this", "a", "an", "to",
    "in", "on", "at", "is", "are", "was", "were", "be", "as", "by", "or", "its",
    "it", "their", "our", "your", "part", "using", "used", "use", "based",
    "into", "over", "under", "about", "between", "concept", "concepts",
    "overview", "introduction", "summary", "key", "important", "different",
    "various", "several", "main", "major", "new", "also", "can", "will", "may",
    "slide", "slides", "presentation", "topic", "example", "examples", "details",
    "content", "section", "chapter", "understanding", "fundamentals",
}


class _Candidate(NamedTuple):
    """One downloadable image result, with everything needed to rank it."""

    score: float
    url: str
    thumb: Optional[str]
    title: str


def _query_tokens(text: str) -> set:
    """Meaningful lowercase words of an image query or result title/tag."""
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) > 2 and token not in _SEARCH_STOPWORDS
    }


def _candidate_score(relevance: float, width: int, height: int, target_ratio: float) -> Optional[float]:
    """Smaller-is-better score: relevance first, aspect ratio as a tie-breaker."""
    if not width or not height:
        return None
    ratio = width / height
    if ratio <= 0:
        return None
    ratio_penalty = min(abs(ratio - target_ratio) / max(target_ratio, 1e-6), 2.0)
    return (1.0 - relevance) + 0.35 * ratio_penalty


def _relevance(texts: Iterable[str], query_tokens: set) -> float:
    """Fraction of the query's words that appear in the result title/tags."""
    if not query_tokens:
        return 0.0
    tokens: set = set()
    for text in texts:
        tokens |= _query_tokens(text)
    return len(tokens & query_tokens) / len(query_tokens)


def _usable_image(mime: Optional[str], width: int, height: int) -> bool:
    if mime and not mime.startswith("image/"):
        return False
    return width >= 640 and height >= 360


def _wikimedia_candidates(keyword: str, target_ratio: float, query_tokens: set) -> list:
    """Ranked Wikimedia Commons files for the query (curated, freely licensed)."""
    if _NETWORK_BLOCKED:
        return []
    candidates: list = []
    seen: set = set()
    for query in (keyword, " ".join(keyword.split()[:2])):
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": 10,
            "prop": "imageinfo",
            "iiprop": "url|mime|size",
            "iiurlwidth": "1600",
            "format": "json",
        }
        response = requests.get(_WIKIMEDIA_API, params=params, timeout=8, headers=_HEADERS, verify=_ca_bundle())
        if response.status_code != 200:
            continue
        for page in response.json().get("query", {}).get("pages", {}).values():
            title = page.get("title", "")
            if title in seen:
                continue
            imageinfo = (page.get("imageinfo") or [{}])[0]
            width = imageinfo.get("width") or 0
            height = imageinfo.get("height") or 0
            if not _usable_image(imageinfo.get("mime"), width, height):
                continue
            url = imageinfo.get("thumburl") or imageinfo.get("url")
            if not url:
                continue
            score = _candidate_score(_relevance([title], query_tokens), width, height, target_ratio)
            if score is None:
                continue
            seen.add(title)
            candidates.append(_Candidate(score, url, imageinfo.get("url"), title))
        if candidates:
            break
    return sorted(candidates, key=lambda c: c.score)


def _openverse_candidates(keyword: str, target_ratio: float, query_tokens: set) -> list:
    """Ranked Openverse results (aggregates Flickr, museums and more)."""
    if _NETWORK_BLOCKED:
        return []
    params = {"q": keyword, "page_size": 10, "license_type": "all", "mature": "false"}
    response = requests.get(_OPENVERSE_API, params=params, timeout=8, headers=_HEADERS, verify=_ca_bundle())
    if response.status_code != 200:
        return []
    candidates: list = []
    for result in response.json().get("results", []):
        url = result.get("url")
        if not url:
            continue
        tags = [tag.get("name", "") for tag in result.get("tags", [])]
        relevance = _relevance([result.get("title") or "", *tags], query_tokens)
        score = _candidate_score(relevance, result.get("width") or 0, result.get("height") or 0, target_ratio)
        if score is None:
            continue
        candidates.append(_Candidate(score, result.get("thumbnail") or url, url, result.get("title") or ""))
    return sorted(candidates, key=lambda c: c.score)


def _wikipedia_candidates(keyword: str, target_ratio: float, query_tokens: set) -> list:
    """Ranked lead images of the Wikipedia articles matching the keyword.

    The article title is a strong topical signal, so its lead image is usually
    exactly what a concept slide should show. Files live on Wikimedia servers but
    the search itself is over the encyclopedia, a different index from Commons.
    """
    if _NETWORK_BLOCKED:
        return []
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": keyword,
        "gsrlimit": 5,
        "prop": "pageimages",
        "piprop": "original|thumbnail",
        "pithumbsize": "1600",
        "format": "json",
    }
    response = requests.get(_WIKIPEDIA_API, params=params, timeout=8, headers=_HEADERS, verify=_ca_bundle())
    if response.status_code != 200:
        return []
    candidates: list = []
    for page in response.json().get("query", {}).get("pages", {}).values():
        original = page.get("original") or {}
        thumbnail = page.get("thumbnail") or {}
        url = thumbnail.get("source") or original.get("source")
        if not url:
            continue
        width = original.get("width") or thumbnail.get("width") or 0
        height = original.get("height") or thumbnail.get("height") or 0
        if not _usable_image(None, width, height):
            # The original may be huge and the thumbnail small; trust the larger
            # of the two known sizes rather than discarding a relevant article.
            width = max(width, thumbnail.get("width") or 0)
            height = max(height, thumbnail.get("height") or 0)
            if not _usable_image(None, width, height):
                continue
        score = _candidate_score(_relevance([page.get("title", "")], query_tokens), width, height, target_ratio)
        if score is None:
            continue
        candidates.append(_Candidate(score, url, original.get("source"), page.get("title", "")))
    return sorted(candidates, key=lambda c: c.score)


_MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024


def _download_candidate(candidate: _Candidate) -> Optional[bytes]:
    """Download and normalise a candidate to JPEG bytes, or None on failure."""
    for url in (candidate.url, candidate.thumb):
        if not url:
            continue
        try:
            response = requests.get(url, timeout=8, headers=_HEADERS, verify=_ca_bundle(), stream=True)
            if response.status_code != 200:
                continue
            chunks: list = []
            total = 0
            for chunk in response.iter_content(65536):
                total += len(chunk)
                chunks.append(chunk)
                if total >= _MAX_DOWNLOAD_BYTES:
                    break
            data = b"".join(chunks)
            if len(data) < 2048:
                continue
            Image.open(io.BytesIO(data)).verify()
            image = Image.open(io.BytesIO(data)).convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=90)
            return buffer.getvalue()
        except requests.exceptions.SSLError as exc:
            _mark_network_blocked(f"SSL certificate verification failed: {exc.__class__.__name__}")
            return None
        except Exception as exc:
            if _is_certificate_error(exc):
                _mark_network_blocked(f"certificate error: {exc}")
                return None
            logger.debug("Image download failed (%s): %s", url, exc)
            continue
    return None


# Providers are queried concurrently; their single best candidate each is pooled
# and the highest ranked is downloaded.
_IMAGE_PROVIDERS = (_wikimedia_candidates, _wikipedia_candidates, _openverse_candidates)


def _try_photo_fetch(keyword: str, width: int, height: int) -> Optional[bytes]:
    """Search several internet sources for the best-matching photo.

    Providers are queried concurrently (each is an independent index), their
    single best candidate is pooled, and the pool is ranked by relevance before
    downloading, so a hit on one domain is not wasted waiting on another.
    """
    if _NETWORK_BLOCKED:
        return None
    keyword = " ".join((keyword or "").split()) or "presentation"
    target_ratio = width / height if height else DEFAULT_FETCH_WIDTH / DEFAULT_FETCH_HEIGHT
    query_tokens = _query_tokens(keyword)
    pooled: list = []
    with ThreadPoolExecutor(max_workers=len(_IMAGE_PROVIDERS)) as pool:
        futures = [pool.submit(provider, keyword, target_ratio, query_tokens) for provider in _IMAGE_PROVIDERS]
        for future in futures:
            try:
                found = future.result()
            except requests.exceptions.SSLError as exc:
                _mark_network_blocked(f"SSL certificate verification failed: {exc.__class__.__name__}")
                continue
            except Exception as exc:
                if _is_certificate_error(exc):
                    _mark_network_blocked(f"certificate error: {exc}")
                else:
                    logger.debug("Image provider failed: %s", exc)
                continue
            if found:
                pooled.append(found[0])
    for candidate in sorted(pooled, key=lambda c: c.score)[:2]:
        data = _download_candidate(candidate)
        if data is not None:
            return data
    return None


def _cover_crop_bytes(data: bytes, target_ratio: float) -> bytes:
    """Cover-crop JPEG bytes to a target width/height ratio (edge-to-edge)."""
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return data
    iw, ih = img.size
    if not iw or not ih or abs(iw / ih - target_ratio) < 0.01:
        return data
    if iw / ih > target_ratio:
        new_w = max(int(ih * target_ratio), 1)
        x0 = (iw - new_w) // 2
        img = img.crop((x0, 0, x0 + new_w, ih))
    else:
        new_h = max(int(iw / target_ratio), 1)
        y0 = (ih - new_h) // 2
        img = img.crop((0, y0, iw, y0 + new_h))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def fetch_image(
    keyword: str,
    primary: str = "#0B3C5D",
    secondary: str = "#1D5C7C",
    accent: str = "#3A7CA5",
    background: str = "#F0F8FF",
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    points: Optional[list[str]] = None,
    diagram: Optional[dict] = None,
) -> bytes:
    """Fetch a themed image for a slide. Always returns usable JPEG bytes.

    Tries real internet photos first (Wikimedia Commons, then the legacy
    Unsplash Source when ``settings.enable_legacy_unsplash`` is set).
    ``points`` (the slide's key bullets) is used to render a content diagram in
    the final offline fallback; a live photo stays keyword-based. ``diagram``
    (from the AI visual planner) forces a locally drawn diagram/flow. Results are
    memoized per (keyword, palette, points, diagram) so a deck never
    re-downloads the same image. ``width``/``height`` are accepted for backwards
    compatibility; the download always uses the canonical size and callers
    cover-crop it.
    """
    key = ImageSpec(keyword, primary, secondary, accent, background, points, diagram).cache_key
    cached = _cache_get(key)
    if cached is not None:
        return cached
    # Always fetch at the canonical size so the cache entry is identical whether
    # the image was warmed by ``prefetch_images`` or fetched on demand; callers
    # cover-crop it to whatever box they render into.
    data = _fetch_image_uncached(
        keyword, primary, secondary, accent, background,
        DEFAULT_FETCH_WIDTH, DEFAULT_FETCH_HEIGHT, points, diagram,
    )
    _cache_put(key, data)
    return data


def _fetch_image_uncached(
    keyword: str,
    primary: str,
    secondary: str,
    accent: str,
    background: str,
    width: int,
    height: int,
    points: Optional[list[str]],
    diagram: Optional[dict] = None,
) -> bytes:
    key = _spec_key(keyword, primary, secondary, accent, background, points, diagram)
    if diagram is not None:
        # The planner asked for a diagram/flow: always draw it, never search.
        _mark_generated(key, True)
        return generate_infographic(
            keyword, primary, secondary, accent, background, width, height,
            points=points, diagram=diagram,
        )
    photo = None
    if settings.enable_legacy_unsplash:
        try:
            photo = try_unsplash_source(keyword, width, height)
        except Exception as exc:
            logger.debug("Unsplash source failed: %s", exc)
            photo = None
    if photo is None:
        photo = _try_photo_fetch(keyword, width, height)
    if photo is not None:
        _mark_generated(key, False)
        return photo
    _mark_generated(key, True)
    return generate_infographic(keyword, primary, secondary, accent, background, width, height, points=points)


def image_is_generated(
    keyword: str,
    primary: str = "#0B3C5D",
    secondary: str = "#1D5C7C",
    accent: str = "#3A7CA5",
    background: str = "#F0F8FF",
    points: Optional[list[str]] = None,
) -> bool:
    """Whether this slide's image is the local Pillow fallback.

    A generated infographic is a diagram with small text, so the deck gives it a
    full slide rather than shrinking it into a side panel. Resolves (and caches)
    the image if the prefetch has not run yet; a later ``fetch_image`` for the
    same arguments is then a cache hit.
    """
    key = _spec_key(keyword, primary, secondary, accent, background, points)
    if _cache_get(key) is None:
        _cache_put(
            key,
            _fetch_image_uncached(
                keyword, primary, secondary, accent, background,
                DEFAULT_FETCH_WIDTH, DEFAULT_FETCH_HEIGHT, points,
            ),
        )
    with _CACHE_LOCK:
        return key in _GENERATED_KEYS


def _spec_args(spec: ImageSpec) -> tuple:
    """Positional arguments of ``_fetch_image_uncached`` for an ``ImageSpec``."""
    return (
        spec.keyword, spec.primary, spec.secondary, spec.accent, spec.background,
        DEFAULT_FETCH_WIDTH, DEFAULT_FETCH_HEIGHT, spec.points, spec.diagram,
    )


def prefetch_images(specs: Iterable[ImageSpec], workers: Optional[int] = None) -> None:
    """Warm the image cache for several slides in parallel.

    Fetching is I/O bound, so a deck with N image slides costs roughly one image
    fetch instead of N of them in series.
    """
    pending = []
    for spec in specs:
        if _cache_get(spec.cache_key) is None:
            pending.append(spec)
    if not pending:
        return
    if len(pending) == 1:
        spec = pending[0]
        _cache_put(spec.cache_key, _fetch_image_uncached(*_spec_args(spec)))
        return

    pool_size = workers or settings.image_prefetch_workers or 4
    pool_size = max(1, min(pool_size, len(pending)))
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        futures = {
            pool.submit(_fetch_image_uncached, *_spec_args(spec)): spec.cache_key
            for spec in pending
        }
        for future, key in futures.items():
            try:
                _cache_put(key, future.result())
            except Exception as exc:
                logger.debug("Image prefetch failed: %s", exc)


def image_render_colors(palette: dict[str, str]) -> Tuple[str, str, str, str]:
    """Map a palette dict to (primary, secondary, accent, background)."""
    return (
        palette.get("primary", "#0B3C5D"),
        palette.get("secondary", "#1D5C7C"),
        palette.get("accent", "#3A7CA5"),
        palette.get("background", "#F0F8FF"),
    )