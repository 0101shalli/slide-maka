"""Deck Builder: deterministic, LLM-free slide assembly.

Consumes the universal ``PresentationData`` contract (produced by the rules-based
Text Structurer for text/files, or by the LLM only for prompt input) and emits a
flat ``list[dict]`` of slide descriptors that the PPTX generator renders.

Slide layout contract (matches the template repertory):
    cover    -> slide 1
    outline  -> slide 2
    content  -> slides 3 .. total-1   (theory / practical)
    end      -> final slide

The requested ``total_slides`` are produced exactly; the end slide is added as a
professional closer, so the final deck contains ``total_slides + 1`` slides.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .parameter_calculator import Distribution, image_slide_indices
from .practical_activities_generator import _get_default_activities
from .content_planner import plan_content
from .llm_structurer import select_slide_image

AUDIENCE_GUIDANCE = {
    "Beginner": "simple, clear and practical language",
    "Intermediate": "balanced theory and hands-on application",
    "Advanced": "authoritative depth and strategic insight",
}

# Words too generic to be useful as an image/diagram subject.
_IMAGE_STOPWORDS = {
    "the", "and", "of", "for", "with", "from", "that", "this",
    "introduction", "conclusion", "overview", "objectives", "section",
    "chapter", "fundamentals", "key", "concepts", "understanding",
    "practical", "activities", "seminar", "details", "content",
    "part", "using", "used", "based", "various", "different", "several",
    "important", "information", "example", "examples", "topic", "topics",
}

# Fallback subjects used so no two image slides in a deck repeat unnecessarily.
_CONCEPT_WORDS = ["concept", "principles", "framework", "strategy", "insight",
                  "structure", "summary", "process", "impact", "design"]

# Weight of "this visual came from the same document section as this slide".
# Set high enough to beat a coincidental word overlap, which can reach ~1.2.
SECTION_MATCH_BONUS = 2.0

_THEORY_SUBTITLES = {
    "Beginner": "Understanding the Fundamentals",
    "Intermediate": "Key Theoretical Concepts",
    "Advanced": "Advanced Theoretical Framework",
}

_PRACTICAL_SUBTITLES = {
    "Beginner": "Practical Application Guide",
    "Intermediate": "Practical Implementation",
    "Advanced": "Advanced Implementation Strategies",
}

# A trailing part marker on a title whose section was split over several slides.
_TITLE_PART_RE = re.compile(r"(?:[—–-]\s*Part\s*\d+|\(\d+\))\s*$")

# Longest bullet a slide will show, and the shortest a clipped bullet may be.
# The content planner already splits over-long lines at clause boundaries, so
# this is a backstop rather than the main length control.
MAX_BULLET_WORDS = 30
_MIN_CLIP_WORDS = 10

# ---------------------------------------------------------------------------
# Small deterministic content helpers
# ---------------------------------------------------------------------------


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _light_refine_bullet(bullet: str) -> str:
    bullet = bullet.strip()
    bullet = re.sub(r"^[•\-*\s]+", "", bullet)
    if not bullet:
        return "Key information point."
    bullet = re.sub(r"\s+", " ", bullet)
    bullet = bullet.capitalize()
    bullet = re.sub(r"(\.\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), bullet)
    if not bullet.endswith((".", "!", "?")):
        bullet += "."
    words = bullet.split()
    if len(words) > MAX_BULLET_WORDS:
        bullet = _clip_to_boundary(bullet)
    return bullet


def _clip_to_boundary(bullet: str) -> str:
    """Shorten an over-long line, but only where the text actually divides.

    The previous version took the first 18 words and appended a full stop, which
    is how slides ended up carrying "model 2: only after the." and
    "a down payment (e.g." -- fragments that say nothing. A line with no usable
    boundary inside the budget is returned as it stands: slightly long beats
    broken.
    """
    words = bullet.split()
    if len(words) <= MAX_BULLET_WORDS:
        return bullet

    candidate = " ".join(words[:MAX_BULLET_WORDS])
    position = max(candidate.rfind(". "), candidate.rfind("; "), candidate.rfind(" — "))
    if position > 0 and len(candidate[:position].split()) >= _MIN_CLIP_WORDS:
        return candidate[: position + 1].rstrip() + "."

    # No sentence break fits. Fall back to the last comma that still leaves a
    # substantial line, so the cut reads as a phrase rather than a stub.
    position = candidate.rfind(", ")
    if position > 0 and len(candidate[:position].split()) >= _MIN_CLIP_WORDS:
        return candidate[:position].rstrip(" ,;:") + "."

    return bullet


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title or "").strip().rstrip(".:;")
    # A "— Part 2" marker is set aside so the word budget below cannot truncate
    # it into a dangling "— Part".
    marker = ""
    match = _TITLE_PART_RE.search(title)
    if match:
        marker = match.group(0).strip()
        title = title[: match.start()].strip().rstrip(".:;")
    words = title.split()
    if not words:
        return "Topic Overview"
    if len(words) > 8:
        title = " ".join(words[:8])
    return f"{title} {marker}" if marker else title


def _image_hint(title: str, extra: str = "", bullets: Optional[List[str]] = None) -> list[str]:
    hints = []
    sources = [extra, title, *(bullets or [])]
    for source in sources:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]+", source or "")
        hints.extend(tokens)
    seen = []
    for token in hints:
        token_l = token.lower()
        if token_l in _IMAGE_STOPWORDS:
            continue
        if token_l not in seen and len(token) > 2:
            seen.append(token_l)
        if len(seen) >= 3:
            break
    return seen or ["presentation"]


def _distinct_image_keywords(slide: Dict[str, Any], used: List[tuple]) -> List[str]:
    """Propose image keywords that don't duplicate any subject used elsewhere."""
    title = slide.get("title", "")
    extra = slide.get("image_description", "") or ""
    bullet_sources = [b for b in slide.get("bullets", []) if b and b.strip() and not b.startswith("**")]
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]+", " ".join([extra, title, *bullet_sources]))
    seen = []
    for token in tokens:
        token_l = token.lower()
        if token_l in _IMAGE_STOPWORDS or len(token) <= 2:
            continue
        if any(token_l in used_tuple for used_tuple in used):
            continue
        if token_l not in seen:
            seen.append(token_l)
        if len(seen) >= 3:
            break
    if len(seen) >= 1:
        return seen[:3]
    fallback = _CONCEPT_WORDS[len(used) % len(_CONCEPT_WORDS)]
    return [fallback, "diagram"]


