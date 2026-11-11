"""Bloom's Taxonomy pedagogy for higher-education lecture decks.

Deterministic, LLM-free helpers that give a deck the structure expected of
university lecture material:

* every content slide (sub-topic) is classified onto one of the six Bloom
  cognitive levels and tagged with a matching learning objective;
* the deck opens with a "Learning Objectives" slide built from those
  objectives, so the lecture states what students will be able to do;
* each sub-topic is followed by a "Check Your Understanding" slide carrying a
  small active-learning task plus a two-question quiz whose answer key lives
  in the speaker notes;
* sections whose wording signals explainable context (processes, definitions,
  cause-effect, comparisons) are marked for an explanatory poster that the
  image pipeline draws offline.

Everything here is derived from the deck's own wording, so no extra LLM call
is spent and the pedagogy matches the material rather than generic filler.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

__all__ = [
    "BLOOM_LEVELS",
    "LEVEL_DISPLAY",
    "OBJECTIVE_VERBS",
    "PedagogyOptions",
    "classify_bloom_level",
    "objective_for",
    "build_objectives_slide",
    "build_check_understanding_slide",
    "has_explanatory_context",
    "attach_posters",
]

BLOOM_LEVELS = ("remember", "understand", "apply", "analyze", "evaluate", "create")

LEVEL_DISPLAY = {
    "remember": "Remember",
    "understand": "Understand",
    "apply": "Apply",
    "analyze": "Analyze",
    "evaluate": "Evaluate",
    "create": "Create",
}

# Leading verb used when writing objectives at each level
# ("By the end you will be able to ...").
OBJECTIVE_VERBS = {
    "remember": "Define",
    "understand": "Explain",
    "apply": "Apply",
    "analyze": "Analyze",
    "evaluate": "Evaluate",
    "create": "Design",
}

# Word-stem signals counted across a slide's own wording. A stem matches any
# inflection that starts with it ("appl" covers apply/applied/application).
_LEVEL_STEMS = {
    "remember": (
        "defin", "identif", "recall", "recognis", "recogniz", "terminolog",
        "memoris", "memoriz", "label",
    ),
    "understand": (
        "explain", "describ", "summaris", "summariz", "interpret", "outlin",
        "paraphras", "concept", "principle", "understand", "meaning", "idea",
    ),
    "apply": (
        "appl", "implement", "demonstrat", "solv", "practis", "practic",
        "calculat", "execut", "configur", "install", "operat",
    ),
    "analyze": (
        "analy", "compar", "differenti", "examin", "distinguish", "categoris",
        "categoriz", "deconstruct", "relat", "connect", "structur", "compon",
    ),
    "evaluate": (
        "evaluat", "justif", "assess", "critiq", "judg", "defend", "validat",
        "argu", "apprais", "strength", "weakness", "trade-off",
    ),
    "create": (
        "creat", "design", "develop", "compos", "construct", "formulat",
        "produc", "generat", "prototyp", "propos", "invent",
    ),
}

# Structural markers (matched as substrings) that also carry a level signal.
_LEVEL_PHRASES = {
    "remember": ("what is", "key terms", "overview of", "introduction to"),
    "understand": ("because", "why does", "why is", "refers to", "defined as"),
    "apply": (
        "how to", "step by step", "steps", "process", "procedure", "workflow",
        "pipeline", "work through", "in practice", "worked example",
    ),
    "analyze": (
        "types of", "kinds of", "consists of", "comprises", "compare",
        "versus", "difference between", "relationship", "break down",
    ),
    "evaluate": (
        "advantage", "disadvantage", "pros and cons", "criteria", "best",
        "should", "recommend", "trade-off", "evaluate",
    ),
    "create": ("build", "make your own", "design", "produce", "put together"),
}

# Level used when a slide's wording carries no signal at all, by position in
# the deck: a lecture that climbs the taxonomy from recall to creation.
_POSITION_FALLBACKS = (
    "remember", "understand", "understand", "apply",
    "apply", "analyze", "analyze", "evaluate", "create",
)

_TASK_TEMPLATES = {
    "remember": "Write down the key terms of \"{topic}\" from memory, then check them against the slide.",
    "understand": "Explain \"{topic}\" to the person next to you in one or two sentences, without reading the slide.",
    "apply": "Apply \"{topic}\" to a short scenario from your own work or studies (2-3 minutes, in pairs).",
    "analyze": "Compare \"{topic}\" with the previous sub-topic and note one similarity and one difference.",
    "evaluate": "Judge how useful \"{topic}\" is for your own context and justify your view in one sentence.",
    "create": "Sketch a small diagram or outline that uses \"{topic}\" to solve a simple problem.",
}

# Wording that says a section carries context worth a standalone explanatory
# poster (drawn offline by the image pipeline as a concept diagram).
_POSTER_SIGNAL_RE = re.compile(
    r"\b(because|therefore|process|processes|steps?|stages?|phases?|workflow|"
    r"procedure|definition|defined as|defines|consists of|comprises|includes|"
    r"causes?|leads to|results? in|types? of|kinds? of|categories|how it works|"
    r"pipeline|architecture|framework|structure|components|layered|sequence)\b",
    re.IGNORECASE,
)

# Rows an objectives slide may list before the rest are summarised.
MAX_OBJECTIVE_ROWS = 8


@dataclass
class PedagogyOptions:
    """Toggle the Bloom's-Taxonomy features of a generated deck."""

    objectives: bool = True
    quizzes: bool = True
    posters: bool = True


