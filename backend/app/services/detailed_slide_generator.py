"""
Stage 2: Generates detailed per-slide content based on the outline.
Creates formatted bullet points with emphasis, proper pacing, and engagement.
"""
import json
from typing import Any
from ..core.config import settings
from .llm import generate_content


def _strip_code_fences(raw_text: str) -> str:
    """Remove markdown code fences from response."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    return cleaned.strip()


def generate_detailed_slide_content(
    outline_item: dict[str, Any],
    source_text: str,
    audience_level: str,
    slide_type: str,
) -> dict[str, Any]:
    """
    Generate detailed content for a single slide based on outline item.
    
    Args:
        outline_item: From stage 1 outline generation
        source_text: Original source material
        audience_level: Target audience
        slide_type: "theory" or "practical"
    
    Returns:
        Dictionary with detailed slide content
    """
    if not settings.gemini_api_key:
        raise RuntimeError("Missing GEMINI_API_KEY")

    topic = outline_item.get("topic", "Content")
    summary = outline_item.get("summary", "")
    key_concepts = outline_item.get("key_concepts", [])

    audience_guidance = {
        "Beginner": "Use simple vocabulary, explain all terms, include relatable examples, avoid jargon",
        "Intermediate": "Use professional language, include technical details where appropriate, practical applications",
        "Advanced": "Use sophisticated terminology, include strategic context, innovation and leadership angles",
    }

    guidance = audience_guidance.get(audience_level, audience_guidance["Intermediate"])

    prompt = f"""You are an expert presentation content writer creating compelling, specific slide content.

SLIDE REQUIREMENTS:
Topic: {topic}
Summary: {summary}
Key Concepts: {", ".join(key_concepts)}
Audience: {audience_level} ({guidance})
Type: {slide_type} slide

Create SPECIFIC, DETAILED content for this slide using the source material below.

REQUIREMENTS:
1. Write 4-5 bullet points that are SPECIFIC and DETAILED (12-18 words each)
2. Include formatting hints: use **text** for emphasis, use --text-- for important callouts
3. Each bullet should be substantive and distinct from others
4. Make content engaging and appropriate for {audience_level} audience
5. For {slide_type} slides: {"Apply practical, actionable focus" if slide_type == "practical" else "Explain concepts and principles"}
6. Use concrete examples or data when possible

Return JSON with:
- "title": Final optimized slide title (4-8 words, more specific than topic)
- "formatted_bullets": List of 4-5 detailed, specific bullet points with **emphasis** markers
- "engagement_hook": 1 sentence to grab attention or connect to audience
- "visual_hint": Suggested image keyword or visual element

Example format:
{{
  "title": "Specific, Focused Title",
  "formatted_bullets": [
    "First detailed point with **key emphasis** word",
    "Second distinct point with --important callout--",
    "Third specific example or data point"
  ],
  "engagement_hook": "Consider this real-world scenario...",
  "visual_hint": "keyword for relevant image"
}}

SOURCE MATERIAL (extract specific content for this slide):
{source_text}

Generate detailed content for this specific slide:"""

    try:
        raw = _strip_code_fences(generate_content(prompt, temperature=0.6, response_mime_type="application/json", task="detailed_slides"))
        content = json.loads(raw)
        
        # Validate and return
        formatted_bullets = content.get("formatted_bullets", [])
        if not isinstance(formatted_bullets, list):
            formatted_bullets = [str(formatted_bullets)]
        
        formatted_bullets = [str(b) for b in formatted_bullets[:5]]  # Max 5 bullets
        while len(formatted_bullets) < 3:  # Minimum 3 bullets
            formatted_bullets.append("Key information point.")

        return {
            "title": str(content.get("title", topic))[:100],
            "formatted_bullets": formatted_bullets,
            "engagement_hook": str(content.get("engagement_hook", "")),
            "visual_hint": str(content.get("visual_hint", topic.lower())),
        }
    except (json.JSONDecodeError, ValueError, RuntimeError):
        return _get_default_slide_content(topic)


def _get_default_slide_content(topic: str) -> dict[str, Any]:
    """Generate default slide content."""
    return {
        "title": topic,
        "formatted_bullets": [
            f"Core aspect of {topic.lower()}",
            "Key consideration for this topic",
            "Important principle to remember",
            "Practical application or example",
        ],
        "engagement_hook": f"Let's explore {topic.lower()} in detail.",
        "visual_hint": topic.lower().replace(" ", "-"),
    }