def _audience_cover_bullets(audience_level: str, author_name: Optional[str], author_email: Optional[str]) -> List[str]:
    if audience_level == "Beginner":
        bullets = [
            "Clear explanations of foundational concepts and ideas.",
            "Practical examples you can understand and remember.",
            "Step-by-step guidance for learning and improvement.",
        ]
    elif audience_level == "Advanced":
        bullets = [
            "Strategic insights and innovation opportunities.",
            "Advanced frameworks for complex problem-solving.",
            "Leadership and competitive advantage strategies.",
        ]
    else:
        bullets = [
            "Comprehensive analysis of key concepts and principles.",
            "Practical recommendations for effective implementation.",
            "Professional framework for decision-making.",
        ]
    if author_name:
        bullets.append(f"Prepared by {author_name}")
    if author_email:
        bullets.append(f"Contact: {author_email}")
    return bullets


def _default_speaker_notes(title: str, slide_type: str) -> Dict[str, Any]:
    return {
        "opening_remarks": f"Our next topic is: {title}",
        "main_talking_points": [
            "Highlight the key concepts on this slide",
            "Connect the ideas to a real-world example",
            "Invite audience input or questions",
        ],
        "audience_engagement": "Feel free to ask questions about this topic",
        "time_estimate": 90,
        "key_takeaway": f"Remember: {title} is important",
        "transition_to_next": "Let's continue with the next point.",
    }


def _subtitle_for(slide_type: str, audience_level: str) -> str:
    if slide_type == "practical":
        return _PRACTICAL_SUBTITLES.get(audience_level, "Practical Implementation")
    return _THEORY_SUBTITLES.get(audience_level, "Key Concepts")


def _expansion_bullets(title: str, slide_type: str, audience_level: str) -> List[str]:
    """Deterministic filler bullets so a slide is never left with a single line."""
    if slide_type == "practical":
        by_level = {
            "Beginner": [
                "Use the steps below to apply this approach in a simple, guided scenario.",
                "A worked example shows exactly how the steps fit together.",
                "Repeat the steps a few times to build confidence and accuracy.",
            ],
            "Intermediate": [
                "Follow a clear, repeatable process to put this approach into practice.",
                "Best practices here produce consistent and measurable results.",
                "Check the outcomes at each step to avoid common mistakes.",
            ],
            "Advanced": [
                "Integrate this approach into existing systems and larger workflows.",
                "Evaluate the impact using performance metrics and measured outcomes.",
                "Refine the process based on the results and team feedback.",
            ],
        }
    else:
        by_level = {
            "Beginner": [
                "This section explains the key ideas and why they matter, using simple language.",
                "Important definitions are introduced before the concept is taken further.",
                "Everyday examples make the main points easy to remember.",
            ],
            "Intermediate": [
                "This section builds a structured understanding of the concept and its context.",
                "The key principles are linked to professional decision-making in practice.",
                "Evidence and examples clarify when this concept applies.",
            ],
            "Advanced": [
                "The concept is analysed at a strategic level, including its trade-offs.",
                "The framework is compared with alternative models used in the field.",
                "Mastering these ideas supports leadership and innovation.",
            ],
        }
    return by_level.get(audience_level, by_level["Intermediate"])[:3]


