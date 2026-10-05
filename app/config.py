from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    google_places_api_key: str = ""
    database_url: str = "sqlite:///./data/profilefinder.db"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def settings():
    return Settings()
