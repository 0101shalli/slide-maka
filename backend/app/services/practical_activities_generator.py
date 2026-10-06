"""
Practical activities generator: Creates exercises, examples, and interactive elements.
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


def generate_practical_activities(
    slide_title: str,
    slide_content: str,
    audience_level: str,
    slide_index: int,
) -> dict[str, Any]:
    """
    Generate practical exercises and activities for a slide.
    
    Args:
        slide_title: Title of the slide
        slide_content: Bullet point content
        audience_level: Target audience
        slide_index: Slide number
    
    Returns:
        Dictionary with practical activities
    """
    if not settings.gemini_api_key:
        raise RuntimeError("Missing GEMINI_API_KEY")

    prompt = f"""You are an educational activity designer creating practical exercises and interactive elements.

SLIDE INFORMATION:
- Title: {slide_title}
- Content: {slide_content}
- Audience Level: {audience_level}
- Slide: {slide_index}

Create practical activities in JSON format with:

1. "quick_activity": A 2-5 minute hands-on exercise the audience can do RIGHT NOW
2. "discussion_question": A thought-provoking question to engage audience thinking
3. "real_world_example": Concrete example or case study relevant to the audience
4. "reflection_prompt": What should audience reflect on or remember

Make activities:
- Age-appropriate and engaging for {audience_level} learners
- Doable without special materials
- Related to the slide content
- About 2-3 sentences each

Return JSON:
{{
  "quick_activity": "description of activity",
  "discussion_question": "question for audience",
  "real_world_example": "concrete example or case study",
  "reflection_prompt": "what to remember or reflect on"
}}
"""

    try:
        raw = _strip_code_fences(generate_content(prompt, temperature=0.5, response_mime_type="application/json", task="activities"))
        activities = json.loads(raw)
        
        return {
            "quick_activity": str(activities.get("quick_activity", "")),
            "discussion_question": str(activities.get("discussion_question", "")),
            "real_world_example": str(activities.get("real_world_example", "")),
            "reflection_prompt": str(activities.get("reflection_prompt", "")),
        }
    except Exception:
        return _get_default_activities()


def _get_default_activities() -> dict[str, Any]:
    """Return default activities when generation fails."""
    return {
        "quick_activity": "Take a moment to reflect on how this concept applies to your own experience.",
        "discussion_question": "How does this relate to what you already know?",
        "real_world_example": "This concept is applied in common real-world scenarios.",
        "reflection_prompt": "Consider one way you could use this knowledge in your life.",
    }