def _enrich_bullets(
    bullets: List[str],
    title: str,
    slide_type: str,
    audience_level: str,
) -> List[str]:
    """Return the document's own lines, padded only when there are none to show.

    A slide that already carries real extracted text is never padded with the
    generic expansions below: those lines describe the deck rather than the
    document, and they used to make up roughly a third of the bullets on a
    file-upload deck.
    """
    cleaned = []
    for bullet in bullets:
        b = _light_refine_bullet(bullet)
        if b and b != "Key information point.":
            cleaned.append(b)
    # Only a slide with nothing at all from the document is padded, and then it
    # is filled properly so the layout does not show a single stranded line.
    target = 3 if not cleaned else MIN_CONTENT_ROWS
    if len(cleaned) >= target:
        return cleaned

    existing = {b.lower()[:24] for b in cleaned}
    for filler in _expansion_bullets(title, slide_type, audience_level):
        if len(cleaned) >= target:
            break
        key = filler.lower()[:24]
        if key not in existing:
            cleaned.append(filler)
            existing.add(key)
    return cleaned


# ---------------------------------------------------------------------------
# Raw slide -> structured content slide
# ---------------------------------------------------------------------------


# Rows a content slide may use. The LLM material is always laid out first, so a
# nested "**Practical Activities:**" sub-block can never push generated text
# out of the slide.
MAX_CONTENT_ROWS = 6

# Real extracted lines a slide shows before the deck considers adding anything.
# A slide that already has the document's own wording is never padded, even with
# a single line: the accompanying visual covers the rest, and invented
# meta-commentary is exactly what "do not summarise the slides" rules out.
MIN_CONTENT_ROWS = 1

def _structured_content_slide(
    slide_number: int,
    title: str,
    bullets: List[str],
    slide_type: str,
    audience_level: str,
    image_description: str = "",
    subtitle: Optional[str] = None,
) -> Dict[str, Any]:
    title = _clean_title(title)
    refined = [_light_refine_bullet(b) for b in bullets]
    refined = [r for r in refined if r and r != "Key information point."]

    # The content planner already routes hands-on material onto practical slides
    # and keeps them within the row budget, so there is no nested
    # "**Practical Activities:**" sub-block to build here any more. It used to
    # leave a blank row and a literal marker on the slide.
    structured = _enrich_bullets(refined, title, slide_type, audience_level)

    return {
        "slide_number": slide_number,
        "title": title,
        "subtitle": subtitle or _subtitle_for(slide_type, audience_level),
        "bullets": structured,
        "type": slide_type,
        "image_description": image_description,
        "speaker_notes": _default_speaker_notes(title, slide_type),
    }


def _figure_tokens(figure: Any) -> set[str]:
    """Meaningful words a figure can be matched on (caption + its section)."""
    tokens: set[str] = set()
    if isinstance(figure, dict):
        haystack = " ".join(
            str(figure.get(key) or "") for key in ("caption", "section", "title", "name")
        )
    else:
        haystack = f"{getattr(figure, 'caption', '')} {getattr(figure, 'section', '')}"
    for token in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", haystack or ""):
        lowered = token.lower()
        if lowered not in _IMAGE_STOPWORDS:
            tokens.add(lowered)
    return tokens


def _slide_match_text(slide: Dict[str, Any]) -> str:
    return " ".join(
        [slide.get("title", "") or "", slide.get("image_description", "") or ""]
        + [b for b in slide.get("bullets", []) if b and not b.startswith("**")]
    )


def _score_figure(figure: Any, slide_text_tokens: set[str], figure_tokens: set[str]) -> float:
    """How well a document visual fits a slide, by shared subject words.

    Scored on how much of the *figure's* identity the slide confirms, not on
    how many words overlap. A single shared word used to be enough to pull a
    chart from one section onto an unrelated slide -- "a model is reproducible"
    was enough to claim the training-loss figure. A visual now has to be mostly
    accounted for by the slide's wording before it is considered a match, and a
    lone word is never enough on its own.
    """
    if not figure_tokens or not slide_text_tokens:
        return 0.0
    shared = figure_tokens & slide_text_tokens
    if not shared:
        return 0.0
    coverage = len(shared) / len(figure_tokens)
    if coverage < MIN_FIGURE_COVERAGE:
        return 0.0
    if len(shared) < MIN_FIGURE_SHARED_WORDS and len(figure_tokens) > 2:
        return 0.0
    return coverage * min(len(shared), 4) ** 0.5


