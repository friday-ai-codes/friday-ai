"""Friday 配置管理，使用 pydantic-settings。"""
from functools import lru_cache
from pathlib import Path
from typing import Optional
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
 DEBUG: bool = False
 # 数据库配置
 DATA_DIR: Path = Path("data")
 SQLITE_PATH: Path = Path("data/friday.db")
 # 安全配置
 SECRET_KEY: str = "change-me-in-production"
 # Anthropic API 配置
 ANTHROPIC_API_KEY: str = ""
 ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
 # 飞书插件配置（全局默认，已弃用 - 建议使用项目级配置）
 # 这些配置仅用于向后兼容单项目场景
 # 飞书项目使用插件凭证（plugin_id/plugin_secret）而非应用凭证
 FEISHU_PLUGIN_ID: Optional[str] = ""
 FEISHU_PLUGIN_SECRET: Optional[str] = ""
 FEISHU_WEBHOOK_SECRET: Optional[str] = "" # 已弃用，使用项目级 webhook_token
 def __init__(self, **kwargs):
 super.__init__(**kwargs)
 # 确保数据目录存在
 self.DATA_DIR.mkdir(parents=True, exist_ok=True)
 (self.DATA_DIR / "repos").mkdir(exist_ok=True)
 (self.DATA_DIR / "sessions").mkdir(exist_ok=True)
 (self.DATA_DIR / "credentials").mkdir(exist_ok=True)
@lru_cache
def get_settings -> Settings:
 """获取缓存的配置实例。"""
 return Settings
