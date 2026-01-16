"""Repository model for Git codebases."""
import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, List, Optional
from sqlmodel import Field, Relationship, SQLModel
if TYPE_CHECKING:
 from .credential import GitCredential
 from .project import Project
class GitPlatform(str, Enum):
 """Supported Git platforms."""
 GITHUB = "github"
 GITLAB = "gitlab"
 GITEA = "gitea"
 BITBUCKET = "bitbucket"
class ProjectRepository(SQLModel, table=True):
 """Association table between Project and Repository."""
 __tablename__: ClassVar[str] = "project_repositories"
 project_id: str = Field(foreign_key="projects.id", primary_key=True)
 repository_id: str = Field(foreign_key="repositories.id", primary_key=True)
class RepositoryBase(SQLModel):
 """Repository base fields."""
 name: str = Field(index=True, description="仓库显示名称")
 git_url: str = Field(description="Git 仓库 URL")
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
 description: Optional[str] = Field(
 default=None,
 description="仓库描述",
 )
class Repository(RepositoryBase, table=True):
 """Repository database model."""
 __tablename__: ClassVar[str] = "repositories"
 id: str = Field(
 default_factory=lambda: str(uuid.uuid4),
 primary_key=True,
 )
 created_at: datetime = Field(default_factory=datetime.utcnow)
 updated_at: datetime = Field(default_factory=datetime.utcnow)
 # Relationships
 projects: List["Project"] = Relationship(
 back_populates="repositories",
 link_model=ProjectRepository,
 )
 credential: Optional["GitCredential"] = Relationship(
 back_populates="repository",
 sa_relationship_kwargs={"uselist": False},
 )
class RepositoryCreate(RepositoryBase):
 """Repository creation schema."""
 pass
class RepositoryUpdate(SQLModel):
 """Repository update schema."""
 name: Optional[str] = None
 git_url: Optional[str] = None
 git_platform: Optional[GitPlatform] = None
 default_branch: Optional[str] = None
 claude_md_path: Optional[str] = None
 description: Optional[str] = None
class RepositoryRead(RepositoryBase):
 """Repository read schema."""
 id: str
 created_at: datetime
 updated_at: datetime
 has_credential: bool = False
class ProjectSummary(SQLModel):
 """项目摘要信息，用于仓库关联展示。"""
 id: str
 name: str
class RepositoryWithProjectsRead(RepositoryRead):
 """包含关联项目的仓库读取 Schema。"""
 projects: list[ProjectSummary] =
