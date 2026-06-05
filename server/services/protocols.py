"""Friday 容器文件通信协议定义。

容器与主服务通过共享卷中的 JSON 文件通信。
宿主机侧挂载到 server/data/transfers/{session_id}/.friday/
容器内映射到 /workspace/.friday/

Phase: 定义协议常量和 schema
Phase: 实现读写逻辑和回调处理
"""

from dataclasses import dataclass, field
from typing import Any

# === 路径常量 ===

# 容器内协议目录
CONTAINER_PROTOCOL_DIR = "/workspace/.friday"

# 协议文件名
STATUS_FILE = "status.json"
RESULT_FILE = "result.json"
CONTEXT_FILE = "context.json"
QUESTION_FILE = "question.json"  # Phase
ANSWER_FILE = "answer.json"  # Phase
HEARTBEAT_FILE = "heartbeat"  # Phase

# === 状态值常量 ===


class ProtocolStatus:
    """status.json 中的 status 字段值。"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ResultStatus:
    """result.json 中的 status 字段值。"""

    COMPLETED = "completed"
    FAILED = "failed"


# === Schema 定义（用于文档和验证） ===


@dataclass
class StatusPayload:
    """status.json 结构 -- SubAgent 写入，Friday 读取。"""

    status: str  # running | completed | failed
    task_type: str  # coding | plan | explore | ask
    started_at: str  # ISO 8601
    updated_at: str  # ISO 8601
    progress: float = 0.0  # 0.0 - 1.0
    message: str = ""  # 可选进度消息


@dataclass
class ResultPayload:
    """result.json 结构 -- SubAgent 写入，Friday 读取。"""

    status: str  # completed | failed
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    completed_at: str = ""  # ISO 8601


@dataclass
class ContextPayload:
    """context.json 结构 -- Friday 写入，SubAgent 读取。"""

    session_id: str
    task_type: str
    prompt: str = ""
    project: dict[str, Any] = field(default_factory=dict)
    work_item: dict[str, Any] = field(default_factory=dict)
    repo_url: str = ""
    branch: str = ""
    target_branch: str | None = None


# === 环境变量名常量 ===

# 注入到容器的环境变量（统一 FRIDAY_* 前缀）
ENV_SESSION_ID = "FRIDAY_SESSION_ID"
ENV_TASK_TYPE = "FRIDAY_TASK_TYPE"
ENV_PROTOCOL_DIR = "FRIDAY_PROTOCOL_DIR"
ENV_CALLBACK_URL = "FRIDAY_CALLBACK_URL"
ENV_CALLBACK_TOKEN = "FRIDAY_CALLBACK_TOKEN"


# === 回调协议 Schema（Phase）===


class CallbackType:
    """回调端点 type 字段值。"""

    COMPLETED = "completed"
    FAILED = "failed"
    QUESTION = "question"
    HEARTBEAT = "heartbeat"
    PROGRESS = "progress"
    ACTION_LOG = "action_log"
    TOKEN_USAGE = "token_usage"


@dataclass
class CallbackPayload:
    """统一回调端点请求结构。"""

    type: str  # completed | failed | question | heartbeat | progress
    session_id: str
    token: str
    timestamp: str  # ISO 8601
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompletedPayload:
    """type=completed 时的 payload 结构。"""

    result_type: str  # text | git
    output: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    branch_name: str = ""
    commit_sha: str = ""
    modified_files: list[str] = field(default_factory=list)


@dataclass
class FailedPayload:
    """type=failed 时的 payload 结构。"""

    error: str = ""
    exit_code: int = 1
    logs: str = ""


@dataclass
class QuestionPayload:
    """type=question 时的 payload 结构。"""

    question: str = ""
    options: list[str] = field(default_factory=list)
    context: str = ""
    default_option: str = ""
    timeout_minutes: int = 10


@dataclass
class AnswerPayload:
    """answer.json 结构 — Friday 写入，SubAgent 读取。"""

    question_id: str = ""
    answer: str = ""
    answered_at: str = ""  # ISO 8601


@dataclass
class HeartbeatPayload:
    """type=heartbeat 时的 payload 结构。"""

    progress: float = 0.0
    message: str = ""


@dataclass
class ProgressPayload:
    """type=progress 时的 payload 结构。"""

    phase: str = ""  # cloning | installing | coding | testing | pushing
    progress: float = 0.0
    message: str = ""


@dataclass
class ActionLogPayload:
    """type=action_log 时的 payload 结构。"""

    action_type: str
    tool_name: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""  # ISO 8601
    duration_ms: int = 0
    thinking: str = ""
    model: str = ""
    sequence: int = 0


@dataclass
class TokenUsagePayload:
    """type=token_usage 时的 payload 结构。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    model: str = ""
    timestamp: str = ""  # ISO 8601
    total_cost_usd: float = 0.0
