"""Project model for managing Git repositories."""
import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional
from sqlmodel import Field, Relationship, SQLModel
if TYPE_CHECKING:
 from .credential import GitCredential
 from .task import Task
class GitPlatform(str, Enum):
 """Supported Git platforms."""
 GITHUB = "github"
 GITLAB = "gitlab"
 GITEA = "gitea"
 BITBUCKET = "bitbucket"
class ProjectBase(SQLModel):
 """Base project fields."""
 name: str = Field(index=True, description="Project display name")
 repo_url: str = Field(description="Git repository URL")
 git_platform: GitPlatform = Field(
 default=GitPlatform.GITHUB,
 description="Git platform type",
 )
 default_branch: str = Field(
 default="main",
 description="Default branch name",
 )
 claude_md_path: str = Field(
 default="developer-notes.md",
 description="Path to developer-notes.md file in repository",
 )
 feishu_project_key: Optional[str] = Field(
 default=None,
 description="Feishu Project key for API calls",
 )
class Project(ProjectBase, table=True):
 """Project database model."""
 __tablename__ = "projects"
 id: str = Field(
 default_factory=lambda: str(uuid.uuid4),
 primary_key=True,
 )
 created_at: datetime = Field(default_factory=datetime.utcnow)
 updated_at: datetime = Field(default_factory=datetime.utcnow)
 # Relationships
 credential: Optional["GitCredential"] = Relationship(
 back_populates="project",
 sa_relationship_kwargs={"uselist": False},
 )
 tasks: list["Task"] = Relationship(back_populates="project")
class ProjectCreate(ProjectBase):
 """Schema for creating a project."""
 pass
class ProjectUpdate(SQLModel):
 """Schema for updating a project."""
 name: Optional[str] = None
 repo_url: Optional[str] = None
 git_platform: Optional[GitPlatform] = None
 default_branch: Optional[str] = None
 claude_md_path: Optional[str] = None
 feishu_project_key: Optional[str] = None
class ProjectRead(ProjectBase):
 """Schema for reading a project."""
 id: str
 created_at: datetime
 updated_at: datetime
 has_credential: bool = False