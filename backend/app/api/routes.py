from pathlib import Path
import logging

from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from ..core.config import settings
from ..db.session import Base, engine, get_db
from ..models.models import Presentation, TaskStatus, User
from ..schemas.presentation import (
    PresentationCreate,
    PresentationGenerateResponse,
    PresentationPreviewResponse,
    TaskStatusResponse,
)
from ..services.deck_builder import build_deck
from ..services.default_theme import DEFAULT_TEMPLATE
from ..services.llm_structurer import build_prompt_input_prompt
from ..services.parameter_calculator import compute_distribution
from ..services.pdf_converter import convert_to_pdf
from ..services.pptx_generator import build_pptx
from ..services import document_extractor
from ..services import gemini_structurer
from ..services.llm import (
    PROVIDER_TYPES,
    ProviderConfig,
    build_provider,
)
from ..services.llm import invalidate_cache as invalidate_llm_cache
from ..models.models import LLMProvider, Template

router = APIRouter()
logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    import hashlib

    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def check_password(password: str, password_hash: str) -> bool:
    return bool(password_hash) and hash_password(password) == password_hash


def is_admin(user: User | None) -> bool:
    if user is None:
        return False
    if user.id == 1:
        return True
    if getattr(user, "is_admin", False):
        return True
    return getattr(user, "role", "") == "admin"


def resolve_content(
    content_type: str,
    content_text: str | None,
    prompt_text: str | None,
    content_file: UploadFile | None,
    slide_count: int,
    theory_percent: int = 50,
    image_percent: int = 30,
    audience_level: str = "Intermediate",
    title: str = "",
) -> tuple[str, list[dict] | None, list]:
    """Return (original_text, llm_slides, figures).

    Only the ``prompt`` source uses the LLM. A ``file`` upload is read in detail:
    its body text becomes the material, its table of contents and other
    preliminary pages are read but excluded, and its diagrams / charts / photos
    are returned as ``figures`` to fill the deck's image slides.
    """
    if content_type == "text":
        return content_text or "", None, []
    if content_type == "file":
        if not content_file:
            raise HTTPException(status_code=400, detail="content_file is required for content_type=file")
        document = document_extractor.extract_document_from_upload(
            content_file,
            assets_dir=Path(settings.storage_dir) / "assets",
        )
        if not document.text.strip() and document.front_matter_text.strip():
            # Everything looked preliminary; use it rather than return nothing.
            document.text = document.front_matter_text
        return document.text, None, document.load_figures()
    if content_type == "prompt":
        if not prompt_text:
            raise HTTPException(status_code=400, detail="prompt_text is required for content_type=prompt")
        dist = compute_distribution(slide_count, theory_percent, image_percent, prompt_text)
        # Ask for exactly the content slides the calculator reserved. Reserving
        # two here instead of four paid for two extra slides of model output
        # that the deck builder then discarded.
        content_slides = max(dist.content_slides, 1)
        prompt = build_prompt_input_prompt(prompt_text, dist, audience_level, title)
        try:
            # Memoized on the prompt, so the /generate call that follows a
            # /preview reuses this material instead of paying for it twice.
            generated = gemini_structurer.generate_slides_json(prompt, content_slides)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Slide material could not be generated: {exc}") from exc
        original_text = "\n".join(
            f"{slide.get('title', '')}\n" + "\n".join(slide.get("bullets", []))
            for slide in generated
        )
        return original_text, generated, []
    raise HTTPException(status_code=400, detail="invalid content_type")


