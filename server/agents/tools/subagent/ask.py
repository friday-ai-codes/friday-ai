"""Ask Claude Code tool for SubAgent.
Allows the main Agent to ask technical questions to Claude Code SubAgent.
"""
import structlog
from agents.models import AgentSession
from agents.tools.base import ToolResult, tool
from agents.tools.subagent.context import build_subagent_context
from services.container_config import TASK_TIMEOUTS
from services.container_manager import ContainerConfig, ContainerManager
from subagent.models import SubAgentSession, generate_execution_id
logger = structlog.get_logger(__name__)
@tool(
 name="ask_claude_code",
 description="向 Claude Code 提问技术问题。委派给 SubAgent 在仓库上下文中回答代码相关问题。",
 category="SUBAGENT",
 parameters={
 "type": "object",
 "properties": {
 "repo_url": {
 "type": "string",
 "description": "Git 仓库 URL",
 },
 "branch": {
 "type": "string",
 "description": "分支名称",
 },
 "question": {
 "type": "string",
 "description": "要问的技术问题",
 },
 "session_id": {
 "type": "string",
 "description": "主 Agent 会话 ID（由系统自动提供）",
 },
 "context_files": {
 "type": "array",
 "items": {"type": "string"},
 "description": "可选的相关文件路径列表，帮助 SubAgent 聚焦",
 },
 },
 "required": ["repo_url", "branch", "question", "session_id"],
 },
 requires_suspension=True,
)
async def ask_claude_code(
 repo_url: str,
 branch: str,
 question: str,
 session_id: str,
 context_files: list[str] | None = None,
) -> ToolResult:
 """Ask a technical question via SubAgent.
 Submits a question to Claude Code SubAgent with repository context
 and suspends the main Agent until the answer is ready.
 Args:
 repo_url: Git repository URL
 branch: Branch name
 question: Technical question to ask
 session_id: Main Agent session ID
 context_files: Optional list of relevant file paths
 Returns:
 ToolResult with task_id and suspension metadata
 """
 log = logger.bind(
 session_id=session_id,
 repo_url=repo_url,
 question=question[:50],
 )
 # Load main session
 try:
 main_session = await AgentSession.objects.select_related("project").aget(
 session_id=session_id
 )
 except AgentSession.DoesNotExist:
 log.error("session_not_found")
 return ToolResult(
 success=False,
 error=f"会话不存在: {session_id}",
 )
 # Generate unique execution ID
 subagent_session_id = generate_execution_id
 # Build context for SubAgent
 context = await build_subagent_context(main_session)
 if context_files:
 context["context_files"] = context_files
 # Build prompt
 prompt = f"""请回答以下技术问题：
{question}
仓库: {repo_url}
分支: {branch}
"""
 if context_files:
 prompt += f"\n相关文件: {', '.join(context_files)}"
 prompt += "\n\n请基于代码库内容给出详细、准确的回答。"
 # 使用 ContainerManager 启动容器
 try:
 manager = ContainerManager
 config = ContainerConfig(
 session_id=subagent_session_id,
 task_type="ask",
 repo_url=repo_url,
 branch=branch,
 prompt=prompt,
 main_session_id=session_id,
 timeout=TASK_TIMEOUTS.get("ask", 600),
 context=context,
 )
 container_id = await manager.start(config)
 log.info(
 "container_started",
 subagent_session_id=subagent_session_id,
 container_id=container_id[:12],
 )
 except Exception as e:
 log.error("container_start_failed", error=str(e))
 return ToolResult(
 success=False,
 error=f"容器启动失败: {e}",
 )
 # 创建 SubAgentSession 记录
 await SubAgentSession.objects.aupdate_or_create(
 session_id=subagent_session_id,
 defaults={
 "main_session": main_session,
 "repo_url": repo_url,
 "task_type": SubAgentSession.TaskType.ASK,
 "status": SubAgentSession.Status.RUNNING,
 "container_id": container_id,
 },
 )
 # Store mapping in main session temp_data
 temp_data = main_session.temp_data or {}
 subagent_sessions = temp_data.setdefault("subagent_sessions", {})
 subagent_sessions[subagent_session_id] = {
 "task_type": "ask",
 "status": "running",
 "question": question,
 }
 main_session.temp_data = temp_data
 await main_session.asave(update_fields=["temp_data"])
 return ToolResult(
 success=True,
 output={
 "subagent_session_id": subagent_session_id,
 "status": "running",
 "message": "已提交技术问题，等待 SubAgent 回答",
 },
 metadata={
 "suspension": True,
 "suspension_reason": "subagent_task",
 "subagent_session_id": subagent_session_id,
 },
 )
