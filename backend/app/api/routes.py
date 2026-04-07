from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import Base, engine, get_db
from app.models.models import Presentation, TaskStatus
from app.schemas.presentation import (
    DistributionPreview,
    PresentationCreate,
    TaskStatusResponse,
)
from app.services.gemini_structurer import generate_slides_json
from app.services.llm_structurer import build_prompt
from app.services.parameter_calculator import compute_distribution
from app.services.pptx_generator import build_pptx

router = APIRouter()


@router.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


@router.post("/presentations/preview", response_model=DistributionPreview)
def preview_distribution(payload: PresentationCreate) -> DistributionPreview:
    dist = compute_distribution(
        slide_count=payload.configuration.slide_count,
        theory_percent=payload.configuration.theory_percent,
        image_percent=payload.configuration.image_percent,
        text=payload.original_text,
    )
    return DistributionPreview(
        total_slides=dist.total_slides,
        theory_slides=dist.theory_slides,
        practical_slides=dist.practical_slides,
        image_slides=dist.image_slides,
        warning=dist.warning,
    )


@router.post("/presentations/generate", response_model=TaskStatusResponse)
def generate_presentation(payload: PresentationCreate, db: Session = Depends(get_db)) -> TaskStatusResponse:
    dist = compute_distribution(
        payload.configuration.slide_count,
        payload.configuration.theory_percent,
        payload.configuration.image_percent,
        payload.original_text,
    )

    record = Presentation(
        user_id=payload.user_id,
        original_text=payload.original_text,
        configuration_json=payload.configuration.model_dump(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    task = TaskStatus(presentation_id=record.id, status="Processing", message="Structuring content with Gemini...")
    db.add(task)
    db.commit()
    db.refresh(task)

    try:
        prompt = build_prompt(payload.original_text, dist, payload.configuration.audience_level)
        slides = generate_slides_json(prompt=prompt, requested_count=dist.total_slides)

        output = Path(settings.storage_dir) / f"presentation_{record.id}.pptx"
        build_pptx(slides, dist.image_slides, output)

        record.file_path = str(output)
        task.status = "Completed"
        task.message = "Presentation generated successfully"
        db.commit()
    except Exception as exc:  # noqa: BLE001
        task.status = "Failed"
        task.message = f"Generation failed: {exc}"
        db.commit()
        raise HTTPException(status_code=500, detail=task.message) from exc

    return TaskStatusResponse(
        task_id=task.id,
        presentation_id=record.id,
        status=task.status,
        message=task.message,
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: int, db: Session = Depends(get_db)) -> TaskStatusResponse:
    task = db.get(TaskStatus, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatusResponse(
        task_id=task.id,
        presentation_id=task.presentation_id,
        status=task.status,
        message=task.message,
    )
