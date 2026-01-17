"""项目模型，用于管理 Git 仓库和飞书项目集成。"""
import secrets
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Optional
from sqlmodel import Field, Relationship, SQLModel
from .repository import ProjectRepository, RepositoryRead
if TYPE_CHECKING:
 from .repository import Repository
 from .task import Task
def _utc_now -> datetime:
 """返回当前 UTC 时间（推荐方式）。"""
 return datetime.now(UTC)
def generate_webhook_token -> str:
 """生成 32 字符的随机 Webhook Token。"""
 return secrets.token_urlsafe(24)[:32]
class ProjectBase(SQLModel):
 """项目基础字段。"""
 name: str = Field(index=True, description="项目显示名称")
 description: Optional[str] = Field(default=None, description="项目描述")
 feishu_project_key: Optional[str] = Field(
 default=None,
 description="飞书项目空间 Key，用于 API 调用",
 )
class Project(ProjectBase, table=True):
 """项目数据库模型。"""
 __tablename__: ClassVar[str] = "projects"
 id: str = Field(
 default_factory=lambda: str(uuid.uuid4),
 primary_key=True,
 )
 created_at: datetime = Field(default_factory=_utc_now)
 updated_at: datetime = Field(default_factory=_utc_now)
 # 飞书插件凭证字段（加密存储）
 feishu_plugin_id: Optional[str] = Field(
 default=None,
 description="飞书插件 ID",
 )
 feishu_plugin_secret_encrypted: Optional[str] = Field(
 default=None,
 description="飞书插件 Secret（加密存储）",
 )
 feishu_webhook_token: str = Field(
 default_factory=generate_webhook_token,
 description="飞书 Webhook 验证 Token（创建项目时自动生成）",
 )
 feishu_user_key: Optional[str] = Field(
 default=None,
 description="飞书用户 Key，用于 API 调用时的用户身份（必填，可通过双击用户头像获取）",
 )
 # Claude 配置字段（项目级覆盖系统配置）
 claude_api_key_encrypted: Optional[str] = Field(
 default=None,
 description="Claude API Key（加密存储，可选，覆盖系统配置）",
 )
 claude_base_url: Optional[str] = Field(
 default=None,
 description="Claude API Base URL（可选，覆盖系统配置）",
 )
 # 关联关系
 # 关联关系
 tasks: list["Task"] = Relationship(back_populates="project")
 repositories: list["Repository"] = Relationship(
 back_populates="projects",
 link_model=ProjectRepository,
 )
 def has_feishu_config(self) -> bool:
 """检查是否已配置飞书集成。"""
 return bool(
 self.feishu_project_key
 and self.feishu_plugin_id
 and self.feishu_plugin_secret_encrypted
 )
class ProjectCreate(ProjectBase):
 """项目创建 Schema。"""
 pass
class ProjectUpdate(SQLModel):
 """项目更新 Schema。"""
 name: Optional[str] = None
 description: Optional[str] = None
 feishu_project_key: Optional[str] = None
class ProjectRead(ProjectBase):
 """项目读取 Schema。"""
 id: str
 created_at: datetime
 updated_at: datetime
 description: Optional[str] = None
 has_feishu_config: bool = False
 webhook_token: str = Field(description="Webhook 验证 Token")
 repositories: list[RepositoryRead] =
# 飞书配置相关 Schema
class FeishuConfigCreate(SQLModel):
 """飞书配置创建 Schema（不包含 webhook_token，它在项目级别管理）。"""
 plugin_id: str = Field(description="飞书插件 ID")
 plugin_secret: str = Field(description="飞书插件 Secret")
 user_key: str = Field(
 description="飞书用户 Key，用于 API 调用时的用户身份（必填，可通过双击用户头像获取）",
 )
class FeishuConfigRead(SQLModel):
 """飞书配置读取 Schema（不返回敏感信息，不含 webhook_token 由项目接口返回）。"""
 project_key: Optional[str] = Field(description="飞书项目空间 Key")
 plugin_id: Optional[str] = Field(description="飞书插件 ID")
 user_key: Optional[str] = Field(default=None, description="飞书用户 Key（必填）")
 has_plugin_secret: bool = Field(description="是否已配置插件 Secret")
 is_configured: bool = Field(description="是否已完成配置")
class FeishuConfigTestResult(SQLModel):
 """飞书配置测试结果。"""
 success: bool = Field(description="测试是否成功")
 message: str = Field(description="测试结果消息")
 plugin_token_valid: bool = Field(
 default=False,
 description="是否能获取 plugin_access_token",
 )
 project_accessible: bool = Field(
 default=False,
 description="是否能访问飞书项目空间",
 )
class FeishuConfigTest(SQLModel):
 """飞书配置测试请求 Schema，用于传入临时配置进行测试。"""
 plugin_id: Optional[str] = Field(
 default=None,
 description="飞书插件 ID（可选，不传则使用已保存的配置）",
 )
 plugin_secret: Optional[str] = Field(
 default=None,
 description="飞书插件 Secret（可选，不传则使用已保存的配置）",
 )
 user_key: Optional[str] = Field(
 default=None,
 description="飞书用户 Key（不传则使用已保存的配置）",
 )
# Webhook Token 相关 Schema
class WebhookTokenUpdate(SQLModel):
 """Webhook Token 更新 Schema。"""
 token: str = Field(
 max_length=32,
 description="自定义 Webhook Token（最大 32 字符）",
 )
class WebhookTokenRead(SQLModel):
 """Webhook Token 读取 Schema。"""
 webhook_token: str = Field(description="Webhook 验证 Token")
# Claude 配置相关 Schema
class ClaudeConfigCreate(SQLModel):
 """Claude 配置创建/更新 Schema。"""
 api_key: Optional[str] = Field(
 default=None,
 description="Claude API Key（可选，覆盖系统配置）",
 )
 base_url: Optional[str] = Field(
 default=None,
 description="Claude API Base URL（可选，覆盖系统配置）",
 )
class ClaudeConfigRead(SQLModel):
 """Claude 配置读取 Schema（不返回敏感信息）。"""
 has_api_key: bool = Field(description="是否已配置项目级 API Key")
 base_url: Optional[str] = Field(default=None, description="Claude API Base URL")
 source: str = Field(
 default="system",
 description="配置来源：project（项目级）、system（系统级）、environment（环境变量）",
 )
