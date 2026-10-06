"""
Speaker notes generator: Creates detailed speaking points, talking points, and guidance.
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


def generate_speaker_notes(
    slide_title: str,
    slide_content: str,
    slide_type: str,
    audience_level: str,
    slide_index: int,
    total_slides: int,
) -> dict[str, Any]:
    """
    Generate comprehensive speaker notes for a slide.
    
    Args:
        slide_title: Title of the slide
        slide_content: Bullet point content of the slide
        slide_type: "theory" or "practical"
        audience_level: Target audience level
        slide_index: Current slide number
        total_slides: Total number of content slides
    
    Returns:
        Dictionary with speaker notes content
    """
    if not settings.gemini_api_key:
        raise RuntimeError("Missing GEMINI_API_KEY")

    context = "opening" if slide_index == 1 else "transition" if slide_index == total_slides else "development"

    prompt = f"""You are a presentation coach creating detailed speaker notes for a professional speaker.

SLIDE INFORMATION:
- Title: {slide_title}
- Content: {slide_content}
- Type: {slide_type}
- Audience: {audience_level}
- Position: Slide {slide_index} of {total_slides} ({context})

Create comprehensive speaker notes in JSON format with these sections:

1. "opening_remarks": 2-3 sentences to introduce this slide (how to transition to it)
2. "main_talking_points": 3-4 detailed points to cover while presenting (expand on bullets)
3. "audience_engagement": 1-2 suggestions for interacting with audience or real-world connection
4. "time_estimate": Suggested seconds to spend on this slide
5. "key_takeaway": 1-2 sentence summary of what audience should remember
6. "transition_to_next": 1 sentence bridge to next slide (or conclusion if last)

Make notes conversational, practical, and speaker-friendly. Tailor language to {audience_level} audience.

For {slide_type} slides:
- Theory: Emphasize understanding and context, explain the "why"
- Practical: Focus on "how to apply", steps, and real-world examples

Return valid JSON:
{{
  "opening_remarks": "text",
  "main_talking_points": ["point 1", "point 2", "point 3"],
  "audience_engagement": "suggestion",
  "time_estimate": 90,
  "key_takeaway": "summary",
  "transition_to_next": "bridge"
}}
"""

    try:
        raw = _strip_code_fences(generate_content(prompt, temperature=0.4, response_mime_type="application/json", task="speaker_notes"))
        notes = json.loads(raw)
        
        # Validate and set defaults
        return {
            "opening_remarks": str(notes.get("opening_remarks", "")),
            "main_talking_points": notes.get("main_talking_points", [])[:4],
            "audience_engagement": str(notes.get("audience_engagement", "")),
            "time_estimate": int(notes.get("time_estimate", 90)),
            "key_takeaway": str(notes.get("key_takeaway", "")),
            "transition_to_next": str(notes.get("transition_to_next", "")),
        }
    except (json.JSONDecodeError, ValueError, RuntimeError):
        return _get_default_speaker_notes(slide_title, slide_type, slide_index, total_slides)


def _get_default_speaker_notes(title: str, slide_type: str, index: int, total: int) -> dict[str, Any]:
    """Generate basic default speaker notes."""
    return {
        "opening_remarks": f"Moving to our next point: {title}",
        "main_talking_points": [
            "Focus on the key concepts presented",
            "Connect to the previous discussion",
            "Invite audience questions",
        ],
        "audience_engagement": "Ask the audience if they can relate to this concept",
        "time_estimate": 90,
        "key_takeaway": f"Remember: {title}",
        "transition_to_next": "Let's move forward to the next important aspect." if index < total else "Thank you for your attention.",
    }
