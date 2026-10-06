"""Markdown-aware normalisation for every text input.

All three inputs -- pasted text, an uploaded ``.docx``/``.pdf`` and a plain
brief -- are written by a human or produced by another model, so they arrive
carrying Markdown: ``##`` headings, ``**bold**``, ``|a|b|`` tables, ``` fences,
``- `` lists and emoji. ``structure_text`` used to read that raw, which is why
a deck could show a slide titled "Key Concepts & Overview (part 3)" whose
bullets were "### 🔄 the two models" and "| :--- | :--- | :--- |".

This module is the single gate every source passes through before the text
structurer looks at a line. It rewrites Markdown into the plain markers the
rest of the pipeline already understands:

    "## Intro"            -> "## Intro"          (the extractor's heading marker)
    "### 🔄 The Two"      -> "## The Two"        (emoji dropped, level flattened)
    "**Sale:** a credit"  -> "Sale: A credit"
    "| A | B |"           -> "• A: B"
    "``` ... ```"         -> dropped
    "---"                 -> dropped

Only presentation markup is removed. No wording is rewritten, summarised or
invented: a table cell keeps its own sentence, it is just joined to its row
label so the line still reads as English on a slide.
"""

from __future__ import annotations

import re
import unicodedata

from .document_extractor import HEADER_MARKER

__all__ = [
    "normalize_source_text",
    "clean_inline_markdown",
    "collapse_whitespace",
    "strip_decoration",
]

# ---------------------------------------------------------------------------
# Line-level patterns
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s{0,3}(?:`{3,}|~{3,})")
_ATX_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_HR_RE = re.compile(r"^\s{0,3}(?:[-*_][ \t]*){3,}$")
_TABLE_RE = re.compile(r"^\s*\|.*\|[ \t]*$")
_TABLE_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")
_QUOTE_RE = re.compile(r"^\s{0,3}(?:>\s?)+")
_LIST_RE = re.compile(r"^(\s*)(?:[-*+•▪◦‣⁃])\s+")
_ORDERED_RE = re.compile(r"^\s*\d{1,3}[.)]\s+")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_URL_RE = re.compile(r"(?<![(\w])https?://\S+")
_WORD_RE = re.compile(r"[A-Za-z0-9]")

# Column headings that only restate the cell, so they are dropped when a table
# row is flattened onto one line.
_GENERIC_COLUMN_WORDS = {
    "", "-", "notes", "note", "detail", "details", "description", "comment",
    "comments", "example", "examples", "value", "content", "text", "meaning",
}

# A closing column that explains the row rather than describing it. Its cells
# are appended with a dash so "Why: prevents fraud" becomes
# "...; Model 2: mandatory -- prevents fraud".
_RATIONALE_COLUMN_WORDS = {
    "why", "why it matters", "why it's important", "why it is important",
    "reason", "rationale", "purpose", "benefit", "impact", "effect",
    "consequence", "note", "notes", "comment", "comments", "remark",
}


# ---------------------------------------------------------------------------
# Inline markdown
# ---------------------------------------------------------------------------

_INLINE_RULES: list[tuple[re.Pattern[str], str]] = [
    # Images before links, so "![alt](src)" does not become "![alt]".
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),
    (re.compile(r"!\[([^\]]*)\]\[[^\]]*\]"), r"\1"),
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    (re.compile(r"\[([^\]]+)\]\[[^\]]*\]"), r"\1"),
    (re.compile(r"<[^<>]{1,80}>"), ""),
    (re.compile(r"`+([^`]*)`+"), r"\1"),
    (re.compile(r"\*\*\*(\S(?:.*?\S)?)\*\*\*"), r"\1"),
    (re.compile(r"\*\*(\S(?:.*?\S)?)\*\*"), r"\1"),
    (re.compile(r"\*(\S(?:.*?\S)?)\*"), r"\1"),
    (re.compile(r"___(\S(?:.*?\S)?)___"), r"\1"),
    (re.compile(r"__(\S(?:.*?\S)?)__"), r"\1"),
    (re.compile(r"(?<![A-Za-z0-9_])_(\S(?:.*?\S)?)_(?![A-Za-z0-9_])"), r"\1"),
    (re.compile(r"~~(\S(?:.*?\S)?)~~"), r"\1"),
]

# Emoji, pictographs and the zero-width joiners that hold them together.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002600-\U000027BF"
    "\U00002B00-\U00002BFF"
    "\U0001F900-\U0001F9FF"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "\U00002190-\U000021FF"
    "\U00002300-\U000023FF"
    "\U000024C2"
    "\U00002B50-\U00002B55"
    "]"
)

# Symbols a technical document legitimately uses, so they survive the sweep.
_EMOJI_KEEP = {"°", "©", "®", "™", "±", "×", "÷", "§", "¶", "†", "‡", "°"}

# Pre-composed letters that must survive ("café" typed as e + combining acute).
_COMBINING_RE = re.compile(r"\u0300-\u036f")


def strip_decoration(text: str) -> str:
    """Drop emoji and stray variation selectors, keeping technical symbols."""
    text = _EMOJI_RE.sub("", text or "")
    out = []
    for char in text:
        if char in _EMOJI_KEEP:
            out.append(char)
            continue
        if ord(char) > 0x2000 and unicodedata.category(char) == "So":
            continue
        if char == "﻿":
            continue
        out.append(char)
    return "".join(out)


def collapse_whitespace(text: str) -> str:
    """Collapse every run of spaces/tabs into a single space."""
    return re.sub(r"[^\S\n]+", " ", text or "").strip()


# A space the source left in front of its own punctuation ("credit check .").
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:!?])")
_REPEATED_PUNCT_RE = re.compile(r"([.,;:])\1+")


