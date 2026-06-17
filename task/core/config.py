"""Task Container Configuration.

支持两种配置来源：
1. 环境变量（容器模式）- 使用 FRIDAY_TASK_ 前缀
2. 命令行参数（CLI 模式）- 直接传入构造函数
"""

from typing import Self

from pydantic import Field, model_validator
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
    claude_small_model: str = Field(
        default="",
        description="Claude 子代理模型（Explore 等），不设置时回退到主模型",
    )
    # cc-switch 风格三档模型映射（Claude Code 模型映射）。非空时映射到
    # ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL，让 Claude Code 的三档模型别名
    # 指向所选 provider 的具体模型。留空则回退 claude_model / claude_small_model。
    claude_opus_model: str = Field(
        default="", description="opus 档映射模型（ANTHROPIC_DEFAULT_OPUS_MODEL）"
    )
    claude_sonnet_model: str = Field(
        default="", description="sonnet 档映射模型（ANTHROPIC_DEFAULT_SONNET_MODEL）"
    )
    claude_haiku_model: str = Field(
        default="", description="haiku 档映射模型（ANTHROPIC_DEFAULT_HAIKU_MODEL）"
    )
    claude_max_tokens: int = Field(default=8192, description="Max tokens per request")
    claude_max_turns: int = Field(
        default=50,
        description="Claude Code 最大对话轮数，防止非 Claude 模型死循环",
    )

    # Phase 11 RemoteTool 链路（FRIDAY_TASK_ 前缀经 env_prefix 自动映射）。
    # 三字段默认空 → 不设置 env 时行为与现状完全一致（向后兼容，不挂 MCP server）。
    user_token: str = Field(
        default="",
        description="用户直传 PAT（friday_pat_...），仅注入 Authorization，绝不入日志",
    )
    tools_endpoint: str = Field(
        default="",
        description="Friday Server /api/tools/execute/ 完整 URL",
    )
    remote_tools: list[dict] = Field(
        default_factory=list,
        description="RemoteTool schema 列表（FRIDAY_TASK_REMOTE_TOOLS JSON）",
    )

    # Phase 22-04 排除规则下传（EXCL-02 容器读取面）。server 两条派发路径经
    # FRIDAY_TASK_EXCLUDE_PATTERNS（JSON 规则列表 [{pattern, rule_type}]）注入；
    # 容器 clone+checkout 后 prune 据此物理删除被排除文件，使 agent 不可见。
    # 默认空 → 不删任何文件（向后兼容；未注入时行为与现状一致）。
    exclude_patterns: list[dict] = Field(
        default_factory=list,
        description="排除规则列表（FRIDAY_TASK_EXCLUDE_PATTERNS JSON：[{pattern, rule_type}]）",
    )

    # Phase 51 GATE-02：SDD/openspec 仓标记（D-51-4）。经 env_prefix 自动映射
    # FRIDAY_TASK_FOLLOW_OPENSPEC。默认 False → system_prompt 与现状逐字一致（零回归）；
    # 为真（server gate 放行的 approved SDD 仓注入 "true"）时 _get_system_prompt 追加 openspec 指引段。
    follow_openspec: bool = Field(
        default=False,
        description="SDD/openspec 仓标记：为真时 system_prompt 追加 openspec 指引段（server gate 放行的 approved SDD 仓注入 FRIDAY_TASK_FOLLOW_OPENSPEC=true）",
    )

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

    # 两阶段 dispatch 支持
    task_type: str = Field(
        default="coding",
        description="任务类型: coding (完整编码) / coding_commit (仅 commit+push)",
    )
    commit_message: str = Field(
        default="",
        description="用户确认的 commit message（Phase 容器通过 FRIDAY_TASK_COMMIT_MESSAGE 环境变量接收）",
    )

    # Timeouts
    execution_timeout: int = Field(default=3600, description="Max execution time in seconds")
    git_timeout: int = Field(default=300, description="Git operation timeout in seconds")

    # Cache support (work item, work item)
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

    @model_validator(mode="after")
    def normalize_legacy_task_mode(self) -> Self:
        """兼容旧 Runner 把 task_type 写进 task_mode 的协议。"""
        if self.task_mode in {"coding", "coding_commit"}:
            legacy_task_type = self.task_mode
            if self.task_type == "coding":
                self.task_type = legacy_task_type
            self.task_mode = "execute"
        return self
