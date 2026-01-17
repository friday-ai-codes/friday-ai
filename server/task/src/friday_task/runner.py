"""Task Runner - Main entry point for task container execution."""
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
 log.info("Task runner starting")
 try:
 # Report started
 await self.callback.report_started
 # Set up Git repository
 log.info("Setting up Git repository")
 await self.git_ops.setup
 # Create feature branch
 branch_name = await self.git_ops.create_feature_branch(
 f"task-{self.config.task_id}"
 )
 await self.callback.report_git_ready(branch_name)
 # Initialize Claude runner
 self.claude = ClaudeRunner(self.config, self.git_ops.workspace)
 # Execute based on mode
 if self.config.task_mode == "plan":
 return await self._run_plan_mode(log, branch_name)
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
 """Run in execute mode to implement changes."""
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
 commit_message = f"feat: {self.config.task_title}\n\nTask ID: {self.config.task_id}\nImplemented by Friday AI Agent"
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
 """Main entry point."""
 try:
 config = TaskConfig
 except Exception as e:
 logger.error("Failed to load configuration", error=str(e))
 return 1
 runner = TaskRunner(config)
 return await runner.run
if __name__ == "__main__":
 exit_code = asyncio.run(main)
 sys.exit(exit_code)
