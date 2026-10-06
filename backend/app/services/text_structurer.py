"""Rules-based, LLM-free Text Structurer.

Turns arbitrary extracted text (plain text, ``.docx``, ``.pdf``) into a
universal structured contract used by the rest of the pipeline:

    PresentationData = {
        "title": str,
        "subtitle": str | None,
        "sections": [
            {
                "heading": str,
                "type": "theory" | "practical",
                "points": [str, ...],
            },
            ...
        ],
        "metadata": {
            "author": str | None,
            "date": str | None,
        },
    }

Headings are detected heuristically:
- lines prefixed with the "## " marker placed by the PDF/Word extractors
  (font-size / heading style based);
- numbered headings (``1. Objectives``, ``2. Methodology``);
- all-caps short lines;
- lines starting with a recognised labeller word (Introduction, Objectives,
  Practical Activities, Conclusion, ...);
- short title-case lines followed by a body line or bullet list.

Bullets are detected by leading markers (``-`` ``*`` ``\\u2022`` ``\\u2023``
``\\u25aa`` ``\\u25cf`` ``\\u25e6`` ``o`` ``>``).  Sections are classified
theory/practical by a small keyword lexicon.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .document_extractor import CAPTION_MARKER, HEADER_MARKER
from .text_normalizer import normalize_source_text

# ---------------------------------------------------------------------------
# Heuristic lexicons
# ---------------------------------------------------------------------------

STRONG_HEADING_WORDS = {
    "intro", "introduction", "background", "overview", "summary", "conclusion",
    "conclusions", "objectives", "objective", "agenda", "outline", "section",
    "chapter", "part", "module", "topic", "review", "key", "materials",
    "methods", "methodology", "results", "finding", "findings", "discussion",
    "discussions", "recommendation", "recommendations", "appendix", "reference",
    "references", "motivation", "problem", "aim", "aims", "goals", "definition",
    "definitions", "abstract", "acknowledgements", "practical", "practices",
    "practice", "activity", "activities", "statement", "significance",
    "limitations", "hypothesis", "premise", "references", "index", "contents",
    "mitigation", "adaptation", "interventions", "causes", "effects",
    "benefits", "strategies", "approaches", "risks", "management",
}

PRACTICAL_WORDS = [
    "practice", "practices", "exercise", "exercises", "activity", "activities",
    "implement", "implementation", "applied", "application", "applications",
    "apply", "how to", "tutorial", "guide", "hands-on", "workflow",
    "procedure", "procedures", "step-by-step", "steps", "demonstration",
    "demonstrate", "tool", "tools", "experiment", "lab", "assignment",
    "interactive", "case study", "checklist",
]

BULLET_CHAR_RE = re.compile(r"^\s*(?:[-*\u2022\u2023\u25aa\u25cf\u25e6o>])\s+")

NUMBERED_ITEM_RE = re.compile(r"^\s*(\d{1,2}|[ivxlc]+)[.)\]]\s*(.*)$")

AUTHOR_PREFIX_RE = re.compile(
    r"^\s*(?:by|presented\s+by|written\s+by|prepared\s+by|reported\s+by|"
    r"author[s]?:?)\s*:?\s+(.+)$",
    re.IGNORECASE,
)

DATE_RE = re.compile(
    r"\b(?:jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|sep\w*|"
    r"oct\w*|nov\w*|dec\w*)[.,]?\s+\d{1,2}(?:st|nd|rd|th)?(?:[,.]?\s*\d{2,4})?\b|"
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|"
    r"jul\w*|aug\w*|sep\w*|oct\w*|nov\w*|dec\w*)[.,]?\s*(?:\d{2,4})?\b|"
    r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b\d{4}\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Cleaning helpers
# ---------------------------------------------------------------------------


def _clean_point(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip()).strip()


def _split_sentences(paragraph: str, max_len: int = 220) -> List[str]:
    """Split a prose paragraph into sentence-level points."""
    paragraph = re.sub(r"\s+", " ", paragraph.strip())
    if not paragraph:
        return []
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", paragraph)
    out: List[str] = []
    buffer = ""
    for sentence in sentences:
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence.strip()
        if len(candidate) <= max_len:
            buffer = candidate
        else:
            if buffer:
                out.append(buffer)
            buffer = sentence.strip()
    if buffer:
        out.append(buffer)
    return [s.strip() for s in out if s.strip()]


def _is_char_bullet(line: str) -> bool:
    return bool(BULLET_CHAR_RE.match(line))


def _is_caption(line: str) -> bool:
    """A figure/table caption, marked by the document reader."""
    return line.startswith(CAPTION_MARKER)


def _strip_caption_marker(line: str) -> str:
    return line[len(CAPTION_MARKER):].strip() if line.startswith(CAPTION_MARKER) else line


def _strip_bullet_marker(line: str) -> str:
    return re.sub(BULLET_CHAR_RE, "", line).strip()


def _numbered_rest(line: str) -> str | None:
    """Return the text after a numbered marker, or None if not numbered."""
    match = NUMBERED_ITEM_RE.match(line)
    if not match:
        return None
    return match.group(2).strip()


def _looks_like_header(line: str, *, next_line: str | None = None) -> bool:
    """Heuristic heading detection for a single line."""
    line = line.strip()
    if not line:
        return False

    if line.startswith(HEADER_MARKER):
        return True

    # A caption is subordinate to its figure, never a section heading.
    if _is_caption(line):
        return False

    # Dash / bullet markers are never headers.
    if _is_char_bullet(line):
        return False

    numbered_rest = _numbered_rest(line)

    if numbered_rest is not None:
        # "1. Objectives of the Seminar" -> header; long sentences -> bullet.
        rest_words = numbered_rest.split()
        if numbered_rest.endswith(".") and len(rest_words) > 5:
            return False
        if len(rest_words) <= 9:
            return True
        return False

    words = line.split()
    word_count = len(words)
    lower = line.lower().rstrip(".")
    first_token = lower.split()[0].rstrip(".:,;") if lower else ""

    # All-caps short line.
    if line.isupper() and word_count <= 10 and len(line) <= 90:
        return True

    has_strong_word = first_token in STRONG_HEADING_WORDS or lower in STRONG_HEADING_WORDS
    if has_strong_word and word_count <= 12 and (not line.endswith(".") or word_count <= 5):
        return True

    # "Section 1: ...", "Chapter 3 ...", "Part II ..."
    if line.rstrip(":").startswith(("Section", "Chapter", "Part", "Module")):
        return True

    # Short label ending with a colon.
    if line.endswith(":") and word_count <= 8:
        return True

    # Title-case short line followed by a body line or a bullet list.
    if (
        word_count <= 10
        and len(line) <= 90
        and line[0].isupper()
        and not line.endswith((".", ",", ";", "!", "?"))
    ):
        next_wc = len(next_line.split()) if next_line else 0
        if next_line:
            if next_wc >= 4 or _is_char_bullet(next_line):
                return True

    return False


def _classify_section_type(heading: str, points: List[str]) -> str:
    haystack = " ".join([heading] + points).lower()
    for word in PRACTICAL_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", haystack):
            return "practical"
    return "theory"


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------


def _extract_metadata(lines: List[str]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {"author": None, "date": None}
    for line in lines:
        stripped = line.replace(HEADER_MARKER, "").strip()
        if not metadata["author"]:
            match = AUTHOR_PREFIX_RE.match(stripped)
            if match:
                metadata["author"] = match.group(1).strip().strip(":")
                continue
            if (
                stripped
                and not _is_char_bullet(stripped)
                and 1 <= len(stripped.split()) <= 4
                and len(stripped) <= 40
                and re.search(r"(?:,|prof|dr|mr|mrs|ms|ph\.?d|md)\b", stripped, re.IGNORECASE)
                and re.fullmatch(r"[A-Za-z .'\-]+(?:,?\s+(?:PhD|MD|Prof|Dr|MSc|MA|BA|BSc))?", stripped)
                and not stripped.rstrip(".").isupper()
            ):
                metadata["author"] = stripped.rstrip(".")
                continue
        if not metadata["date"]:
            date_match = DATE_RE.search(stripped)
            if date_match:
                metadata["date"] = date_match.group(0).strip()
    return metadata


def _is_metadata_line(line: str) -> bool:
    stripped = line.replace(HEADER_MARKER, "").strip()
    if AUTHOR_PREFIX_RE.match(stripped):
        return True
    if DATE_RE.search(stripped):
        return True
    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def structure_text(raw_text: str) -> Dict[str, Any]:
    """Parse raw text into the PresentationData contract.

    Returns:
        {
            "title": str,
            "subtitle": str | None,
            "sections": [{"heading", "type", "points"}],
            "metadata": {"author", "date"},
        }
    """
    empty = {"title": "", "subtitle": None, "sections": [], "metadata": {"author": None, "date": None}}
    if not raw_text or not raw_text.strip():
        return empty

    # Everything the three inputs share passes through the Markdown-aware
    # normaliser first. Without it a pasted answer from another model reaches
    # the deck verbatim: "### the two models", "| :--- | :--- |" and
    # "**down payment**" used to be shown as slide bullets.
    raw_text = normalize_source_text(raw_text)
    if not raw_text.strip():
        return empty

    lines: List[str] = [line.strip() for line in raw_text.splitlines() if line.strip()]

    metadata = _extract_metadata(lines)
    skip_indexes = {i for i, line in enumerate(lines) if _is_metadata_line(line)}

    # ---- Title / subtitle zone -------------------------------------------------
    zone = lines[:12]
    title = ""
    title_index = -1
    subtitle: str | None = None
    subtitle_index = -1

    for i, line in enumerate(zone):
        if i in skip_indexes or _is_char_bullet(line) or _is_caption(line):
            continue
        # A line the reader marked as a heading is a section, not the deck
        # title. Claiming it here left the material under it with no section to
        # belong to, so it surfaced as an "Overview" section instead.
        if line.startswith(HEADER_MARKER):
            continue
        if title:
            break
        stripped = line.replace(HEADER_MARKER, "").strip()
        words = stripped.split()
        # A title does not end in a full stop, and a long sentence that does is
        # body prose rather than a heading.
        if 2 <= len(words) <= 16 and stripped[0].isupper() and not stripped.endswith("."):
            title = stripped
            title_index = i

    # No prose title in the opening lines. The first marked heading is *not*
    # promoted to the title: doing so consumed the line, so the material under
    # it lost its section and resurfaced as an "Overview".
    if not title:
        title = "Presentation"

    # Subtitle: the next short, non-sentence line after the title, but stop at
    # the first real heading so a section title is never mistaken for a subtitle.
    if title_index != -1:
        for i in range(title_index + 1, len(zone)):
            if i in skip_indexes or _is_char_bullet(zone[i]):
                continue
            next_line = zone[i + 1] if i + 1 < len(zone) else None
            if _looks_like_header(zone[i], next_line=next_line):
                break
            stripped = zone[i].replace(HEADER_MARKER, "").strip()
            words = stripped.split()
            if 2 <= len(words) <= 16 and not stripped.endswith(".") and not _looks_like_header(stripped, next_line=None):
                subtitle = stripped
                subtitle_index = i
                break

    if title_index != -1:
        skip_indexes.add(title_index)
    if subtitle_index != -1:
        skip_indexes.add(subtitle_index)

    # ---- Section building -------------------------------------------------------
    sections: List[Dict[str, Any]] = []
    current_heading: str | None = None
    current_points: List[str] = []
    pending_captions: List[str] = []

    i = 0
    while i < len(lines):
        if i in skip_indexes:
            i += 1
            continue

        line = lines[i]
        next_line = lines[i + 1] if i + 1 < len(lines) else None

        if _looks_like_header(line, next_line=next_line):
            if current_heading is not None:
                sections.append({
                    "heading": current_heading,
                    "type": _classify_section_type(current_heading, current_points + pending_captions),
                    "points": current_points + pending_captions,
                })
                current_points = []
                pending_captions = []
            elif current_points or pending_captions:
                # Orphaned points before the first recognised header.
                sections.append({
                    "heading": "Overview",
                    "type": _classify_section_type("Overview", current_points + pending_captions),
                    "points": current_points + pending_captions,
                })
                current_points = []
                pending_captions = []
            numbered_rest = _numbered_rest(line)
            if numbered_rest is not None:
                current_heading = re.sub(r"\s+", " ", numbered_rest).strip().rstrip(".:")
            else:
                current_heading = line.replace(HEADER_MARKER, "").strip().rstrip(".:")
            i += 1
            continue

        if _is_caption(line):
            # Captions trail their section: kept as material, but after the
            # real content so they never lead a slide.
            caption = _clean_point(_strip_caption_marker(line))
            if caption:
                pending_captions.append(caption)
        elif _is_char_bullet(line):
            point = _clean_point(_strip_bullet_marker(line))
            if point:
                current_points.append(point)
        else:
            numbered_rest = _numbered_rest(line)
            if numbered_rest is not None and not _looks_like_header(line):
                point = _clean_point(numbered_rest)
                if point:
                    current_points.append(point)
            else:
                for sentence in _split_sentences(line):
                    if sentence:
                        current_points.append(sentence)

        i += 1

    if current_heading is not None:
        sections.append({
            "heading": current_heading,
            "type": _classify_section_type(current_heading, current_points + pending_captions),
            "points": current_points + pending_captions,
        })

    if not sections:
        sections.append({
            "heading": "Key Concepts & Overview",
            "type": "theory",
            "points": [p for p in current_points + pending_captions if p] or ["Summary of the source content."],
        })

    # Drop empty sections and sections whose heading duplicated the title.
    filtered: List[Dict[str, Any]] = []
    for section in sections:
        points = [p for p in section["points"] if p]
        if not points:
            continue
        if section["heading"] == title:
            continue
        filtered.append({
            "heading": section["heading"],
            "type": section["type"],
            "points": points,
        })
    sections = filtered

    return {
        "title": title,
        "subtitle": subtitle,
        "sections": sections,
        "metadata": metadata,
    }