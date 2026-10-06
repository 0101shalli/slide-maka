"""Content Planner: the stage between "structured text" and "slide dicts".

Every input source ends up in the same shape -- a list of sections, each with a
heading, a theory/practical type and its own lines of material -- and the
``Distribution`` from the slide calculator says how many slides the user asked
for and how they must be split. The planner is the one place that reconciles
the two.

It guarantees three things the deck builder used to have to compromise on:

1. **The requested slide count is met.** ``Distribution.content_slides`` slides
   come out of here, every time, drawn only from wording the source actually
   contains. Nothing is padded with "Key Takeaway" placeholders and no two
   slides repeat a line.
2. **The requested mix is respected.** ``theory_slides`` slides are theory and
   ``content_slides - theory_slides`` are practical, spread by
   ``theory_slide_indices`` so the two kinds interleave instead of arriving in
   two blocks. When the source only has material of one kind the planner still
   fills every slot, borrowing across pools rather than inventing text.
3. **Every slide earns its title.** A section split over several slides takes
   its titles from the material it contains -- ``Sale Creation:`` and
   ``Payment Schedule:`` become slide titles -- instead of repeating its heading
   with "(part 2)" stapled on.

To reach the requested count the planner may only use what is already in the
source. Its last resort is to break a long line at a clause boundary, which
keeps the author's wording and creates a genuinely different slide. If even
that is not enough the planner returns fewer slides plus a note explaining the
shortfall, because the alternative -- repeating or inventing lines -- is what
produced decks with two identical "Key Takeaway" slides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .parameter_calculator import Distribution, theory_slide_indices

__all__ = ["PlannedSlide", "PlanResult", "plan_content", "split_points_by_theme"]


# A slide that cannot show more than this many lines without the type shrinking
# to unreadable sizes. The PPTX renderer scales down below it, but a slide
# stacked with twenty rows is never what the user asked for.
MAX_BULLETS_PER_SLIDE = 5

# Slides never start from fewer lines than this; below it the slide looks
# stranded and the extra material is better spent on another slide.
MIN_BULLETS_PER_SLIDE = 2

# The most slides one section may fill. Without a cap a single long chapter
# swallows the deck and every one of its slides says the same thing.
MAX_SLOTS_PER_SECTION = 4

# A line longer than this is split at a clause boundary when more slides are
# needed, because a 60-word bullet cannot be shown on a 16:9 slide.
MAX_POINT_WORDS = 30

# "Sale Creation: your staff creates ..." -> label "Sale Creation". Real
# documents label their own list items constantly, and that label is a far
# better slide title than the section heading it sits under.
_LABEL_RE = re.compile(r"^([A-Z][A-Za-z0-9&/'\-]*(?:[ ][A-Za-z0-9&/'\-]+){0,5}):(?:\s|$)")

# Labels that only say which variant a line describes. "Model 2: reserved but
# remains in stock" is not a slide title, it is one column of a comparison.
_VARIANT_LABEL_RE = re.compile(
    r"^(?:model|option|variant|alternative|approach|method|phase|step|stage|"
    r"type|version|tier|level|scenario|case|column|row|item|point|part)\s*"
    r"(?:[0-9]+|[IVXLC]+|[a-z]|[0-9]+\.[0-9]+)$",
    re.IGNORECASE,
)

# A clause tail shorter than this cannot stand alone as a bullet, so it is
# folded into the clause before it instead of being cut loose.
_MIN_CLAUSE_WORDS = 5

# A heading is only usable as a slide title if it is short and has no sentence
# punctuation; anything else is a sentence the normalizer left alone.
_TITLE_MAX_WORDS = 9

_CLAUSE_SPLIT_RE = re.compile(
    r",\s+(?:and|but|while|which|where|so|because|then|although|though)\s+|;\s+",
    re.IGNORECASE,
)

# Strong markers for hands-on content. Kept deliberately narrow: a slide that
# mixes theory with a stray "apply" reads worse than one that stays theory.
_PRACTICAL_RE = re.compile(
    r"\b(?:practice|practices|exercise|exercises|activity|activities|implement(?:ing|ation)?|"
    r"hands-on|workflow|procedure|procedures|step-by-step|step by step|demonstrat\w*|"
    r"experiment|lab|assignment|interactive|case study|checklist|worksheet|tutorial|how to|"
    r"configure|configuring|setup|set up|install|installation|build(?:ing)? the|enforce)\b",
    re.IGNORECASE,
)

_GENERIC_HEADINGS = {
    "overview", "introduction", "key concepts", "key concepts & overview",
    "summary", "conclusion", "conclusions", "objectives", "agenda",
    "topic", "topics", "details", "content", "presentation", "notes",
    "background", "main points", "general",
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with",
    "that", "this", "these", "those", "it", "its", "is", "are", "was", "were",
    "as", "by", "at", "from", "be", "been", "has", "have", "had", "which",
    "when", "you", "your", "we", "our", "they", "their", "can", "will",
    "not", "but", "if", "then", "than", "so", "such", "into", "about",
}


# Both the legacy "(2)" and the current "— Part 2" markers are stripped before
# a title stem is reused for a differently-numbered slide.
_PART_SUFFIX_RE = re.compile(r"\s*(?:\(\d+\)|[\u2014\u2013-]\s*Part\s*\d+)$")


@dataclass
class PlannedSlide:
    """One content slide, before the renderer sees it."""

    title: str
    bullets: List[str]
    type: str
    subtitle: str = ""
    section: str = ""
    image_description: str = ""


@dataclass
class PlanResult:
    slides: List[PlannedSlide] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    theory_slides: int = 0
    practical_slides: int = 0

    @property
    def total(self) -> int:
        return len(self.slides)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-/&]*", text or "")


def _label_of(point: str) -> Optional[str]:
    """``"Sale Creation: your staff ..."`` -> ``"Sale Creation"``."""
    match = _LABEL_RE.match(point or "")
    if not match:
        return None
    label = _clean(match.group(1)).strip(" .:-")
    if not label or len(_words(label)) > _TITLE_MAX_WORDS:
        return None
    if label.lower() in _GENERIC_HEADINGS:
        return None
    if _VARIANT_LABEL_RE.match(label):
        return None
    return label


def usable_title(text: str, *, fallback: str = "") -> str:
    """A section heading the planner is willing to put on a slide."""
    text = _clean(text).strip(" .:-#")
    if not text:
        return fallback
    if text.lower() in _GENERIC_HEADINGS:
        return fallback
    words = _words(text)
    if not words:
        return fallback
    if len(words) > _TITLE_MAX_WORDS:
        text = " ".join(words[:_TITLE_MAX_WORDS]).rstrip(" ,;:")
    # A heading that is really a sentence reads badly at title size.
    if len(text) > 90:
        text = " ".join(words[:_TITLE_MAX_WORDS]).rstrip(" ,;:")
    return text or fallback


def _split_long_point(point: str) -> List[str]:
    """Break one over-long line at a clause boundary, keeping the wording.

    This is the planner's only way to create more material than the source
    appears to hold, and it never rewrites: the sentence is cut at "and", "so"
    or a semicolon and each half is given the punctuation it needs to stand on
    its own. A line that opens with ``Label:`` passes that label on to the
    continuation, so "Inventory Impact: Model 1 ...; Model 2 ..." does not
    leave its second half starting at "Model 2" with nothing to say what it is.
    """
    text = _clean(point)
    if len(_words(text)) <= MAX_POINT_WORDS:
        return [text]

    matches = list(_CLAUSE_SPLIT_RE.finditer(text))
    if not matches:
        return [text]

    # Each cut has a start and an end: the head stops *before* the comma and
    # the conjunction, and the tail resumes *after* it. Using one boundary for
    # both left "…recognises the revenue as a sale, but." on a slide.
    segments: List[str] = []
    cursor = 0
    for match in matches:
        head = text[cursor: match.start()]
        if head.strip():
            segments.append(head)
        cursor = match.end()
    tail = text[cursor:]
    if tail.strip():
        segments.append(tail)
    if len(segments) < 2:
        return [text]

    lead_in = _label_of(text) or ""
    prefix = f"{lead_in}: " if lead_in else ""

    # Fold any clause too short to stand on its own into the one before it.
    # Dropping it instead would truncate the sentence.
    merged: List[str] = []
    for chunk in segments:
        chunk = _clean(chunk).lstrip(" ,;:.-\u2013\u2014")
        if not chunk:
            continue
        if len(_words(chunk)) >= _MIN_CLAUSE_WORDS:
            merged.append(chunk)
        elif merged:
            # Too short to be its own line: glue it back onto the previous one.
            merged[-1] = f"{merged[-1].rstrip(' ,;:')}, {chunk[0].lower()}{chunk[1:]}"
        else:
            merged.append(chunk)
    if len(merged) < 2:
        return [text]

    parts: List[str] = []
    for index, chunk in enumerate(merged):
        if index and prefix and not _label_of(chunk):
            chunk = f"{prefix}{chunk}"
        chunk = chunk.rstrip(" ,;:.")
        if not chunk.endswith(("!", "?")):
            chunk = f"{chunk}."
        chunk = chunk[0].upper() + chunk[1:]
        parts.append(chunk)

    return parts


def _shorten(point: str, limit: int = MAX_POINT_WORDS) -> str:
    """Trim a line to a readable length, cutting the text and never rebuilding it.

    Rejoining word tokens would silently drop every comma, colon and quote in
    the source, which is how "Identification & Verification" ended up on a
    slide as "Identification Verification".
    """
    text = _clean(point)
    if len(_words(text)) <= limit:
        return text

    # Cut the original string where the ``limit``-th word ends.
    spans = [match.span() for match in re.finditer(r"[A-Za-z0-9][^\s]*", text)]
    if len(spans) <= limit:
        return text
    cut = spans[limit - 1][1]

    candidate = text[:cut].rstrip(" ,;:-")
    # Prefer ending on a clause or sentence boundary within the budget.
    for marker in ("; ", ". ", ", and ", ", which ", ", so ", ", but "):
        position = candidate.rfind(marker)
        if position > cut * 0.55:
            candidate = candidate[: position + len(marker) - 1].rstrip()
            break

    candidate = _clean(candidate).rstrip(" ,;:-.")
    if not candidate:
        return _clean(text[:cut])
    if not candidate.endswith((".", "!", "?")):
        candidate += "."
    return candidate


def split_points_by_theme(points: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Split one section's lines into theory and hands-on material."""
    theory: List[str] = []
    practical: List[str] = []
    for point in points or []:
        text = _clean(point)
        if not text:
            continue
        (practical if _PRACTICAL_RE.search(text) else theory).append(text)
    return theory, practical


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


