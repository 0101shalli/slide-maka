import re
from urllib.parse import quote_plus
from ..core.config import settings
from .parameter_calculator import Distribution, theory_slide_indices, image_slide_indices
from .gemini_structurer import generate_slides_json
from .speaker_notes_generator import generate_speaker_notes
from .practical_activities_generator import generate_practical_activities, _get_default_activities


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate the Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def _calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity percentage between two texts (0.0 to 1.0)."""
    if not text1 or not text2:
        return 0.0
    
    # Normalize texts for comparison
    text1 = re.sub(r'[^\w\s]', '', text1.lower())
    text2 = re.sub(r'[^\w\s]', '', text2.lower())
    
    max_len = max(len(text1), len(text2))
    if max_len == 0:
        return 1.0
    
    distance = _levenshtein_distance(text1, text2)
    similarity = 1 - (distance / max_len)
    return max(0.0, min(1.0, similarity))


def build_enhanced_prompt(source_text: str, distribution: Distribution, audience_level: str, title: str) -> str:
    content_slides = max(distribution.content_slides, 1)
    theory_indices = [i + 1 for i in theory_slide_indices(content_slides, distribution.theory_slides)]
    practical_indices = [i for i in range(1, content_slides + 1) if i not in theory_indices]

    audience_guidance = {
        "Beginner": "Use simple language, explain terms clearly, focus on fundamentals and practical benefits",
        "Intermediate": "Use professional terminology, include relevant details, balance theory and practice",
        "Advanced": "Use sophisticated language, focus on strategic implications, innovation, and leadership"
    }

    return f"""
You are an expert presentation designer. Generate exactly {content_slides} content slides from the source text.

Provide the response using the exact block format below. Do not include any extra text before or after the slide blocks.

<<<START_SLIDE>>>
SLIDE_NUMBER: 1
TITLE: Slide title here
TYPE: theory or practical
BULLETS:
- First bullet
- Second bullet
- Third bullet
IMAGE_DESCRIPTION: A short phrase describing an image that explains this slide
<<<END_SLIDE>>>

Create one block like this for each slide.

SLIDE RULES:
- Generate exactly {content_slides} unique slides.
- Use clear, descriptive titles (4-8 words).
- Use 3-5 bullets per slide.
- Keep bullets concise (max 18 words) and distinct.
- CRITICAL: Do not repeat topics, concepts, or content across slides.
- CRITICAL: Each slide must cover a completely different aspect of the source material.
- CRITICAL: Divide the source text into {content_slides} distinct sections and assign each section to one slide only.
- Use the audience style: {audience_guidance[audience_level]}.
- Follow a clear three-act arc: open with context, develop each idea, close with next steps.
- Apply the 6x6 rule (at most 6 bullets per slide) and keep the deck visually clean with generous white space.
- Use these indices for types:
  - Theory slides: {theory_indices}
  - Practical slides: {practical_indices}
- Each slide must include IMAGE_DESCRIPTION that explains what visual should accompany the slide.

CONTENT DISTRIBUTION REQUIREMENTS:
- Analyze the source text and identify {content_slides} distinct topics or concepts.
- Assign exactly one topic/concept to each slide.
- Ensure no overlap between slides - each slide covers unique information.
- If the source text has numbered sections, use those as slide boundaries.
- If the source text flows continuously, create logical breaks at topic changes.

Presentation title: {title}
Source text:
{source_text}
""".strip()


def build_prompt_input_prompt(
    brief: str,
    distribution: Distribution,
    audience_level: str,
    title: str,
) -> str:
    """Prompt used for the ``prompt`` input source: the LLM creates the deck
    material from the user's brief + all the user-selected parameters.

    The output uses the same ``<<<START_SLIDE>>>`` block format that
    ``generate_slides_json`` parses.
    """
    content_slides = max(distribution.content_slides, 1)
    theory_indices = [i + 1 for i in theory_slide_indices(content_slides, distribution.theory_slides)]
    practical_indices = [i for i in range(1, content_slides + 1) if i not in theory_indices]
    image_slots = [i + 1 for i in image_slide_indices(content_slides, distribution.image_slides)]

    audience_guidance = {
        "Beginner": "Use simple language, explain terms clearly, focus on fundamentals and practical benefits",
        "Intermediate": "Use professional terminology, include relevant details, balance theory and practice",
        "Advanced": "Use sophisticated language, focus on strategic implications, innovation, and leadership",
    }

    return f"""
