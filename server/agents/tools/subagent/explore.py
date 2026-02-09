"""Explore repository tool for SubAgent.
Allows the main Agent to delegate repository exploration to Claude Code SubAgent.
"""
import structlog
from agents.models import AgentSession
from agents.tools.base import ToolResult, tool
from agents.tools.subagent.context import build_subagent_context
from subagent.client import SubAgentClient, SubAgentRequest
from subagent.models import SubAgentSession, generate_subagent_session_id
logger = structlog.get_logger(__name__)
@tool(
 name="explore_repository",
 description="探索仓库结构和代码。委派给 Claude Code SubAgent 进行深度分析，返回仓库的目录结构、主要模块、技术栈等信息。",
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
 "description": "要探索的分支名称",
 },
 "session_id": {
 "type": "string",
 "description": "主 Agent 会话 ID（由系统自动提供）",
 },
 "focus_areas": {
 "type": "array",
 "items": {"type": "string"},
 "description": "可选的关注领域列表，如 ['authentication', 'api', 'database']",
 },
 },
 "required": ["repo_url", "branch", "session_id"],
 },
 requires_suspension=True,
)
async def explore_repository(
 repo_url: str,
 branch: str,
 session_id: str,
 focus_areas: list[str] | None = None,
) -> ToolResult:
 """Explore repository structure via SubAgent.
 Submits an exploration task to Claude Code SubAgent and suspends
 the main Agent until the SubAgent completes.
 Args:
 repo_url: Git repository URL
 branch: Branch name to explore
 session_id: Main Agent session ID
 focus_areas: Optional list of areas to focus on
 Returns:
 ToolResult with task_id and suspension metadata
 """
 log = logger.bind(
 session_id=session_id,
 repo_url=repo_url,
 branch=branch,
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
 # Generate SubAgent session ID (deterministic for reuse)
 subagent_session_id = generate_subagent_session_id(
 main_session_id=session_id,
 repo_url=repo_url,
 task_type="explore",
 )
 # Build context for SubAgent
 context = await build_subagent_context(main_session, focus_areas)
 # Build prompt for exploration
 prompt = f"""探索仓库 {repo_url} (分支: {branch})
请分析并返回：
1. 项目结构概览（目录组织、主要模块）
2. 技术栈识别（语言、框架、依赖）
3. 入口点和核心文件
4. 代码风格和约定
"""
 if focus_areas:
 prompt += f"\n重点关注以下领域: {', '.join(focus_areas)}"
 # Create SubAgent request
 request = SubAgentRequest(
 session_id=subagent_session_id,
 task_type="explore",
 repo_url=repo_url,
 branch=branch,
 main_session_id=session_id,
 prompt=prompt,
 context=context,
 )
 # Submit task to SubAgent
 try:
 client = SubAgentClient
 task_id = await client.submit_task(request)
 log.info("subagent_task_submitted", task_id=task_id)
 except Exception as e:
 log.error("subagent_submit_failed", error=str(e))
 return ToolResult(
 success=False,
 error=f"提交 SubAgent 任务失败: {e}",
 )
 # Create or update SubAgentSession record
 subagent_session, created = await SubAgentSession.objects.aupdate_or_create(
 session_id=subagent_session_id,
 defaults={
 "main_session": main_session,
 "repo_url": repo_url,
 "task_type": SubAgentSession.TaskType.EXPLORE,
 "status": SubAgentSession.Status.RUNNING,
 "current_task_id": task_id,
 },
 )
 log.info(
 "subagent_session_updated",
 subagent_session_id=subagent_session_id,
 created=created,
 )
 # Store mapping in main session temp_data
 temp_data = main_session.temp_data or {}
 subagent_sessions = temp_data.setdefault("subagent_sessions", {})
 subagent_sessions[subagent_session_id] = {
 "task_id": task_id,
 "task_type": "explore",
 "status": "running",
 }
 main_session.temp_data = temp_data
 await main_session.asave(update_fields=["temp_data"])
 return ToolResult(
 success=True,
 output={
 "task_id": task_id,
 "subagent_session_id": subagent_session_id,
 "status": "running",
 "message": "已提交仓库探索任务，等待 SubAgent 完成分析",
 },
 metadata={
 "suspension": True,
 "suspension_reason": "subagent_task",
 "subagent_session_id": subagent_session_id,
 "task_id": task_id,
 },
 )
