from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "SlideMaka API"
    database_url: str = "postgresql+psycopg2://postgres:postgres@db:5432/slide_maka"
    storage_dir: str = "generated"


settings = Settings()
