"""系统设置模型，用于存储全局配置。"""
from datetime import UTC, datetime
from typing import ClassVar, Optional
from sqlmodel import Field, SQLModel
def _utc_now -> datetime:
 """返回当前 UTC 时间（推荐方式）。"""
 return datetime.now(UTC)
class SystemSettingBase(SQLModel):
 """系统设置基础字段。"""
 key: str = Field(primary_key=True, description="配置键")
 value: Optional[str] = Field(default=None, description="配置值（敏感值加密存储）")
 is_encrypted: bool = Field(default=False, description="是否加密存储")
 description: Optional[str] = Field(default=None, description="配置描述")
class SystemSetting(SystemSettingBase, table=True):
 """系统设置数据库模型。"""
 __tablename__: ClassVar[str] = "system_settings"
 updated_at: datetime = Field(default_factory=_utc_now)
class SystemSettingCreate(SQLModel):
 """系统设置创建 Schema。"""
 key: str = Field(description="配置键")
 value: str = Field(description="配置值")
 is_encrypted: bool = Field(default=False, description="是否加密存储")
 description: Optional[str] = Field(default=None, description="配置描述")
class SystemSettingUpdate(SQLModel):
 """系统设置更新 Schema。"""
 value: str = Field(description="配置值")
 is_encrypted: Optional[bool] = Field(default=None, description="是否加密存储")
 description: Optional[str] = Field(default=None, description="配置描述")
class SystemSettingRead(SQLModel):
 """系统设置读取 Schema（敏感值不直接返回）。"""
 key: str = Field(description="配置键")
 has_value: bool = Field(description="是否已配置值")
 is_encrypted: bool = Field(description="是否加密存储")
 description: Optional[str] = Field(default=None, description="配置描述")
 updated_at: datetime = Field(description="更新时间")
class SystemSettingReadWithValue(SystemSettingRead):
 """系统设置读取 Schema（包含值）。
 对于非加密配置，value 字段包含实际值；
 对于加密配置，masked_value 字段包含遮罩后的值。
 """
 value: Optional[str] = Field(default=None, description="配置值（仅非加密配置）")
 masked_value: Optional[str] = Field(default=None, description="遮罩后的值（仅加密配置）")
# 预定义的系统设置键
class SettingKeys:
 """系统设置键常量。"""
 ANTHROPIC_API_KEY = "anthropic_api_key"
 ANTHROPIC_BASE_URL = "anthropic_base_url"