# A visual's caption must be at least this fraction confirmed by the slide, and
# must agree on at least this many words when the caption is long enough for a
# single shared word to be meaningless.
MIN_FIGURE_COVERAGE = 0.34
MIN_FIGURE_SHARED_WORDS = 2


def _normalise_heading(text: str) -> str:
    """Comparable form of a heading: "3. Results" and "Results" both -> "results".

    Only true noise words are dropped: unlike _IMAGE_STOPWORDS this keeps
    "introduction" and "overview", which are the very words a section heading is
    matched on.
    """
    stripped = re.sub(r"^\s*(?:\d+(?:\.\d+)*[.)]?|[IVXLC]+[.)])\s*", "", text or "")
    stripped = re.sub(r"\s*[:–—-]\s*.*$", "", stripped)
    # "(continued)" and "(part 2)" are deck-added decorations, not the subject.
    stripped = re.sub(r"\s*\([^)]*\)", "", stripped)
    words = re.findall(r"[a-z0-9]+", stripped.lower())
    return " ".join(w for w in words if w not in _HEADING_NOISE_WORDS)


_HEADING_NOISE_WORDS = {"the", "and", "of", "for", "with", "from", "part", "a", "an", "to"}


def _section_affinity(figure: Any, slide: Dict[str, Any]) -> float:
    """Bonus when a visual was lifted from the same document section as the slide.

    Every content slide is built from exactly one section of the source, and each
    extracted figure records the section it came from, so the origin is a far
    stronger signal than word overlap. A chart in "3. Results" belongs on the
    "3. Results" slide even if that slide's wording shares no words with it.
    """
    if isinstance(figure, dict):
        section = figure.get("section")
    else:
        section = getattr(figure, "section", None)
    fig_section = _normalise_heading(section or "")
    if not fig_section:
        return 0.0

    slide_section = _normalise_heading(slide.get("title", "") or "")
    if not slide_section:
        return 0.0
    if fig_section == slide_section:
        return SECTION_MATCH_BONUS
    # "3. Results" vs "3. Results (part 2)" / "3. Results: In Focus".
    if slide_section.startswith(fig_section) or fig_section.startswith(slide_section):
        return SECTION_MATCH_BONUS * 0.8
    return 0.0


def _attach_document_figures(
    slides: List[Dict[str, Any]],
    figures: Optional[List[Any]],
    image_slides: int,
) -> List[Dict[str, Any]]:
    """Give image slides a real visual from the uploaded document when one fits.

    A figure is only used where the deck already wants an image, and each figure
    is used at most once. Slides with no good match keep the keyword-based image
    so an image slide is never left empty.
    """
    if not figures or not slides:
        return slides

    candidates: List[Dict[str, Any]] = []
    for idx, slide in enumerate(slides):
        if not slide.get("image_url"):
            continue
        text_tokens = {
            token.lower()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", _slide_match_text(slide))
            if token.lower() not in _IMAGE_STOPWORDS
        }
        best_score = 0.0
        best = None
        for figure in figures:
            score = _score_figure(figure, text_tokens, _figure_tokens(figure))
            score += _section_affinity(figure, slide)
            if score > best_score:
                best_score, best = score, figure
        if best is not None:
            candidates.append({"index": idx, "score": best_score, "figure": best})

    if not candidates:
        return slides

    # Best matches first, so a strongly-matching visual is never crowded out.
    candidates.sort(key=lambda item: item["score"], reverse=True)
    used: set[int] = set()
    for item in candidates:
        figure = item["figure"]
        key = id(figure)
        if key in used:
            continue
        used.add(key)
        slide = slides[item["index"]]
        path = figure.get("path") if isinstance(figure, dict) else getattr(figure, "path", None)
        if path and Path(path).exists():
            slide["image_local_path"] = str(path)
            caption = (
                figure.get("caption") if isinstance(figure, dict) else getattr(figure, "caption", "")
            ) or ""
            kind = (
                figure.get("kind") if isinstance(figure, dict) else getattr(figure, "kind", "figure")
            ) or "figure"
            slide["image_source"] = f"document:{kind}"
            # A chart, diagram, table or generic figure carries labels too small
            # to read in the side panel, so the renderer gives it a full slide of
            # its own. A plain photo stays in the panel.
            if kind in _DENSE_FIGURE_KINDS:
                slide["image_promote"] = True
            if caption:
                slide["image_caption"] = caption
                _drop_duplicate_caption_bullet(slide, caption)
    return slides


