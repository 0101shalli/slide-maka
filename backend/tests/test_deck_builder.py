import re

from app.services.deck_builder import (
    MAX_CONTENT_ROWS,
    _attach_image_slots,
    _build_outline,
    _outline_slides,
    _paginate_outline,
    _structured_content_slide,
)


def _content_titles():
    return [
        {"title": f"Topic {i}", "type": "theory" if i % 2 == 0 else "practical"}
        for i in range(8)
    ]


def test_outline_uses_the_presentation_title_not_a_placeholder():
    content = _content_titles()
    outline = _build_outline(content, 12, {0, 2, 4}, "Framework components")
    assert "1. Framework components" in outline
    assert not any("Title & Context" in item for item in outline)


def test_outline_drops_the_more_topics_filler():
    content = _content_titles()
    outline = _build_outline(content, 12, {0, 2, 4}, "Framework components")
    assert not any("more topics" in item for item in outline)


def test_outline_lists_every_content_topic():
    content = _content_titles()
    outline = _build_outline(content, 12, {0, 2, 4}, "Framework components")
    joined = "\n".join(outline)
    for index in range(len(content)):
        assert f"{index + 2}. Topic {index} (" in joined, joined
    # The closing entry continues the numbering after the last topic.
    assert f"{len(content) + 2}. Key Takeaways & Next Steps" in outline


def test_outline_paginates_and_numbering_continues_across_pages():
    content = _content_titles() * 3
    slides = _outline_slides(content, 30, set(), "Framework components")
    assert len(slides) > 1
    assert slides[0]["title"] == "Presentation Outline"
    assert slides[-1]["title"] == f"Presentation Outline ({len(slides)}/{len(slides)})"
    assert all(slide["type"] == "outline" for slide in slides)
    for slide in slides:
        assert slide["bullets"], slide
        assert not slide["bullets"][-1].strip().startswith("**"), slide["bullets"][-1]
    numbers = [
        int(match.group(1))
        for slide in slides
        for bullet in slide["bullets"]
        if (match := re.match(r"^(\d+)\.", bullet))
    ]
    assert numbers == sorted(numbers)
    assert numbers == list(range(1, len(content) + 3))


def test_outline_pagination_never_orphans_an_act_marker():
    items = ["**Opening**", "1. Deck"] + ["**Core Topics**"] + [
        f"{i}. Topic {i}" for i in range(2, 14)
    ] + ["**Closing**", "14. Key Takeaways & Next Steps"]
    pages = _paginate_outline(items, max_rows=6)
    assert all(page for page in pages)
    for page in pages[:-1]:
        assert not page[-1].strip().startswith("**"), page
    assert pages[0][0] == "**Opening**"
    assert pages[-1][-1] == "14. Key Takeaways & Next Steps"


def test_flow_plan_marks_the_slide_for_a_full_slide_diagram():
    slides = [
        {
            "title": "Approval Workflow",
            "type": "theory",
            "bullets": ["Draft the request.", "Route it for review."],
        }
    ]
    plan = {
        0: {
            "kind": "flow",
            "query": "approval workflow",
            "caption": "From draft to approval",
            "steps": ["Draft", "Review", "Approve"],
            "flow_title": "Approval Workflow",
        }
    }
    out = _attach_image_slots(slides, 0, None, plan)
    assert out[0]["image_promote"] is True
    assert out[0]["image_diagram"]["steps"] == ["Draft", "Review", "Approve"]
    assert out[0]["image_diagram"]["title"] == "Approval Workflow"
    assert out[0]["image_caption"] == "From draft to approval"


def test_flow_plan_adds_an_image_slot_beyond_the_budget():
    slides = [
        {"title": "Intro", "type": "theory", "bullets": ["A line."]},
        {"title": "Process", "type": "theory", "bullets": ["One.", "Two."]},
    ]
    plan = {1: {"kind": "flow", "steps": ["One", "Two"], "query": "process"}}
    out = _attach_image_slots(slides, 0, None, plan)
    assert "image_url" not in out[0]
    assert out[1]["image_promote"] is True


def test_generated_bullets_are_kept_on_a_practical_slide():
    """Every real line the planner sends survives onto the slide."""
    slide = _structured_content_slide(
        slide_number=3,
        title="Deploying Zero Trust",
        bullets=[
            "Zero trust replaces perimeter thinking with identity checks.",
            "Verify every request against device posture and user identity.",
            "Roll the policy out in observe mode first.",
            "Implement the change in audit mode, then enforce it.",
            "Practice the rollback before the production cutover.",
        ],
        slide_type="practical",
        audience_level="Intermediate",
    )
    rows = slide["bullets"]
    assert len(rows) <= MAX_CONTENT_ROWS
    assert "Implement the change in audit mode, then enforce it." in rows
    assert "Practice the rollback before the production cutover." in rows
    assert all(row.strip() for row in rows), "no blank rows left on the slide"
    assert not any(row.startswith("**") for row in rows), "no raw markup on the slide"


def test_generated_bullets_are_kept_on_a_theory_slide():
    slide = _structured_content_slide(
        slide_number=3,
        title="Identity Governance",
        bullets=["First generated line.", "Second generated line.", "Third generated line."],
        slide_type="theory",
        audience_level="Intermediate",
    )
    assert slide["bullets"][:3] == [
        "First generated line.",
        "Second generated line.",
        "Third generated line.",
    ]
    assert not any(b in ("Summary point", "Action item", "Recap") for b in slide["bullets"])
