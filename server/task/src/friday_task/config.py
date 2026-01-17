"""Task Container Configuration."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
class TaskConfig(BaseSettings):
 """Configuration for the task container."""
 model_config = SettingsConfigDict(
 env_prefix="FRIDAY_TASK_",
 env_file=".env",
 extra="ignore",
 )
 # Task identification
 task_id: str = Field(..., description="Unique task identifier")
 project_id: str = Field(..., description="Project identifier")
 # Task details
 task_title: str = Field(..., description="Task title")
 task_description: str = Field(default="", description="Task description")
 task_mode: str = Field(default="plan", description="Mode: plan or execute")
 # Git configuration
 git_repo_url: str = Field(..., description="Git repository URL")
 git_branch: str = Field(default="main", description="Git branch to work on")
 git_auth_type: str = Field(default="ssh", description="Auth type: ssh or token")
 git_ssh_key: str = Field(default="", description="SSH private key content")
 git_access_token: str = Field(default="", description="Access token for HTTPS auth")
 git_ssl_verify: bool = Field(
 default=False,
 description="Verify SSL certificates for HTTPS Git operations (默认禁用以支持自签名证书的内部 Git 服务器)",
 )
 # Claude Code configuration
 claude_api_key: str = Field(default="", description="Anthropic API key")
 claude_base_url: str = Field(
 default="", description="Anthropic API base URL（可选，用于代理服务）"
 )
 claude_model: str = Field(
 default="claude-sonnet-4-20250514", description="Claude model to use"
 )
 claude_max_tokens: int = Field(default=8192, description="Max tokens per request")
 # Callback configuration
 callback_url: str = Field(..., description="API callback URL for status updates")
 callback_token: str = Field(
 default="", description="Bearer token for callback auth"
 )
 # Working directories
 workspace_dir: str = Field(
 default="/app/workspace", description="Git workspace directory"
 )
 session_dir: str = Field(
 default="/app/sessions", description="Session persistence directory"
 )
 # Timeouts
 execution_timeout: int = Field(
 default=3600, description="Max execution time in seconds"
 )
 git_timeout: int = Field(
 default=300, description="Git operation timeout in seconds"
 )
