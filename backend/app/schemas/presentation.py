from pydantic import BaseModel, Field
from fastapi import UploadFile


class PresentationConfig(BaseModel):
    slide_count: int = Field(ge=5, le=50)
    image_percent: int = Field(ge=0, le=100)
    theory_percent: int = Field(ge=0, le=100)
    audience_level: str
    palette_id: int


class SlidePreview(BaseModel):
    slide_number: int
    title: str
    bullets: list[str]
    type: str
    engagement_hook: str | None = None
    speaker_notes: dict | None = None
    activities: dict | None = None


class PresentationPreviewResponse(BaseModel):
    total_slides: int
    theory_slides: int
    practical_slides: int
    image_slides: int
    warning: str | None = None
    slides: list[SlidePreview]


class PresentationCreate(BaseModel):
    user_id: int
    # content can come from either direct text, uploaded file, or a prompt
    content_type: str = Field(description="one of: text, file, prompt")
    content_text: str | None = Field(None, description="Direct text input (for content_type='text')")
    prompt_text: str | None = Field(None, description="Prompt to send to LLM (for content_type='prompt')")
    title: str = Field(min_length=1, max_length=100)
    logo_url: str | None = None
    # file uploads are handled at the route level as UploadFile
    template_id: int | None = None
    configuration: PresentationConfig


class TaskStatusResponse(BaseModel):
    task_id: int
    presentation_id: int
    status: str
    message: str | None = None


class PresentationGenerateResponse(TaskStatusResponse):
    pptx_url: str | None = None
    pdf_url: str | None = None
