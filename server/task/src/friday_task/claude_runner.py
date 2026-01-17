"""Claude Agent SDK runner for task execution.
使用 claude-agent-sdk Python SDK 来执行 AI 开发任务，
替代原来的 Claude Code CLI 方式。
"""
import json
import os
from pathlib import Path
from typing import Literal
import structlog
from claude_agent_sdk import (
 AssistantMessage,
 ClaudeAgentOptions,
 ResultMessage,
 TextBlock,
 query,
)
from .config import TaskConfig
logger = structlog.get_logger
# SDK 支持的权限模式
PermissionModeType = Literal["default", "acceptEdits", "plan", "bypassPermissions"]
class ClaudeRunner:
 """Run Claude Agent SDK for AI-powered development."""
 def __init__(self, config: TaskConfig, workspace: Path):
 """Initialize Claude runner with config and workspace path."""
 self.config = config
 self.workspace = workspace
 self.session_file = Path(config.session_dir) / f"{config.task_id}.json"
 async def run_plan_mode(self) -> dict:
 """Run Claude Agent in plan mode to generate implementation plan."""
 log = logger.bind(task_id=self.config.task_id, mode="plan")
 log.info("Starting plan mode execution with claude-agent-sdk")
 prompt = self._build_plan_prompt
 result = await self._execute_claude(
 prompt=prompt,
 permission_mode="plan", # 只读模式，只能读取文件
 )
 log.info("Plan mode completed", success=result.get("success", False))
 return result
 async def run_execute_mode(self, plan: str | None = None) -> dict:
 """Run Claude Agent in execute mode to implement changes."""
 log = logger.bind(task_id=self.config.task_id, mode="execute")
 log.info("Starting execute mode execution with claude-agent-sdk")
 prompt = self._build_execute_prompt(plan)
 result = await self._execute_claude(
 prompt=prompt,
 permission_mode="acceptEdits", # 自动接受编辑
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
 permission_mode: PermissionModeType = "acceptEdits",
 ) -> dict:
 """Execute Claude Agent SDK with the given prompt."""
 log = logger.bind(task_id=self.config.task_id)
 try:
 # 设置环境变量
 if self.config.claude_api_key:
 os.environ["ANTHROPIC_API_KEY"] = self.config.claude_api_key
 if self.config.claude_base_url:
 os.environ["ANTHROPIC_BASE_URL"] = self.config.claude_base_url
 # 构建 Claude Agent 选项
 options = ClaudeAgentOptions(
 system_prompt=self._get_system_prompt,
 permission_mode=permission_mode,
 cwd=str(self.workspace),
 setting_sources=["project"], # 加载项目级 developer-notes.md
 )
 log.info(
 "Executing Claude Agent SDK",
 permission_mode=permission_mode,
 workspace=str(self.workspace),
 )
 # 收集所有消息
 messages =
 final_output = ""
 session_id = None
 total_cost = None
 async for message in query(prompt=prompt, options=options):
 messages.append(message)
 log.debug("Received message", message_type=type(message).__name__)
 # 处理 AssistantMessage - 获取文本输出
 if isinstance(message, AssistantMessage):
 for block in message.content:
 if isinstance(block, TextBlock):
 final_output += block.text
 # 处理 ResultMessage - 获取会话信息
 if isinstance(message, ResultMessage):
 session_id = message.session_id
 total_cost = message.total_cost_usd
 if message.result:
 final_output = message.result
 # 保存会话
 await self._save_session(
 {
 "output": final_output,
 "messages": len(messages),
 "session_id": session_id,
 }
 )
 return {
 "success": True,
 "output": final_output,
 "message_count": len(messages),
 "session_id": session_id,
 "cost": total_cost,
 }
 except Exception as e:
 log.exception("Claude Agent SDK execution failed")
 return {
 "success": False,
 "error": str(e),
 }
 def _get_system_prompt(self) -> str:
 """Get the system prompt for Claude Agent."""
 return """你是一个资深的全栈开发工程师，精通各种编程语言和框架，能够：
1. 理解复杂的代码库结构
2. 编写高质量、可维护的代码
3. 遵循最佳实践和设计模式
4. 考虑边界情况和错误处理
请根据任务需求进行代码分析和实现。"""
 async def _save_session(self, result: dict) -> None:
 """Save session data for potential resume."""
 session_data = {
 "task_id": self.config.task_id,
 "session_id": result.get("session_id"),
 "last_output": result.get("output", "")[:1000], # 截断存储
 "message_count": result.get("message_count", 0),
 }
 self.session_file.parent.mkdir(parents=True, exist_ok=True)
 self.session_file.write_text(
 json.dumps(session_data, indent=2, ensure_ascii=False)
 )
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
