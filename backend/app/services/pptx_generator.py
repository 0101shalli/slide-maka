"""Professional template-driven PPTX builder.

Renders a flat slide list (cover / outline / content / end) from the Deck
Builder into a polished 16:9 PowerPoint deck. Uses the user's palette, logo,
footer and (if chosen) a saved template's ``slide_order`` + ``styles`` to style
every slide. Images are fetched via the Image Fetcher (Unsplash photo or a
themed Pillow infographic) and framed consistently.
"""

from pathlib import Path
import re
from io import BytesIO

import requests
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

from .image_fetcher import (
    ImageSpec,
    fetch_image,
    prefetch_images,
    image_is_generated,
    image_render_colors,
    _infographic_keyword,
    _luminance,
    _cover_crop_bytes,
)

PALETTES = {
    1: {"name": "Ocean", "primary": "#0B3C5D", "secondary": "#1D5C7C", "accent": "#3A7CA5", "background": "#F0F8FF"},
    2: {"name": "Forest", "primary": "#2F5233", "secondary": "#4A7C59", "accent": "#6B9F7F", "background": "#F0FFF0"},
    3: {"name": "Sunset", "primary": "#C44536", "secondary": "#D2691E", "accent": "#FF6347", "background": "#FFF8DC"},
}

SLIDE_W = 10.0
SLIDE_H = 5.625
MARGIN = 0.6
CONTENT_W = SLIDE_W - 2 * MARGIN


