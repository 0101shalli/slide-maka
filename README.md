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

## API

- `POST /api/presentations/preview` – live distribution preview.
- `POST /api/presentations/generate` – creates presentation task and generates PPTX.
- `GET /api/tasks/{task_id}` – task state polling endpoint.

## Notes

- The backend contains a placeholder LLM call. Replace with your provider SDK and parse model JSON output.
- Generated files are written to `backend/generated/`.
