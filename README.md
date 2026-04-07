# SlideMaka

SlideMaka is a three-tier presentation generator with a React frontend, FastAPI backend, PostgreSQL persistence, and LLM-driven slide structuring.

## Architecture

- **Presentation Layer:** React dashboard with slide count, theory/practical ratio, image density, audience level, palette picker, and text input.
- **Application Layer:** FastAPI orchestration with parameter calculator, prompt builder, PPTX generator, and PDF converter.
- **Data Layer:** PostgreSQL tables for users, color palettes, presentations, and task status.
- **External AI Layer:** LLM receives strict constraints and returns exact slide-count JSON.

## Backend modules

- `app/services/parameter_calculator.py` – computes theory/practical/image counts and insufficiency warnings.
- `app/services/llm_structurer.py` – builds hard-constraint prompt for exact slide count and distribution.
- `app/services/pptx_generator.py` – creates slides, switching layouts for image-designated slides.
- `app/services/pdf_converter.py` – converts PPTX to PDF using headless LibreOffice.

## Quick start

```bash
docker compose up --build
```

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`

## Local Python setup (important for imports)

The backend code imports modules as `from app...`, so Python must see `backend/` on its import path.

Choose one option:

```bash
# Option A (recommended): install backend package in editable mode
python -m pip install -e backend

# Option B: set module path manually for the shell session
export PYTHONPATH=backend
```

Then run backend from repo root with either:

```bash
uvicorn app.main:app --app-dir backend --reload
# or, if using editable install
uvicorn app.main:app --reload
```

## API

- `POST /api/presentations/preview` – live distribution preview.
- `POST /api/presentations/generate` – creates presentation task and generates PPTX.
- `GET /api/tasks/{task_id}` – task state polling endpoint.

## Gemini configuration

Create a root `.env` file with:

```
GEMINI_API_KEY=your_api_key_here
# optional
GEMINI_MODEL=gemini-1.5-pro
```

The backend now calls Gemini `generateContent` directly and expects JSON slide output.

## Notes

- Generated files are written to `backend/generated/`.