def _caption_key(text: str) -> str:
    """Normalised form of a caption, so "Figure 1. Loss." matches "figure 1 loss"."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return " ".join(
        w for w in words
        if w not in _FIGURE_LABEL_WORDS and not w.isdigit()
    )


_FIGURE_LABEL_WORDS = {"figure", "fig", "table", "chart", "diagram", "image", "exhibit", "no", "n"}

# Document visual kinds that carry text too small for a side panel. A "photo"
# is excluded: it reads fine at panel size and does not need its own slide.
_DENSE_FIGURE_KINDS = {"diagram", "chart", "table", "figure"}


def _drop_duplicate_caption_bullet(slide: Dict[str, Any], caption: str) -> None:
    """Remove a bullet that only restates the caption now shown on the visual.

    A section split across slides pushes its trailing caption to the head of the
    next slide, where it reads as filler; the visual already carries the text.
    """
    key = _caption_key(caption)
    if not key:
        return
    kept = [
        bullet
        for bullet in slide.get("bullets", [])
        if _caption_key(bullet) != key
    ]
    if kept and len(kept) != len(slide.get("bullets", [])):
        slide["bullets"] = kept


def _attach_image_slots(
    slides: List[Dict[str, Any]],
    image_slides: int,
    figures: Optional[List[Any]] = None,
    visual_plan: Optional[Dict[int, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    content_count = len(slides)
    image_indices = set(image_slide_indices(max(content_count, 1), image_slides))
    if figures:
        image_indices = _prefer_slides_with_figures(slides, image_indices, figures)
    # A slide the planner read as a process or a breakdown earns a visual of its
    # own even if the requested image budget did not reach it.
    for idx, spec in (visual_plan or {}).items():
        if 0 <= idx < content_count and spec.get("kind") in ("flow", "diagram"):
            image_indices.add(idx)

    used_keywords: List[tuple] = []
    for idx, slide in enumerate(slides):
        if idx not in image_indices:
            continue
        plan = (visual_plan or {}).get(idx) or {}
        points = [b for b in slide.get("bullets", []) if b and b.strip() and not b.startswith("**")]
        kind = plan.get("kind")
        if plan.get("query"):
            keywords = [plan["query"]]
        else:
            keywords = _image_hint(
                slide.get("title", ""), slide.get("image_description", ""), bullets=points
            )
        if kind in (None, "photo") and tuple(keywords) in used_keywords:
            keywords = _distinct_image_keywords(slide, used_keywords)
        used_keywords.append(tuple(keywords))
        slide["image_url"] = select_slide_image(" ".join(keywords))
        slide["image_keywords"] = keywords
        slide["image_content"] = points[:4]
        if kind in ("flow", "diagram"):
            diagram: Dict[str, Any] = {
                "title": plan.get("flow_title") or slide.get("title", ""),
            }
            if plan.get("steps"):
                diagram["steps"] = plan["steps"]
            if plan.get("points"):
                diagram["points"] = plan["points"]
            # A diagram/flow is drawn locally and always takes a full slide, so
            # its labels stay legible instead of being shrunk into a panel.
            slide["image_diagram"] = diagram
            slide["image_promote"] = True
            slide["image_caption"] = plan.get("caption") or slide.get("subtitle")
    if figures:
        _attach_document_figures(slides, figures, image_slides)
    return slides


def _prefer_slides_with_figures(
    slides: List[Dict[str, Any]],
    image_indices: set,
    figures: List[Any],
) -> set:
    """Nudge the image slots onto the slides a document visual actually belongs to.

    Slots were spread by position alone, so a chart lifted from "3. Model
    Training" went unused whenever no slot happened to land on that section,
    and the deck showed a stock photo instead. The requested number of image
    slides is unchanged; only which slides they land on is adjusted.
    """
    wanted = max(len(image_indices), 0)
    if wanted == 0:
        return image_indices

    def affinity(idx: int) -> float:
        slide = slides[idx]
        tokens = {
            token.lower()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", _slide_match_text(slide))
            if token.lower() not in _IMAGE_STOPWORDS
        }
        best = 0.0
        for figure in figures:
            score = _score_figure(figure, tokens, _figure_tokens(figure)) + _section_affinity(figure, slide)
            if score > best:
                best = score
        return best

    ranked = sorted(range(len(slides)), key=lambda i: (-affinity(i), i))
    keep = set(ranked[:wanted])
    # Never take a slide away from a slot that already has a strong match.
    for idx in image_indices:
        if len(keep) >= wanted and affinity(idx) > 0 and idx not in keep:
            weakest = min((i for i in keep if i not in image_indices), key=affinity, default=None)
            if weakest is not None and affinity(weakest) < affinity(idx):
                keep.discard(weakest)
                keep.add(idx)
    return keep


_GENERIC_TAKEAWAY_RE = re.compile(
    r"\b(this section|use the steps|follow a clear|best practices here|"
    r"check the outcomes|integrate this approach|evaluate the impact|"
    r"refine the process|the concept is analysed|the framework is compared|"
    r"mastering these ideas|repeat the steps|a worked example|"
    r"important definitions|everyday examples|key takeaway|summary point|"
    r"action item|recap)\b",
    re.IGNORECASE,
)


def _pick_takeaway(points: List[str]) -> str:
    """Prefer the most content-rich point; ignore deterministic filler text."""
    for point in reversed(points or []):
        if point and not _GENERIC_TAKEAWAY_RE.search(point):
            return point
    return (points[-1] if points else "Key point covered in the session.")


def _build_takeaways_slide(content: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Recap slide listing every content slide's key takeaway with a short
    explanation, so the close of the deck recaps the whole presentation.

    Each line repeats its slide's own best line, so the count is bounded by
    what the slide can hold: an unbounded recap overflowed the text box and
    pushed the closing slides off the deck.
    """
    entries: List[str] = []
    for slide in content:
        title = _clean_title(slide.get("title", "")) or "Key point"
        # "(part 2)" is a layout artefact of splitting a section across slides;
        # repeating it in the recap just looks like a typo.
        base = _split_base_heading(title)
        if base != title:
            title = base
        points = [b for b in slide.get("bullets", []) if b and b.strip() and not b.startswith("**")]
        takeaway = _pick_takeaway(points)
        entry = f"**{title}:** {_shorten_takeaway(_strip_repeated_label(title, _light_refine_bullet(takeaway)))}"
        if any(entry == existing or existing.startswith(f"**{title}:**") for existing in entries):
            # Two slides of the same section: one recap line is enough.
            continue
        entries.append(entry)

    if not entries:
        return {
            "slide_number": 3 + len(content),
            "title": "Key Takeaways",
            "subtitle": "Recap of the main ideas covered in this session",
            "bullets": ["Summarize the most important ideas covered in this presentation."],
            "type": "takeaways",
        }

    shown = entries[:MAX_TAKEAWAY_LINES]
    if len(entries) > len(shown):
        shown[-1] = f"... and {len(entries) - len(shown) + 1} more key points"
    return {
        "slide_number": 3 + len(content),
        "title": "Key Takeaways",
        "subtitle": "Recap of the main ideas covered in this session",
        "bullets": shown,
        "type": "takeaways",
    }


