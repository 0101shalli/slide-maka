from pydantic import BaseModel, Field


class PresentationConfig(BaseModel):
    slide_count: int = Field(ge=5, le=50)
    image_percent: int = Field(ge=0, le=100)
    theory_percent: int = Field(ge=0, le=100)
    audience_level: str
    palette_id: int


class PresentationCreate(BaseModel):
    user_id: int
    original_text: str = Field(min_length=50)
    configuration: PresentationConfig


class DistributionPreview(BaseModel):
    total_slides: int
    theory_slides: int
    practical_slides: int
    image_slides: int
    warning: str | None = None


class TaskStatusResponse(BaseModel):
    task_id: int
    presentation_id: int
    status: str
    message: str | None = None
