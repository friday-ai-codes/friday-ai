"""Friday 配置管理，使用 pydantic-settings。"""
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
 """应用配置，从环境变量加载。"""
 model_config = SettingsConfigDict(
 env_file=".env",
 env_file_encoding="utf-8",
 extra="ignore",
 )
 # 应用配置
 APP_NAME: str = "Friday"
 PORT: int = 8000
 DEBUG: bool = False
 # 数据库配置
 DATA_DIR: Path = Path("data")
 SQLITE_PATH: Path = Path("data/friday.db")
 # 安全配置
 SECRET_KEY: str = "change-me-in-production"
 # JWT 配置
 JWT_SECRET_KEY: str = "" # 默认使用 SECRET_KEY
 JWT_ALGORITHM: str = "HS256"
 JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15 # Access Token 15分钟
 JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7 # Refresh Token 7天
 # Cookie 配置
 COOKIE_SECURE: bool = False # 开发环境为 False，生产环境应为 True
 COOKIE_SAMESITE: str = "lax" # 防止 CSRF
 COOKIE_HTTPONLY: bool = True # 防止 XSS 读取
 # Anthropic API 配置
 ANTHROPIC_API_KEY: str = ""
 ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
 def __init__(self, **kwargs):
 super.__init__(**kwargs)
 # 确保数据目录存在
 self.DATA_DIR.mkdir(parents=True, exist_ok=True)
 (self.DATA_DIR / "repos").mkdir(exist_ok=True)
 (self.DATA_DIR / "sessions").mkdir(exist_ok=True)
 (self.DATA_DIR / "credentials").mkdir(exist_ok=True)
 # 如果没有单独设置 JWT_SECRET_KEY，使用 SECRET_KEY
 if not self.JWT_SECRET_KEY:
 self.JWT_SECRET_KEY = self.SECRET_KEY
@lru_cache
def get_settings -> Settings:
 """获取缓存的配置实例。"""
 return Settings
