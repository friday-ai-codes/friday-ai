import enum
from dataclasses import dataclass, field
class TaskState(str, enum.Enum):
 QUEUED = "queued"
 RUNNING = "running"
 COMPLETED = "completed"
 FAILED = "failed"
 TIMEOUT = "timeout"
 CANCELLED = "cancelled"
@dataclass
class TaskInfo:
 task_id: str
 task_type: str = "coding"
 image: str = ""
 repo_url: str = ""
 branch: str = ""
 timeout: int = 0
 payload: dict = field(default_factory=dict)
@dataclass
class RunnerConfig:
 name: str
 url: str
 token: str # encrypted
 scope: str
 concurrent: int
 project_id: str | None = None
@dataclass
class GlobalConfig:
 log_level: str = "info"
@dataclass
class RegisterResponse:
 runner_id: str
 runner_token: str
 name: str
 scope: str
@dataclass
class RunnerStatus:
 id: str
 name: str
 scope: str
 status: str
 concurrent: int
 version: str
 last_heartbeat: str | None = None
