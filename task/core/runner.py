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
 async def _check_workspace_clean(self, log) -> bool:
 """检查工作区是否干净，返回 True 表示干净。
 explore 任务结束时自动调用。
 非 clean（有未提交修改或未跟踪文件）则标记任务失败。
 """
 if not self.git_ops.repo:
 return True # 没有 repo 无法检查
 try:
 # --porcelain 输出机器可读格式，空输出 = 干净
 status_output = self.git_ops.repo.git.status("--porcelain")
 if status_output.strip:
 log.error(
 "workspace_not_clean",
 git_status=status_output,
 task_id=self.config.task_id,
 )
 await self.callback.report_error(
 f"explore 模式工作区不干净:\n{status_output}",
 "workspace_check",
 )
 return False
 log.info("workspace_clean", task_id=self.config.task_id)
 return True
 except Exception as e:
 log.error(
 "workspace_check_failed",
 error=str(e),
 task_id=self.config.task_id,
 )
 return False
 async def _run_explore_mode(self, log) -> int:
 """Run in explore mode for deep code analysis (no commits)."""
 log.info("Running in explore mode")
 explore_exit_code = 0
 try:
 assert self.claude is not None, "ClaudeRunner not initialized"
 result = await self.claude.run_explore_mode
 if not result.get("success"):
 error = result.get("error", "Unknown error")
 log.error("Explore failed", error=error)
 await self.callback.report_error(error, "execution")
 explore_exit_code = 1
 except Exception as e:
 log.exception("Explore mode execution error")
 await self.callback.report_error(str(e), "execution")
 explore_exit_code = 1
 finally:
 # 工作区干净度校验
 # 无论 explore 成功或失败，都检查工作区状态
 workspace_clean = await self._check_workspace_clean(log)
 if not workspace_clean:
 log.error(
 "explore_workspace_dirty",
 task_id=self.config.task_id,
 )
 explore_exit_code = 1
 if explore_exit_code == 0:
 log.info("Explore mode completed successfully")
 return explore_exit_code
 async def _run_execute_mode(self, log, branch_name: str) -> int:
 """Run in execute mode to implement changes."""
 log.info("Running in execute mode")
 assert self.claude is not None, "ClaudeRunner not initialized"
 plan = await self.claude.get_session_summary
 result = await self.claude.run_execute_mode(plan)
 if not result.get("success"):
 error = result.get("error", "Unknown error")
 log.error("Execution failed", error=error)
 await self.callback.report_error(error, "execution")
 return 1
 # Commit changes
 commit_message = (
 f"feat: {self.config.task_title}\n\n"
 f"{self.config.task_description}\n\n"
 f"Task ID: {self.config.task_id}\n"
 f"Implemented by Friday AI Agent"
 )
 commit_sha = await self.git_ops.commit_changes(commit_message)
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
 # Get modified files for MR description
 modified_files = await self.git_ops.get_modified_files
 # Report push complete - server will create MR
 await self.callback.report_push_complete(
 branch_name=branch_name,
 commit_sha=commit_sha,
 modified_files=modified_files,
 )
 except GitCommandError as e:
 # Push failed after 3 retries
 log.error("Push failed after retries", error=str(e))
 await self.callback.report_error(str(e), "push")
 return 1
 diff_summary = await self.git_ops.get_diff_summary
 # Report completion
 await self.callback.report_execution_complete(
 branch_name=branch_name,
 commit_sha=commit_sha,
 diff_summary=diff_summary,
 )
 log.info("Execute mode completed successfully", commit=commit_sha[:8])
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
if __name__ == "__main__":
 exit_code = asyncio.run(main)
 sys.exit(exit_code)