def tidy_punctuation(text: str) -> str:
    """Repair the spacing artefacts Markdown sources are full of."""
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text or "")
    text = _REPEATED_PUNCT_RE.sub(r"\1", text)
    # "... agreement.;" -> "... agreement." when rows are joined with "; ".
    text = re.sub(r"([.;:]),", r"\1", text)
    return text.strip()


def clean_inline_markdown(text: str) -> str:
    """Strip inline markup from one line, keeping its wording."""
    if not text:
        return ""
    text = _HTML_COMMENT_RE.sub(" ", text)
    for pattern, replacement in _INLINE_RULES:
        text = pattern.sub(replacement, text)
    text = _URL_RE.sub("", text)
    text = collapse_whitespace(text)
    return tidy_punctuation(text)


def _strip_combining_marks(text: str) -> str:
    """Normalise decomposed accents so heading detection sees whole words."""
    return _COMBINING_RE.sub("", text)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _split_table_row(line: str) -> list[str]:
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    cells = row.split("|")
    return [clean_inline_markdown(cell) for cell in cells]


def _is_table_separator(cells: list[str]) -> bool:
    filled = [c.strip() for c in cells if c.strip()]
    return bool(filled) and all(_TABLE_SEP_CELL_RE.match(c) for c in filled)


def _short_column_label(header: str) -> str:
    """``"Model 1: Take Now, Pay Later (Credit Sale)"`` -> ``"Model 1"``.

    A two-column table needs no labels at all -- the row label and the value
    read as a sentence on their own. Three or more do, and the full heading is
    far too long for a slide, so the part before the colon is kept.
    """
    label = clean_inline_markdown(header or "").rstrip(":")
    if ":" in label:
        label = label.split(":", 1)[0]
    label = re.sub(r"\s*\([^)]*\)\s*", " ", label)
    label = collapse_whitespace(strip_decoration(label)).strip(" .:-")
    words = label.split()
    if len(words) > 4:
        label = " ".join(words[:4])
    return label


def _table_rows_to_bullets(rows: list[str]) -> list[str]:
    """Flatten a Markdown table into one readable bullet per body row."""
    grid = [_split_table_row(row) for row in rows]
    if not grid:
        return []

    header: list[str] = []
    if len(grid) >= 2 and _is_table_separator(grid[1]):
        header = grid[0]
        body = grid[2:]
    else:
        header = grid[0]
        body = grid[1:]

    labels = [_short_column_label(cell) for cell in header]
    bullets: list[str] = []
    for row in body:
        cells = [cell for cell in row if cell]
        if not cells or _is_table_separator(cells):
            continue
        label, values = cells[0], cells[1:]
        if not values:
            bullets.append(label)
            continue
        if len(header) <= 2:
            # Two columns: the row label plus the value already reads cleanly.
            rendered = "; ".join(values)
        else:
            parts = []
            for offset, value in enumerate(values):
                column = labels[offset + 1] if offset + 1 < len(labels) else ""
                lowered = column.lower().strip()
                # Cells already end in their own full stop; the semicolon that
                # joins them would otherwise read as "agreement.; Model 2:".
                value = value.rstrip(" .,;:")
                if not value:
                    continue
                if lowered in _RATIONALE_COLUMN_WORDS:
                    # The row above already said what each value is.
                    parts.append(value if offset == 0 else f"— {value}")
                elif lowered in _GENERIC_COLUMN_WORDS:
                    parts.append(value)
                else:
                    parts.append(f"{column}: {value}" if column else value)
            rendered = "; ".join(parts)
        # A cell that ends in its own full stop would double up against the
        # semicolon that joins it to the next column.
        bullets.append(f"{label.rstrip(' .,;:')}: {rendered}".strip())
    return bullets


