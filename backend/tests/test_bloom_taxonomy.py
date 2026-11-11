from app.services.bloom_taxonomy import (
    BLOOM_LEVELS,
    LEVEL_DISPLAY,
    PedagogyOptions,
    attach_posters,
    build_check_understanding_slide,
    build_objectives_slide,
    classify_bloom_level,
    objective_for,
)
from app.services.deck_builder import build_deck
from app.services.parameter_calculator import compute_distribution


def _content(n=3):
    return [
        {
            "title": "Introduction to Databases",
            "type": "theory",
            "bullets": [
                "Define a database and its key terms.",
                "Identify the main components.",
            ],
        },
        {
            "title": "The Query Process",
            "type": "theory",
            "bullets": [
                "The query process has four steps.",
                "A query is parsed, planned and executed.",
                "This workflow keeps results consistent.",
            ],
        },
        {
            "title": "Design a Schema",
            "type": "practical",
            "bullets": [
                "Design tables for a small library.",
                "Develop the relationships between entities.",
            ],
        },
    ]


def _llm_slides():
    return [
        {
            "title": "Introduction to Databases",
            "type": "theory",
            "bullets": [
                "Define a database and its key terms.",
                "Explain why databases organise data.",
            ],
        },
        {
            "title": "The Query Process",
            "type": "theory",
            "bullets": [
                "The process has four steps.",
                "Compare a parsed query with a planned one.",
            ],
        },
        {
            "title": "Design a Schema",
            "type": "practical",
            "bullets": [
                "Design tables for a small library.",
                "Create a prototype schema in pairs.",
            ],
        },
    ]


def _deck(**options):
    distribution = compute_distribution(7, 50, 0, "word " * 400)
    return build_deck(
        "prompt",
        "word " * 400,
        _llm_slides(),
        distribution,
        "Beginner",
        "Databases 101",
        pedagogy=PedagogyOptions(**options),
    )


def test_classify_uses_the_slides_own_wording():
    assert classify_bloom_level("Introduction", ["Define the key terms."]) == "remember"
    assert classify_bloom_level("Workflow", ["The process has four steps."]) == "apply"
    assert classify_bloom_level("Design a Schema", ["Create a prototype."]) == "create"


def test_classification_climbs_by_position_when_wording_is_neutral():
    levels = [
        classify_bloom_level(f"Topic {i}", ["A neutral observation."], i)
        for i in range(9)
    ]
    assert levels[0] == "remember"
    assert levels[-1] == "create"
    assert [BLOOM_LEVELS.index(level) for level in levels] == sorted(
        BLOOM_LEVELS.index(level) for level in levels
    )


def test_objective_verb_matches_the_level():
    assert objective_for("databases", "remember").startswith("Define")
    assert objective_for("databases", "create").startswith("Design")


def test_objectives_slide_tags_every_row_and_climbs_the_taxonomy():
    content = _content()
    for index, slide in enumerate(content):
        slide["bloom_level"] = classify_bloom_level(
            slide["title"], slide["bullets"], index
        )

    objectives = build_objectives_slide(content)
    assert objectives is not None
    assert objectives["type"] == "objectives"
    assert len(objectives["bullets"]) == len(content)
    assert len(objectives["objectives"]) == len(content)
    levels = [entry["level"] for entry in objectives["objectives"]]
    assert levels == sorted(levels, key=BLOOM_LEVELS.index)
    for bullet, entry in zip(objectives["bullets"], objectives["objectives"]):
        assert f"({LEVEL_DISPLAY[entry['level']]})" in bullet


def test_objectives_slide_with_no_content_is_omitted():
    assert build_objectives_slide([]) is None


def test_objectives_slide_summarises_rows_past_the_cap():
    content = [
        {"title": f"Topic {i}", "bullets": ["Define the key terms."]}
        for i in range(10)
    ]
    objectives = build_objectives_slide(content)
    assert len(objectives["objectives"]) == 8
    assert objectives["bullets"][-1] == "... plus 2 further objectives"


def test_check_understanding_has_three_options_and_an_answer_key():
    content = _content()
    slide = content[1]
    slide["bloom_level"] = classify_bloom_level(
        slide["title"], slide["bullets"], 1
    )

    check = build_check_understanding_slide(slide, content)
    assert check is not None
    assert check["type"] == "quiz"
    assert check["bloom_level"] == "apply"
    assert check["task"]["level"] == "apply"
    assert len(check["questions"]) == 2
    for question in check["questions"]:
        assert len(question["options"]) == 3
        assert question["options"][question["answer_index"]] in [
            b.strip() for b in slide["bullets"]
        ]
    assert "Q1:" in check["speaker_notes"]["answers"]
    assert "Q2:" in check["speaker_notes"]["answers"]


def test_check_understanding_is_skipped_without_material():
    assert build_check_understanding_slide({"title": "Empty", "bullets": []}) is None


def test_poster_attached_only_without_a_visual_and_with_context():
    with_image = {
        "title": "Workflow",
        "bullets": ["The process has four steps.", "It leads to a result."],
        "image_url": "https://example.invalid/x.jpg",
    }
    plain = {
        "title": "Workflow",
        "bullets": ["The process has four steps.", "It leads to a result."],
    }
    assert attach_posters([with_image, plain])[0].get("poster") is None
    assert plain["poster"] is True
    assert plain["image_promote"] is True
    assert plain["image_diagram"]["points"] == plain["bullets"]


def test_posters_can_be_disabled():
    slide = {
        "title": "Workflow",
        "bullets": ["The process has four steps.", "It leads to a result."],
    }
    attach_posters([slide], enabled=False)
    assert slide.get("poster") is None


def test_deck_all_pedagogy_on_adds_objectives_and_one_quiz_per_subtopic():
    deck = _deck()
    assert deck[0]["type"] == "cover"
    assert deck[1]["type"] == "objectives"
    content = [s for s in deck if s["type"] in ("theory", "practical")]
    quizzes = [s for s in deck if s["type"] == "quiz"]
    assert len(quizzes) == len(content)
    assert all(s.get("bloom_level") for s in content)


def test_deck_pedagogy_can_be_switched_off():
    deck = _deck(objectives=False, quizzes=False, posters=False)
    types = [s["type"] for s in deck]
    assert "objectives" not in types
    assert "quiz" not in types
    assert not any(s.get("poster") for s in deck)
    assert types[0] == "cover"
    assert types[-2:] == ["takeaways", "end"]
