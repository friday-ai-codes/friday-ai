"""Callback client for reporting task status to main API.
支持两种模式：
1. 回调模式 - 设置 callback_url 后向 server API 报告状态
2. 独立模式 - 不设置 callback_url 时仅记录日志
[新增] 文件模式 - 如果环境变量 FRIDAY_TASK_OUTPUT_DIR 存在，将状态写入文件
这作为网络回调不可靠时的兜底方案。
"""
from __future__ import annotations
import json
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any
import httpx
import structlog
if TYPE_CHECKING:
 from core.config import TaskConfig
logger = structlog.get_logger
class CallbackClient:
 """Client for sending status updates back to the main Friday API.
 当 callback_url 为空时，自动切换到独立模式，仅记录日志。
 当 FRIDAY_TASK_OUTPUT_DIR 存在时，同时写入文件。
 """
 def __init__(self, config: "TaskConfig"):
 """Initialize callback client with config."""
 self.config = config
 self.enabled = bool(config.callback_url)
 self.base_url = config.callback_url if self.enabled else None
 self.headers = {
 "Content-Type": "application/json",
 }
 if config.callback_token:
 self.headers["Authorization"] = f"Bearer {config.callback_token}"
 # 检查是否开启了文件输出模式（用于网络隔离环境）
 self.output_dir = os.environ.get("FRIDAY_TASK_OUTPUT_DIR")
 if self.output_dir and not os.path.exists(self.output_dir):
 try:
 os.makedirs(self.output_dir, exist_ok=True)
 except Exception as e:
 logger.warning("Failed to create output directory", path=self.output_dir, error=str(e))
 self.output_dir = None
 if not self.enabled:
 logger.info("Callback disabled, running in standalone mode", task_id=config.task_id)
 if self.output_dir:
 logger.info("File output enabled", path=self.output_dir)
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
 # [新增] 1. 优先写入文件（这是最可靠的通道）
 if self.output_dir:
 try:
 # 只有关键状态才写入 result.json，避免 IO 频繁
 # 但这里为了调试方便，我们可以记录所有状态到 events.jsonl
 # 关键结果写入 result.json
 if status in ("plan_ready", "execution_complete", "push_complete", "error"):
 result_path = os.path.join(self.output_dir, "result.json")
 with open(result_path, "w") as f:
 json.dump(payload, f, indent=2, ensure_ascii=False)
 log.info("Status written to file", path=result_path)
 except Exception as e:
 log.error("Failed to write status to file", error=str(e))
 # 2. 如果没启用 HTTP 回调，就结束
 if not self.enabled:
 log.info("Status update (standalone mode)", message=message, details=details)
 return True
 # 3. 尝试 HTTP 回调
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
 # 如果配置了文件输出，HTTP 失败是可以接受的，只是个警告
 if self.output_dir:
 log.warning("Failed to report status via HTTP (backed up to file)", error=str(e))
 else:
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
 """Report that execution is complete."""
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
 details={"error": error, "phase": phase},
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
 details={"branch_name": branch_name},
 )
 async def report_push_complete(
 self,
 branch_name: str,
 commit_sha: str,
 modified_files: list[str],
 ) -> bool:
 """Report that push is complete, triggering MR creation on server."""
 return await self.report_status(
 status="push_complete",
 message="Branch pushed successfully, ready for MR creation",
 details={
 "branch_name": branch_name,
 "commit_sha": commit_sha,
 "modified_files": modified_files,
 },
 )
 async def report_suggested_commit_message(
 self,
 suggested_commit_message: str,
 ) -> bool:
 """回传 AI 建议的 commit message 到 SubAgentSession.last_output。
 通过 progress 回调写入 last_output，供 Phase 完成回调读取。
 Per: Phase 容器通过 SubAgentSession.last_output 回传 suggested_commit_message。
 """
 return await self.report_status(
 status="progress",
 message="AI suggested commit message generated",
 details={
 "suggested_commit_message": suggested_commit_message,
 "phase": "coding_complete",
 },
 )