You are an expert presentation designer. Create exactly {content_slides} content slides for the brief below.

Provide the response using the exact block format below. Do not include any extra text before or after the slide blocks.

<<<START_SLIDE>>>
SLIDE_NUMBER: 1
TITLE: Slide title here
TYPE: theory or practical
BULLETS:
- First bullet
- Second bullet
- Third bullet
IMAGE_DESCRIPTION: A short phrase describing an image that explains this slide
<<<END_SLIDE>>>

Create one block like this for each slide.

SLIDE RULES:
- Generate exactly {content_slides} unique content slides that fully answer the brief.
- Use clear, action-oriented titles (4-8 words) that state the slide's purpose.
- Use 3-5 bullets per slide; keep bullets concise (max 18 words) and distinct.
- One idea per slide; never repeat a topic or concept across slides.
- Keep the whole deck concise and presentation-ready (16:9, scannable in 3 seconds).
- Use the audience style: {audience_guidance[audience_level]}.
- Use these indices for types (theory slides carry conceptual/foundational content, practical slides carry how-to/application content):
  - Theory slides: {theory_indices}
  - Practical slides: {practical_indices}
- Give slides {image_slots} an IMAGE_DESCRIPTION that describes a compelling, content-relevant photo or diagram.
- Every slide must include an IMAGE_DESCRIPTION that explains what visual should accompany the slide.

