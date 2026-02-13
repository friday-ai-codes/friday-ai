"""Claude Agent SDK runner for task execution.
使用 claude-agent-sdk Python SDK 来执行 AI 开发任务。
权限模式：
- Plan 模式：使用 permission_mode="plan"（只读，不能修改文件）
- Execute 模式：使用 permission_mode="bypassPermissions"（跳过所有权限检查，包括 Bash 命令确认）
bypassPermissions 在 Docker 容器隔离环境中是安全的，可以支持无人值守执行。
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal
import structlog
from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query
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
 self.mapping_file = Path(config.session_dir) / "mapping.json"
 async def run_plan_mode(self) -> dict:
 """Run Claude Agent in plan mode to generate implementation plan.
 使用 plan 权限模式，只能读取文件，不能修改。
 """
 log = logger.bind(task_id=self.config.task_id, mode="plan")
 log.info("Starting plan mode execution with claude-agent-sdk")
 prompt = self._build_plan_prompt
 result = await self._execute_claude(
 prompt=prompt,
 permission_mode="plan", # 只读模式
 )
 log.info("Plan mode completed", success=result.get("success", False))
 return result
 async def run_execute_mode(self, plan: str | None = None) -> dict:
 """Run Claude Agent in execute mode to implement changes.
 使用 bypassPermissions 权限模式，跳过所有权限检查，
 包括文件编辑和 Bash 命令确认，支持无人值守执行。
 """
 log = logger.bind(task_id=self.config.task_id, mode="execute")
 log.info("Starting execute mode execution with claude-agent-sdk")
 prompt = self._build_execute_prompt(plan)
 result = await self._execute_claude(
 prompt=prompt,
 permission_mode="bypassPermissions", # 跳过所有权限检查，支持无人值守执行
 )
 log.info("Execute mode completed", success=result.get("success", False))
 return result
 def _build_plan_prompt(self) -> str:
 """Build the prompt for plan mode."""
 return f"""You are an AI development agent working on a coding task.
