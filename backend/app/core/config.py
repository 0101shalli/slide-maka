from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "SlideMaka API"
    database_url: str = "postgresql+psycopg2://postgres:postgres@db:5432/slide_maka"
    storage_dir: str = "generated"
    gemini_api_key: str = "AIzaSyCNcD50uxfvSstiK8mGjyRBNkyOJrOw8Bw"
    gemini_model: str = "gemini-3.5-flash"
    # "minimal" keeps the model's internal reasoning short (a 12-slide deck spent
    # ~4k thinking tokens on 1.3k output tokens, which dominated the latency).
    # Set to "" to use the model default. gemini_client drops the field
    # automatically if the API rejects it.
    gemini_thinking_level: str = "minimal"
    # Seconds a structured-slide response stays reusable. The preview and the
    # generate request send the same prompt, so this halves the LLM calls (and
    # the free-tier quota spent) for a single preview -> generate flow.
    gemini_slides_cache_ttl: int = 1800
    # Off by default: free-tier quotas allow ~20 requests/day, and per-slide
    # speaker notes + activities burn ~14 calls per deck. When False, those are
    # filled with deterministic defaults and only the main content call uses AI.
    enable_detailed_ai_content: bool = False
    # Slide images are fetched in parallel before rendering; a 14-slide deck with
    # 4 image slides went from ~37s of serial network stalls to ~7s.
    image_prefetch_workers: int = 6
    # source.unsplash.com is decommissioned, so it is no longer tried by default.
    enable_legacy_unsplash: bool = False
    # One batched call per deck asks the LLM for a per-slide visual brief
    # (a precise image query and, where the content is a process, the steps of a
    # flow diagram drawn offline with Pillow). Kept to one call so a deck costs
    # a single extra free-tier request; if it fails the deck falls back to the
    # keyword heuristic.
    enable_ai_visual_planner: bool = True
    # Optional model name override for the visual planner task.
    ai_visual_planner_model: str = ""
    
        


settings = Settings()
