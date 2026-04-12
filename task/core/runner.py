"""Task Runner - Main entry point for task container execution.
这个模块是容器模式的入口点，通过环境变量读取配置。
CLI 模式使用 cli 模块作为入口点。
执行流程：
1. 读取环境变量配置
2. 设置 Git 仓库
3. 根据模式执行任务（plan 或 execute）
4. 报告结果（如果配置了回调 URL）
"""
import asyncio
import sys
import structlog
from structlog.stdlib import BoundLogger
from git.exc import GitCommandError
from git_ops import GitOperations
from integrations import CallbackClient
from .config import TaskConfig
from .executor import ClaudeRunner
# Configure structured logging
structlog.configure(
 processors=[
 structlog.stdlib.filter_by_level,
 structlog.stdlib.add_logger_name,
 structlog.stdlib.add_log_level,
 structlog.stdlib.PositionalArgumentsFormatter,
 structlog.processors.TimeStamper(fmt="iso"),
 structlog.processors.StackInfoRenderer,
 structlog.processors.format_exc_info,
 structlog.processors.UnicodeDecoder,
 structlog.processors.JSONRenderer,
 ],
 wrapper_class=structlog.stdlib.BoundLogger,
 context_class=dict,
 logger_factory=structlog.stdlib.LoggerFactory,
 cache_logger_on_first_use=True,
)
logger = structlog.get_logger
class TaskRunner:
 """Main task runner that orchestrates the entire task execution."""
 def __init__(self, config: TaskConfig):
 """Initialize task runner with config."""
 self.config = config
 self.git_ops = GitOperations(config)
 self.callback = CallbackClient(config)
 self.claude: ClaudeRunner | None = None
 self._task_branch: str | None = None # Store branch name for push
 async def run(self) -> int:
 """Run the task and return exit code."""
 log = logger.bind(
 task_id=self.config.task_id,
 project_id=self.config.project_id,
 mode=self.config.task_mode,
 )
 log.info(
 "Task runner starting",
 git_url=self.config.git_repo_url,
 branch=self.config.git_branch,
 has_api_key=bool(self.config.claude_api_key),
 has_callback_url=bool(self.config.callback_url),
 )
 try:
 # Report started
 await self.callback.report_started
 # Set up Git repository
 log.info("Setting up Git repository")
 await self.git_ops.setup
 # Setup task-specific branch based on branch_strategy
 # CRITICAL: Branch must be created/switched BEFORE any Claude coding execution
 branch_name = self.config.git_branch
 if self.config.task_mode == "execute":
 # Use branch_strategy if provided, otherwise fall back to git_new_branch or default
 branch_strategy = self.config.branch_strategy or self.config.git_new_branch
 self._task_branch = await self.git_ops.setup_task_branch(
 branch_strategy=branch_strategy,
 task_id=self.config.task_id,
 )
 branch_name = self._task_branch
 await self.callback.report_git_ready(branch_name)
 log.info("Task branch ready for coding", branch=branch_name)
 else:
 log.info("Plan mode - staying on branch", branch=branch_name)
 # Initialize Claude runner
 self.claude = ClaudeRunner(self.config, self.git_ops.get_workspace_path)
 # Execute based on mode
 if self.config.task_mode == "plan":
 return await self._run_plan_mode(log, branch_name)
 elif self.config.task_mode == "explore":
 return await self._run_explore_mode(log)
 elif self.config.task_mode == "repo_summary":
 return await self._run_repo_summary_mode(log)
 else:
 return await self._run_execute_mode(log, branch_name)
 except Exception as e:
 log.exception("Task execution failed")
 await self.callback.report_error(str(e), "execution")
 return 1
 finally:
 self.git_ops.cleanup
 log.info("Task runner finished")
 async def _run_plan_mode(self, log, branch_name: str) -> int:
 """Run in plan mode to generate implementation plan."""
 log.info("Running in plan mode")
 assert self.claude is not None, "ClaudeRunner not initialized"
 result = await self.claude.run_plan_mode
 if not result.get("success"):
 error = result.get("error", "Unknown error")
 log.error("Plan generation failed", error=error)
 await self.callback.report_error(error, "planning")
 return 1
 plan = result.get("output", "")
 await self.callback.report_plan_ready(plan)
 log.info("Plan mode completed successfully")
 return 0
 async def _run_explore_mode(self, log) -> int:
 """Run in explore mode for deep code analysis (no commits)."""
 log.info("Running in explore mode")
 assert self.claude is not None, "ClaudeRunner not initialized"
 result = await self.claude.run_explore_mode
 if not result.get("success"):
 error = result.get("error", "Unknown error")
 log.error("Explore failed", error=error)
 await self.callback.report_error(error, "execution")
 return 1
 log.info("Explore mode completed successfully")
 return 0
 async def _run_repo_summary_mode(self, log: BoundLogger) -> int:
 """Run in repo summary mode — plan permission, sanitize output, new callback."""
 log.info("Running in repo summary mode")
 assert self.claude is not None, "ClaudeRunner not initialized"
 result = await self.claude.run_repo_summary_mode
 if not result.get("success"):
 error_msg = result.get("error", "Unknown error")
 log.error("repo_summary_failed", error=error_msg)
 await self.callback.report_failed(error_msg)
 return 1
 raw_output = result.get("output", "")
 sanitized = _sanitize_summary(raw_output)[:2000]
 await self.callback.report_completed(
 output={"text": sanitized, "task_type": "repo_summary"},
 result_type="text",
 )
 log.info("repo_summary_completed", output_length=len(sanitized))
 return 0
 async def _run_execute_mode(self, log, branch_name: str) -> int:
 """Run in execute mode to implement changes.
 根据 task_type 分流:
 - coding_commit (Phase): 仅 amend commit message + push
 - coding (Phase / 默认): AI coding + commit(临时 msg) + push + 回传 suggested_commit_message
 """
 # Phase: coding_commit 模式 (per )
 if self.config.task_type == "coding_commit":
 return await self._run_commit_mode(log, branch_name)
 # === Phase / 默认 coding 流程 ===
 log.info("Running in execute mode")
 assert self.claude is not None, "ClaudeRunner not initialized"
 plan = await self.claude.get_session_summary
 result = await self.claude.run_execute_mode(plan)
 if not result.get("success"):
 error = result.get("error", "Unknown error")
 log.error("Execution failed", error=error)
 await self.callback.report_error(error, "execution")
 return 1
 # 使用临时 commit message 执行 commit (per: Phase 必须 commit+push 以保留工作成果)
 # Open Question 2 解决方案: Phase 使用临时 msg commit+push，Phase amend msg + force push
 temp_commit_message = (
 f"feat: {self.config.task_title}\n\n"
 f"{self.config.task_description}\n\n"
 f"Task ID: {self.config.task_id}\n"
 f"Implemented by Friday AI Agent"
 )
 commit_sha = await self.git_ops.commit_changes(temp_commit_message)
 if not commit_sha:
 log.warning("No changes to commit")
 await self.callback.report_status(
 status="no_changes",
 message="No code changes were made",
 )
 return 0
 # Push branch with retry
 try:
 await self.git_ops.push_branch_with_retry(branch_name)
 modified_files = await self.git_ops.get_modified_files
 await self.callback.report_push_complete(
 branch_name=branch_name,
 commit_sha=commit_sha,
 modified_files=modified_files,
 )
 except GitCommandError as e:
 log.error("Push failed after retries", error=str(e))
 await self.callback.report_error(str(e), "push")
 return 1
 diff_summary = await self.git_ops.get_diff_summary
 # === Phase 新增: 生成 AI suggested commit message 并回传 (per ) ===
 suggested_commit_message = self._generate_suggested_commit_message(
 diff_summary=diff_summary,
 task_title=self.config.task_title,
 task_description=self.config.task_description,
 )
 # 回传 suggested_commit_message 到 SubAgentSession.last_output (per )
 await self.callback.report_suggested_commit_message(suggested_commit_message)
 log.info(
 "suggested_commit_message_sent",
 msg_preview=suggested_commit_message[:80],
 )
 # === End Phase 新增 ===
 # Report completion
 await self.callback.report_execution_complete(
 branch_name=branch_name,
 commit_sha=commit_sha,
 diff_summary=diff_summary,
 )
 log.info("Execute mode completed successfully", commit=commit_sha[:8])
 return 0
 def _generate_suggested_commit_message(
 self,
 diff_summary: str,
 task_title: str,
 task_description: str,
 ) -> str:
 """基于 diff 和任务信息生成 AI 建议的 commit message。
 使用简单的模板方式生成，后续可替换为 AI 模型调用生成更智能的 commit message。
 """
 title_line = f"feat: {task_title}" if task_title else "feat: implement changes"
 body_parts: list[str] =
 if task_description:
 body_parts.append(task_description)
 if diff_summary:
 body_parts.append(f"\nChanges:\n{diff_summary[:500]}")
 body = "\n".join(body_parts) if body_parts else ""
 return f"{title_line}\n\n{body}".strip if body else title_line
 async def _run_commit_mode(self, log: BoundLogger, branch_name: str) -> int:
 """Phase: 使用用户确认的 commit message 执行 git commit --amend + push。
 Phase 已完成 coding + commit(临时 message) + push。
 Phase checkout 分支后执行 amend commit message 并 force push。
 Per /。
 """
 commit_message = self.config.commit_message
 if not commit_message:
 log.error("commit_mode_missing_message", task_id=self.config.task_id)
 await self.callback.report_error("缺少 commit message", "commit")
 return 1
 log.info("commit_mode_start", task_id=self.config.task_id, branch=branch_name)
 # amend 最近一次 commit 的 message（使用 asyncio.create_subprocess_exec 直接执行 git 命令）
 # GitOperations 没有 run_command 方法，直接使用 subprocess
 workspace = self.git_ops.get_workspace_path
 try:
 proc = await asyncio.create_subprocess_exec(
 "git", "commit", "--amend", "-m", commit_message,
 cwd=str(workspace),
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 stdout, stderr = await asyncio.wait_for(proc.communicate, timeout=60)
 if proc.returncode != 0:
 error_msg = stderr.decode.strip if stderr else "unknown error"
 raise RuntimeError(f"git commit --amend failed: {error_msg}")
 log.info("commit_amended", result=stdout.decode[:200] if stdout else "")
 except Exception as e:
 log.error("commit_amend_failed", error=str(e))
 await self.callback.report_error(f"commit amend 失败: {e}", "commit")
 return 1
 # 获取新的 commit SHA
 try:
 proc = await asyncio.create_subprocess_exec(
 "git", "rev-parse", "HEAD",
 cwd=str(workspace),
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 stdout, stderr = await asyncio.wait_for(proc.communicate, timeout=10)
 commit_sha = stdout.decode.strip if stdout else ""
 except Exception:
 commit_sha = ""
 # force push (--force-with-lease 安全 force push, per T-)
 try:
 proc = await asyncio.create_subprocess_exec(
 "git", "push", "--force-with-lease", "origin", branch_name,
 cwd=str(workspace),
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 stdout, stderr = await asyncio.wait_for(
 proc.communicate, timeout=self.config.git_timeout
 )
 if proc.returncode != 0:
 error_msg = stderr.decode.strip if stderr else "unknown error"
 raise RuntimeError(f"git push --force-with-lease failed: {error_msg}")
 except Exception as e:
 log.error("push_failed", error=str(e))
 await self.callback.report_error(f"push 失败: {e}", "push")
 return 1
 modified_files = await self.git_ops.get_modified_files
 await self.callback.report_push_complete(
 branch_name=branch_name,
 commit_sha=commit_sha,
 modified_files=modified_files,
 )
 diff_summary = await self.git_ops.get_diff_summary
 await self.callback.report_execution_complete(
 branch_name=branch_name,
 commit_sha=commit_sha,
 diff_summary=diff_summary,
 )
 log.info("commit_mode_complete", commit_sha=commit_sha[:8] if commit_sha else "")
 return 0
async def main -> int:
 """Main entry point for container mode."""
 logger.info("Container mode main starting")
 try:
 config = TaskConfig
 logger.info(
 "TaskConfig loaded successfully",
 task_id=config.task_id,
 mode=config.task_mode,
 )
 except Exception:
 logger.exception("Failed to load configuration")
 return 1
 runner = TaskRunner(config)
 return await runner.run
def _sanitize_summary(text: str) -> str:
 """脱敏 — 移除凭据、API key、邮箱等敏感信息。"""
 import re
 # Email 地址
 text = re.sub(r"[a-zA-._%+-]+@[a-zA-.-]+\.[a-zA-Z]{2,}", "[EMAIL]", text)
 # Bearer token
 text = re.sub(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", "Bearer [REDACTED]", text)
 # API key 前缀 (ghp_, glpat-, sk-, xoxb-, xoxp-)
 text = re.sub(r"(ghp_|glpat-|sk-|xoxb-|xoxp-)[A-Za-z0-9_\-]{10,}", r"\1[REDACTED]", text)
 return text
if __name__ == "__main__":
 exit_code = asyncio.run(main)
 sys.exit(exit_code)
