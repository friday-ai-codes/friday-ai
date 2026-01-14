"""Git credential model for authentication management."""
import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional
from sqlmodel import Field, Relationship, SQLModel
if TYPE_CHECKING:
 from .project import Project
class AuthType(str, Enum):
 """Authentication types for Git access."""
 SSH_KEY = "ssh_key"
 ACCESS_TOKEN = "access_token"
 DEPLOY_KEY = "deploy_key"
class GitCredentialBase(SQLModel):
 """Base credential fields."""
 auth_type: AuthType = Field(
 default=AuthType.SSH_KEY,
 description="Authentication type",
 )
 # For SSH_KEY: path to key file stored in data/credentials/
 ssh_key_path: Optional[str] = Field(
 default=None,
 description="Path to SSH private key file",
 )
 # For ACCESS_TOKEN: encrypted token value
 encrypted_token: Optional[str] = Field(
 default=None,
 description="Encrypted access token",
 )
 # Git user info
 git_user_name: str = Field(
 default="Friday AI Agent",
 description="Git commit author name",
 )
 git_user_email: str = Field(
 default="ai-agent@friday.dev",
 description="Git commit author email",
 )
class GitCredential(GitCredentialBase, table=True):
 """Git credential database model."""
 __tablename__ = "git_credentials"
 id: str = Field(
 default_factory=lambda: str(uuid.uuid4),
 primary_key=True,
 )
 project_id: str = Field(foreign_key="projects.id", unique=True)
 created_at: datetime = Field(default_factory=datetime.utcnow)
 updated_at: datetime = Field(default_factory=datetime.utcnow)
 # Relationships
 project: "Project" = Relationship(back_populates="credential")
class GitCredentialCreate(SQLModel):
 """Schema for creating a credential."""
 auth_type: AuthType
 git_user_name: Optional[str] = "Friday AI Agent"
 git_user_email: Optional[str] = "ai-agent@friday.dev"
class GitCredentialRead(GitCredentialBase):
 """Schema for reading a credential (without sensitive data)."""
 id: str
 project_id: str
 created_at: datetime
 # Never expose: ssh_key_path, encrypted_token
 auth_type: AuthType
 git_user_name: str
 git_user_email: str