def _count_warning(dist, slides) -> str | None:
    """Say so when the deck came out shorter than the number that was asked for.

    The generator will not pad a deck by repeating the source or inventing
    summary lines, so a document with less material than the requested slide
    count produces fewer slides. Returning the short deck silently looked like
    the parameter being ignored, so the shortfall is reported explicitly.
    """
    built = len(slides or [])
    if built >= dist.total_slides:
        return dist.warning
    content_built = sum(1 for s in slides or [] if s.get("type") in ("theory", "practical"))
    content_wanted = dist.content_slides
    return (
        f"Only {built} of the {dist.total_slides} requested slides were built: the "
        f"document provides material for {content_built} content slide"
        f"{'' if content_built == 1 else 's'} (out of {content_wanted}). "
        "Slides are never padded by repeating or inventing text -- add source "
        "material, or lower the slide count, to reach the full number."
    )


def fetch_user_identity(db: Session, user_id: int) -> tuple[User | None, str, str]:
    user = db.get(User, user_id)
    if user is not None:
        return user, user.username, user.email
    return None, f"guest{user_id}", f"guest{user_id}@example.com"


@router.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    if "users" in inspector.get_table_names():
        columns = [column["name"] for column in inspector.get_columns("users")]
        with engine.begin() as conn:
            if "is_admin" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_admin boolean NOT NULL DEFAULT false"))
            if "role" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'"))
            if "is_active" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_active boolean NOT NULL DEFAULT true"))

    ensure_default_template()


def ensure_default_template() -> None:
    """Seed the system's default template so one always exists."""
    with Session(bind=engine) as db:
        if db.query(Template).count() == 0:
            db.add(
                Template(
                    name=DEFAULT_TEMPLATE["name"],
                    description=DEFAULT_TEMPLATE["description"],
                    creator_id=1,
                    template_json=DEFAULT_TEMPLATE,
                )
            )
            db.commit()


@router.post("/presentations/preview", response_model=PresentationPreviewResponse)
def preview_presentation(
    user_id: int = Form(...),
    content_type: str = Form(...),
    content_text: str | None = Form(None),
    prompt_text: str | None = Form(None),
    content_file: UploadFile | None = File(None),
    title: str = Form(...),
    logo_url: str | None = Form(None),
    logo_file: UploadFile | None = File(None),
    slide_count: int = Form(...),
    image_percent: int = Form(...),
    theory_percent: int = Form(...),
    audience_level: str = Form(...),
    palette_id: int = Form(...),
    template_id: int | None = Form(None),
    db: Session = Depends(get_db),
) -> PresentationPreviewResponse:
    original_text, llm_slides, figures = resolve_content(
        content_type,
        content_text,
        prompt_text,
        content_file,
        slide_count,
        theory_percent,
        image_percent,
        audience_level,
        title,
    )

    dist = compute_distribution(
        slide_count,
        theory_percent,
        image_percent,
        original_text,
    )
    _, username, email = fetch_user_identity(db, user_id)
    slides = build_deck(
        content_type,
        original_text,
        llm_slides,
        dist,
        audience_level,
        title,
        username,
        email,
        figures,
    )

    return PresentationPreviewResponse(
        total_slides=dist.total_slides,
        theory_slides=dist.theory_slides,
        practical_slides=dist.practical_slides,
        image_slides=dist.image_slides,
        warning=_count_warning(dist, slides),
        slides=slides,
    )


