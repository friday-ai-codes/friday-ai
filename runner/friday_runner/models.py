from dataclasses import dataclass
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
