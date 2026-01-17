"""Callback client for reporting task status to main API."""
from datetime import datetime
from typing import Any
import httpx
import structlog
from .config import TaskConfig
logger = structlog.get_logger
class CallbackClient:
 """Client for sending status updates back to the main Friday API."""
 def __init__(self, config: TaskConfig):
 """Initialize callback client with config."""
 self.config = config
 self.base_url = config.callback_url
 self.headers = {
 "Content-Type": "application/json",
 }
 if config.callback_token:
 self.headers["Authorization"] = f"Bearer {config.callback_token}"
 async def report_status(
 self,
 status: str,
 message: str | None = None,
 details: dict[str, Any] | None = None,
 ) -> bool:
 """Report task status to the main API."""
 log = logger.bind(task_id=self.config.task_id, status=status)
 payload = {
 "task_id": self.config.task_id,
 "status": status,
 "message": message,
 "details": details or {},
 "timestamp": datetime.utcnow.isoformat,
 }
 try:
 async with httpx.AsyncClient as client:
 response = await client.post(
 f"{self.base_url}/tasks/{self.config.task_id}/status",
 json=payload,
 headers=self.headers,
 timeout=30.0,
 )
 response.raise_for_status
 log.info("Status reported successfully")
 return True
 except httpx.HTTPError as e:
 log.error("Failed to report status", error=str(e))
 return False
 async def report_plan_ready(self, plan: str) -> bool:
 """Report that a plan is ready for review."""
 return await self.report_status(
 status="plan_ready",
 message="Implementation plan is ready for review",
 details={"plan": plan},
 )
 async def report_execution_complete(
 self,
 branch_name: str,
 commit_sha: str,
 diff_summary: str,
 ) -> bool:
 """Report that execution is complete and PR is ready."""
 return await self.report_status(
 status="execution_complete",
 message="Code changes are ready for review",
 details={
 "branch_name": branch_name,
 "commit_sha": commit_sha,
 "diff_summary": diff_summary,
 },
 )
 async def report_error(self, error: str, phase: str) -> bool:
 """Report an error during execution."""
 return await self.report_status(
 status="error",
 message=f"Error during {phase}: {error}",
 details={
 "error": error,
 "phase": phase,
 },
 )
 async def report_started(self) -> bool:
 """Report that task execution has started."""
 return await self.report_status(
 status="started",
 message=f"Task execution started in {self.config.task_mode} mode",
 details={
 "mode": self.config.task_mode,
 "repo_url": self.config.git_repo_url,
 "branch": self.config.git_branch,
 },
 )
 async def report_git_ready(self, branch_name: str) -> bool:
 """Report that git repository is ready."""
 return await self.report_status(
 status="git_ready",
 message="Git repository cloned and branch created",
 details={
 "branch_name": branch_name,
 },
 )
