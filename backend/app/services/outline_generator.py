"""
Stage 1: Generates a structured outline with unique slide titles and content summaries.
This ensures each slide will have distinct content before detailed generation.
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


def generate_outline(
    source_text: str,
    slide_count: int,
    audience_level: str,
    title: str,
    image_count: int = 0,
) -> list[dict[str, Any]]:
    """
    Generate a structured outline with unique slide titles and content summaries.
    
    Args:
        source_text: The source material to create presentation from
        slide_count: Number of content slides (excluding cover)
        audience_level: Target audience (Beginner, Intermediate, Advanced)
        title: Presentation title
    
    Returns:
        List of outline items with title and summary
    """
    if not settings.gemini_api_key:
        raise RuntimeError("Missing GEMINI_API_KEY. Add it to your .env file.")

    audience_guidance = {
        "Beginner": "Use simple language, explain all terms clearly, focus on fundamentals with practical benefits, use relatable examples",
        "Intermediate": "Use professional terminology, include relevant details, examples from practice, balance theory and application",
        "Advanced": "Use sophisticated language, focus on strategic implications, innovation, leadership aspects, advanced concepts",
    }

    guidance = audience_guidance.get(audience_level, audience_guidance["Intermediate"])

    prompt = f"""You are an expert educational content designer creating a structured outline for a presentation.

Task: Create a detailed outline with {slide_count} UNIQUE content slides.

CRITICAL REQUIREMENTS:
1. Each slide MUST have a distinctly different topic/focus
2. No slide should duplicate content from another
3. Content must be logically sequenced and build upon each other
4. Each topic should cover a different aspect of the source material

IMAGE PLACEMENT: You have {image_count} images available. Decide which {image_count} slides would benefit most from visual elements (diagrams, charts, illustrations). Mark these slides with "needs_image": true and provide a specific "image_description" for what the image should show.

SLIDE CHARACTERISTICS:
- Topic: Descriptive slide title (4-8 words) emphasizing this slide's unique focus
- Summary: 2-3 sentence description of specific content for this slide (NOT generic)
- Unique angle: What makes this slide different from others
- Suitable for audience: "{guidance}"

CONTENT GUIDELINES:
- Extract and distribute actual content from source text across all {slide_count} slides
- Each slide focuses on a distinct subtopic or aspect
- Avoid repetition - ensure variety in content
- Ensure logical flow and progression
- Make content age-appropriate and engaging for {audience_level} audience

Return a JSON array with exactly {slide_count} outline items. Each item must have:
- "slide_number": Sequential number starting from 1
- "title": Unique slide title
- "key_talking_points": List of 3-4 specific concepts/points to cover
- "needs_image": true/false (only {image_count} slides should be true)
- "image_description": Specific description of what image to show (only if needs_image is true)

Example format:
[
  {{
    "slide_number": 1,
    "title": "Foundational Concepts Overview",
    "key_talking_points": ["Definition of X", "Historical context", "Why this matters"],
    "needs_image": false
  }},
  {{
    "slide_number": 2,
    "title": "Implementation Strategies",
    "key_talking_points": ["Method A", "Method B", "Best practices"],
    "needs_image": true,
    "image_description": "Flowchart showing the step-by-step implementation process"
  }}
]

Source material:
{source_text}

Generate exactly {slide_count} UNIQUE outline items with {image_count} marked for images:"""

    raw = _strip_code_fences(generate_content(prompt, temperature=0.5, response_mime_type="application/json", timeout=60, task="outline"))
    outline_items = json.loads(raw)
    
    if not isinstance(outline_items, list):
        raise RuntimeError("Gemini outline response is not a JSON array")

    # Normalize and validate outline items
    validated: list[dict[str, Any]] = []
    for idx, item in enumerate(outline_items, start=1):
        if not isinstance(item, dict):
            continue
        
        validated.append({
            "slide_number": idx,
            "title": str(item.get("title", f"Slide {idx}")),
            "key_talking_points": item.get("key_talking_points", [])[:4],
            "needs_image": bool(item.get("needs_image", False)),
            "image_description": str(item.get("image_description", "")) if item.get("needs_image") else "",
            # Keep backward compatibility
            "topic": str(item.get("title", f"Slide {idx}")),
            "summary": str(item.get("summary", "Content summary")),
            "key_concepts": item.get("key_talking_points", item.get("key_concepts", []))[:4],
            "content_focus": str(item.get("content_focus", "Content")),
            "outline_index": idx,
        })

    # Ensure we have exactly slide_count items
    while len(validated) < slide_count:
        idx = len(validated) + 1
        validated.append({
            "slide_number": idx,
            "title": f"Topic {idx}",
            "key_talking_points": ["Key point"],
            "needs_image": False,
            "image_description": "",
            # Backward compatibility
            "topic": f"Topic {idx}",
            "summary": "Additional content area.",
            "key_concepts": ["Key point"],
            "content_focus": "Content",
            "outline_index": idx,
        })

    return validated[:slide_count]
