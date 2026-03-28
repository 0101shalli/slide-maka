from app.services.parameter_calculator import Distribution, theory_slide_indices


def build_prompt(source_text: str, distribution: Distribution, audience_level: str) -> str:
    theory_indices = [i + 1 for i in theory_slide_indices(distribution.total_slides, distribution.theory_slides)]
    practical_indices = [i for i in range(1, distribution.total_slides + 1) if i not in theory_indices]

    density_hint = (
        "Use one point per slide and expand with examples."
        if distribution.total_slides > 15
        else "Summarize heavily and keep each slide concise."
    )

    return f"""
You are a presentation planner.
Hard constraint: return valid JSON array with exactly {distribution.total_slides} slide objects.
Audience level: {audience_level}.
Theory slides target: {distribution.theory_slides}.
Practical slides target: {distribution.practical_slides}.
Theory slide numbers: {theory_indices}.
Practical slide numbers: {practical_indices}.
{density_hint}
If source content is short, create title/section/key takeaway slides to fill count.
Each object schema:
{{
  \"title\": string,
  \"bullets\": [string],
  \"type\": \"theory\" | \"practical\"
}}
Source text:
{source_text}
""".strip()