# A recap line is a title plus a shortened quote; more than this cannot be read
# on one slide at the layout's leading.
MAX_TAKEAWAY_LINES = 6


def _shorten_takeaway(text: str, limit: int = 78) -> str:
    """Trim a recap quote to its first clause so the line stays on one or two rows."""
    if len(text) <= limit:
        return text
    # "e.g. " and "i.e. " contain a ". " that is not a sentence break, so a
    # sentence cut is only taken when the period is followed by a capital.
    sentence = re.search(r"\.\s+(?=[A-Z])", text[: limit + 2])
    if sentence:
        return text[: sentence.start() + 1].rstrip()
    for marker in ("; ", ", and ", ", which ", ", so "):
        cut = text.find(marker)
        if 0 < cut <= limit:
            return text[:cut].rstrip() + "."
    return text[: limit - 1].rsplit(" ", 1)[0] + "..."


def _strip_repeated_label(title: str, text: str) -> str:
    """Drop a line's own ``Label:`` when the recap already prints it."""
    match = re.match(r"^([^:]{3,60}):\s+", text)
    if match and match.group(1).strip().lower() == title.strip().lower():
        return text[match.end():]
    return text


# ---------------------------------------------------------------------------
# Deterministic deck (text / file inputs — no LLM)
# ---------------------------------------------------------------------------


def _split_base_heading(heading: str) -> str:
    return _TITLE_PART_RE.sub("", heading).strip()


