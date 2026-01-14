"""Friday configuration management using pydantic-settings."""
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
 """Application settings loaded from environment variables."""
 model_config = SettingsConfigDict(
 env_file=".env",
 env_file_encoding="utf-8",
 extra="ignore",
 )
 # Application
 APP_NAME: str = "Friday"
 DEBUG: bool = False
 # Database
 DATA_DIR: Path = Path("data")
 SQLITE_PATH: Path = Path("data/friday.db")
 # Security
 SECRET_KEY: str = "change-me-in-production"
 # Anthropic
 ANTHROPIC_API_KEY: str = ""
 ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
 # Feishu
 FEISHU_APP_ID: str = ""
 FEISHU_APP_SECRET: str = ""
 FEISHU_WEBHOOK_SECRET: str = ""
 def __init__(self, **kwargs):
 super.__init__(**kwargs)
 # Ensure data directories exist
 self.DATA_DIR.mkdir(parents=True, exist_ok=True)
 (self.DATA_DIR / "repos").mkdir(exist_ok=True)
 (self.DATA_DIR / "sessions").mkdir(exist_ok=True)
 (self.DATA_DIR / "credentials").mkdir(exist_ok=True)
@lru_cache
def get_settings -> Settings:
 """Get cached settings instance."""
 return Settings