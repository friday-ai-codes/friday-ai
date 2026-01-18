"""Task Runner - Main entry point for task container execution.
这个模块是容器模式的入口点，通过环境变量读取配置。
CLI 模式使用 cli.py 作为入口点。
执行流程：
1. 读取环境变量配置
2. 设置 Git 仓库
3. 根据模式执行任务（plan 或 execute）
4. 报告结果（如果配置了回调 URL）
"""
import asyncio
import sys
import structlog
from .callback import CallbackClient
from .claude_runner import ClaudeRunner
from .config import TaskConfig
from .git_ops import GitOperations
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
 print("[DEBUG] Reporting task started", flush=True)
 log.info("Reporting task started to callback (if configured)")
 await self.callback.report_started
 print("[DEBUG] Callback report_started completed", flush=True)
 log.info("Callback report_started completed")
 # Set up Git repository
 print("[DEBUG] Setting up Git repository", flush=True)
 log.info("Setting up Git repository")
 await self.git_ops.setup
 print("[DEBUG] Git repository setup completed", flush=True)
 log.info("Git repository setup completed successfully")
 # Create feature branch only in execute mode
 branch_name = self.config.git_branch
 if self.config.task_mode == "execute":
 print("[DEBUG] Creating feature branch (execute mode)", flush=True)
 # 使用指定的分支名或自动生成
 feature_branch = self.config.git_new_branch or f"friday/task-{self.config.task_id}"
 branch_name = await self.git_ops.create_feature_branch(feature_branch)
 await self.callback.report_git_ready(branch_name)
 log.info("Created feature branch", branch=branch_name)
 else:
 print("[DEBUG] Plan mode - staying on current branch", flush=True)
 # Plan 模式不创建分支，直接在目标分支上分析
 log.info("Plan mode - staying on branch", branch=branch_name)
 # Initialize Claude runner
 print(
 f"[DEBUG] Initializing Claude runner, workspace={self.git_ops.get_workspace_path}",
 flush=True,
 )
 self.claude = ClaudeRunner(self.config, self.git_ops.get_workspace_path)
 print("[DEBUG] Claude runner initialized", flush=True)
 # Execute based on mode
 if self.config.task_mode == "plan":
 print("[DEBUG] Starting plan mode execution", flush=True)
 return await self._run_plan_mode(log, branch_name)
 else:
 print("[DEBUG] Starting execute mode execution", flush=True)
 return await self._run_execute_mode(log, branch_name)
 except Exception as e:
 log.exception("Task execution failed")
 await self.callback.report_error(str(e), "execution")
 return 1
 finally:
 self.git_ops.cleanup
 log.info("Task runner finished")
 async def _run_plan_mode(self, log, branch_name: str) -> int:
 """Run in plan mode to generate implementation plan.
 Plan 模式是只读的，不创建新分支，不修改代码。
 """
 log.info("Running in plan mode")
 # Execute Claude in plan mode
 result = await self.claude.run_plan_mode
 if not result.get("success"):
 error = result.get("error", "Unknown error")
 log.error("Plan generation failed", error=error)
 await self.callback.report_error(error, "planning")
 return 1
 plan = result.get("output", "")
 # Report plan ready for review
 await self.callback.report_plan_ready(plan)
 log.info("Plan mode completed successfully")
 return 0
 async def _run_execute_mode(self, log, branch_name: str) -> int:
 """Run in execute mode to implement changes.
 Execute 模式会创建新分支，实现代码变更，提交并推送。
 """
 log.info("Running in execute mode")
 # Check if there's an approved plan from previous session
 plan = await self.claude.get_session_summary
 # Execute Claude in execute mode
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
 # Push branch
 await self.git_ops.push_branch(branch_name)
 # Get diff summary
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
 print("[DEBUG] Container mode main starting", flush=True)
 logger.info("Container mode main starting")
 try:
 print("[DEBUG] Loading TaskConfig from environment variables", flush=True)
 logger.info("Loading TaskConfig from environment variables")
 config = TaskConfig
 print(
 f"[DEBUG] TaskConfig loaded: task_id={config.task_id}, mode={config.task_mode}",
 flush=True,
 )
 logger.info(
 "TaskConfig loaded successfully",
 task_id=config.task_id,
 project_id=config.project_id,
 mode=config.task_mode,
 git_url=config.git_repo_url,
 git_branch=config.git_branch,
 auth_type=config.git_auth_type,
 has_access_token=bool(config.git_access_token),
 access_token_length=len(config.git_access_token) if config.git_access_token else 0,
 has_ssh_key=bool(config.git_ssh_key),
 has_api_key=bool(config.claude_api_key),
 api_key_value=config.claude_api_key[:10] + "..."
 if config.claude_api_key
 else "(empty)",
 base_url=config.claude_base_url or "(not set)",
 callback_url=config.callback_url or "(not set)",
 )
 except Exception as e:
 logger.exception("Failed to load configuration")
 print(f"[ERROR] Failed to load configuration: {e}", flush=True)
 return 1
 logger.info("Creating TaskRunner instance")
 runner = TaskRunner(config)
 logger.info("TaskRunner created, starting run")
 result = await runner.run
 logger.info("TaskRunner.run completed", exit_code=result)
 return result
if __name__ == "__main__":
 exit_code = asyncio.run(main)
 sys.exit(exit_code)
