"""Git credential model for authentication management."""
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Optional
from sqlmodel import Field, Relationship, SQLModel
if TYPE_CHECKING:
 from .repository import Repository
def _utc_now -> datetime:
 """返回当前 UTC 时间（推荐方式）。"""
 return datetime.now(UTC)
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
 # For SSH_KEY: encrypted SSH private key content (Fernet encrypted)
 ssh_key_encrypted: Optional[str] = Field(
 default=None,
 description="加密的 SSH 私钥内容",
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
 __tablename__: ClassVar[str] = "git_credentials"
 id: str = Field(
 default_factory=lambda: str(uuid.uuid4),
 primary_key=True,
 )
 repository_id: str = Field(foreign_key="repositories.id", unique=True)
 created_at: datetime = Field(default_factory=_utc_now)
 updated_at: datetime = Field(default_factory=_utc_now)
 # Relationships
 repository: "Repository" = Relationship(back_populates="credential")
class GitCredentialCreate(SQLModel):
 """Schema for creating a credential."""
 auth_type: AuthType
 git_user_name: Optional[str] = "Friday AI Agent"
 git_user_email: Optional[str] = "ai-agent@friday.codes"
class GitCredentialRead(SQLModel):
 """Schema for reading a credential (without sensitive data)."""
 id: str
 repository_id: str
 created_at: datetime
 # Never expose: ssh_key_encrypted, encrypted_token
 auth_type: AuthType
 git_user_name: str
 git_user_email: str
 # 标识是否已配置 SSH 密钥
 has_ssh_key: bool = False
 # 标识是否已配置访问令牌
 has_access_token: bool = False
