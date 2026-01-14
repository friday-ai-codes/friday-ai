"""Claude Code CLI runner for task execution."""
import asyncio
import json
import os
from pathlib import Path
import structlog
from .config import TaskConfig
logger = structlog.get_logger
class ClaudeRunner:
 """Run Claude Code CLI for AI-powered development."""
 def __init__(self, config: TaskConfig, workspace: Path):
 """Initialize Claude runner with config and workspace path."""
 self.config = config
 self.workspace = workspace
 self.session_file = Path(config.session_dir) / f"{config.task_id}.json"
 async def run_plan_mode(self) -> dict:
 """Run Claude Code in plan mode to generate implementation plan."""
 log = logger.bind(task_id=self.config.task_id, mode="plan")
 log.info("Starting plan mode execution")
 prompt = self._build_plan_prompt
 result = await self._execute_claude(
 prompt=prompt,
 allowed_tools=[
 "Read",
 "Glob",
 "Grep",
 "LS",
 ], # Read-only tools for planning
 )
 log.info("Plan mode completed", success=result.get("success", False))
 return result
 async def run_execute_mode(self, plan: str | None = None) -> dict:
 """Run Claude Code in execute mode to implement changes."""
 log = logger.bind(task_id=self.config.task_id, mode="execute")
 log.info("Starting execute mode execution")
 prompt = self._build_execute_prompt(plan)
 result = await self._execute_claude(
 prompt=prompt,
 allowed_tools=None, # All tools allowed
 )
 log.info("Execute mode completed", success=result.get("success", False))
 return result
 def _build_plan_prompt(self) -> str:
 """Build the prompt for plan mode."""
 return f"""You are an AI development agent working on a coding task.
## Task Information
- **Title**: {self.config.task_title}
- **Description**: {self.config.task_description}
## Your Goal
Analyze the codebase and create a detailed implementation plan. Do NOT make any changes yet.
## Instructions
1. Explore the codebase structure to understand the project
2. Identify relevant files that need to be modified or created
3. Create a step-by-step implementation plan with:
 - Files to modify/create
 - Specific changes needed for each file
 - Any dependencies or considerations
4. Estimate the complexity and potential risks
## Output Format
Provide your plan in a structured markdown format that can be reviewed by a human.
"""
 def _build_execute_prompt(self, plan: str | None = None) -> str:
 """Build the prompt for execute mode."""
 base_prompt = f"""You are an AI development agent implementing a coding task.
## Task Information
- **Title**: {self.config.task_title}
- **Description**: {self.config.task_description}
"""
 if plan:
 base_prompt += f"""## Approved Plan
{plan}
## Instructions
Implement the changes according to the approved plan above.
"""
 else:
 base_prompt += """## Instructions
Implement the task as described. Make necessary code changes.
"""
 base_prompt += """
## Guidelines
1. Write clean, well-documented code
2. Follow existing code style and conventions
3. Add appropriate tests if applicable
4. Commit your changes with meaningful commit messages
"""
 return base_prompt
 async def _execute_claude(
 self,
 prompt: str,
 allowed_tools: list[str] | None = None,
 ) -> dict:
 """Execute Claude Code CLI with the given prompt."""
 log = logger.bind(task_id=self.config.task_id)
 # Build command
 cmd = [
 "claude",
 "--print", # Print output to stdout
 "--output-format",
 "json", # JSON output for parsing
 ]
 # Add allowed tools restriction if specified
 if allowed_tools:
 cmd.extend(["--allowedTools", ",".join(allowed_tools)])
 # Add session resume if exists
 if self.session_file.exists:
 cmd.extend(["--resume", str(self.session_file)])
 # Add prompt
 cmd.extend(["--prompt", prompt])
 # Set environment
 env = os.environ.copy
 if self.config.claude_api_key:
 env["ANTHROPIC_API_KEY"] = self.config.claude_api_key
 log.info("Executing Claude Code CLI", command=" ".join(cmd[:5]) + "...")
 try:
 # Create process
 process = await asyncio.create_subprocess_exec(
 *cmd,
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 cwd=str(self.workspace),
 env=env,
 )
 # Wait with timeout
 stdout, stderr = await asyncio.wait_for(
 process.communicate,
 timeout=self.config.execution_timeout,
 )
 stdout_str = stdout.decode("utf-8") if stdout else ""
 stderr_str = stderr.decode("utf-8") if stderr else ""
 if process.returncode != 0:
 log.error(
 "Claude Code CLI failed",
 returncode=process.returncode,
 stderr=stderr_str,
 )
 return {
 "success": False,
 "error": stderr_str or "Unknown error",
 "returncode": process.returncode,
 }
 # Parse JSON output
 try:
 result = json.loads(stdout_str)
 except json.JSONDecodeError:
 result = {"output": stdout_str}
 # Save session for resume
 await self._save_session(result)
 return {
 "success": True,
 "output": result.get("output", stdout_str),
 "session_id": result.get("session_id"),
 "cost": result.get("cost"),
 }
 except asyncio.TimeoutError:
 log.error(
 "Claude Code CLI timed out", timeout=self.config.execution_timeout
 )
 if process:
 process.kill
 return {
 "success": False,
 "error": f"Execution timed out after {self.config.execution_timeout}s",
 }
 except Exception as e:
 log.exception("Claude Code CLI execution failed")
 return {
 "success": False,
 "error": str(e),
 }
 async def _save_session(self, result: dict) -> None:
 """Save session data for potential resume."""
 session_data = {
 "task_id": self.config.task_id,
 "session_id": result.get("session_id"),
 "last_output": result.get("output", "")[:1000], # Truncate for storage
 }
 self.session_file.parent.mkdir(parents=True, exist_ok=True)
 self.session_file.write_text(json.dumps(session_data, indent=2))
 logger.debug("Session saved", session_file=str(self.session_file))
 async def get_session_summary(self) -> str | None:
 """Get summary of previous session if exists."""
 if not self.session_file.exists:
 return None
 try:
 data = json.loads(self.session_file.read_text)
 return data.get("last_output")
 except Exception:
 return None
