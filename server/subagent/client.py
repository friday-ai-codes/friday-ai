"""SubAgent HTTP client for communication with Claude Code containers.
Provides async HTTP client for submitting tasks to SubAgent containers
and receiving task status updates.
"""
from dataclasses import dataclass, field
from typing import Any
import httpx
import structlog
from django.conf import settings
logger = structlog.get_logger(__name__)
@dataclass
class SubAgentRequest:
 """SubAgent request data structure."""
 session_id: str
 """SubAgent session ID (sub-{hash})"""
 task_type: str
 """Task type: explore, ask, plan, coding"""
 repo_url: str
 """Git repository URL"""
 branch: str
 """Source branch name"""
 main_session_id: str
 """Main Agent session ID for callback"""
 target_branch: str | None = None
 """Target branch for coding tasks"""
 prompt: str = ""
 """Task prompt/instructions"""
 context: dict[str, Any] | None = None
 """Additional context (project info, work item, etc.)"""
@dataclass
class SubAgentResponse:
 """SubAgent response data structure."""
 task_id: str
 """Unique task identifier"""
 status: str
 """Task status: pending, running, completed, error"""
 output: Any = None
 """Task output (when completed)"""
 error: str | None = None
 """Error message (when error)"""
 metadata: dict[str, Any] = field(default_factory=dict)
 """Additional metadata"""
class SubAgentTimeoutConfig:
 """SubAgent task timeout configuration.
 Different task types have different timeouts based on complexity.
 """
 # Task type -> timeout seconds
 TIMEOUTS: dict[str, int] = {
 "explore": 10 * 60, # 10 minutes - explore repository structure
 "ask": 5 * 60, # 5 minutes - answer technical questions
 "plan": 15 * 60, # 15 minutes - generate technical plan
 "coding": 30 * 60, # 30 minutes - coding tasks (most complex)
 }
 # Default timeout for unknown task types
 DEFAULT_TIMEOUT: int = 10 * 60 # 10 minutes
 @classmethod
 def get_timeout(cls, task_type: str) -> int:
 """Get timeout seconds for specified task type."""
 return cls.TIMEOUTS.get(task_type, cls.DEFAULT_TIMEOUT)
class SubAgentClient:
 """SubAgent HTTP client.
 Handles async HTTP communication with Claude Code containers.
 """
 def __init__(
 self,
 base_url: str | None = None,
 timeout: float = 30.0,
 ) -> None:
 """Initialize SubAgent client.
 Args:
 base_url: SubAgent API base URL. Defaults to settings.SUBAGENT_API_URL
 timeout: Request timeout in seconds. Defaults to 30.0
 """
 self.base_url = base_url or getattr(
 settings, "SUBAGENT_API_URL", "http://localhost:8080"
 )
 self.timeout = httpx.Timeout(timeout, connect=10.0)
 self.log = logger.bind(base_url=self.base_url)
 async def submit_task(self, request: SubAgentRequest) -> str:
 """Submit task to SubAgent, return task ID.
 Async non-blocking: immediately returns task ID,
 SubAgent notifies via callback when complete.
 Args:
 request: SubAgent request data
 Returns:
 Task ID for tracking
 Raises:
 httpx.HTTPStatusError: If request fails
 """
 callback_url = (
 getattr(settings, "FRIDAY_BASE_URL", "http://localhost:8000")
 + "/api/subagent/callback/"
 )
 payload = {
 "session_id": request.session_id,
 "task_type": request.task_type,
 "repo_url": request.repo_url,
 "branch": request.branch,
 "target_branch": request.target_branch,
 "prompt": request.prompt,
 "context": request.context or {},
 "main_session_id": request.main_session_id,
 "callback_url": callback_url,
 }
 self.log.info(
 "subagent_submit_task",
 session_id=request.session_id,
 task_type=request.task_type,
 )
 async with httpx.AsyncClient(timeout=self.timeout) as client:
 response = await client.post(
 f"{self.base_url}/api/subagent/tasks/",
 json=payload,
 )
 response.raise_for_status
 data = response.json
 task_id = data["task_id"]
 self.log.info(
 "subagent_task_submitted",
 task_id=task_id,
 session_id=request.session_id,
 )
 return task_id
 async def get_task_status(self, task_id: str) -> SubAgentResponse:
 """Query task status (for debugging/monitoring).
 Args:
 task_id: Task ID to query
 Returns:
 SubAgentResponse with current status
 Raises:
 httpx.HTTPStatusError: If request fails
 """
 self.log.debug("subagent_get_status", task_id=task_id)
 async with httpx.AsyncClient(timeout=self.timeout) as client:
 response = await client.get(
 f"{self.base_url}/api/subagent/tasks/{task_id}/",
 )
 response.raise_for_status
 data = response.json
 return SubAgentResponse(
 task_id=data.get("task_id", task_id),
 status=data.get("status", "unknown"),
 output=data.get("output"),
 error=data.get("error"),
 metadata=data.get("metadata", {}),
 )
