from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    google_places_api_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-5"
    database_url: str = "sqlite:///./data/profilefinder.db"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    google_places_nearby_rpm: int = 60
    google_places_workers: int = 8
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def settings():
    return Settings()