def _stem_score(text: str, stems: Sequence[str]) -> int:
    return sum(1 for stem in stems if re.search(rf"\b{stem}", text))


def _phrase_score(text: str, phrases: Sequence[str]) -> int:
    return sum(2 for phrase in phrases if phrase in text)


def classify_bloom_level(
    title: str,
    bullets: Optional[Sequence[str]] = None,
    position: int = 0,
) -> str:
    """Map one sub-topic onto a Bloom cognitive level.

    Signals are counted across the slide's own wording (verb stems and
    structural markers); a slide with no signal at all falls back to a
    position-based level so a full lecture climbs from recall towards
    creation.
    """
    text = f"{title or ''} {' '.join(bullets or [])}".lower()
    scores = {
        level: _stem_score(text, stems) + _phrase_score(text, _LEVEL_PHRASES[level])
        for level, stems in _LEVEL_STEMS.items()
    }
    best = max(scores.values())
    if best > 0:
        # The lowest level that ties for the top score wins, which keeps a
        # mixed slide anchored at its foundational level.
        for level in BLOOM_LEVELS:
            if scores[level] == best:
                return level
    return _POSITION_FALLBACKS[position % len(_POSITION_FALLBACKS)]


def objective_for(topic: str, level: str) -> str:
    """A learning objective for one sub-topic at its Bloom level."""
    verb = OBJECTIVE_VERBS.get(level, "Explain")
    return f"{verb} {topic}"


def _clean_topic(title: str) -> str:
    topic = re.sub(r"\s+", " ", (title or "").strip().rstrip(".:;"))
    # "(part 2)" style layout markers are not part of the subject.
    topic = re.sub(r"\s*(?:\(\d+\)|\u2014\s*Part\s*\d+)$", "", topic)
    return topic or "this topic"


def _clip(text: str, limit: int = 96) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{cut}..."


def build_objectives_slide(
    content: Sequence[Dict[str, Any]],
    slide_number: int = 2,
) -> Optional[Dict[str, Any]]:
    """The deck's opening "Learning Objectives" slide.

    One objective per sub-topic, each tagged with its Bloom level, ordered by
    the taxonomy so the lecture visibly climbs from remembering to creating.
    """
    entries: List[Dict[str, str]] = []
    for index, slide in enumerate(content):
        topic = _clean_topic(slide.get("title", ""))
        level = slide.get("bloom_level") or classify_bloom_level(
            slide.get("title", ""), slide.get("bullets", []), index
        )
        entries.append(
            {
                "topic": topic,
                "level": level,
                "text": objective_for(topic, level),
            }
        )
    if not entries:
        return None
    entries.sort(key=lambda e: BLOOM_LEVELS.index(e["level"]))

    shown = entries[:MAX_OBJECTIVE_ROWS]
    bullets = [
        f"{index}. {entry['text']} ({LEVEL_DISPLAY[entry['level']]})"
        for index, entry in enumerate(shown, start=1)
    ]
    if len(entries) > len(shown):
        bullets.append(f"... plus {len(entries) - len(shown)} further objectives")

    return {
        "slide_number": slide_number,
        "title": "Learning Objectives",
        "subtitle": "By the end of this session, you will be able to:",
        "bullets": bullets,
        "type": "objectives",
        # Only the rows the slide actually shows, so the renderer can pair
        # each visible bullet with its own Bloom level.
        "objectives": shown,
        "speaker_notes": {
            "opening_remarks": (
                "State the objectives up front so students know what they are "
                "accountable for; each is written at a Bloom's Taxonomy level."
            ),
            "main_talking_points": [
                f"{entry['text']} ({LEVEL_DISPLAY[entry['level']]})"
                for entry in shown[:4]
            ],
            "audience_engagement": (
                "Ask students which objective they expect to find hardest; "
                "return to it during the recap."
            ),
            "time_estimate": 45,
            "key_takeaway": "Objectives are assessed by the quizzes after each sub-topic.",
            "transition_to_next": "Here is how the session is organised to reach them.",
        },
    }


def _stable_rotation(items: List[Any], seed_text: str) -> List[Any]:
    """Rotate a list by a stable hash so shuffling is deterministic."""
    if not items:
        return items
    digest = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    shift = int(digest[:8], 16) % len(items)
    return items[shift:] + items[:shift]


