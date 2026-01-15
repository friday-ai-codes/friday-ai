"""Task model for tracking AI development tasks."""
import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional
from sqlmodel import Field, Relationship, SQLModel
if TYPE_CHECKING:
 from .project import Project
 from .repository import Repository
class TaskStatus(str, Enum):
 """Task status states in the state machine."""
 PENDING = "pending"
 PLANNING = "planning"
 PLAN_REVIEW = "plan_review"
 EXECUTING = "executing"
 CODE_REVIEW = "code_review"
 MERGED = "merged"
 FAILED = "failed"
class TaskMode(str, Enum):
 """Task execution modes."""
 PLAN = "plan"
 EXECUTE = "execute"
 AUTO = "auto"
class TaskBase(SQLModel):
 """Base task fields."""
 # Feishu work item info
 work_item_id: str = Field(index=True, description="Feishu work item ID")
 feature_id: str = Field(description="Feature ID for branch naming")
 title: str = Field(description="Task title")
 description: Optional[str] = Field(
 default=None,
 description="Task description (Markdown)",
 )
 # Git info
 branch_name: Optional[str] = Field(
 default=None,
 description="Feature branch name created for this task",
 )
 commit_sha: Optional[str] = Field(
 default=None,
 description="Latest commit SHA",
 )
 pr_url: Optional[str] = Field(
 default=None,
 description="Pull request URL",
 )
 # Claude session
 session_id: Optional[str] = Field(
 default=None,
 description="Claude Code session ID for context resume",
 )
 # Plan output
 plan_output: Optional[str] = Field(
 default=None,
 description="Generated implementation plan",
 )
 # Status
 status: TaskStatus = Field(
 default=TaskStatus.PENDING,
 description="Current task status",
 )
class Task(TaskBase, table=True):
 """Task database model."""
 __tablename__ = "tasks"
 id: str = Field(
 default_factory=lambda: str(uuid.uuid4),
 primary_key=True,
 )
 project_id: str = Field(foreign_key="projects.id", index=True)
 repository_id: Optional[str] = Field(
 default=None,
 foreign_key="repositories.id",
 index=True,
 )
 created_at: datetime = Field(default_factory=datetime.utcnow)
 updated_at: datetime = Field(default_factory=datetime.utcnow)
 # Execution tracking
 plan_started_at: Optional[datetime] = None
 plan_completed_at: Optional[datetime] = None
 execute_started_at: Optional[datetime] = None
 execute_completed_at: Optional[datetime] = None
 # Human feedback
 human_feedback: Optional[str] = Field(
 default=None,
 description="Human review feedback from Feishu comments",
 )
 # Error tracking
 error_message: Optional[str] = None
 retry_count: int = Field(default=0)
 # Relationships
 project: "Project" = Relationship(back_populates="tasks")
 repository: Optional["Repository"] = Relationship
class TaskCreate(SQLModel):
 """Schema for creating a task."""
 project_id: str
 repository_id: Optional[str] = None
 work_item_id: str
 feature_id: str
 title: str
 description: Optional[str] = None
class TaskUpdate(SQLModel):
 """Schema for updating a task."""
 status: Optional[TaskStatus] = None
 branch_name: Optional[str] = None
 commit_sha: Optional[str] = None
 pr_url: Optional[str] = None
 session_id: Optional[str] = None
 plan_output: Optional[str] = None
 human_feedback: Optional[str] = None
 error_message: Optional[str] = None
class TaskRead(TaskBase):
 """Schema for reading a task."""
 id: str
 project_id: str
 repository_id: Optional[str]
 created_at: datetime
 updated_at: datetime
 plan_started_at: Optional[datetime]
 plan_completed_at: Optional[datetime]
 execute_started_at: Optional[datetime]
 execute_completed_at: Optional[datetime]
 retry_count: int
 error_message: Optional[str]
 human_feedback: Optional[str]