# ---------------------------------------------------------------------------
# Line emission
# ---------------------------------------------------------------------------


def _push(out: list[str], line: str) -> None:
    """Append one output line, collapsing runs of blank separators into one.

    Lines are never merged together. Hard-wrapped prose stays hard-wrapped, so
    "Introduction" followed by its body keeps being two lines and the structurer
    can still tell the heading from the paragraph -- joining them destroyed every
    heading in the document.
    """
    if not line:
        if out and out[-1] == "":
            return
        out.append("")
        return
    if out and out[-1] == "":
        out.pop()
    out.append(line)


def _space(out: list[str]) -> None:
    """Request a blank separator before whatever is emitted next."""
    if out and out[-1] != "":
        out.append("")


def _emit_paragraph(out: list[str], line: str) -> None:
    text = clean_inline_markdown(line)
    text = collapse_whitespace(strip_decoration(text))
    text = _strip_combining_marks(text)
    if not text or not _WORD_RE.search(text):
        _push(out, "")
        return
    _push(out, text)


def _emit_heading(out: list[str], text: str) -> None:
    heading = collapse_whitespace(strip_decoration(clean_inline_markdown(text)))
    heading = _strip_combining_marks(heading).strip(" .:-#")
    if not heading or not _WORD_RE.search(heading):
        return
    _space(out)
    _push(out, f"{HEADER_MARKER}{heading}")
    _space(out)


def _emit_list_item(out: list[str], body: str, marker: str = "• ") -> None:
    text = collapse_whitespace(strip_decoration(clean_inline_markdown(body)))
    text = _strip_combining_marks(text).strip()
    if not text or not _WORD_RE.search(text):
        return
    _space(out)
    # "- " becomes the character bullet the structurer already detects; an
    # ordered item keeps its own number.
    _push(out, f"{marker}{text}")


def _emit_blockquote(out: list[str], line: str) -> None:
    body = _QUOTE_RE.sub("", line)
    text = collapse_whitespace(strip_decoration(clean_inline_markdown(body)))
    if not text or not _WORD_RE.search(text):
        return
    _space(out)
    _push(out, text)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def normalize_source_text(raw_text: str) -> str:
    """Turn any source text into the plain, marked-up form the structurer reads.

    The result uses only the markers the pipeline already understands: the
    ``HEADER_MARKER`` for headings and a character bullet for list items. Every
    other line is plain prose, which the structurer turns into sentences.
    """
    if not raw_text or not raw_text.strip():
        return ""

    text = raw_text.replace("\r\n", "\n").replace("\r", "\n").replace("\u2028", "\n")
    lines = text.split("\n")

    out: list[str] = []
    fence: str | None = None
    index = 0

    while index < len(lines):
        line = lines[index]

        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(0).strip()[0]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            index += 1
            continue
        if fence is not None:
            index += 1
            continue

        if not line.strip():
            _space(out)
            index += 1
            continue

        if _HR_RE.match(line):
            _space(out)
            index += 1
            continue

        if _TABLE_RE.match(line):
            table_lines: list[str] = []
            while index < len(lines) and _TABLE_RE.match(lines[index]):
                table_lines.append(lines[index])
                index += 1
            bullets = _table_rows_to_bullets(table_lines)
            if not bullets:
                _space(out)
                continue
            for bullet in bullets:
                _space(out)
                _push(out, f"• {bullet}")
            continue

        atx_match = _ATX_RE.match(line)
        if atx_match:
            _emit_heading(out, atx_match.group(2))
            index += 1
            continue

        if _QUOTE_RE.match(line):
            _emit_blockquote(out, line)
            index += 1
            continue

        list_match = _LIST_RE.match(line)
        if list_match:
            _emit_list_item(out, line[list_match.end():])
            index += 1
            continue

        if _ORDERED_RE.match(line):
            # "1. Objectives of the Seminar" is a numbered heading and
            # "1. Verify the ID" is a numbered bullet; only the structurer can
            # tell them apart, so the number is left in place for it.
            _emit_list_item(out, _ORDERED_RE.sub("", line), marker="")
            index += 1
            continue

        # A caption emitted by the document reader, or any other pre-marked
        # line, is passed through untouched apart from inline cleanup.
        if line.startswith("! "):
            caption = collapse_whitespace(clean_inline_markdown(line[2:]))
            if caption:
                _space(out)
                _push(out, f"! {caption}")
            index += 1
            continue

        if line.startswith(HEADER_MARKER):
            _emit_heading(out, line[len(HEADER_MARKER):])
            index += 1
            continue

        _emit_paragraph(out, line)
        index += 1

    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)