def _build_outline(
    content: List[Dict[str, Any]],
    total_slides: int,
    theory_positions,
    title: str = "",
) -> List[str]:
    """Build a three-act outline from the final content slides.

    The outline is grouped under ``**Opening**`` / ``**Core Topics**`` /
    ``**Closing**`` act markers (rendered as distinct accent headings by the
    PPTX generator) and each topic is tagged with the slide's theory/practice
    role so the user can see at a glance how the requested distribution is
    applied.

    The opening entry is the presentation's own title (falling back to the first
    content slide), so the outline opens with the actual subject instead of a
    generic "Title & Context" placeholder.
    """
    opening = _clean_title(title)
    if not opening and content:
        opening = _clean_title(content[0].get("title", ""))
    items = ["**Opening**", f"1. {opening or 'Introduction'}"]
    if content:
        items.append("**Core Topics**")
        positions = set(theory_positions)
        for i, slide in enumerate(content):
            tag = "Theory" if i in positions else "Practice"
            items.append(f"{i + 2}. {slide.get('title', '')} ({tag})")
    items.append("**Closing**")
    items.append(f"{len(content) + 2}. Key Takeaways & Next Steps")
    return items


# The outline text box is 3.6" tall at 15pt, which fits a touch over ten rows.
# One row is a single topic; act markers (``**Opening**`` ...) are rows too.
MAX_OUTLINE_ROWS = 10


def _is_outline_header(item: str) -> bool:
    stripped = (item or "").strip()
    return stripped.startswith("**") and stripped.endswith("**")


def _paginate_outline(
    items: List[str],
    max_rows: int = MAX_OUTLINE_ROWS,
) -> List[List[str]]:
    """Split the outline into slide-sized pages without orphaning an act marker.

    The topics are numbered once by ``_build_outline`` and the numbers keep
    counting across pages, so a reader can follow the outline from one slide to
    the next. A page that would otherwise end on ``**Core Topics**`` (an act
    marker with no topics under it) pushes the marker to the next page.
    """
    pages: List[List[str]] = []
    current: List[str] = []
    for item in items:
        if len(current) >= max_rows:
            pages.append(current)
            current = []
        current.append(item)
    if current:
        pages.append(current)
    if not pages:
        return [[]]

    # Never leave an act marker dangling at the foot of a page.
    for index in range(len(pages) - 1):
        if pages[index] and _is_outline_header(pages[index][-1]):
            pages[index + 1].insert(0, pages[index].pop())
    return [page for page in pages if page]


def _outline_slides(
    content: List[Dict[str, Any]],
    total_slides: int,
    theory_positions,
    title: str,
) -> List[Dict[str, Any]]:
    """One or more outline slides, continuing the outline when it runs long."""
    pages = _paginate_outline(
        _build_outline(content, total_slides, theory_positions, title)
    )
    total = len(pages)
    slides: List[Dict[str, Any]] = []
    for index, page in enumerate(pages):
        if index == 0:
            page_title = "Presentation Outline"
        else:
            page_title = f"Presentation Outline ({index + 1}/{total})"
        slides.append(
            {
                "slide_number": index + 2,
                "title": page_title,
                "bullets": page,
                "type": "outline",
            }
        )
    return slides


def _content_slide_from_plan(
    slide_number: int,
    planned: Any,
    audience_level: str,
) -> Dict[str, Any]:
    """Turn one planner result into the slide dict the renderer consumes."""
    title = _clean_title(planned.title) or "Key Points"
    bullets = [bullet for bullet in planned.bullets if bullet and bullet.strip()]
    if not bullets:
        return {}

    slide = _structured_content_slide(
        slide_number=slide_number,
        title=title,
        bullets=bullets,
        slide_type=planned.type,
        audience_level=audience_level,
        image_description=planned.image_description or "",
        # The planner knows which section the slide came from, which says more
        # than a generic "Understanding the Fundamentals" strapline.
        subtitle=_clean(planned.subtitle) or None,
    )
    if slide.get("type") == "practical":
        slide["activities"] = _get_default_activities()
    return slide


