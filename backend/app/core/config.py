import os
from pathlib import Path

from pydantic import BaseModel


def _load_env_file() -> None:
    env_candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[3] / ".env"]
    for env_path in env_candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_env_file()


class Settings(BaseModel):
    app_name: str = "SlideMaka API"
    database_url: str = "postgresql+psycopg2://postgres:postgres@db:5432/slide_maka"
    storage_dir: str = "generated"
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")


settings = Settings()
