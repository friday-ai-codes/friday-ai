"""项目模型，用于管理 Git 仓库和飞书项目集成。"""
import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Optional
from sqlmodel import Field, Relationship, SQLModel
if TYPE_CHECKING:
 from .credential import GitCredential
 from .task import Task
class GitPlatform(str, Enum):
 """支持的 Git 平台类型。"""
 GITHUB = "github"
 GITLAB = "gitlab"
 GITEA = "gitea"
 BITBUCKET = "bitbucket"
class ProjectBase(SQLModel):
 """项目基础字段。"""
 name: str = Field(index=True, description="项目显示名称")
 repo_url: str = Field(description="Git 仓库 URL")
 git_platform: GitPlatform = Field(
 default=GitPlatform.GITHUB,
 description="Git 平台类型",
 )
 default_branch: str = Field(
 default="main",
 description="默认分支名称",
 )
 claude_md_path: str = Field(
 default="developer-notes.md",
 description="仓库中 developer-notes.md 文件的路径",
 )
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
 created_at: datetime = Field(default_factory=datetime.utcnow)
 updated_at: datetime = Field(default_factory=datetime.utcnow)
 # 飞书插件凭证字段（加密存储）
 feishu_plugin_id: Optional[str] = Field(
 default=None,
 description="飞书插件 ID",
 )
 feishu_plugin_secret_encrypted: Optional[str] = Field(
 default=None,
 description="飞书插件 Secret（加密存储）",
 )
 feishu_webhook_token: Optional[str] = Field(
 default=None,
 description="飞书 Webhook 验证 Token",
 )
 # 关联关系
 credential: Optional["GitCredential"] = Relationship(
 back_populates="project",
 sa_relationship_kwargs={"uselist": False},
 )
 tasks: list["Task"] = Relationship(back_populates="project")
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
 repo_url: Optional[str] = None
 git_platform: Optional[GitPlatform] = None
 default_branch: Optional[str] = None
 claude_md_path: Optional[str] = None
 feishu_project_key: Optional[str] = None
class ProjectRead(ProjectBase):
 """项目读取 Schema。"""
 id: str
 created_at: datetime
 updated_at: datetime
 has_credential: bool = False
 has_feishu_config: bool = False
# 飞书配置相关 Schema
class FeishuConfigCreate(SQLModel):
 """飞书配置创建 Schema。"""
 plugin_id: str = Field(description="飞书插件 ID")
 plugin_secret: str = Field(description="飞书插件 Secret")
 webhook_token: Optional[str] = Field(
 default=None,
 description="Webhook 验证 Token（在飞书项目自动化规则中配置）",
 )
class FeishuConfigRead(SQLModel):
 """飞书配置读取 Schema（不返回敏感信息）。"""
 project_key: Optional[str] = Field(description="飞书项目空间 Key")
 plugin_id: Optional[str] = Field(description="飞书插件 ID")
 has_plugin_secret: bool = Field(description="是否已配置插件 Secret")
 has_webhook_token: bool = Field(description="是否已配置 Webhook Token")
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
