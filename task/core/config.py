"""Task Container Configuration.
支持两种配置来源：
1. 环境变量（容器模式）- 使用 FRIDAY_TASK_ 前缀
2. 命令行参数（CLI 模式）- 直接传入构造函数
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
class TaskConfig(BaseSettings):
 """Configuration for the task container.
 支持环境变量和直接参数两种配置方式。
 CLI 模式下，参数直接传入构造函数；
 容器模式下，从环境变量读取（FRIDAY_TASK_ 前缀）。
 """
 model_config = SettingsConfigDict(
 env_prefix="FRIDAY_TASK_",
 env_file=".env",
 extra="ignore",
 )
 # Task identification
 task_id: str = Field(..., description="Unique task identifier")
 project_id: str = Field(default="cli", description="Project identifier")
 # Task details
 task_title: str = Field(default="", description="Task title (可选，从 description 提取)")
 task_description: str = Field(..., description="Task description (必填)")
 task_mode: str = Field(default="plan", description="Mode: plan or execute")
 # Git configuration
 git_repo_url: str = Field(..., description="Git repository URL")
 git_branch: str = Field(default="main", description="Git branch to work on")
 git_new_branch: str | None = Field(
 default=None,
 description="New feature branch name (仅 execute 模式，可选，默认自动生成)",
 )
 git_auth_type: str = Field(default="ssh", description="Auth type: ssh or token")
 git_ssh_key: str = Field(default="", description="SSH private key content")
 git_access_token: str = Field(default="", description="Access token for HTTPS auth")
 git_ssl_verify: bool = Field(
 default=False,
 description="Verify SSL certificates for HTTPS Git operations (默认禁用以支持自签名证书的内部 Git 服务器)",
 )
 git_http_proxy: str | None = Field(
 default=None,
 description="HTTP/HTTPS proxy URL for Git operations",
 )
 # Claude Code configuration
 claude_api_key: str = Field(default="", description="Anthropic API key")
 claude_base_url: str = Field(
 default="", description="Anthropic API base URL（可选，用于代理服务）"
 )
 claude_model: str = Field(default="", description="Claude model to use")
 claude_max_tokens: int = Field(default=8192, description="Max tokens per request")
 # Callback configuration (可选 - 不设置则仅记录日志)
 callback_url: str = Field(
 default="",
 description="API callback URL for status updates (可选，不设置则运行在独立模式)",
 )
 callback_token: str = Field(default="", description="Bearer token for callback auth")
 # Working directories
 workspace_dir: str = Field(default="/app/workspace", description="Git workspace directory")
 session_dir: str = Field(default="/app/sessions", description="Session persistence directory")
 # Session management
 resume_session_id: str | None = Field(
 default=None,
 description="Session ID to resume from (可选)",
 )
 # Branch strategy for MR creation
 branch_strategy: str | None = Field(
 default=None,
 description="Branch name pattern (supports {task_id} placeholder), e.g., 'friday/task-{task_id}'",
 )
 target_branch: str | None = Field(
 default=None,
 description="MR target branch from tech plan (defaults to git_branch)",
 )
 # Timeouts
 execution_timeout: int = Field(default=3600, description="Max execution time in seconds")
 git_timeout: int = Field(default=300, description="Git operation timeout in seconds")
 # Cache support
 git_reference_path: str = Field(
 default="",
 description="预克隆仓库的本地路径（FRIDAY_REPO_REFERENCE 环境变量）",
 json_schema_extra={"env": "FRIDAY_REPO_REFERENCE"},
 )
 deps_cache_path: str = Field(
 default="",
 description="预安装依赖的挂载路径（FRIDAY_DEPS_CACHE_PATH 环境变量）",
 json_schema_extra={"env": "FRIDAY_DEPS_CACHE_PATH"},
 )
 deps_manager: str = Field(
 default="",
 description="依赖管理器类型 pip/npm/pnpm（FRIDAY_DEPS_MANAGER 环境变量）",
 json_schema_extra={"env": "FRIDAY_DEPS_MANAGER"},
 )
