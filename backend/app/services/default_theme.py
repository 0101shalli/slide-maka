"""The system's default presentation theme.

Used to seed the first Template row (so a default template always exists) and as
the built-in theme when no template is selected.
"""

DEFAULT_TEMPLATE = {
    "name": "PMTCT Default Theme",
    "description": "Green corporate theme used by default for all generated presentations.",
    "styles": {
        "primary": "#0B523E",
        "secondary": "#147A45",
        "accent": "#D4A01E",
        "background": "#F0F7F2",
        "text": "#2C2C2C",
    },
    "footer_text": "REPUBLIC OF CAMEROON | Peace – Work – Fatherland",
    "slide_order": [
        {
            "id": "cover",
            "type": "cover",
            "title": "EARLY TESTING, EARLY TREATMENT:",
            "subtitle": "HEALTHY MOTHERS, HIV-FREE BABIES",
            "backgroundColor": "#0B523E",
            "textColor": "#FFFFFF",
            "layout": "center",
            "design": "modern",
        },
        {
            "id": "outline",
            "type": "outline",
            "title": "Outline of Presentation",
            "subtitle": "Key sections and flow",
            "backgroundColor": "#FFFFFF",
            "textColor": "#0B523E",
            "layout": "default",
            "design": "minimal",
        },
        {
            "id": "theory",
            "type": "content",
            "title": "Key Theoretical Concepts",
            "subtitle": "Foundations of the topic",
            "backgroundColor": "#FFFFFF",
            "textColor": "#0B523E",
            "layout": "bullets",
            "design": "modern",
        },
        {
            "id": "practical",
            "type": "content",
            "title": "Practical Application",
            "subtitle": "How it works in practice",
            "backgroundColor": "#F0F7F2",
            "textColor": "#0B523E",
            "layout": "bullets",
            "design": "corporate",
        },
        {
            "id": "image",
            "type": "image",
            "title": "Visual Overview",
            "subtitle": "Concept diagram of the topic",
            "backgroundColor": "#FFFFFF",
            "textColor": "#0B523E",
            "layout": "fullscreen",
            "design": "minimal",
        },
        {
            "id": "end",
            "type": "end",
            "title": "Thank You",
            "subtitle": "Questions & discussion",
            "backgroundColor": "#0B523E",
            "textColor": "#FFFFFF",
            "layout": "center",
            "design": "modern",
        },
    ],
}