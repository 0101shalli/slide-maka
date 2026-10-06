from app.services.text_structurer import structure_text


STRUCTURED_SAMPLE = """Mother-to-Child HIV Transmission Prevention

Presented by: Dr. Jane Doe
25 March 2024

Introduction
Mother-to-child transmission (MTCT) is the primary route of paediatric HIV infection. Scaling up prevention of mother-to-child transmission (PMTCT) services reduces infant infections dramatically.

1. Objectives of the Seminar
- Define the core principles of PMTCT.
- Explain the WHO Option B+ approach.
- Outline a step-by-step national implementation plan.

Practical Activities
- Conduct a small-group workflow exercise for antenatal screening.
- Draft an implementation checklist for the clinic team.
- Practice counselling using the hands-on scenario cards.

Conclusion
Early testing and early treatment are decisive for healthy mothers and HIV-free babies."""


def test_structure_extracts_title_and_metadata():
    data = structure_text(STRUCTURED_SAMPLE)
    assert data["title"] == "Mother-to-Child HIV Transmission Prevention"
    assert data["metadata"]["author"] == "Dr. Jane Doe"
    assert data["metadata"]["date"] == "25 March 2024"


def test_structure_detects_headers_and_sections():
    data = structure_text(STRUCTURED_SAMPLE)
    headings = [s["heading"] for s in data["sections"]]
    assert headings == ["Introduction", "Objectives of the Seminar", "Practical Activities", "Conclusion"]


def test_structure_classifies_practical_sections():
    data = structure_text(STRUCTURED_SAMPLE)
    by_heading = {s["heading"]: s for s in data["sections"]}
    assert by_heading["Practical Activities"]["type"] == "practical"
    assert by_heading["Introduction"]["type"] == "theory"


def test_structure_extracts_bullet_points():
    data = structure_text(STRUCTURED_SAMPLE)
    practical = [s for s in data["sections"] if s["heading"] == "Practical Activities"][0]
    assert len(practical["points"]) == 3
    assert practical["points"][0].startswith("Conduct")


def test_structure_flattened_prose_becomes_single_section():
    blob = (
        "Artificial intelligence is transforming education by personalising learning paths."
        " Teachers can now tailor lessons to each student's pace."
        " This improves engagement and outcomes across classrooms."
    )
    data = structure_text(blob)
    assert data["sections"]
    assert data["sections"][0]["heading"] == "Key Concepts & Overview"
    assert len(data["sections"][0]["points"]) >= 1


def test_structure_empty_input():
    assert structure_text("")["sections"] == []
    assert structure_text("   \n  ")["sections"] == []


def test_structure_numbered_heading_loses_prefix():
    data = structure_text(STRUCTURED_SAMPLE)
    assert "Objectives of the Seminar" in [s["heading"] for s in data["sections"]]


def test_structure_does_not_steal_section_heading_as_subtitle():
    sample = """HIV Prevention of Mother-to-Child Transmission (PMTCT)

Introduction
The Mother-to-Child Transmission (MTCT) of HIV remains a major public health challenge.

The Option B+ Approach
This approach provides lifelong antiretroviral therapy. It is safe, simple and effective.

Conclusion
Together, we can end new HIV infections in children."""
    data = structure_text(sample)
    headings = [s["heading"] for s in data["sections"]]
    assert headings == ["Introduction", "The Option B+ Approach", "Conclusion"]
    by_heading = {s["heading"]: s for s in data["sections"]}
    assert len(by_heading["The Option B+ Approach"]["points"]) == 1
    assert by_heading["The Option B+ Approach"]["points"][0].startswith("This approach")
    assert all("antiretroviral" not in p for p in by_heading["Introduction"]["points"])