Presentation title: {title}
Brief:
{brief}
""".strip()


def enhance_slide_content(title: str, bullets: list[str], slide_type: str, audience_level: str) -> dict:
    """Enhance slide content for professional presentation standards while preserving original meaning."""

    # Keep title mostly as-is, just basic formatting
    enhanced_title = title.strip().title()
    words = enhanced_title.split()
    if len(words) > 8:
        enhanced_title = ' '.join(words[:8])

    # Process bullets very lightly to preserve original meaning
    enhanced_bullets = []
    for bullet in bullets[:5]:  # Limit to 5 bullets max
        enhanced = _lightly_refine_bullet(bullet)
        if enhanced and enhanced not in enhanced_bullets:  # Avoid duplicates
            enhanced_bullets.append(enhanced)

    # If we don't have enough bullets, add lightly refined versions of remaining original bullets
    if len(enhanced_bullets) < 3:
        for original_bullet in bullets[len(enhanced_bullets):]:
            if len(enhanced_bullets) >= 3:
                break
            refined = _lightly_refine_bullet(original_bullet)
            if refined and refined not in enhanced_bullets:
                enhanced_bullets.append(refined)

    # Ensure we have at least 3 bullets with minimal content
    while len(enhanced_bullets) < 3:
        enhanced_bullets.append("Key information point.")

    # Ensure maximum 5 bullets
    enhanced_bullets = enhanced_bullets[:5]

    return {
        "title": enhanced_title,
        "bullets": enhanced_bullets,
        "type": slide_type
    }


def _redistribute_content(single_slide: dict, target_slides: int, distribution: Distribution) -> list[dict]:
    """Redistribute content from a single slide across multiple slides."""
    original_title = single_slide.get("title", "Content Overview")
    original_bullets = single_slide.get("bullets", [])
    theory_indices = set(theory_slide_indices(target_slides, distribution.theory_slides))

    # If we have enough bullets to distribute
    if len(original_bullets) >= target_slides:
        # Split bullets evenly across slides
        bullets_per_slide = len(original_bullets) // target_slides
        remainder = len(original_bullets) % target_slides

        slides = []
        bullet_index = 0

        for i in range(target_slides):
            slide_type = "theory" if i in theory_indices else "practical"

            # Calculate how many bullets this slide gets
            bullets_count = bullets_per_slide + (1 if i < remainder else 0)
            slide_bullets = original_bullets[bullet_index:bullet_index + bullets_count]
            bullet_index += bullets_count

            # Create title for this slide
            if i == 0:
                slide_title = original_title
            else:
                # Create a subtitle based on the content
                first_bullet = slide_bullets[0] if slide_bullets else f"Part {i + 1}"
                slide_title = _create_meaningful_title(first_bullet[:50], slide_type)

            slides.append({
                "title": slide_title,
                "bullets": slide_bullets,
                "type": slide_type
            })

        return slides
    else:
        # If we don't have enough bullets, create slides with distributed content
        slides = []
        for i in range(target_slides):
            slide_type = "theory" if i in theory_indices else "practical"

            # Cycle through available bullets
            bullet_index = i % len(original_bullets) if original_bullets else 0
            bullet = original_bullets[bullet_index] if original_bullets else f"Key point {i + 1}"

            if i == 0:
                slide_title = original_title
            else:
                slide_title = _create_meaningful_title(bullet[:50], slide_type)

            slides.append({
                "title": slide_title,
                "bullets": [bullet] if bullet else ["Key information point."],
                "type": slide_type
            })

        return slides


def _create_meaningful_title(text: str, slide_type: str) -> str:
    """Create a meaningful title from content text."""
    text = text.strip()

    # Try to extract a good title from the beginning
    words = text.split()
    if len(words) <= 8:
        title = text.title()
    else:
        # Take first meaningful phrase
        title = ' '.join(words[:8]).title()

    # Clean up the title
    title = re.sub(r'[^\w\s-]', '', title)  # Remove special chars except hyphens
    title = re.sub(r'\s+', ' ', title).strip()

    if not title:
        title = f"Content Overview"

    return title


def _refine_bullet(bullet: str, slide_type: str, audience_level: str) -> str:
    """Refine bullet point to be professional while preserving original meaning."""

    bullet = bullet.strip()

    # Remove bullet markers
    bullet = re.sub(r'^[•\-*\s]+', '', bullet)

    if not bullet:
        return ""

    # Light professional enhancements based on audience level
    if audience_level == "Beginner":
        # Simple improvements for clarity
        bullet = re.sub(r'\bmake\b', 'create', bullet, flags=re.I)
        bullet = re.sub(r'\bget\b', 'obtain', bullet, flags=re.I)
    elif audience_level == "Intermediate":
        # Moderate professional language
        bullet = re.sub(r'\bmake\b', 'develop', bullet, flags=re.I)
        bullet = re.sub(r'\bget\b', 'acquire', bullet, flags=re.I)
    # Advanced level keeps original language

    # Ensure proper capitalization and punctuation
    bullet = bullet.capitalize()
    if not bullet.endswith(('.', '!', '?')):
        bullet += '.'

    # Keep it concise but preserve meaning
    words = bullet.split()
    if len(words) > 18:  # Allow longer bullets to preserve meaning
        bullet = ' '.join(words[:18]) + '.'

    return bullet


def _lightly_refine_bullet(bullet: str) -> str:
    """Very light refinement that just ensures proper formatting."""
    bullet = bullet.strip()
    bullet = re.sub(r'^[•\-*\s]+', '', bullet)

    if not bullet:
        return "Key information point."

    bullet = bullet.capitalize()
    if not bullet.endswith(('.', '!', '?')):
        bullet += '.'

    return bullet


def extract_slide_points(source_text: str) -> list[str]:
    lines = [line.strip() for line in source_text.splitlines() if line.strip()]
    points: list[str] = []

    for line in lines:
        if line.startswith(('•', '-', '*')):
            points.append(re.sub(r'^[•\-*\s]+', '', line).strip())
        elif '•' in line:
            for part in line.split('•'):
                clean_part = part.strip()
                if clean_part:
                    points.append(clean_part)
        else:
            sentences = re.split(r'(?<=[.!?])\s+', line)
            for sentence in sentences:
                clean_sentence = sentence.strip()
                if clean_sentence:
                    points.append(clean_sentence)

    normalized = [re.sub(r'^[\-\*\s]+', '', point).strip() for point in points if point.strip()]
    return normalized or ["Summary of the source content."]


def build_slide_title(content: str, index: int, slide_type: str) -> str:
    content = content.strip()
    if not content:
        return f"Slide {index}"

    title = _shorten_point(content)
    if not title:
        title = re.sub(r'^\s*(it|this|that|these|those)\s+is\s+(a|an|the)\s+', '', content, flags=re.I)
        title = re.split(r'[:—–-]|\bis\b|\bbased on\b|\bthat\b|\bthis\b', title, maxsplit=1)[0].strip()
        title = re.sub(r'\s+', ' ', title)
        title = re.sub(r'^(it|this|that|these|those)\s+', '', title, flags=re.I).strip()
        if not title:
            title = content.split()[0] if content.split() else f"Slide {index}"

    if len(title.split()) > 7:
        title = ' '.join(title.split()[:7])

    if slide_type == "practical":
        if not title.lower().startswith("practical"):
            return f"Practical {title}"
    elif slide_type == "theory":
        if not title.lower().endswith("fundamentals"):
            return f"{title} Fundamentals"
    return title or f"Slide {index}"


def _shorten_point(point: str) -> str:
    text = point.strip().rstrip('.!?')
    text = re.sub(r'^\s*(it|this|that|these|those)\s+is\s+(a|an|the)\s+', '', text, flags=re.I)
    split_pattern = re.compile(r'[,;:]|\bis\b|\bare\b|\bbased on\b|\bthat\b|\bthis\b', flags=re.I)
    short = split_pattern.split(text, maxsplit=1)[0].strip()
    short = re.sub(r'^(it|this|that|these|those)\s+', '', short, flags=re.I).strip()
    if not short:
        short = re.sub(r'^\s*(it|this|that|these|those)\s+', '', text, flags=re.I).strip()
    if len(short.split()) > 12:
        short = ' '.join(short.split()[:8])
    return short


def _semantic_explanation(point: str, slide_type: str, audience_level: str) -> str:
    text = point.rstrip('.!?').strip()
    lower = text.lower()

    if "data" in lower:
        base = "This explains how the information is structured and used to support your goals."
    elif "model" in lower:
        base = "This explains the framework or prediction system behind the concept."
    elif "algorithm" in lower:
        base = "This explains the step-by-step logic that drives the process."
    elif "architecture" in lower:
        base = "This explains how components work together to deliver reliable results."
    elif "process" in lower:
        base = "This explains the sequence of actions and decisions needed for a strong outcome."
    elif "tool" in lower or "framework" in lower:
        base = "This explains the practical resource used to deliver results in real-world work."
    else:
        base = "This explains the concept clearly and shows why it matters in context."

    if audience_level == "Beginner":
        return f"{base} It is described in a simple, easy-to-follow way for new learners."
    if audience_level == "Intermediate":
        return f"{base} It is explained with enough depth to connect theory to practical decision-making."
    return f"{base} It is expressed at a professional level for an experienced audience."


def _semantic_context(point: str, slide_type: str) -> str:
    if slide_type == "practical":
        return "It explains how this idea is used in real work to solve a specific challenge or deliver value."
    return "It explains why this concept is important to the broader subject and how it helps shape decisions."


def generate_professional_bullets(point: str, slide_type: str, audience_level: str) -> list[str]:
    """Generate professional, unique bullet points for a slide."""
    base_bullet = _format_point(point)
    
    bullets = [base_bullet]
    
    # Add 2-3 more professional bullets based on type and level
    if slide_type == "theory":
        if audience_level == "Beginner":
            bullets.extend([
                f"Key concept: {point.lower().strip('.')} forms the foundation of understanding.",
                "This principle helps connect basic ideas to broader applications.",
                "Understanding this concept enables better decision-making in related areas."
            ])
        elif audience_level == "Intermediate":
            bullets.extend([
                f"Core principle: {point.lower().strip('.')} integrates with existing knowledge frameworks.",
                "This concept provides analytical depth for complex problem-solving.",
                "Application of this theory leads to optimized outcomes in professional settings."
            ])
        else:  # Advanced
            bullets.extend([
                f"Advanced framework: {point.lower().strip('.')} enables sophisticated system design.",
                "This theoretical foundation supports cutting-edge innovation and research.",
                "Mastery of this concept is essential for leadership in the field."
            ])
    else:  # practical
        if audience_level == "Beginner":
            bullets.extend([
                f"Practical application: Start with {point.lower().strip('.')} in controlled environments.",
                "Implementation tip: Focus on measurable results and iterative improvements.",
                "Success metric: Track progress through clear, achievable milestones."
            ])
        elif audience_level == "Intermediate":
            bullets.extend([
                f"Implementation strategy: Leverage {point.lower().strip('.')} for scalable solutions.",
                "Best practice: Combine this approach with industry standards for optimal results.",
                "Performance optimization: Monitor and refine based on real-world feedback."
            ])
        else:  # Advanced
            bullets.extend([
                f"Enterprise application: Integrate {point.lower().strip('.')} into complex system architectures.",
                "Innovation opportunity: Use this method to drive competitive advantages.",
                "Leadership consideration: Align implementation with strategic business objectives."
            ])
    
    return bullets[:4]  # Limit to 4 bullets


def _format_point(point: str) -> str:
    content = point.strip().rstrip('.!?')
    if not content:
        return "Key concept."
    return f"{content}."


def select_slide_image(query: str) -> str:
    keyword = quote_plus(" ".join(query.split()[:3])) if query else "presentation"
    return f"https://source.unsplash.com/960x720/?{keyword}"


def generate_slides(
    source_text: str,
    distribution: Distribution,
    audience_level: str,
    title: str,
    author_name: str | None = None,
    author_email: str | None = None,
) -> list[dict]:
    """
    Generate presentation slides with a single LLM prompt.
    The model returns marker-delimited slide blocks, which are parsed and assembled.
    """
    content_slides = max(distribution.content_slides, 1)

    print(f"DEBUG: Starting ONE-SHOT presentation generation for {content_slides} content slides")

    slides: list[dict] = []
    theory_indices = set(theory_slide_indices(content_slides, distribution.theory_slides))
    image_indices = set(image_slide_indices(content_slides, distribution.image_slides))

    # Create cover slide with audience-appropriate content
    cover_bullets = _generate_audience_appropriate_cover(audience_level, author_name, author_email)
    slides.append({
        "slide_number": 1,
        "title": title,
        "bullets": cover_bullets,
        "type": "cover",
    })

    # Create outline slide
    outline_bullets = _generate_presentation_outline(generated_slides if 'generated_slides' in locals() else [], content_slides, audience_level)
    slides.append({
        "slide_number": 2,
        "title": "Presentation Outline",
        "bullets": outline_bullets,
        "type": "outline",
    })

    try:
        prompt = build_enhanced_prompt(source_text, distribution, audience_level, title)
        generated_slides = generate_slides_json(prompt, content_slides)

        print(f"DEBUG: Successfully generated {len(generated_slides)} slide blocks from the LLM")
        for idx, slide_item in enumerate(generated_slides, start=1):
            print(f"  - Slide {idx}: {slide_item.get('title', 'N/A')} (type={slide_item.get('type', 'N/A')})")

        for content_index, slide_item in enumerate(generated_slides):
            slide_number = content_index + 3  # Start from 3 since we have cover (1) and outline (2)
            slide_type = slide_item.get("type", "theory")
            if slide_type not in {"theory", "practical"}:
                slide_type = "theory"

            bullets = _process_formatted_bullets(slide_item.get("bullets", []))
            
            # Create structured content with subtitles and main content
            structured_content = _create_structured_slide_content(
                slide_item.get("title", f"Slide {slide_number}"),
                bullets,
                slide_type,
                audience_level,
                distribution.practical_slides > distribution.theory_slides  # High practical content flag
            )
            
            slide_data = {
                "slide_number": slide_number,
                "title": structured_content["main_title"],
                "subtitle": structured_content["subtitle"],
                "bullets": structured_content["bullets"],
                "type": slide_type,
                "image_description": slide_item.get("image_description", ""),
            }

            # Check for content duplication with previous slides
            slide_text = " ".join(bullets).lower()
            is_duplicate = False
            for prev_slide in slides[1:]:  # Skip cover slide
                prev_text = " ".join(prev_slide.get("bullets", [])).lower()
                similarity = _calculate_similarity(slide_text, prev_text)
                if similarity > 0.7:  # High similarity threshold for duplicates
                    print(f"  WARNING: Slide {slide_number} has {similarity:.2%} similarity with previous slide - content duplication detected")
                    is_duplicate = True
                    break

            if is_duplicate:
                # Try to create unique content by modifying the slide data
                slide_data["title"] = f"Additional: {slide_data['title']}"
                slide_data["bullets"] = [f"Further details: {bullet}" for bullet in bullets[:3]]

            if content_index in image_indices:
                image_hint = slide_data.get("image_description") or slide_data["title"]
                slide_data["image_url"] = select_slide_image(image_hint)

            speaker_notes_content = "\n".join(bullets)
            if settings.enable_detailed_ai_content:
                try:
                    speaker_notes = generate_speaker_notes(
                        slide_title=slide_data.get("title", ""),
                        slide_content=speaker_notes_content,
                        slide_type=slide_type,
                        audience_level=audience_level,
                        slide_index=slide_number,
                        total_slides=distribution.total_slides,
                    )
                    slide_data["speaker_notes"] = speaker_notes
                except Exception as e:
                    print(f"  WARNING: Speaker notes generation failed: {e}")
                    slide_data["speaker_notes"] = _get_default_speaker_notes(slide_data.get("title", ""), slide_type)
            else:
                slide_data["speaker_notes"] = _get_default_speaker_notes(slide_data.get("title", ""), slide_type)

            if settings.enable_detailed_ai_content and slide_type == "practical":
                try:
                    activities = generate_practical_activities(
                        slide_title=slide_data.get("title", ""),
                        slide_content=speaker_notes_content,
                        audience_level=audience_level,
                        slide_index=slide_number,
                    )
                    slide_data["activities"] = activities
                except Exception as e:
                    print(f"  WARNING: Activities generation failed: {e}")
            elif slide_type == "practical":
                slide_data["activities"] = _get_default_activities()

            slides.append(slide_data)

    except Exception as e:
        print(f"WARNING: Slide generation failed: {e}. Using fallback outline content.")
        fallback_items = _create_fallback_outline(source_text, content_slides, audience_level)
        for content_index, outline_item in enumerate(fallback_items):
            slide_number = content_index + 3  # Start from 3 since we have cover (1) and outline (2)
            slide_type = "theory" if content_index in theory_indices else "practical"
            
            # Create structured content for fallback slides
            structured_content = _create_structured_slide_content(
                outline_item.get("title", outline_item.get("topic", f"Slide {slide_number}")),
                outline_item.get("key_talking_points", [outline_item.get("summary", "Key point")]),
                slide_type,
                audience_level,
                distribution.practical_slides > distribution.theory_slides
            )
            
            slide_data = {
                "slide_number": slide_number,
                "title": structured_content["main_title"],
                "subtitle": structured_content["subtitle"],
                "bullets": structured_content["bullets"],
                "type": slide_type,
                "image_description": outline_item.get("image_description", ""),
            }
            if content_index in image_indices:
                image_hint = slide_data.get("image_description") or slide_data["title"]
                slide_data["image_url"] = select_slide_image(image_hint)
            slides.append(slide_data)

    print(f"DEBUG: ✓ Successfully generated {len(slides)} total slides (1 cover + {len(slides)-1} content)")
    return slides


# ==================== HELPER FUNCTIONS FOR TWO-STAGE PIPELINE ====================

def _process_formatted_bullets(formatted_bullets: list[str]) -> list[str]:
    """
    Process formatted bullets, converting emphasis markers to plain text for PPTX.
    The emphasis will be applied by the PPTX generator based on markers.
    """
    result = []
    for bullet in formatted_bullets:
        # Keep the emphasis markers for PPTX to process
        if bullet:
            result.append(bullet.strip())
    return result[:5]  # Max 5 bullets


def _create_structured_slide_content(title: str, bullets: list[str], slide_type: str, audience_level: str, high_practical_content: bool) -> dict:
    """Create structured slide content with main title, subtitle, and organized content."""
    
    # Create main title (keep original title as main title)
    main_title = title.strip()
    
    # Create subtitle based on slide type and audience
    if slide_type == "theory":
        if audience_level == "Beginner":
            subtitle = "Understanding the Fundamentals"
        elif audience_level == "Advanced":
            subtitle = "Advanced Theoretical Framework"
        else:
            subtitle = "Key Theoretical Concepts"
    else:  # practical
        if audience_level == "Beginner":
            subtitle = "Practical Application Guide"
        elif audience_level == "Advanced":
            subtitle = "Advanced Implementation Strategies"
        else:
            subtitle = "Practical Implementation"
    
    # Organize bullets into main content and practical sections
    main_content = []
    practical_content = []
    
    # Split bullets into main content and practical activities
    for bullet in bullets:
        if any(keyword in bullet.lower() for keyword in ["practice", "exercise", "activity", "implement", "apply", "hands-on"]):
            practical_content.append(bullet)
        else:
            main_content.append(bullet)
    
    # Ensure we have main content
    if not main_content:
        main_content = bullets[:2] if bullets else ["Key information point."]
        practical_content = bullets[2:] if len(bullets) > 2 else []
    
    # Combine content with practical section if high practical content ratio
    final_bullets = main_content.copy()
    
    if high_practical_content and practical_content:
        final_bullets.append("")  # Empty line for separation
        final_bullets.append("**Practical Activities:**")
        final_bullets.extend(practical_content)
    
    return {
        "main_title": main_title,
        "subtitle": subtitle,
        "bullets": final_bullets
    }


def _generate_presentation_outline(slide_data: list[dict], content_slides: int, audience_level: str) -> list[str]:
    """Generate an outline slide showing the presentation structure."""
    outline_items = []
    
    # Add total slide count
    outline_items.append(f"Total Slides: {content_slides + 2}")  # +2 for cover and outline
    
    # Add main sections
    outline_items.append("1. Introduction and Overview")
    outline_items.append("2. Detailed Content Sections")
    
    # Add slide titles if available
    if slide_data:
        outline_items.append("Content Topics:")
        for i, slide in enumerate(slide_data[:min(5, len(slide_data))]):  # Show first 5 topics
            title = slide.get("title", f"Topic {i+1}")
            outline_items.append(f"   • {title}")
        
        if len(slide_data) > 5:
            outline_items.append(f"   • ... and {len(slide_data) - 5} more topics")
    
    # Add conclusion
    outline_items.append(f"{content_slides + 1}. Summary and Conclusions")
    
    return outline_items


def _generate_audience_appropriate_cover(audience_level: str, author_name: str | None, author_email: str | None) -> list[str]:
    """Generate cover slide bullets appropriate for the audience level."""
    if audience_level == "Beginner":
        cover_bullets = [
            "Clear explanations of foundational concepts and ideas.",
            "Practical examples you can understand and remember.",
            "Step-by-step guidance for learning and improvement.",
        ]
    elif audience_level == "Advanced":
        cover_bullets = [
            "Strategic insights and innovation opportunities.",
            "Advanced frameworks for complex problem-solving.",
            "Leadership and competitive advantage strategies.",
        ]
    else:  # Intermediate
        cover_bullets = [
            "Comprehensive analysis of key concepts and principles.",
            "Practical recommendations for effective implementation.",
            "Professional framework for decision-making.",
        ]
    
    if author_name:
        cover_bullets.append(f"Prepared by {author_name}")
    if author_email:
        cover_bullets.append(f"Contact: {author_email}")
    
    return cover_bullets


def _get_default_speaker_notes(title: str, slide_type: str) -> dict:
    """Generate default speaker notes when generation fails."""
    return {
        "opening_remarks": f"Our next topic is: {title}",
        "main_talking_points": [
            "Explain the key concepts",
            "Connect to real-world application",
            "Invite audience participation",
        ],
        "audience_engagement": "Feel free to ask questions about this topic",
        "time_estimate": 90,
        "key_takeaway": f"Remember: {title} is important",
        "transition_to_next": "Let's continue with the next point.",
    }


def _analyze_content_structure(source_text: str, slide_count: int) -> list[str]:
    """Analyze source text and divide it into logical sections for slides."""
    # Split by paragraphs first
    paragraphs = [p.strip() for p in source_text.split('\n\n') if p.strip()]

    if len(paragraphs) >= slide_count:
        # If we have enough paragraphs, distribute them
        sections = []
        paras_per_slide = len(paragraphs) // slide_count
        remainder = len(paragraphs) % slide_count

        start_idx = 0
        for i in range(slide_count):
            paras_for_slide = paras_per_slide + (1 if i < remainder else 0)
            end_idx = start_idx + paras_for_slide
            section_content = ' '.join(paragraphs[start_idx:end_idx])
            sections.append(section_content[:200])  # Limit section size
            start_idx = end_idx
        return sections

    # If not enough paragraphs, split by sentences
    sentences = [s.strip() for s in source_text.split('.') if s.strip() and len(s.strip()) > 5]

    if len(sentences) >= slide_count:
        sections = []
        sents_per_slide = len(sentences) // slide_count
        remainder = len(sentences) % slide_count

        start_idx = 0
        for i in range(slide_count):
            sents_for_slide = sents_per_slide + (1 if i < remainder else 0)
            end_idx = start_idx + sents_for_slide
            section_content = '. '.join(sentences[start_idx:end_idx])
            sections.append(section_content[:200])
            start_idx = end_idx
        return sections

    # If still not enough, create sections by word chunks
    words = source_text.split()
    if len(words) < slide_count * 10:
        # Not enough content, return what we can
        return [source_text] * slide_count

    words_per_slide = len(words) // slide_count
    sections = []
    for i in range(slide_count):
        start_idx = i * words_per_slide
        end_idx = start_idx + words_per_slide
        if i == slide_count - 1:  # Last slide gets remainder
            end_idx = len(words)
        section_content = ' '.join(words[start_idx:end_idx])
        sections.append(section_content[:200])

    return sections


def _create_fallback_outline(source_text: str, slide_count: int, audience_level: str) -> list[dict]:
    """Create a fallback outline when outline generation fails."""
    # Analyze content structure to create better divisions
    content_sections = _analyze_content_structure(source_text, slide_count)

    # Create diverse topics based on different aspects of the content
    topic_templates = [
        "Introduction to {}",
        "Key Concepts in {}",
        "Understanding {}",
        "Applications of {}",
        "Best Practices for {}",
        "Challenges in {}",
        "Future of {}",
        "Implementation Guide for {}",
        "Case Studies in {}",
    ]

    outline_items = []
    for i in range(slide_count):
        # Use content sections to create unique topics
        section_content = content_sections[i] if i < len(content_sections) else f"Additional content section {i+1}"

        # Extract key phrases from the section
        words = section_content.split()
        if len(words) > 3:
            # Use first meaningful phrase as base topic
            base_topic = ' '.join(words[:min(6, len(words))])
        else:
            base_topic = section_content[:50]

        # Ensure uniqueness by adding slide-specific modifiers
        modifiers = ["Overview", "Deep Dive", "Practical Guide", "Strategic View",
                    "Implementation", "Analysis", "Framework", "Methodology", "Approach"]
        modifier = modifiers[i % len(modifiers)]

        # Clean up the base topic to make it more readable
        base_topic = base_topic.replace('  ', ' ').strip()  # Remove double spaces
        if not base_topic.endswith('.') and len(base_topic) > 20:
            # Try to end at a natural break point
            last_space = base_topic.rfind(' ', 20, 50)
            if last_space > 0:
                base_topic = base_topic[:last_space]

        unique_topic = f"{modifier}: {base_topic[:50]}"

        # Create diverse talking points based on the topic and section content
        talking_points = []
        section_words = section_content.lower().split()

        if "overview" in modifier.lower():
            talking_points = [
                f"Core aspects of {base_topic.lower()[:30]}",
                f"Key considerations for understanding",
                f"Fundamental principles and concepts"
            ]
        elif "deep dive" in modifier.lower():
            talking_points = [
                f"Detailed analysis of {base_topic.lower()[:30]}",
                f"Advanced concepts and implications",
                f"Technical details and specifications"
            ]
        elif "practical" in modifier.lower():
            talking_points = [
                f"Real-world application of {base_topic.lower()[:30]}",
                f"Implementation steps and procedures",
                f"Best practices and recommendations"
            ]
        else:
            # Extract key points from section content
            key_terms = []
            for word in section_words:
                if len(word) > 4 and word not in ['that', 'this', 'with', 'from', 'they', 'their', 'there', 'these', 'those']:
                    key_terms.append(word.title())
                    if len(key_terms) >= 3:
                        break
            talking_points = [
                f"Key aspects of {base_topic.lower()[:30]}",
                f"Important considerations and factors",
                f"Strategic implications and outcomes"
            ]

        outline_items.append({
            "slide_number": i + 1,
            "title": unique_topic,
            "key_talking_points": talking_points,
            "needs_image": (i % 3 == 0),  # Every 3rd slide gets an image
            "image_description": f"Visual representation of {base_topic.lower()[:50]} concepts",
            # Backward compatibility
            "topic": unique_topic,
            "summary": f"Detailed exploration of {base_topic.lower()} with focus on {modifier.lower()} aspects.",
            "key_concepts": [base_topic.split()[0]] if base_topic.split() else ["concept"],
            "content_focus": modifier,
            "outline_index": i + 1,
        })

    return outline_items