@router.post("/presentations/generate", response_model=PresentationGenerateResponse)
def generate_presentation(
    user_id: int = Form(...),
    content_type: str = Form(...),
    content_text: str | None = Form(None),
    prompt_text: str | None = Form(None),
    content_file: UploadFile | None = File(None),
    title: str = Form(...),
    logo_url: str | None = Form(None),
    logo_file: UploadFile | None = File(None),
    slide_count: int = Form(...),
    image_percent: int = Form(...),
    theory_percent: int = Form(...),
    audience_level: str = Form(...),
    palette_id: int = Form(...),
    template_id: int | None = Form(None),
    db: Session = Depends(get_db),
) -> PresentationGenerateResponse:
    original_text, llm_slides, figures = resolve_content(
        content_type,
        content_text,
        prompt_text,
        content_file,
        slide_count,
        theory_percent,
        image_percent,
        audience_level,
        title,
    )

    config = {
        "slide_count": slide_count,
        "image_percent": image_percent,
        "theory_percent": theory_percent,
        "audience_level": audience_level,
        "palette_id": palette_id,
        "template_id": template_id,
    }
    dist = compute_distribution(
        slide_count,
        theory_percent,
        image_percent,
        original_text,
    )

    user = db.get(User, user_id)
    if user is None:
        user = User(
            id=user_id,
            username=f"guest{user_id}",
            email=f"guest{user_id}@example.com",
            password_hash="",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    record = Presentation(
        user_id=user.id,
        original_text=original_text,
        configuration_json={
            "title": title,
            **config,
        },
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    task = TaskStatus(presentation_id=record.id, status="Processing", message="Structuring content...")
    db.add(task)
    db.commit()
    db.refresh(task)

    slides = build_deck(
        content_type,
        original_text,
        llm_slides,
        dist,
        audience_level,
        title,
        user.username,
        user.email,
        figures,
    )
    output = Path(settings.storage_dir) / f"presentation_{record.id}.pptx"

    # Handle logo
    logo_path = None
    if logo_file:
        logo_path = Path(settings.storage_dir) / f"logo_{record.id}.png"
        with open(logo_path, "wb") as f:
            f.write(logo_file.file.read())
    elif logo_url:
        logo_path = logo_url

    template_def = None
    base_template_path = None
    python_template_path = None
    if template_id:
        template = db.get(Template, template_id)
        if template:
            template_def = template.template_json
            if template.file_path:
                template_path = Path(template.file_path)
                if template_path.exists():
                    ext = template_path.suffix.lower()
                    if ext == ".pptx":
                        base_template_path = template_path
                    elif ext == ".py":
                        python_template_path = template_path

    if python_template_path:
        from ..services.pptx_generator import execute_python_template

        output = execute_python_template(
            python_template_path,
            slides,
            dist.image_slides,
            output,
            logo_path,
            palette_id,
            template_def=template_def,
        )
    else:
        build_pptx(
            slides,
            dist.image_slides,
            output,
            logo_path,
            palette_id,
            template_def=template_def,
            base_template_path=base_template_path,
        )

    record.file_path = str(output)
    task.status = "Completed"
    task.message = "Presentation generated successfully"
    db.commit()

    return PresentationGenerateResponse(
        task_id=task.id,
        presentation_id=record.id,
        status=task.status,
        message=task.message,
        pptx_url=f"/api/presentations/{record.id}/download/pptx",
        pdf_url=f"/api/presentations/{record.id}/download/pdf",
    )


@router.post("/templates")
def create_template(
    user_id: int = Form(...),
    name: str = Form(...),
    description: str | None = Form(None),
    template_file: UploadFile | None = File(None),
    template_json: str | None = Form(None),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None and user_id == 1:
        user = User(
            id=user_id,
            username=f"admin{user_id}",
            email=f"admin{user_id}@example.com",
            password_hash="",
            is_admin=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    if not user or not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin privileges required")

    parsed = None
    file_path = None
    if template_json:
        import json

        parsed = json.loads(template_json)
    elif template_file:
        data = template_file.file.read()
        file_name = Path(template_file.filename).name
        extension = Path(file_name).suffix.lower()

        if extension == ".json":
            try:
                import json

                parsed = json.loads(data.decode("utf-8"))
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid JSON template: {exc}")
        else:
            # save raw file for PPTX/Python import
            out_dir = Path(settings.storage_dir) / "templates"
            out_dir.mkdir(parents=True, exist_ok=True)
            file_path = out_dir / file_name
            with open(file_path, "wb") as f:
                f.write(data)
            if extension == ".pptx":
                import copy

                from ..services.default_theme import DEFAULT_TEMPLATE as _default

                parsed = copy.deepcopy(_default)
                parsed["background_source"] = "pptx"
                parsed["name"] = name
                parsed["description"] = f"Uploaded PPTX template ({file_name}). Slides 1-6 map to cover, outline, theory, practical, image and end slides."
            elif extension == ".py":
                parsed = None
    else:
        raise HTTPException(status_code=400, detail="Provide template_json or template_file")

    if isinstance(parsed, dict) and isinstance(parsed.get("slide_order"), list):
        order = parsed["slide_order"]
        if len(order) > 6:
            raise HTTPException(
                status_code=400,
                detail="A template may contain at most 6 slides (cover, outline, theory, practical, image, end).",
            )
        for block in order:
            if isinstance(block, dict) and block.get("type") == "content" and not block.get("flavor"):
                block["flavor"] = "theory"

    record = Template(
        name=name,
        description=description,
        creator_id=user.id,
        template_json=parsed,
        file_path=str(file_path) if file_path else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {"id": record.id, "name": record.name}


@router.get("/templates")
def list_templates(db: Session = Depends(get_db)) -> list[dict]:
    templates = db.query(Template).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "has_json": bool(t.template_json),
            "file_path": t.file_path,
            "template_json": t.template_json,
            "created_by": (db.get(User, t.creator_id).username if t.creator_id else None),
            "creator_id": t.creator_id,
        }
        for t in templates
    ]


@router.get("/templates/{template_id}")
def get_template(template_id: int, db: Session = Depends(get_db)) -> dict:
    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "file_path": template.file_path,
        "template_json": template.template_json,
    }


@router.put("/templates/{template_id}")
def update_template(
    template_id: int,
    user_id: int = Form(...),
    name: str | None = Form(None),
    description: str | None = Form(None),
    template_json: str | None = Form(None),
    template_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    import json as _json

    if name is not None:
        template.name = name
    if description is not None:
        template.description = description
    if template_json:
        try:
            template.template_json = _json.loads(template_json)
            parsed = template.template_json
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON template: {exc}")
        if isinstance(parsed, dict) and isinstance(parsed.get("slide_order"), list):
            order = parsed["slide_order"]
            if len(order) > 6:
                raise HTTPException(
                    status_code=400,
                    detail="A template may contain at most 6 slides (cover, outline, theory, practical, image, end).",
                )
            for block in order:
                if isinstance(block, dict) and block.get("type") == "content" and not block.get("flavor"):
                    block["flavor"] = "theory"
    if template_file and template_file.filename:
        data = template_file.file.read()
        file_name = Path(template_file.filename).name
        extension = Path(file_name).suffix.lower()
        out_dir = Path(settings.storage_dir) / "templates"
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"template_{template_id}{extension}"
        with open(file_path, "wb") as f:
            f.write(data)
        template.file_path = str(file_path)
        if extension == ".pptx" and isinstance(template.template_json, dict):
            template.template_json = {**template.template_json, "background_source": "pptx"}

    db.commit()
    db.refresh(template)
    return {"id": template.id, "name": template.name}


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, user_id: int, db: Session = Depends(get_db)) -> dict:
    user = db.get(User, user_id)
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if template.file_path:
        path = Path(template.file_path)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    db.delete(template)
    db.commit()
    return {"message": "Template deleted successfully"}


# ---------------------------------------------------------------------------
# LLM providers (dispatcher configuration)
# ---------------------------------------------------------------------------

def _require_admin(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


def _provider_payload(provider: LLMProvider) -> dict:
    return {
        "id": provider.id,
        "name": provider.name,
        "provider_type": provider.provider_type,
        "base_url": provider.base_url,
        "model": provider.model,
        "enabled": bool(provider.enabled),
        "priority": provider.priority,
        "is_default": bool(provider.is_default),
        "extra_json": provider.extra_json or {},
        "has_api_key": bool(provider.api_key),
        "created_at": provider.created_at.isoformat() if provider.created_at else None,
    }


def _provider_config(provider: LLMProvider) -> ProviderConfig:
    return ProviderConfig(
        name=provider.name,
        provider_type=provider.provider_type,
        model=provider.model,
        api_key=provider.api_key or "",
        base_url=provider.base_url or "",
        priority=int(provider.priority or 100),
        is_default=bool(provider.is_default),
        extra=dict(provider.extra_json or {}),
    )


def _coerce_extra(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        import json

        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


@router.get("/llm-providers")
def list_llm_providers(user_id: int, db: Session = Depends(get_db)) -> list[dict]:
    _require_admin(db, user_id)
    providers = db.query(LLMProvider).order_by(LLMProvider.priority, LLMProvider.id).all()
    return [_provider_payload(provider) for provider in providers]


@router.post("/llm-providers")
def create_llm_provider(user_id: int, payload: dict, db: Session = Depends(get_db)) -> dict:
    _require_admin(db, user_id)
    name = (payload.get("name") or "").strip()
    model = (payload.get("model") or "").strip()
    provider_type = (payload.get("provider_type") or "openai").strip().lower()
    if not name or not model:
        raise HTTPException(status_code=400, detail="name and model are required")
    if provider_type not in PROVIDER_TYPES:
        raise HTTPException(status_code=400, detail="provider_type must be gemini, openai or anthropic")
    if db.query(LLMProvider).filter(LLMProvider.name == name).first():
        raise HTTPException(status_code=400, detail="A provider with that name already exists")

    provider = LLMProvider(
        name=name,
        provider_type=provider_type,
        base_url=(payload.get("base_url") or "").strip() or None,
        api_key=(payload.get("api_key") or "").strip() or None,
        model=model,
        enabled=bool(payload.get("enabled", True)),
        priority=int(payload.get("priority") or 100),
        is_default=bool(payload.get("is_default", False)),
        extra_json=_coerce_extra(payload.get("extra_json")),
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    invalidate_llm_cache()
    return _provider_payload(provider)


@router.put("/llm-providers/{provider_id}")
def update_llm_provider(
    provider_id: int,
    user_id: int,
    payload: dict,
    db: Session = Depends(get_db),
) -> dict:
    _require_admin(db, user_id)
    provider = db.get(LLMProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if payload.get("name"):
        provider.name = payload["name"].strip()
    if payload.get("provider_type"):
        provider_type = payload["provider_type"].strip().lower()
        if provider_type not in PROVIDER_TYPES:
            raise HTTPException(status_code=400, detail="provider_type must be gemini, openai or anthropic")
        provider.provider_type = provider_type
    if payload.get("model"):
        provider.model = payload["model"].strip()
    if "base_url" in payload:
        provider.base_url = (payload.get("base_url") or "").strip() or None
    if "api_key" in payload and payload.get("api_key"):
        provider.api_key = payload["api_key"].strip()
    if "enabled" in payload:
        provider.enabled = bool(payload["enabled"])
    if "priority" in payload and payload.get("priority") is not None:
        provider.priority = int(payload["priority"])
    if "is_default" in payload:
        provider.is_default = bool(payload["is_default"])
    if "extra_json" in payload:
        provider.extra_json = _coerce_extra(payload.get("extra_json"))

    db.commit()
    db.refresh(provider)
    invalidate_llm_cache()
    return _provider_payload(provider)


@router.delete("/llm-providers/{provider_id}")
def delete_llm_provider(provider_id: int, user_id: int, db: Session = Depends(get_db)) -> dict:
    _require_admin(db, user_id)
    provider = db.get(LLMProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    db.delete(provider)
    db.commit()
    invalidate_llm_cache()
    return {"message": "Provider deleted successfully"}


@router.post("/llm-providers/{provider_id}/test")
def test_llm_provider(provider_id: int, user_id: int, db: Session = Depends(get_db)) -> dict:
    _require_admin(db, user_id)
    provider = db.get(LLMProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    try:
        adapter = build_provider(_provider_config(provider))
        reply = adapter.complete(
            "Reply with the single word OK.",
            temperature=0.0,
            timeout=30,
            model=provider.model,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the admin UI
        raise HTTPException(status_code=502, detail=f"{provider.name} test failed: {exc}") from exc
    return {"ok": True, "provider": provider.name, "reply": (reply or "").strip()[:200]}


# ---------------------------------------------------------------------------
# Profile & user management
# ---------------------------------------------------------------------------


@router.get("/users")
def list_users(user_id: int, db: Session = Depends(get_db)) -> list[dict]:
    requester = db.get(User, user_id)
    if not is_admin(requester):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    users = db.query(User).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "role": getattr(u, "role", "user") or "user",
            "is_admin": bool(getattr(u, "is_admin", False)),
            "is_active": bool(getattr(u, "is_active", True)),
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.post("/users")
def create_user(user_id: int, payload: dict, db: Session = Depends(get_db)) -> dict:
    requester = db.get(User, user_id)
    if not is_admin(requester):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    username = (payload.get("username") or "").strip()
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    role = (payload.get("role") or "user").strip()
    if not username or not email or not password:
        raise HTTPException(status_code=400, detail="username, email and password are required")
    if role not in {"admin", "admin1", "user"}:
        raise HTTPException(status_code=400, detail="role must be admin, admin1 or user")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already exists")

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=role,
        is_active=bool(payload.get("is_active", True)),
        is_admin=(role == "admin") or bool(payload.get("is_admin", False)),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "username": user.username, "role": user.role}


@router.put("/users/{target_id}")
def update_user(target_id: int, user_id: int, payload: dict, db: Session = Depends(get_db)) -> dict:
    requester = db.get(User, user_id)
    if not is_admin(requester):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    username = (payload.get("username") or "").strip()
    email = (payload.get("email") or "").strip()
    role = (payload.get("role") or "").strip()
    if username:
        clash = db.query(User).filter(User.username == username, User.id != target_id).first()
        if clash:
            raise HTTPException(status_code=400, detail="Username already exists")
        user.username = username
    if email:
        clash = db.query(User).filter(User.email == email, User.id != target_id).first()
        if clash:
            raise HTTPException(status_code=400, detail="Email already exists")
        user.email = email
    if role:
        if role not in {"admin", "admin1", "user"}:
            raise HTTPException(status_code=400, detail="role must be admin, admin1 or user")
        user.role = role
        user.is_admin = role == "admin" or target_id == 1
    if "is_active" in payload:
        user.is_active = bool(payload["is_active"])
    if payload.get("password"):
        user.password_hash = hash_password(payload["password"])
    db.commit()
    db.refresh(user)
    return {"id": user.id, "username": user.username, "role": user.role, "is_active": user.is_active}


@router.delete("/users/{target_id}")
def delete_user(target_id: int, user_id: int, db: Session = Depends(get_db)) -> dict:
    requester = db.get(User, user_id)
    if not is_admin(requester):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    if target_id == 1 or target_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete the primary admin account or yourself")
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"message": "User deleted successfully"}


@router.put("/profile/{user_id}")
def update_profile(user_id: int, payload: dict, db: Session = Depends(get_db)) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    username = (payload.get("username") or "").strip()
    email = (payload.get("email") or "").strip()
    if username:
        clash = db.query(User).filter(User.username == username, User.id != user_id).first()
        if clash:
            raise HTTPException(status_code=400, detail="Username already exists")
        user.username = username
    if email:
        clash = db.query(User).filter(User.email == email, User.id != user_id).first()
        if clash:
            raise HTTPException(status_code=400, detail="Email already exists")
        user.email = email
    if "role" in payload and payload["role"]:
        if not is_admin(user):
            raise HTTPException(status_code=403, detail="Only admins can change their role")
        role = payload["role"].strip()
        if role not in {"admin", "admin1", "user"}:
            raise HTTPException(status_code=400, detail="role must be admin, admin1 or user")
        if user_id == 1:
            role = "admin"
        user.role = role
        user.is_admin = role == "admin"
    current_password = payload.get("current_password") or ""
    new_password = payload.get("new_password") or ""
    if new_password:
        if not check_password(current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        user.password_hash = hash_password(new_password)
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
    }


@router.get("/presentations/{presentation_id}/download/{file_format}")
def download_presentation(
    presentation_id: int,
    file_format: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    record = db.get(Presentation, presentation_id)
    if not record or not record.file_path:
        raise HTTPException(status_code=404, detail="Presentation not found")

    presentation_path = Path(record.file_path)
    if not presentation_path.exists():
        raise HTTPException(status_code=404, detail="Generated file missing")

    if file_format == "pptx":
        return FileResponse(
            path=presentation_path,
            filename=presentation_path.name,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )

    if file_format == "pdf":
        pdf_path = presentation_path.with_suffix(".pdf")
        if not pdf_path.exists():
            convert_to_pdf(presentation_path)
        return FileResponse(path=pdf_path, filename=pdf_path.name, media_type="application/pdf")

    raise HTTPException(status_code=400, detail="Invalid download format")


@router.get("/presentations/user/{user_id}")
def get_user_presentations(user_id: int, db: Session = Depends(get_db)) -> list[dict]:
    presentations = db.query(Presentation).filter(Presentation.user_id == user_id).all()
    result = []
    for p in presentations:
        tasks = db.query(TaskStatus).filter(TaskStatus.presentation_id == p.id).all()
        latest_task = max(tasks, key=lambda t: t.created_at) if tasks else None
        user = db.get(User, p.user_id)
        result.append({
            "id": p.id,
            "title": p.configuration_json.get("title", "Untitled"),
            "created_at": latest_task.created_at.isoformat() if latest_task else None,
            "status": latest_task.status if latest_task else "Unknown",
            "file_path": p.file_path,
            "user_name": user.username if user else "Unknown",
            "user_email": user.email if user else "Unknown",
        })
    return result


def _storage_root() -> Path:
    """Absolute path of ``settings.storage_dir`` (it is stored relative)."""
    root = Path(settings.storage_dir)
    if root.is_absolute():
        return root
    # Relative to the backend package root, not the process working directory.
    return Path(__file__).resolve().parents[2] / root


def _presentation_artifacts(record: Presentation) -> list[Path]:
    """Every file a generated presentation may own: deck, PDF and logo."""
    root = _storage_root()
    candidates: list[Path] = []
    if record.file_path:
        stored = Path(record.file_path)
        candidates.append(stored)
        if stored.name:
            candidates.append(root / stored.name)
    candidates.append(root / f"presentation_{record.id}.pptx")
    candidates.append(root / f"logo_{record.id}.png")

    seen: set[Path] = set()
    result: list[Path] = []
    for path in candidates:
        for variant in (path, path.with_suffix(".pdf")):
            if variant not in seen:
                seen.add(variant)
                result.append(variant)
    return result


@router.delete("/presentations/{presentation_id}")
def delete_presentation(
    presentation_id: int,
    db: Session = Depends(get_db),
) -> dict:
    record = db.get(Presentation, presentation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Presentation not found")

    # Delete the generated deck (PPTX + PDF) and the uploaded logo. Paths are
    # resolved against the storage dir so deletion works regardless of the
    # process working directory.
    for path in _presentation_artifacts(record):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:  # noqa: BLE001 - a left-over file must not block the delete
            logger.warning("Could not delete %s: %s", path, exc)

    # Delete associated tasks
    db.query(TaskStatus).filter(TaskStatus.presentation_id == presentation_id).delete()

    # Delete the presentation record
    db.delete(record)
    db.commit()

    return {"message": "Presentation deleted successfully"}