class _Atom:
    """One section (or one theme of it) plus how many slides it may fill."""

    __slots__ = ("section", "kind", "points", "slot_cap")

    def __init__(self, section: str, kind: str, points: List[str]):
        self.section = section
        self.kind = kind
        self.points = points
        self.slot_cap = 1

    @property
    def base_title(self) -> str:
        return usable_title(self.section, fallback="")


def _collect_atoms(sections: Sequence[Dict[str, Any]]) -> List[_Atom]:
    atoms: List[_Atom] = []
    for section in sections or []:
        heading = _clean(section.get("heading", ""))
        points = [_clean(p) for p in (section.get("points") or []) if _clean(p)]
        if not points:
            continue
        declared = (section.get("type") or "theory").strip().lower()
        theory, practical = split_points_by_theme(points)
        if declared == "practical" and not practical and theory:
            # The structurer filed the whole section as practical; keep it
            # intact rather than shredding it by an ambiguous word.
            practical, theory = theory, []
        if declared == "theory" and not theory and practical:
            theory, practical = practical, []
        if theory:
            atoms.append(_Atom(heading, "theory", theory))
        if practical:
            atoms.append(_Atom(heading, "practical", practical))
    return atoms


def _allow_splits(atoms: Sequence[_Atom], target: int) -> None:
    """Raise how far each atom may be split, as far as its material allows."""
    for atom in atoms:
        room = max(len(atom.points) // MIN_BULLETS_PER_SLIDE, 1)
        atom.slot_cap = max(1, min(target, room, MAX_SLOTS_PER_SECTION))


def _is_caption(point: str) -> bool:
    """A figure or table caption, which documents its visual rather than the
    slide's subject. A slide made only of these says nothing on its own."""
    from .document_extractor import CAPTION_RE

    return bool(CAPTION_RE.match(point or ""))


def _chunks(points: Sequence[str], parts: int) -> List[List[str]]:
    """Split ``points`` into ``parts`` runs of nearly equal length, in order.

    Captions ride with the first run rather than being spread across the split:
    a half whose only line was "Figure 2. Loss per training step." carries no
    wording, and if that is all a run has it is dropped and its lines returned
    to the run before it.
    """
    if parts <= 1:
        return [list(points)]

    own = [point for point in points if not _is_caption(point)]
    captions = [point for point in points if _is_caption(point)]

    per = len(own) / parts if own else 0
    chunks: List[List[str]] = []
    start = 0
    for index in range(parts):
        end = round((index + 1) * per)
        end = max(end, start + 1)
        end = min(end, len(own))
        chunk = own[start:end]
        if index == 0 and captions:
            chunk = chunk + captions
        if chunk:
            chunks.append(chunk)
        start = end
    if start < len(own):
        chunks[-1].extend(own[start:])

    # A run left with captions only would be a slide about nothing.
    result: List[List[str]] = []
    for chunk in chunks:
        if chunk and all(_is_caption(point) for point in chunk):
            if result:
                result[-1].extend(chunk)
                continue
        if chunk:
            result.append(chunk)
    return result or [list(points)]


def _merge_atoms(atoms: Sequence[_Atom], limit: int) -> List[_Atom]:
    """Fold atoms together until at most ``limit`` remain.

    Two passes, both of which only ever remove a slide boundary:

    * an atom too thin to fill a slide on its own is folded into its
      neighbour, so a lone lead-in sentence ("Here is a summary of ...")
      does not become a slide of its own next to a crowded one;
    * if there are still more atoms than slides, the ``limit`` richest survive
      and the remainder are merged into the smallest of them.

    Document order is preserved and no wording is dropped.
    """
    if limit <= 0:
        return []
    if not atoms:
        return []

    result: List[_Atom] = []
    for atom in atoms:
        if (
            result
            and len(atom.points) < MIN_BULLETS_PER_SLIDE
            and result[-1].kind == atom.kind
            and len(result[-1].points) + len(atom.points) <= MAX_BULLETS_PER_SLIDE * 2
        ):
            result[-1] = _Atom(
                result[-1].section,
                result[-1].kind,
                list(result[-1].points) + list(atom.points),
            )
            continue
        result.append(atom)

    while len(result) > limit:
        order = sorted(range(len(result)), key=lambda index: (len(result[index].points), index))
        folded = set(order[: len(result) - limit])
        keepers = order[len(result) - limit:]

        # ``order`` is ascending, so the first keeper is the smallest of the
        # survivors and becomes the one that absorbs the folded lines.
        host = keepers[0]
        host_atom = result[host]
        host_points = list(host_atom.points)
        for index in sorted(folded):
            host_points.extend(result[index].points)
        merged_host = _Atom(host_atom.section, host_atom.kind, host_points)

        merged: List[_Atom] = []
        for index, atom in enumerate(result):
            if index in folded:
                continue
            merged.append(merged_host if index == host else atom)
        result = merged

    return result


def _allocate(atoms: Sequence[_Atom], target: int) -> List[int]:
    """Give the atoms slide counts proportional to the material each holds."""
    if target <= 0 or not atoms:
        return []

    allocation = [1] * len(atoms)
    remaining = target - len(atoms)

    while remaining > 0:
        candidates = [
            index
            for index, atom in enumerate(atoms)
            if allocation[index] < atom.slot_cap
        ]
        if not candidates:
            break
        # The atom furthest below what its own material allows gets the slide,
        # so a 40-line chapter is not starved next to a one-line section.
        chosen = max(
            candidates,
            key=lambda index: (
                (atoms[index].slot_cap - allocation[index]),
                len(atoms[index].points),
                -index,
            ),
        )
        allocation[chosen] += 1
        remaining -= 1

    # The caps are a preference, not a veto: the user's slide count is the
    # harder constraint, so any surplus lands on the longest atom.
    while remaining > 0:
        chosen = max(range(len(atoms)), key=lambda index: len(atoms[index].points))
        allocation[chosen] += 1
        remaining -= 1

    return allocation


def _title_for(atom: _Atom, chunk: Sequence[str], base_title: str) -> str:
    """Choose the most descriptive title available for this slide.

    A chunk whose lines all carry the same ``Label:`` wins, because that label
    names exactly what the slide covers. Otherwise the section's own heading is
    used: it is the author's own name for the material, and guessing a title
    from the body's first sentence produced headlines like
    "Before diving into the system design, it's".
    """
    labels = [label for label in (_label_of(point) for point in chunk) if label]
    if labels:
        counts: Dict[str, int] = {}
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
        best = max(counts, key=lambda label: (counts[label], -labels.index(label)))
        if counts[best] >= 2 or (len(chunk) == 1 and len(labels) == 1):
            title = usable_title(best, fallback="")
            if title and title.lower() not in _GENERIC_HEADINGS:
                return title

    # A chunk opening with a labelled line still describes itself.
    if chunk:
        opening = _label_of(chunk[0])
        if opening:
            title = usable_title(opening, fallback="")
            if title and title.lower() not in _GENERIC_HEADINGS:
                return title

    return base_title


def _slides_for(
    atoms: Sequence[_Atom],
    target: int,
    *,
    expand: bool,
    used_titles: set,
) -> List[PlannedSlide]:
    """Turn atoms into exactly ``target`` slides where the material allows."""
    if target <= 0 or not atoms:
        return []

    prepared: List[_Atom] = []
    for atom in atoms:
        points: List[str] = []
        for point in atom.points:
            if expand:
                points.extend(_split_long_point(point))
            else:
                points.append(point)
        if points:
            prepared.append(_Atom(atom.section, atom.kind, points))

    if not prepared:
        return []

    _allow_splits(prepared, target)
    prepared = _merge_atoms(prepared, target)
    allocation = _allocate(prepared, target)

    slides: List[PlannedSlide] = []
    # Lines that did not fit the row budget, kept with the atom they came from
    # so they can become slides of their own below.
    overflow: List[Tuple[_Atom, List[str]]] = []

    for atom, slots in zip(prepared, allocation):
        if slots <= 0:
            continue
        base = atom.base_title
        chunks = _chunks(atom.points, slots)
        for index, chunk in enumerate(chunks):
            title = _title_for(atom, chunk, base)
            if not title:
                title = atom.section or "Key Points"
            if len(chunks) > 1 and title == base and base:
                # A section split across several slides repeats its heading, so
                # mark the parts instead of printing the same words twice.
                title = f"{base} — Part {index + 1}"
            # The subtitle repeats the section this slide belongs to, so it is
            # only worth showing when the title is something more specific.
            stem = _PART_SUFFIX_RE.sub("", title)
            subtitle = atom.section if atom.section and stem != atom.section else ""
            bullets = [_shorten(point) for point in chunk]
            if not bullets:
                continue
            if len(bullets) > MAX_BULLETS_PER_SLIDE:
                overflow.append((atom, bullets[MAX_BULLETS_PER_SLIDE:]))
                bullets = bullets[:MAX_BULLETS_PER_SLIDE]
            slides.append(
                PlannedSlide(
                    title=title,
                    bullets=bullets,
                    type=atom.kind,
                    subtitle=subtitle,
                    section=atom.section,
                )
            )

    # Still short of the requested count: give the spilled lines their own
    # slides rather than dropping them. This is where a deck that used to end
    # in two identical "Key Takeaway" slides gets its real content back.
    extra = target - len(slides)
    while extra > 0 and overflow:
        atom, spare = overflow[0]
        if not spare:
            overflow.pop(0)
            continue
        take = spare[:MAX_BULLETS_PER_SLIDE]
        leftover = spare[MAX_BULLETS_PER_SLIDE:]
        if leftover:
            overflow[0] = (atom, leftover)
        else:
            overflow.pop(0)
        title = usable_title(_label_of(take[0]) or "", fallback="")
        if not title:
            title = atom.section or atom.base_title or "Key Points"
        slides.append(
            PlannedSlide(
                title=title,
                bullets=take,
                type=atom.kind,
                subtitle=atom.section if atom.section != title else "",
                section=atom.section,
            )
        )
        extra -= 1

    return _deduplicate_titles(slides, used_titles)


def _deduplicate_titles(slides: List[PlannedSlide], used_titles: set) -> List[PlannedSlide]:
    """No two slides in a deck may carry the same title."""
    seen = dict.fromkeys(used_titles)
    for slide in slides:
        title = slide.title
        if title in seen:
            stem = _PART_SUFFIX_RE.sub("", title)
            number = 2
            while f"{stem} ({number})" in seen:
                number += 1
            title = f"{stem} ({number})"
            slide.title = title
        seen[title] = True
    return slides


def plan_content(
    sections: Sequence[Dict[str, Any]],
    distribution: Distribution,
    audience_level: str = "Intermediate",
) -> PlanResult:
    """Fit structured sections to the numbers the slide calculator produced.

    Args:
        sections: ``[{"heading", "type", "points"}]`` from the text structurer.
        distribution: the slide calculator's output; ``content_slides`` is the
            number of content slides the deck must contain.
        audience_level: kept for callers that vary the wording by audience.

    Returns:
        A :class:`PlanResult` whose ``slides`` are the content slides in order,
        already mixed theory/practical as requested, plus any notes explaining
        where the source ran out of material.
    """
    del audience_level  # titles come from the source, not from a style guide

    target = max(int(distribution.content_slides or 1), 1)
    theory_target = max(0, min(int(distribution.theory_slides or 0), target))
    practical_target = target - theory_target
    theory_positions = set(theory_slide_indices(target, theory_target))

    result = PlanResult(theory_slides=theory_target, practical_slides=practical_target)

    atoms = _collect_atoms(sections)
    if not atoms:
        result.notes.append(
            "The source contained no usable wording, so the deck has no content slides."
        )
        return result

    theory_pool = [atom for atom in atoms if atom.kind == "theory"]
    practical_pool = [atom for atom in atoms if atom.kind == "practical"]

    if theory_pool and practical_pool:
        theory_slides = _slides_for(theory_pool, theory_target, expand=True, used_titles=set())
        practical_slides = _slides_for(
            practical_pool, practical_target, expand=True, used_titles=set()
        )
    else:
        # Only one kind of material exists. Every slot is filled from it and the
        # theory/practical styling is applied by position afterwards, so the
        # requested mix is still visible in the deck.
        kind = "theory" if theory_pool else "practical"
        pool = theory_pool or practical_pool
        theory_slides = _slides_for(pool, target, expand=True, used_titles=set())
        for slide in theory_slides:
            slide.type = kind
        practical_slides = []

    if not theory_slides and not practical_slides:
        result.notes.append("The source could not be turned into any content slide.")
        return result

    # Fill the requested shape by position, borrowing from whichever pool still
    # has material. Borrowing is always preferred to leaving a slot empty or
    # repeating a line.
    ordered: List[PlannedSlide] = []
    theory_cursor = 0
    practical_cursor = 0
    for position in range(target):
        wants_theory = position in theory_positions
        if wants_theory and theory_cursor < len(theory_slides):
            ordered.append(theory_slides[theory_cursor])
            theory_cursor += 1
            continue
        if not wants_theory and practical_cursor < len(practical_slides):
            ordered.append(practical_slides[practical_cursor])
            practical_cursor += 1
            continue
        spare_pool = theory_slides if theory_cursor < len(theory_slides) else practical_slides
        spare_cursor = theory_cursor if theory_cursor < len(theory_slides) else practical_cursor
        if spare_cursor < len(spare_pool):
            borrowed = spare_pool[spare_cursor]
            ordered.append(borrowed)
            if spare_pool is theory_slides:
                theory_cursor += 1
            else:
                practical_cursor += 1
            continue
        break

    result.slides = ordered
    result.theory_slides = sum(1 for slide in ordered if slide.type == "theory")
    result.practical_slides = sum(1 for slide in ordered if slide.type == "practical")

    if len(ordered) < target:
        missing = target - len(ordered)
        result.notes.append(
            f"The source provides material for {len(ordered)} of the {target} content "
            f"slides requested; the remaining {missing} would have repeated wording "
            f"already used, so they were left out."
        )
    return result