def hex_to_rgb(hex_color: str) -> RGBColor:
    hex_color = hex_color.lstrip("#")
    return RGBColor(int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


def get_contrast_text_color(hex_color: str) -> RGBColor:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return RGBColor(255, 255, 255) if luminance < 140 else RGBColor(0, 0, 0)


def _tint(hex_color: str, factor: float) -> str:
    """Blend a color toward white by ``factor`` (0..1)."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"#{r:02X}{g:02X}{b:02X}"


def download_image(url: str) -> BytesIO | None:
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return BytesIO(response.content)
    except Exception:
        return None


def select_slide_image(slide_data: dict) -> str:
    title = slide_data.get("title", "presentation")
    keyword = " ".join(re.findall(r"[a-zA-Z]+", title)[:3]) if title else "presentation"
    return f"https://source.unsplash.com/960x720/?{keyword}"


def _parse_formatted_text(text: str) -> list[tuple[str, dict]]:
    """Parse text with formatting markers into (text, format_dict) tuples.

    Supported markers:
    - **text** for bold
    - --text-- for highlight/important
    - __text__ for italic
    """
    parts = []
    pos = 0
    pattern = r"(\*\*[^*]+\*\*|--[^-]+--|__[^_]+__)"

    for match in re.finditer(pattern, text):
        if match.start() > pos:
            parts.append((text[pos:match.start()], {}))
        marked_text = match.group(0)
        if marked_text.startswith("**") and marked_text.endswith("**"):
            parts.append((marked_text[2:-2], {"bold": True}))
        elif marked_text.startswith("--") and marked_text.endswith("--"):
            parts.append((marked_text[2:-2], {"bold": True, "color": "accent"}))
        elif marked_text.startswith("__") and marked_text.endswith("__"):
            parts.append((marked_text[2:-2], {"italic": True}))
        pos = match.end()

    if pos < len(text):
        parts.append((text[pos:], {}))
    return parts


def _add_formatted_paragraph(
    text_frame,
    bullet_text: str,
    font_size: int,
    color_rgb: RGBColor,
    accent_color_rgb: RGBColor,
    is_heading: bool = False,
    bullet_color_rgb: RGBColor | None = None,
):
    """Add a paragraph with formatted text (bold, italic, highlight)."""
    p = text_frame.add_paragraph()
    p.text = ""
    p.font.size = Pt(font_size)
    p.font.color.rgb = color_rgb
    p.space_after = Pt(8 if not is_heading else 12)
    p.level = 0

    if not is_heading:
        run = p.add_run()
        run.text = "•  "
        run.font.size = Pt(font_size)
        run.font.color.rgb = bullet_color_rgb or accent_color_rgb
    else:
        run = p.add_run()
        run.text = ""

    formatted_parts = _parse_formatted_text(bullet_text)
    for part_text, formats in formatted_parts:
        run = p.add_run()
        run.text = part_text
        run.font.size = Pt(font_size)
        if formats.get("bold"):
            run.font.bold = True
        if formats.get("italic"):
            run.font.italic = True
        if formats.get("color") == "accent":
            run.font.bold = True
            run.font.color.rgb = accent_color_rgb
        else:
            run.font.color.rgb = color_rgb
    return p


def _add_rect(slide, x_in, y_in, w_in, h_in, fill_hex, outline_hex=None, shape=MSO_SHAPE.RECTANGLE):
    el = slide.shapes.add_shape(shape, Inches(x_in), Inches(y_in), Inches(w_in), Inches(h_in))
    if not fill_hex or fill_hex.lower() in ("transparent", "none"):
        el.fill.background()
    else:
        el.fill.solid()
        el.fill.fore_color.rgb = hex_to_rgb(fill_hex)
    if outline_hex:
        el.line.color.rgb = hex_to_rgb(outline_hex)
        el.line.width = Pt(1.2)
    else:
        el.line.fill.background()
    el.shadow.inherit = False
    return el


SHAPE_TYPES = {
    "rect": MSO_SHAPE.RECTANGLE,
    "square": MSO_SHAPE.RECTANGLE,
    "ellipse": MSO_SHAPE.OVAL,
    "circle": MSO_SHAPE.OVAL,
    "triangle": MSO_SHAPE.ISOSCELES_TRIANGLE,
    "right_triangle": MSO_SHAPE.RIGHT_TRIANGLE,
    "rightAngleTriangle": MSO_SHAPE.RIGHT_TRIANGLE,
    "pentagon": MSO_SHAPE.PENTAGON,
    "hexagon": MSO_SHAPE.HEXAGON,
    "arrowLeft": MSO_SHAPE.LEFT_ARROW,
    "arrowRight": MSO_SHAPE.RIGHT_ARROW,
    "star4": MSO_SHAPE.STAR_4_POINT,
    "star5": MSO_SHAPE.STAR_5_POINT,
    "star6": MSO_SHAPE.STAR_6_POINT,
    "heart": MSO_SHAPE.HEART,
    "calloutRect": MSO_SHAPE.ROUNDED_RECTANGULAR_CALLOUT,
    "calloutOval": MSO_SHAPE.OVAL_CALLOUT,
    "calloutCloud": MSO_SHAPE.CLOUD_CALLOUT,
}


def _add_text(slide, x_in, y_in, w_in, h_in, text, size, color_hex, bold=False, italic=False,
              align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, wrap=True):
    box = slide.shapes.add_textbox(Inches(x_in), Inches(y_in), Inches(w_in), Inches(h_in))
    tf = box.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = hex_to_rgb(color_hex)
    return box


def _set_bg(slide, hex_color: str) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = hex_to_rgb(hex_color)


def _apply_rotation(shape, rotation):
    if rotation:
        try:
            shape.rotation = int(float(rotation)) % 360
        except (TypeError, ValueError):
            pass


def _shape_for(typ):
    """Case-insensitive lookup in SHAPE_TYPES (element type ids may be camelCase)."""
    if typ in SHAPE_TYPES:
        return SHAPE_TYPES[typ]
    for key, mso in SHAPE_TYPES.items():
        if key.lower() == typ:
            return mso
    return None


def _place_block_elements(slide, block):
    """Render user-added canvas elements (shapes / text areas) on the slide.

    Elements are stored in the template block JSON as ``elements`` and use
    percentage coordinates of the slide (0-100). They render right after the
    background so the real content stays readable on top.
    """
    block = block or {}
    background = block.get("backgroundColor") or "#FFFFFF"
    for el in block.get("elements") or []:
        try:
            typ = (el.get("type") or "").lower()
            x_in = float(el.get("x", 5)) / 100.0 * SLIDE_W
            y_in = float(el.get("y", 5)) / 100.0 * SLIDE_H
            w_in = max(float(el.get("w", 20)) / 100.0 * SLIDE_W, 0.12)
            h_in = max(float(el.get("h", 15)) / 100.0 * SLIDE_H, 0.12)
            fill = el.get("fill") or "#3A7CA5"
            outline_color = el.get("outline_color")
            outline_width = max(int(float(el.get("outline_width", 0))), 0)
            mso = _shape_for(typ)
            if mso is not None:
                elmt = _add_rect(slide, x_in, y_in, w_in, h_in, fill,
                                outline_hex=outline_color or None, shape=mso)
                if outline_width:
                    elmt.line.width = Pt(max(1, outline_width))
                _apply_rotation(elmt, el.get("rotation"))
            elif typ == "line":
                stroke = el.get("stroke_color") or fill
                stroke_w = max(int(float(el.get("stroke_width") or el.get("outline_width", 3) or 3)), 1)
                _add_rect(slide, x_in, y_in, w_in, max(h_in, 0.03), stroke, shape=MSO_SHAPE.RECTANGLE)
                elmt = slide.shapes[-1]
                elmt.line.color.rgb = hex_to_rgb(stroke)
                elmt.line.width = Pt(min(stroke_w, 24))
                elmt.fill.background()
                _apply_rotation(elmt, el.get("rotation"))
            elif typ == "pencil":
                _render_pencil_freeform(slide, el, x_in, y_in, w_in, h_in)
            elif typ == "text":
                size = max(int(float(el.get("font_size", 18))), 8)
                if el.get("color"):
                    text_color = el["color"]
                elif not fill or fill.lower() in ("transparent", "none"):
                    text_color = "#1A1A1A"
                else:
                    text_color = "#FFFFFF" if _luminance(fill) < 140 else "#1A1A1A"
                box = _add_text(slide, x_in, y_in, w_in, h_in, el.get("text") or "Text area",
                          size, text_color, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, wrap=True)
                _apply_rotation(box, el.get("rotation"))
        except Exception:
            continue


def _render_pencil_freeform(slide, el, x_in, y_in, w_in, h_in):
    points = el.get("points") or []
    if len(points) < 2:
        return
    try:
        from pptx.util import Emu

        iw, ih = w_in / 100.0, h_in / 100.0
        origin_x = Emu(int(x_in * 914400))
        origin_y = Emu(int(y_in * 914400))
        vertices = [(Emu(int(float(px) * iw * 914400)), Emu(int(float(py) * ih * 914400))) for px, py in points]
        scale = Emu(914400)  # 1 local unit == 1 inch
        fb = slide.shapes.build_freeform(origin_x, origin_y, scale=scale)
        fb.add_line_segments(vertices, close=False)
        shape = fb.convert_to_shape()
        stroke = el.get("stroke_color") or "#0B523E"
        shape.line.color.rgb = hex_to_rgb(stroke)
        shape.line.width = Pt(max(1, int(float(el.get("stroke_width", 3)))))
        shape.fill.background()
    except Exception:
        pass


def _scale_picture(prs, slide, stream_or_path, x_in, y_in, w_in, h_in):
    """Add a picture fitted inside the given box preserving aspect ratio."""
    try:
        pic = slide.shapes.add_picture(stream_or_path, Inches(x_in), Inches(y_in), Inches(w_in), Inches(h_in))
        return pic
    except Exception:
        return None


def _place_picture(prs, slide, image_bytes, x_in, y_in, box_w_in, box_h_in):
    """Add an image centered inside the bounding box, preserving aspect ratio."""
    from PIL import Image
    import io

    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception:
        return None
    iw, ih = img.size
    if not iw or not ih:
        return None
    ratio_w, ratio_h = iw / ih, box_w_in / box_h_in
    if ratio_w > ratio_h:
        fit_w, fit_h = box_w_in, box_w_in / ratio_w
    else:
        fit_h, fit_w = box_h_in, box_h_in * ratio_w
    x = x_in + (box_w_in - fit_w) / 2
    y = y_in + (box_h_in - fit_h) / 2
    return _scale_picture(prs, slide, io.BytesIO(image_bytes), x, y, fit_w, fit_h)


def _add_bg_picture(slide, image_path, w_in=SLIDE_W, h_in=SLIDE_H):
    """Full-bleed background picture (inserted first so later shapes render on top)."""
    try:
        slide.shapes.add_picture(str(image_path), 0, 0, Inches(w_in), Inches(h_in))
    except Exception:
        pass


def _bg_key(slide_type: str, has_image: bool = False) -> str:
    if slide_type == "cover":
        return "cover"
    if slide_type == "outline":
        return "outline"
    if slide_type == "end":
        return "end"
    if slide_type == "practical":
        return "content_practical"
    if slide_type == "image":
        return "image"
    return "content_theory"


def _render_fullscreen_image(prs, slide, palette, block, slide_data, keyword, bullets):
    """Render an image/diagram that fills the whole slide.

    A text-dense visual (a document chart/diagram or a generated infographic) is
    fitted whole into the area below the header and above the footer, so every
    label stays visible and as large as the slide allows. A photo on an
    image-only slide is instead cover-cropped to full-bleed, because cropping a
    photo loses nothing that must be read.
    """
    if block.get("bg_image"):
        return
    points = slide_data.get("image_content") or [
        b for b in bullets if b and b.strip() and not b.startswith("**")
    ]
    local = _local_image_bytes(slide_data)
    # A promoted, text-dense visual is fitted whole; a photo still fills the
    # slide edge to edge, where cropping costs nothing that must be read.
    contain = (
        slide_data.get("image_fit") == "contain"
        or slide_data.get("type") == "image"
        or (bool(local) and slide_data.get("image_promote"))
    )
    try:
        primary, secondary, accent, background = (palette["primary"], palette["secondary"], palette["accent"], palette["background"])
        # A visual from the uploaded document wins: it is the user's own material.
        image_bytes = local or fetch_image(
            keyword, primary, secondary, accent, background,
            points=points, diagram=slide_data.get("image_diagram"),
        )
        if image_bytes and not contain:
            image_bytes = _cover_crop_bytes(image_bytes, SLIDE_W / SLIDE_H)
    except Exception:
        image_bytes = None
    if not image_bytes:
        return

    accent = palette["accent"]
    primary = palette["primary"]
    band_h = 1.05
    footer_h = 0.42

    # A generated infographic is drawn at the slide's own ratio and carries its
    # own headline, so it fills the slide edge to edge with no crop and no title
    # band (which would otherwise cover its heading). Only the page-number strip
    # is added, so the diagram's content stays fully visible.
    if slide_data.get("image_generated") and not local:
        _place_picture(prs, slide, image_bytes, 0, 0, SLIDE_W, SLIDE_H)
        _add_rect(slide, 0, SLIDE_H - footer_h, SLIDE_W, footer_h, _tint(primary, 0.85))
        _add_rect(slide, 0, SLIDE_H - footer_h, SLIDE_W, 0.03, accent)
        return

    # Supporting text, if any, sits in a compact band above the footer.
    shown = []
    for b in points[:3]:
        shown.append(b[:117].rstrip() + "..." if len(b) > 120 else b)
    text_band_h = (0.45 + len(shown) * 0.4) if shown else 0.0

    if contain:
        # Whole visual, centred, in the space the header and footer leave free.
        top = band_h + 0.08
        bottom = footer_h + text_band_h + (0.08 if text_band_h else 0.06)
        _place_picture(prs, slide, image_bytes, 0.1, top, SLIDE_W - 0.2, SLIDE_H - top - bottom)
    else:
        _place_picture(prs, slide, image_bytes, 0, 0, SLIDE_W, SLIDE_H)

    # Header band: title stays readable over any image (python-pptx has no fill
    # transparency API, so a solid band is used instead of a translucent overlay).
    _add_rect(slide, 0, 0, SLIDE_W, band_h, primary)
    _add_rect(slide, 0, band_h, SLIDE_W, 0.045, accent)
    st = slide_data.get("type")
    kicker = "Theory" if st == "theory" else ("Practical" if st == "practical" else None)
    if kicker:
        _add_text(slide, MARGIN + 0.05, 0.12, CONTENT_W, 0.3, kicker, 12, _tint(accent, 0.45), bold=True)
    _add_text(slide, MARGIN + 0.05, 0.38, CONTENT_W, 0.5, slide_data.get("title", ""), 27, "#FFFFFF", bold=True)
    subtitle = slide_data.get("subtitle")
    if subtitle:
        _add_text(slide, MARGIN + 0.05, 0.78, CONTENT_W, 0.3, subtitle, 13, "#DDE7F0")

    if shown:
        y = SLIDE_H - footer_h - text_band_h
        _add_rect(slide, 0, y, SLIDE_W, text_band_h, primary)
        _add_rect(slide, 0, y, SLIDE_W, 0.04, accent)
        box = slide.shapes.add_textbox(Inches(MARGIN), Inches(y + 0.14), Inches(CONTENT_W), Inches(text_band_h - 0.28))
        tf = box.text_frame
        tf.word_wrap = True
        _add_bullets(tf, shown, 13, "#FFFFFF", _tint(accent, 0.45))

    # Footer strip keeps the slide's page number readable over the full-bleed
    # image (the page number is painted on top by _add_footer).
    _add_rect(slide, 0, SLIDE_H - 0.42, SLIDE_W, 0.42, _tint(primary, 0.85))
    _add_rect(slide, 0, SLIDE_H - 0.42, SLIDE_W, 0.03, accent)


def _add_image_panel(prs, slide, palette, x_in, y_in, w_in, h_in, keyword, points=None, slide_data=None):
    """Framed image panel with accent border and a caption chip.

    ``points`` (the slide's key bullets) lets the offline fallback render a
    concept/flow diagram depicting the actual slide content rather than a bare
    keyword poster. When the slide carries a visual read out of the uploaded
    document, that image is used instead and it is fitted whole (never cropped),
    so a chart or diagram stays complete and legible.
    """
    accent = palette["accent"]
    _add_rect(slide, x_in, y_in, w_in, h_in, "#FFFFFF", outline_hex=accent, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    try:
        primary, secondary, accent_c, background = (palette["primary"], palette["secondary"], palette["accent"], palette["background"])
        # The image is requested at the panel box's aspect ratio (via the
        # cover-crop below) so the diagram fills the visible area instead of
        # leaving large empty bands.
        box_w_in = w_in - 0.2
        box_h_in = h_in - 0.55
        local = _local_image_bytes(slide_data) if slide_data else None
        image_bytes = local or fetch_image(
            keyword, primary, secondary, accent_c, background,
            points=points, diagram=(slide_data or {}).get("image_diagram"),
        )
        if image_bytes and not local:
            # Only a fetched photo is cover-cropped; a document visual is
            # fitted whole so nothing is cut off.
            image_bytes = _cover_crop_bytes(image_bytes, box_w_in / box_h_in)
    except Exception:
        image_bytes = None
    if image_bytes:
        _place_picture(prs, slide, image_bytes, x_in + 0.1, y_in + 0.1, box_w_in, box_h_in)
    caption = (slide_data or {}).get("image_caption") or keyword
    chip = _add_rect(slide, x_in + 0.15, y_in + h_in - 0.4, w_in - 0.3, 0.3, accent, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    tfc = chip.text_frame
    tfc.word_wrap = False
    tfc.margin_top = 0
    tfc.margin_bottom = 0
    pc = tfc.paragraphs[0]
    pc.alignment = PP_ALIGN.CENTER
    rc = pc.add_run()
    rc.text = caption[:60]
    rc.font.size = Pt(10)
    rc.font.bold = True
    rc.font.color.rgb = get_contrast_text_color(accent)


def _add_logo(slide, logo_path, x_in, y_in, size_in=0.6):
    if not logo_path:
        return
    try:
        if isinstance(logo_path, str) and logo_path.startswith("http"):
            stream = download_image(logo_path)
            if stream:
                slide.shapes.add_picture(stream, Inches(x_in), Inches(y_in), Inches(size_in), Inches(size_in))
        else:
            slide.shapes.add_picture(str(logo_path), Inches(x_in), Inches(y_in), Inches(size_in), Inches(size_in))
    except Exception:
        pass


def _add_footer(prs, slide, palette, footer_text, page_no, total):
    footer_text = str(footer_text or "").strip()
    y = SLIDE_H - 0.32
    if footer_text:
        _add_text(slide, MARGIN, y - 0.1, CONTENT_W, 0.3, footer_text, 9,
                  palette["secondary"], italic=True, align=PP_ALIGN.CENTER)
    if page_no:
        _add_text(slide, SLIDE_W - 1.1, y - 0.1, 0.9, 0.3, f"{page_no} / {total}", 9,
                  palette["secondary"], align=PP_ALIGN.RIGHT)


def _add_header(prs, slide, palette, title, subtitle, design, accent, kicker=None):
    """Title header with per-design treatment. Returns header bottom (inches)."""
    primary = palette["primary"]
    if design == "corporate":
        _add_rect(slide, 0, 0, SLIDE_W, 0.09, primary)
        _add_rect(slide, 0, 0.09, SLIDE_W, 0.03, accent)
        title_color = primary
        text_x, text_y = MARGIN, 0.28
        title_size = 28
    elif design == "gradient":
        _add_rect(slide, 0, 0, SLIDE_W, 0.08, accent)
        for i in range(5):
            _add_rect(slide, 0, 0.08 + i * 0.05, SLIDE_W, 0.05, _tint(primary, i * 0.14))
        title_color = primary
        text_x, text_y = MARGIN, 0.32
        title_size = 28
    elif design == "colorful":
        _add_rect(slide, 0, 0, SLIDE_W, 0.9, primary)
        _add_rect(slide, 0, 0.9, SLIDE_W, 0.05, accent)
        _add_rect(slide, 8.4, -0.25, 1.9, 1.9, _tint(primary, 0.25), shape=MSO_SHAPE.OVAL)
        title_color = "#FFFFFF"
        text_x, text_y = MARGIN, 0.18
        title_size = 30
    else:  # minimal / modern / default
        _add_rect(slide, 0, 0, SLIDE_W, 0.07, primary)
        if design == "modern":
            _add_rect(slide, 0, 0.07, 0.16, 0.8, accent)
            _add_rect(slide, SLIDE_W - 1.4, -0.45, 1.4, 1.4, _tint(primary, 0.18), shape=MSO_SHAPE.OVAL)
        else:
            _add_rect(slide, MARGIN, 0.82, 1.1, 0.05, accent)
        title_color = primary
        text_x, text_y = MARGIN, 0.2
        title_size = 28

    if kicker:
        _add_text(slide, text_x, text_y - 0.02, CONTENT_W, 0.3, kicker.upper(), 11,
                  accent, bold=True)
    _add_text(slide, text_x, text_y + (0.24 if kicker else 0.0), CONTENT_W, 0.6,
              title, title_size, title_color, bold=True)
    base_y = 0.78
    if subtitle:
        _add_text(slide, text_x, 0.92, CONTENT_W, 0.4, subtitle, 14,
                  palette["secondary"], italic=True)
        base_y = 1.32
    elif kicker:
        base_y = 0.72
    return base_y


def _match_blocks(slides: list[dict], slide_order: list | None) -> dict[int, dict]:
    """Map slide index -> template block from ``slide_order`` by type, in order."""
    if not slide_order:
        return {}
    blocks_by_type: dict[str, list[dict]] = {}
    for block in slide_order:
        if not isinstance(block, dict):
            continue
        blocks_by_type.setdefault(block.get("type", "content"), []).append(block)
    cursor = {t: 0 for t in blocks_by_type}
    assigned: dict[int, dict] = {}

    def _next(pool_type):
        idx = cursor.get(pool_type, 0)
        if idx >= len(blocks_by_type[pool_type]):
            return None
        cursor[pool_type] = idx + 1
        return blocks_by_type[pool_type][idx]

    last_outline_block = None
    for i, slide in enumerate(slides):
        st = slide.get("type")
        if st == "outline":
            # A multi-slide outline reuses the first outline's block so the
            # continuation pages share its styling instead of consuming more
            # template blocks.
            if last_outline_block is not None:
                assigned[i] = last_outline_block
                continue
            pool_type = "outline" if "outline" in blocks_by_type else (
                "content" if "content" in blocks_by_type else None
            )
        elif st in ("cover", "end"):
            pool_type = st if st in blocks_by_type else ("content" if "content" in blocks_by_type else None)
        elif slide.get("image_url") and blocks_by_type.get("image"):
            pool_type = "image"
        elif blocks_by_type.get("content"):
            pool_type = "content"
        else:
            pool_type = None
        if pool_type is None:
            continue
        block = _next(pool_type)
        if block is not None:
            assigned[i] = block
            if st == "outline":
                last_outline_block = block
            continue
        # A content block can carry a "flavor" (theory/practical); prefer a match.
        if pool_type == "content" and st in {"theory", "practical"}:
            flavored = blocks_by_type.get("content", [])
            for candidate in flavored:
                if candidate.get("flavor") == st and candidate not in assigned.values():
                    assigned[i] = candidate
                    break
    return assigned


def _text_color_for(bg_hex: str, block_text: str | None, default_hex: str) -> str:
    if block_text:
        return block_text
    if _tint_luminance(bg_hex) < 140:
        return "#FFFFFF"
    return default_hex


def _tint_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _add_bullets(tf, bullets, size, color_hex, accent_hex, is_dark_bg=False, bullet_color=None):
    first = tf.paragraphs[0]
    first.text = ""
    used_first = False
    for bullet in bullets:
        if bullet == "":
            p = tf.add_paragraph()
            p.text = ""
            p.space_after = Pt(6)
            used_first = True
            continue
        if bullet.strip().startswith("**") and bullet.strip().endswith(":**"):
            section_title = bullet.strip()[2:-2]
            p = tf.add_paragraph()
            p.text = ""
            rc = p.add_run()
            rc.text = section_title
            rc.font.size = Pt(size + 3)
            rc.font.bold = True
            rc.font.color.rgb = hex_to_rgb(accent_hex)
            p.space_after = Pt(8)
            used_first = True
            continue
        if used_first:
            p = tf.add_paragraph()
        else:
            p = first
            used_first = True
        p.text = ""
        p.font.size = Pt(size)
        p.space_after = Pt(max(3.0, size * 0.45))
        run = p.add_run()
        run.text = "•  "
        run.font.size = Pt(size)
        run.font.color.rgb = hex_to_rgb(bullet_color or accent_hex)
        for part_text, fmt in _parse_formatted_text(bullet):
            run = p.add_run()
            run.text = part_text
            run.font.size = Pt(size)
            run.font.bold = bool(fmt.get("bold"))
            run.font.italic = bool(fmt.get("italic"))
            if fmt.get("color") == "accent":
                run.font.bold = True
                run.font.color.rgb = hex_to_rgb(accent_hex)
            else:
                run.font.color.rgb = hex_to_rgb(color_hex)


def _render_cover(prs, slide, palette, block, slide_data, logo_path):
    block = block or {}
    bg_image = block.get("bg_image")
    bg = block.get("backgroundColor") or palette["primary"]
    if bg_image:
        _add_bg_picture(slide, bg_image)
    else:
        _set_bg(slide, bg)
    _place_block_elements(slide, block)
    accent = palette["accent"]
    on_bg = _text_color_for(bg, block.get("textColor"), "#FFFFFF")

    if not bg_image:
        _add_rect(slide, 0, 0, SLIDE_W, 0.12, accent)
        _add_rect(slide, 0, SLIDE_H - 0.34, SLIDE_W, 0.34, _tint(bg, 0.16))
        _add_rect(slide, 7.5, -1.1, 3.6, 3.6, _tint(bg, 0.2), shape=MSO_SHAPE.OVAL)
        _add_rect(slide, -1.2, 4.3, 2.8, 2.8, _tint(bg, 0.14), shape=MSO_SHAPE.OVAL)
        _add_rect(slide, 7.2, 4.0, 0.9, 0.9, accent, shape=MSO_SHAPE.OVAL)

    if logo_path:
        _add_logo(slide, logo_path, 0.35, 0.3, 0.9)

    brand_color = on_bg if bg_image else _tint(bg, 0.55)
    _add_text(slide, SLIDE_W - 4.2, 0.55, 3.8, 0.4, "SlideMaka Presentation", 13,
              brand_color, bold=True, align=PP_ALIGN.RIGHT)

    title = slide_data.get("title") or "Presentation"
    title_font = 38
    if len(title) > 60:
        title_font = 30
    elif len(title) > 42:
        title_font = 33
    box = slide.shapes.add_textbox(Inches(0.55), Inches(1.05), Inches(8.9), Inches(2.4))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = title
    run.font.size = Pt(title_font)
    run.font.bold = True
    run.font.color.rgb = hex_to_rgb(on_bg)

    subtitle = slide_data.get("subtitle")
    if subtitle:
        _add_text(slide, 0.58, 3.15, 8.6, 0.45, subtitle, 18,
                  _tint(bg, 0.75), italic=True)

    bullets = slide_data.get("bullets", [])
    info_lines = [b for b in bullets if "prepared by" in b.lower() or "contact:" in b.lower()]
    if info_lines:
        y = 4.05
        for line in info_lines:
            text = line.strip()
            bold = "prepared by" in text.lower()
            _add_text(slide, 0.58, y, 8.6, 0.32, text, 14,
                      _tint(bg, 0.8), bold=bold)
            y += 0.34
    else:
        _add_text(slide, 0.58, 4.4, 8.6, 0.35,
                  "Topics covered in this session are presented in the slides that follow.",
                  13, _tint(bg, 0.6), italic=True)


def _render_outline(prs, slide, palette, block, slide_data):
    block = block or {}
    bg_image = block.get("bg_image")
    bg = block.get("backgroundColor") or palette["background"]
    if bg_image:
        _add_bg_picture(slide, bg_image)
        primary = palette["primary"]
        text_color = _text_color_for(bg, block.get("textColor"), primary)
    else:
        _set_bg(slide, bg)
        primary = palette["primary"]
        text_color = _text_color_for(bg, block.get("textColor"), primary)
    _place_block_elements(slide, block)
    accent = palette["accent"]

    base_y = _add_header(prs, slide, palette,
                         slide_data.get("title", "Presentation Outline"),
                         slide_data.get("subtitle"), "minimal", accent)

    items = slide_data.get("bullets", [])
    box = slide.shapes.add_textbox(Inches(MARGIN + 0.15), Inches(base_y + 0.15), Inches(CONTENT_W - 0.3), Inches(3.6))
    tf = box.text_frame
    tf.word_wrap = True
    n = 1
    first = True
    for item in items:
        stripped = item.strip()
        numbered = re.match(r"^(\d+)\.\s*(.*)$", stripped)
        is_header = stripped.startswith("**") and stripped.endswith("**")
        if is_header:
            text = stripped[2:-2].strip()
        elif numbered:
            text = numbered.group(2)
        else:
            text = re.sub(r"^\d+\.\s*", "", item)
        if first:
            p = tf.paragraphs[0]
            first = False
        else:
            p = tf.add_paragraph()
        p.text = ""
        if is_header:
            p.space_before = Pt(2)
            p.space_after = Pt(6)
            r = p.add_run()
            r.text = text
            r.font.size = Pt(14)
            r.font.bold = True
            r.font.color.rgb = hex_to_rgb(accent)
            continue
        p.space_after = Pt(8)
        # Keep the outline's own numbering so it continues across pages.
        if numbered:
            chip_txt = f"{int(numbered.group(1)):02d}"
        else:
            chip_txt = f"{n:02d}"
            n += 1
        r1 = p.add_run()
        r1.text = chip_txt
        r1.font.size = Pt(12)
        r1.font.bold = True
        r1.font.color.rgb = hex_to_rgb(accent)
        r2 = p.add_run()
        r2.text = "   "
        r2.font.size = Pt(12)
        r3 = p.add_run()
        r3.text = text
        r3.font.size = Pt(15)
        r3.font.color.rgb = hex_to_rgb(text_color)
        if "..." in text or "Closing" in text or "Introduction" in text:
            r3.font.bold = True
            r3.font.color.rgb = hex_to_rgb(primary)
        tf.word_wrap = True


def _render_end(prs, slide, palette, block, slide_data):
    block = block or {}
    bg_image = block.get("bg_image")
    bg = block.get("backgroundColor") or palette["primary"]
    if bg_image:
        _add_bg_picture(slide, bg_image)
    else:
        _set_bg(slide, bg)
    _place_block_elements(slide, block)
    accent = palette["accent"]
    on_bg = _text_color_for(bg, block.get("textColor"), "#FFFFFF")

    if not bg_image:
        _add_rect(slide, 0, 0, SLIDE_W, 0.1, accent)
        _add_rect(slide, 0, SLIDE_H - 0.28, SLIDE_W, 0.28, _tint(bg, 0.16))
        _add_rect(slide, SLIDE_W - 2.2, -0.9, 2.6, 2.6, _tint(bg, 0.2), shape=MSO_SHAPE.OVAL)
        _add_rect(slide, -0.8, 4.0, 2.2, 2.2, _tint(bg, 0.14), shape=MSO_SHAPE.OVAL)
        _add_text(slide, 0, 1.5, SLIDE_W, 1.1, "Thank You", 54, on_bg, bold=True, align=PP_ALIGN.CENTER)
        _add_rect(slide, (SLIDE_W - 1.6) / 2, 2.75, 1.6, 0.09, accent)
    else:
        _add_text(slide, 0, 1.5, SLIDE_W, 1.1, "Thank You", 54, on_bg, bold=True, align=PP_ALIGN.CENTER)

    lines = slide_data.get("bullets", [])
    body = [b for b in lines if "prepared by" not in b.lower() and "contact:" not in b.lower()]
    if body:
        box = slide.shapes.add_textbox(Inches(2.0), Inches(3.05), Inches(6.0), Inches(1.2))
        tf = box.text_frame
        tf.word_wrap = True
        first = True
        for b in body:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p.text = ""
            p.alignment = PP_ALIGN.CENTER
            p.space_after = Pt(6)
            run = p.add_run()
            run.text = b
            run.font.size = Pt(18)
            run.font.color.rgb = hex_to_rgb(_tint(bg, 0.85))
    meta = [b for b in lines if "prepared by" in b.lower() or "contact:" in b.lower()]
    y = 4.15
    for m in meta:
        _add_text(slide, 0, y, SLIDE_W, 0.32, m, 13, _tint(bg, 0.7),
                  align=PP_ALIGN.CENTER)
        y += 0.32


def _autofit_off(tf):
    """Let the shape size to its text, then re-enable shrink-on-overflow.

    python-pptx cannot write ``normAutofit`` directly, so the element is added
    by hand. PowerPoint and LibreOffice then reduce the type themselves if the
    estimate below is still slightly optimistic.
    """
    from pptx.oxml.ns import qn

    bodyPr = tf._txBody.find(qn("a:bodyPr"))
    if bodyPr is None:
        return
    for tag in ("a:noAutofit", "a:spAutoFit", "a:normAutofit"):
        existing = bodyPr.find(qn(tag))
        if existing is not None:
            bodyPr.remove(existing)
    bodyPr.append(bodyPr.makeelement(qn("a:normAutofit"), {}))


# Fraction of the box the estimate is allowed to fill, leaving slack for the
# difference between the estimate and the real renderer.
FIT_SAFETY_MARGIN = 0.94


def _fit_font_size(bullets, width_in, height_in, base_size, min_size=9):
    """Shrink the type until the slide's own wording fits its box.

    Slides are no longer truncated to a fixed number of lines, so a dense
    section has to fit the room it is given instead of losing sentences.
    """
    if not any(b and b.strip() for b in bullets):
        return base_size
    size = base_size
    while size > min_size:
        # 0.55em average glyph width: measured against rendered decks, 0.5em
        # overestimated the characters per line and let dense slides
        # overflow. 1.22 is the leading.
        chars_per_line = max(int(width_in * 72 / (0.55 * size)), 8)
        lines = 0
        for bullet in bullets:
            if not bullet:
                continue
            if bullet.startswith("**"):
                # Rendered as a larger bold sub-heading, so it costs more room
                # than a plain line and must be measured, not skipped.
                lines += max(1, -(-len(bullet) // max(int(width_in * 72 / (0.55 * (size + 3))), 8)))
                continue
            lines += max(1, -(-len(bullet) // chars_per_line))
        needed = (lines * size * 1.22 + max(3.0, size * 0.45) * max(lines - 1, 0)) / 72
        # Leave headroom: the real renderer wraps slightly differently, and
        # a slide that overflows hides its own text.
        if needed <= height_in * FIT_SAFETY_MARGIN:
            return size
        size -= 0.5
    return min_size


def _render_content(prs, slide, palette, block, slide_data, content_index):
    block = block or {}
    bg_image = block.get("bg_image")
    bg = block.get("backgroundColor") or palette["background"]
    if bg_image:
        _add_bg_picture(slide, bg_image)
    else:
        _set_bg(slide, bg)
    _place_block_elements(slide, block)
    accent = palette["accent"]
    primary = palette["primary"]
    text_color = _text_color_for(bg, block.get("textColor"), primary)

    design = block.get("design") or ("modern" if content_index % 2 else "minimal")
    layout = block.get("layout") or "default"
    bullets = slide_data.get("bullets", [])
    keyword = " ".join(slide_data.get("image_keywords", []) or re.findall(r"[a-zA-Z]{3,}", slide_data.get("title", ""))[:3])

    has_text = any(b and b.strip() and not b.startswith("**") for b in bullets)
    if block.get("type") == "image" or slide_data.get("type") == "image":
        # Dedicated image slide (from a template block or a promoted diagram):
        # the image/diagram alone fills the slide.
        layout = block.get("layout") or ("fullscreen" if bg_image else "full-image")
    elif layout == "default" and slide_data.get("image_url") and not bg_image:
        # The image must be supported by the slide's text: text on the LEFT,
        # image/diagram on the RIGHT. Only when no text supports it does the
        # image fill the slide on its own.
        layout = "with-image" if has_text else "full-image"
    if layout in ("image-left", "image-right"):
        # Always keep the text on the left so the panel reads left-to-right.
        layout = "with-image"

    st = slide_data.get("type")
    kicker = "Theory" if st == "theory" else ("Practical" if st == "practical" else None)

    if layout in ("fullscreen", "full-image"):
        _render_fullscreen_image(prs, slide, palette, block, slide_data, keyword, bullets)
        return

    base_y = _add_header(prs, slide, palette,
                         slide_data.get("title", f"Slide {content_index + 3}"),
                         slide_data.get("subtitle"),
                         design, accent, kicker=kicker)

    content_top = base_y + 0.12
    avail_h = SLIDE_H - 0.45 - content_top

    if layout == "with-image" and slide_data.get("image_url") and not bg_image:
        panel_w = 3.3
        content_w = CONTENT_W - panel_w - 0.25
        points = slide_data.get("image_content") or [
            b for b in bullets if b and b.strip() and not b.startswith("**")
        ]
        _add_image_panel(prs, slide, palette, MARGIN + content_w + 0.25, content_top, panel_w - 0.1, avail_h,
                         keyword, points=points, slide_data=slide_data)
        # The panel takes the right third; the generated text still needs the
        # left column or the slide would show the image alone.
        box = slide.shapes.add_textbox(Inches(MARGIN), Inches(content_top),
                                       Inches(content_w), Inches(avail_h))
        tf = box.text_frame
        tf.word_wrap = True
        _autofit_off(tf)
        _add_bullets(tf, bullets, _fit_font_size(bullets, content_w, avail_h, 15), text_color, accent)
    elif layout == "two-column":
        half = (len(bullets) + 1) // 2
        col_w = (CONTENT_W - 0.3) / 2
        for col_i, col_bullets in enumerate((bullets[:half], bullets[half:])):
            if not col_bullets:
                continue
            box = slide.shapes.add_textbox(Inches(MARGIN + col_i * (col_w + 0.3)), Inches(content_top),
                                           Inches(col_w), Inches(avail_h))
            tf = box.text_frame
            tf.word_wrap = True
            _autofit_off(tf)
            _add_bullets(tf, col_bullets, _fit_font_size(col_bullets, col_w, avail_h, 16), text_color, accent)
    else:
        box = slide.shapes.add_textbox(Inches(MARGIN), Inches(content_top),
                                       Inches(CONTENT_W), Inches(avail_h))
        tf = box.text_frame
        tf.word_wrap = True
        _autofit_off(tf)
        _add_bullets(tf, bullets, _fit_font_size(bullets, CONTENT_W, avail_h, 16), text_color, accent)


def _write_speaker_notes(slide, speaker_notes):
    if not speaker_notes:
        return
    try:
        notes_slide = slide.notes_slide
        notes_tf = notes_slide.notes_text_frame
        notes_tf.clear()
        if isinstance(speaker_notes, dict):
            lines = []
            if speaker_notes.get("opening_remarks"):
                lines.append(f"Opening: {speaker_notes.get('opening_remarks')}")
            points = speaker_notes.get("main_talking_points", [])
            if points:
                lines.append("Key points:")
                lines.extend(f"  • {p}" for p in points[:3])
            if speaker_notes.get("key_takeaway"):
                lines.append(f"Takeaway: {speaker_notes.get('key_takeaway')}")
            text = "\n".join(lines)
        else:
            text = str(speaker_notes)
        notes_tf.paragraphs[0].text = text
        notes_tf.paragraphs[0].font.size = Pt(10)
    except Exception:
        pass


def _bg_auto_text_color(bg_image_path, fallback: str = "#FFFFFF") -> str:
    """Pick black/white text based on the sampled luminance of a background image."""
    try:
        from PIL import Image

        img = Image.open(bg_image_path).convert("L")
        w, h = img.size
        pts = [
            (w // 2, int(h * 0.16)),
            (w // 2, int(h * 0.45)),
            (int(w * 0.28), int(h * 0.5)),
            (int(w * 0.72), int(h * 0.5)),
        ]
        lum = sum(img.getpixel(p) for p in pts) / len(pts)
        return "#1A1A1A" if lum >= 150 else fallback
    except Exception:
        return fallback


def _attach_template_backgrounds(blocked: dict[int, dict], slide_order: list | None,
                                 template_def: dict | None, base_template_path) -> None:
    """Attach ``bg_image`` to matching blocks when an uploaded PPTX template is used."""
    if not (template_def and template_def.get("background_source") == "pptx"):
        return
    if not base_template_path:
        return
    base = Path(base_template_path)
    if base.suffix.lower() != ".pptx" or not base.exists():
        return
    cache_dir = base.parent / f"{base.stem}_bg"
    try:
        from ..services.template_backgrounds import extract_slide_backgrounds

        backgrounds = extract_slide_backgrounds(base, cache_dir)
    except Exception:
        backgrounds = {}
    if not backgrounds:
        return
    for block in blocked.values():
        key = _bg_key(block.get("type", "content"), bool(block.get("layout") == "fullscreen"))
        if key == "image" and "image" not in backgrounds:
            key = "content_theory"
        path = backgrounds.get(key)
        if path and Path(path).exists():
            block["bg_image"] = str(path)
            if not block.get("textColor"):
                block["textColor"] = _bg_auto_text_color(path)


def _local_image_bytes(slide_data: dict) -> bytes | None:
    """Bytes of a visual lifted out of the user's own document, if any."""
    path = slide_data.get("image_local_path")
    if not path:
        return None
    try:
        data = Path(path).read_bytes()
    except Exception:
        return None
    return data or None


def _slide_image_spec(slide_data: dict, palette: dict) -> ImageSpec | None:
    """The image a content slide will need, or ``None`` if it needs none.

    A slide already carrying a document visual needs no download, so it is not
    prefetched.
    """
    diagram = slide_data.get("image_diagram")
    if not slide_data.get("image_url") and not diagram:
        return None
    if _local_image_bytes(slide_data):
        return None
    keyword = " ".join(slide_data.get("image_keywords", []) or re.findall(r"[a-zA-Z]{3,}", slide_data.get("title", ""))[:3])
    if not keyword.strip() and not diagram:
        return None
    points = slide_data.get("image_content") or [
        b for b in slide_data.get("bullets", []) if b and b.strip() and not b.startswith("**")
    ]
    return ImageSpec(
        keyword=keyword,
        primary=palette["primary"],
        secondary=palette["secondary"],
        accent=palette["accent"],
        background=palette["background"],
        points=points,
        diagram=diagram,
    )


def _prefetch_slide_images(slides: list[dict], palette: dict, blocked: dict[int, dict]) -> None:
    """Download every slide image in parallel before rendering starts."""
    specs = []
    for idx, slide_data in enumerate(slides):
        if slide_data.get("type") in ("cover", "outline", "end"):
            continue
        if (blocked.get(idx) or {}).get("bg_image"):
            continue  # the template supplies its own background picture
        spec = _slide_image_spec(slide_data, palette)
        if spec is not None:
            specs.append(spec)
    if not specs:
        return
    try:
        prefetch_images(specs)
    except Exception:
        # Image availability must never break the build; rendering falls back to
        # the local Pillow diagram inside fetch_image.
        pass


def _image_keyword_and_points(slide_data: dict) -> tuple[str, list[str]]:
    """The keyword and supporting lines a slide's image is resolved from."""
    keyword = " ".join(
        slide_data.get("image_keywords", [])
        or re.findall(r"[a-zA-Z]{3,}", slide_data.get("title", ""))[:3]
    )
    points = slide_data.get("image_content") or [
        b for b in slide_data.get("bullets", []) if b and b.strip() and not b.startswith("**")
    ]
    return keyword, points


def _should_promote_image(slide_data: dict, palette: dict) -> bool:
    """Whether this slide's visual deserves a full slide of its own.

    Text-dense visuals do: a document chart/diagram/table (marked upstream) or a
    locally generated Pillow infographic. An ordinary photo stays in the panel.
    """
    if not slide_data.get("image_url") and not slide_data.get("image_diagram"):
        return False
    if slide_data.get("type") in ("cover", "outline", "end", "image"):
        return False
    if slide_data.get("image_diagram"):
        # A planner-drawn diagram/flow always gets its own full slide.
        return True
    if slide_data.get("image_promote"):
        return True
    if _local_image_bytes(slide_data):
        # A document visual that was not marked dense (a photo) is fine inline.
        return False
    keyword, points = _image_keyword_and_points(slide_data)
    if not keyword.strip():
        return False
    try:
        primary, secondary, accent, background = image_render_colors(palette)
        return image_is_generated(keyword, primary, secondary, accent, background, points)
    except Exception:
        return False


def _promote_text_dense_images(slides: list[dict], palette: dict) -> list[dict]:
    """Give text-dense visuals a dedicated full slide right after their content.

    The content slide keeps its wording at full width, and the new image slide
    shows the chart/diagram as large as the slide allows so its labels stay
    readable. The deck grows by one slide per promoted visual.
    """
    promoted: list[dict] = []
    for slide_data in slides:
        if not _should_promote_image(slide_data, palette):
            promoted.append(slide_data)
            continue
        content = dict(slide_data)
        image_slide = dict(slide_data)
        generated = slide_data.get("image_diagram") is not None or not bool(_local_image_bytes(slide_data))
        for key in (
            "image_url", "image_keywords", "image_content", "image_diagram",
            "image_local_path", "image_caption", "image_source", "image_promote",
        ):
            content.pop(key, None)
        # The image slide is the visual plus its title/caption, not the bullets:
        # those are already on the slide before it, and the point here is size.
        image_slide["type"] = "image"
        image_slide["image_fit"] = "contain"
        # A generated infographic is drawn at the slide's own ratio, so it can
        # fill the whole slide edge to edge with no crop; a document figure keeps
        # its own ratio and is fitted whole below the header.
        image_slide["image_generated"] = generated
        image_slide["bullets"] = []
        image_slide["image_content"] = []
        image_slide["subtitle"] = slide_data.get("image_caption") or slide_data.get("subtitle")
        promoted.append(content)
        promoted.append(image_slide)
    return promoted


def build_pptx(
    slides: list[dict],
    image_slides: int,
    output_path: Path,
    logo_path: str | Path | None = None,
    palette_id: int = 1,
    template_def: dict | None = None,
    base_template_path: str | Path | None = None,
) -> Path:
    """Build a professional PPTX deck from the flat slide list."""
    if base_template_path:
        prs = Presentation(str(base_template_path))
    else:
        prs = Presentation()
        prs.slide_width = Inches(SLIDE_W)
        prs.slide_height = Inches(SLIDE_H)

    palette = dict(PALETTES.get(palette_id, PALETTES[1]))
    if template_def:
        style_data = template_def.get("styles") or {}
        for key in ("primary", "secondary", "accent", "background"):
            value = style_data.get(key)
            if value:
                palette[key] = value
    footer_text = (template_def or {}).get("footer_text")
    slide_order = (template_def or {}).get("slide_order")

    # Resolve and cache the images first so promotion can tell a real photo from
    # a locally generated, text-dense diagram. The later render-time fetch is a
    # cache hit.
    _prefetch_slide_images(slides, palette, {})
    slides = _promote_text_dense_images(slides, palette)
    for number, slide_data in enumerate(slides, start=1):
        slide_data["slide_number"] = number

    blocked = _match_blocks(slides, slide_order)
    _attach_template_backgrounds(blocked, slide_order, template_def, base_template_path)
    total = len(slides)
    layout_index = 6 if len(prs.slide_layouts) > 6 else 0

    for idx, slide_data in enumerate(slides):
        slide = prs.slides.add_slide(prs.slide_layouts[layout_index])
        block = blocked.get(idx)
        slide_type = slide_data.get("type", "content")

        if slide_type == "cover":
            _render_cover(prs, slide, palette, block, slide_data, logo_path)
        elif slide_type == "outline":
            _render_outline(prs, slide, palette, block, slide_data)
        elif slide_type == "end":
            _render_end(prs, slide, palette, block, slide_data)
        else:
            # The outline can span several slides, so count the content slides
            # actually seen rather than assuming the outline is a single slide.
            content_index = sum(
                1
                for earlier in slides[:idx]
                if earlier.get("type") not in ("cover", "outline", "end")
            )
            _render_content(prs, slide, palette, block, slide_data, content_index)

        _add_footer(prs, slide, palette, footer_text, page_no=(idx + 1 if slide_type != "cover" else 0), total=total)
        _write_speaker_notes(slide, slide_data.get("speaker_notes"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(output_path)
    return output_path


def execute_python_template(
    script_path: Path,
    slides: list[dict],
    image_slides: int,
    output_path: Path,
    logo_path: str | Path | None,
    palette_id: int,
    template_def: dict | None = None,
) -> Path:
    """Execute a Python template script to generate the presentation."""
    namespace: dict = {"__name__": "__main__"}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(script_path, "r", encoding="utf-8") as f:
        code = f.read()

    exec(code, namespace)

    builder = namespace.get("build_template") or namespace.get("build_presentation")
    if not callable(builder):
        raise RuntimeError("Python template must define a callable named build_template or build_presentation")

    result = builder(
        slides=slides,
        image_slides=image_slides,
        output_path=output_path,
        logo_path=logo_path,
        palette_id=palette_id,
        template_def=template_def,
    )
    if isinstance(result, (str, Path)):
        return Path(result)
    return output_path