## Task Information
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
 permission_mode: PermissionModeType = "bypassPermissions",
 ) -> dict:
 """Execute Claude Agent SDK with the given prompt."""
 log = logger.bind(task_id=self.config.task_id)
 try:
 # 设置环境变量
 if self.config.claude_api_key:
 os.environ["ANTHROPIC_API_KEY"] = self.config.claude_api_key
 log.debug("ANTHROPIC_API_KEY set", key_length=len(self.config.claude_api_key))
 else:
 log.warning("No ANTHROPIC_API_KEY configured!")
 if self.config.claude_base_url:
 os.environ["ANTHROPIC_BASE_URL"] = self.config.claude_base_url
 log.debug("ANTHROPIC_BASE_URL set", url=self.config.claude_base_url)
 # 检查工作目录
 workspace_path = Path(self.workspace)
 if not workspace_path.exists:
 log.error("Workspace directory does not exist", path=str(self.workspace))
 else:
 file_count = len(list(workspace_path.iterdir))
 log.debug(
 "Workspace ready",
 path=str(self.workspace),
 files=file_count,
 )
 # 构建 Claude Agent 选项
 options = ClaudeAgentOptions(
 system_prompt=self._get_system_prompt,
 permission_mode=permission_mode,
 cwd=str(self.workspace),
 model="opus",
 setting_sources=["project"], # 加载项目级 developer-notes.md
 )
 log.info(
 "Executing Claude Agent SDK",
 permission_mode=permission_mode,
 workspace=str(self.workspace),
 has_api_key=bool(self.config.claude_api_key),
 has_base_url=bool(self.config.claude_base_url),
 )
 # 收集所有消息
 messages =
 text_outputs = # 收集所有 AssistantMessage 的文本
 session_id = None
 total_cost = None
 result_output = None # ResultMessage 的 result 字段
 async for message in query(prompt=prompt, options=options):
 messages.append(message)
 log.debug("Received message", message_type=type(message).__name__)
 # 处理 AssistantMessage - 获取文本输出
 if isinstance(message, AssistantMessage):
 for block in message.content:
 if isinstance(block, TextBlock):
 text_outputs.append(block.text)
 log.debug("Collected text block", text_length=len(block.text))
 # 处理 ResultMessage - 获取会话信息和错误状态
 if isinstance(message, ResultMessage):
 session_id = message.session_id
 total_cost = message.total_cost_usd
 if message.result:
 result_output = message.result
 log.debug("Received result", result_length=len(message.result))
 # 检查是否有 SDK 执行错误
 # 如果没有收到任何 AssistantMessage，且 usage 显示 0 tokens，说明 API 调用失败
 result_message = next((m for m in messages if isinstance(m, ResultMessage)), None)
 if result_message:
 result_subtype = getattr(result_message, "subtype", None)
 result_usage = getattr(result_message, "usage", {})
 input_tokens = result_usage.get("input_tokens", 0) if result_usage else 0
 output_tokens = result_usage.get("output_tokens", 0) if result_usage else 0
 # 检测执行错误：subtype 是 error_during_execution 或者没有产生任何 tokens
 if result_subtype == "error_during_execution" or (
 input_tokens == 0 and output_tokens == 0
 ):
 error_msg = f"Claude SDK execution failed: subtype={result_subtype}, input_tokens={input_tokens}, output_tokens={output_tokens}"
 log.error(
 "Claude SDK execution failed",
 subtype=result_subtype,
 input_tokens=input_tokens,
 output_tokens=output_tokens,
 session_id=session_id,
 )
 # 保存会话信息（用于调试）
 await self._save_session(
 {
 "output": "",
 "messages": len(messages),
 "session_id": session_id,
 "cost": total_cost,
 "error": error_msg,
 }
 )
 return {
 "success": False,
 "error": error_msg,
 "message_count": len(messages),
 "session_id": session_id,
 "cost": total_cost,
 "details": {
 "subtype": result_subtype,
 "input_tokens": input_tokens,
 "output_tokens": output_tokens,
 },
 }
 # 确定最终输出：优先使用 ResultMessage.result，否则合并所有 TextBlock
 if result_output:
 final_output = result_output
 else:
 final_output = "\n".join(text_outputs)
 # 如果没有任何输出，也视为失败
 if not final_output.strip:
 error_msg = "Claude SDK returned empty response"
 log.error(error_msg, session_id=session_id)
 return {
 "success": False,
 "error": error_msg,
 "message_count": len(messages),
 "session_id": session_id,
 "cost": total_cost,
 }
 log.info(
 "Claude execution completed",
 text_blocks=len(text_outputs),
 has_result=bool(result_output),
 output_length=len(final_output),
 )
 # 保存会话
 await self._save_session(
 {
 "output": final_output,
 "messages": len(messages),
 "session_id": session_id,
 "cost": total_cost,
 }
 )
 # Write token usage to shared volume for main agent collection (Phase)
 if result_message:
 result_usage = getattr(result_message, "usage", {}) or {}
 usage_data = {
 "input_tokens": result_usage.get("input_tokens", 0),
 "output_tokens": result_usage.get("output_tokens", 0),
 "cache_read_tokens": result_usage.get("cache_read_input_tokens", 0),
 "cache_write_tokens": result_usage.get("cache_creation_input_tokens", 0),
 "total_cost_usd": float(total_cost) if total_cost else 0.0,
 "model": "claude-opus-4-6",
 "session_id": session_id,
 }
 await self._write_usage_data(usage_data)
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
 """Save session data for potential resume.
 保存任务会话并更新 session_id -> task_id 映射。
 """
 session_id = result.get("session_id")
 output = result.get("output", "")
 # 保存任务会话文件
 session_data = {
 "task_id": self.config.task_id,
 "session_id": session_id,
 "mode": self.config.task_mode,
 "description": self.config.task_description,
 "git_url": self.config.git_repo_url,
 "git_branch": self.config.git_branch,
 "last_output": output[:2000], # 截断存储
 "message_count": result.get("messages", 0),
 "cost": result.get("cost"),
 "created_at": datetime.utcnow.isoformat,
 }
 self.session_file.parent.mkdir(parents=True, exist_ok=True)
 self.session_file.write_text(json.dumps(session_data, indent=2, ensure_ascii=False))
 logger.debug("Session saved", session_file=str(self.session_file))
 # 更新 session_id -> task_id 映射
 if session_id:
 await self._update_session_mapping(session_id, output[:200])
 async def _update_session_mapping(self, session_id: str, output_preview: str) -> None:
 """Update the session mapping file."""
 mappings = {}
 if self.mapping_file.exists:
 try:
 mappings = json.loads(self.mapping_file.read_text)
 except json.JSONDecodeError:
 logger.warning("Failed to read mapping file, creating new")
 mappings[session_id] = {
 "task_id": self.config.task_id,
 "created_at": datetime.utcnow.isoformat,
 "last_output_preview": output_preview,
 }
 self.mapping_file.write_text(json.dumps(mappings, indent=2, ensure_ascii=False))
 logger.debug(
 "Session mapping updated",
 session_id=session_id,
 task_id=self.config.task_id,
 )
 async def _write_usage_data(self, usage_data: dict) -> None:
 """Write token usage data to shared volume.
 Main agent will collect this data and store in TokenUsage model.
 Data is written to /workspace/.friday/usage.json following existing protocol.
 """
 friday_dir = Path(self.workspace) / ".friday"
 friday_dir.mkdir(exist_ok=True)
 usage_file = friday_dir / "usage.json"
 usage_file.write_text(json.dumps(usage_data, indent=2))
 logger.info(
 "Token usage written",
 input_tokens=usage_data["input_tokens"],
 output_tokens=usage_data["output_tokens"],
 cost=usage_data["total_cost_usd"],
 )
 async def get_session_summary(self) -> str | None:
 """Get summary of previous session if exists."""
 if not self.session_file.exists:
 return None
 try:
 data = json.loads(self.session_file.read_text)
 return data.get("last_output")
 except Exception:
 return None
 @classmethod
 async def get_session_by_id(cls, session_id: str, session_dir: str) -> dict | None:
 """Get session info by session ID.
 通过 session_id 查找对应的任务信息。
 """
 mapping_file = Path(session_dir) / "mapping.json"
 if not mapping_file.exists:
 return None
 try:
 mappings = json.loads(mapping_file.read_text)
 if session_id not in mappings:
 return None
 session_info = mappings[session_id]
 task_id = session_info["task_id"]
 # 加载完整的任务会话
 task_file = Path(session_dir) / f"{task_id}.json"
 if task_file.exists:
 task_data = json.loads(task_file.read_text)
 return {**session_info, **task_data}
 return session_info
 except Exception as e:
 logger.error("Failed to get session", session_id=session_id, error=str(e))
 return None