def _pick_quiz_lines(
    slide: Dict[str, Any],
    pool: Sequence[Dict[str, Any]],
) -> tuple[List[str], List[str]]:
    """Two informative lines from this sub-topic and two distractor lines."""
    own = [
        _clip(bullet)
        for bullet in slide.get("bullets", [])
        if bullet and bullet.strip() and not bullet.strip().startswith("**")
    ]
    own = own[:2]
    others: List[str] = []
    for other in pool:
        if other is slide:
            continue
        for bullet in other.get("bullets", []):
            line = _clip(bullet)
            if line and line not in own and line not in others:
                others.append(line)
                break
    return own, others[:2]


def build_check_understanding_slide(
    slide: Dict[str, Any],
    pool: Optional[Sequence[Dict[str, Any]]] = None,
    slide_number: int = 0,
) -> Optional[Dict[str, Any]]:
    """A per-sub-topic assessment slide: one small task plus a short quiz.

    The quiz questions are multiple-choice with three options each; the
    correct answer always comes from the sub-topic's own material and the
    distractors from the neighbouring sub-topics, and the answer key is
    written into the speaker notes so the deck can be taught from directly.
    """
    pool = list(pool or [slide])
    topic = _clean_topic(slide.get("title", ""))
    level = slide.get("bloom_level") or classify_bloom_level(
        slide.get("title", ""), slide.get("bullets", [])
    )

    correct_lines, distractors = _pick_quiz_lines(slide, pool)
    if not correct_lines:
        return None

    questions: List[Dict[str, Any]] = []
    for correct in correct_lines:
        options = [correct] + distractors[:2]
        options = _stable_rotation(options, f"{topic}|{correct}")
        answer = options.index(correct)
        questions.append(
            {
                "question": f"According to this lecture, which statement about {topic} is correct?",
                "options": options,
                "answer_index": answer,
            }
        )

    task_text = _TASK_TEMPLATES.get(level, _TASK_TEMPLATES["understand"]).format(topic=topic)
    answer_key = "; ".join(
        f"Q{index + 1}: {chr(ord('A') + question['answer_index'])}"
        for index, question in enumerate(questions)
    )

    bullets = [f"**Quick task ({LEVEL_DISPLAY[level]}):** {task_text}"]
    for index, question in enumerate(questions, start=1):
        bullets.append(f"**Question {index}:** {question['question']}")
        for letter, option in zip("ABC", question["options"]):
            bullets.append(f"{letter}) {option}")

    return {
        "slide_number": slide_number,
        "title": f"Check Your Understanding: {topic}",
        "subtitle": "Small task and quick quiz for this sub-topic",
        "bullets": bullets,
        "type": "quiz",
        "bloom_level": level,
        "task": {"level": level, "text": task_text},
        "questions": questions,
        "speaker_notes": {
            "opening_remarks": f"Pause on {topic} and let students try these before revealing answers.",
            "main_talking_points": [
                "Give students 60-90 seconds for the quick task.",
                "Run the quiz as a show of hands or a quick poll.",
                f"Answer key - {answer_key}.",
            ],
            "audience_engagement": "Ask a volunteer to justify their quiz answer before confirming it.",
            "time_estimate": 120,
            "key_takeaway": f"The quiz checks the {LEVEL_DISPLAY[level]} objective for {topic}.",
            "transition_to_next": "Move on once most students answer correctly.",
            "answers": answer_key,
        },
    }


def has_explanatory_context(slide: Dict[str, Any]) -> bool:
    """Whether a section carries context an explanatory poster can depict."""
    text = " ".join(
        [slide.get("title", "") or ""] + [b for b in slide.get("bullets", []) if b]
    )
    if _POSTER_SIGNAL_RE.search(text):
        return True
    # A slide with several substantive lines has enough context to depict.
    substantive = [
        b for b in slide.get("bullets", [])
        if b and not b.startswith("**") and len(b.split()) >= 6
    ]
    return len(substantive) >= 4


def attach_posters(
    slides: List[Dict[str, Any]],
    enabled: bool = True,
) -> List[Dict[str, Any]]:
    """Give sections with explainable context a dedicated explanatory poster.

    Only slides that carry no visual of their own (no image slot, no document
    figure, no planner diagram) are considered, so a poster never duplicates a
    photo or chart the deck already shows. The poster itself is drawn offline
    by the image pipeline from the slide's own bullets and is promoted to its
    own full-bleed slide by the renderer.
    """
    if not enabled:
        return slides
    for slide in slides:
        if slide.get("image_url") or slide.get("image_diagram"):
            continue
        if slide.get("image_local_path"):
            continue
        if not has_explanatory_context(slide):
            continue
        points = [
            b for b in slide.get("bullets", [])
            if b and b.strip() and not b.startswith("**")
        ][:5]
        slide["image_diagram"] = {
            "title": slide.get("title", ""),
            "points": points,
        }
        slide["image_promote"] = True
        slide["image_caption"] = f"Concept poster: {slide.get('title', '')}"
        slide["image_source"] = "poster"
        slide["poster"] = True
    return slides