def _assemble_deck(
    content: List[Dict[str, Any]],
    distribution: Distribution,
    audience_level: str,
    title: str,
    author_name: Optional[str],
    author_email: Optional[str],
    subtitle: Optional[str],
    figures: Optional[List[Any]],
) -> List[Dict[str, Any]]:
    """Wrap finished content slides in the cover, outline, recap and end slides.

    Both input paths converge here, so the deck shape is identical whatever the
    source was: ``content_slides + 4``, which is exactly the number the slide
    calculator reserved.
    """
    total_slides = max(distribution.total_slides, 4)

    cover = {
        "slide_number": 1,
        "title": _clean_title(title) or "Presentation",
        "subtitle": subtitle or None,
        "bullets": _audience_cover_bullets(audience_level, author_name, author_email),
        "type": "cover",
    }

    theory_positions = {
        index
        for index, slide in enumerate(content)
        if slide.get("type") == "theory"
    }
    outline_slides = _outline_slides(content, total_slides, theory_positions, title)

    visual_plan: Dict[int, Dict[str, Any]] = {}
    try:
        from .visual_planner import plan_visuals

        visual_plan = plan_visuals(content, audience_level)
    except Exception:
        # Visuals are best-effort: the keyword heuristic is the fallback.
        visual_plan = {}
    content = _attach_image_slots(content, distribution.image_slides, figures, visual_plan)
    takeaways = _build_takeaways_slide(content)

    end = {
        "slide_number": 0,
        "title": "Thank You",
        "subtitle": None,
        "bullets": [
            "Questions & discussion",
            *([f"Prepared by {author_name}"] if author_name else []),
            *([f"Contact: {author_email}"] if author_email else []),
        ],
        "type": "end",
    }

    slides = [cover] + outline_slides + content + [takeaways, end]
    # The outline may span several slides, so number the deck once at the end.
    for number, slide in enumerate(slides, start=1):
        slide["slide_number"] = number
    return slides


def build_deterministic_deck(
    presentation_data: Dict[str, Any],
    distribution: Distribution,
    audience_level: str,
    title: str,
    author_name: Optional[str] = None,
    author_email: Optional[str] = None,
    figures: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """Assemble a full deck from structured text without any LLM call."""
    plan = plan_content(
        presentation_data.get("sections", []), distribution, audience_level
    )

    content: List[Dict[str, Any]] = []
    for index, planned in enumerate(plan.slides):
        slide = _content_slide_from_plan(index + 3, planned, audience_level)
        if slide:
            content.append(slide)

    return _assemble_deck(
        content,
        distribution,
        audience_level,
        title,
        author_name,
        author_email,
        presentation_data.get("subtitle"),
        figures,
    )


# ---------------------------------------------------------------------------
# Prompt deck (the ONLY input that touches the LLM)
# ---------------------------------------------------------------------------


def build_prompt_deck(
    llm_slides: List[Dict[str, Any]],
    distribution: Distribution,
    audience_level: str,
    title: str,
    author_name: Optional[str] = None,
    author_email: Optional[str] = None,
    figures: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """Wrap LLM-structured slides into the full deck (cover / outline / end added here).

    The LLM only produces material. It does not get to decide how many slides
    the deck has or how they are mixed, so its output is fed through the same
    planner the text and file inputs use.
    """
    sections = _sections_from_llm_slides(llm_slides)
    plan = plan_content(sections, distribution, audience_level)

    content: List[Dict[str, Any]] = []
    for index, planned in enumerate(plan.slides):
        slide = _content_slide_from_plan(index + 3, planned, audience_level)
        if slide:
            content.append(slide)

    return _assemble_deck(
        content,
        distribution,
        audience_level,
        title,
        author_name,
        author_email,
        subtitle=None,
        figures=figures,
    )


def _sections_from_llm_slides(llm_slides: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Present the model's slide list in the planner's section contract."""
    sections: List[Dict[str, Any]] = []
    for index, slide in enumerate(llm_slides or []):
        bullets = [b for b in (slide.get("bullets") or []) if b and str(b).strip()]
        if not bullets:
            continue
        heading = _clean_title(slide.get("title") or f"Section {index + 1}")
        sections.append({
            "heading": heading,
            "type": (slide.get("type") or "theory").strip().lower(),
            "points": [str(b) for b in bullets],
            "image_description": slide.get("image_description", "") or "",
        })
    return sections


# ---------------------------------------------------------------------------
# Unified entry point used by the API routes
# ---------------------------------------------------------------------------


def build_deck(
    content_type: str,
    original_text: str,
    llm_slides: Optional[List[Dict[str, Any]]],
    distribution: Distribution,
    audience_level: str,
    title: str,
    author_name: Optional[str] = None,
    author_email: Optional[str] = None,
    figures: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """Build the final slide list based on the content source.

    Only ``content_type == "prompt"`` is allowed to depend on LLM output;
    ``text`` and ``file`` are fully deterministic. ``figures`` are the visuals
    read out of an uploaded document; they only ever fill image slides that
    already wanted an image.
    """
    if content_type == "prompt":
        if not llm_slides:
            llm_slides = []
        return build_prompt_deck(
            llm_slides, distribution, audience_level, title, author_name, author_email, figures
        )

    from .text_structurer import structure_text

    presentation_data = structure_text(original_text)
    return build_deterministic_deck(
        presentation_data,
        distribution,
        audience_level,
        title,
        author_name,
        author_email,
        figures,
    )