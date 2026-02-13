"""Generate technical plan section tool for SubAgent.
Allows the main Agent to delegate technical plan generation to Claude Code SubAgent.
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
 name="generate_tech_plan_section",
 description="生成技术方案的特定章节。委派给 Claude Code SubAgent 分析代码库并生成实现步骤、技术选型、架构设计等内容。",
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
 "requirement": {
 "type": "string",
 "description": "需求描述，说明要实现什么功能",
 },
 "session_id": {
 "type": "string",
 "description": "主 Agent 会话 ID（由系统自动提供）",
 },
 "section_type": {
 "type": "string",
 "enum": ["implementation_steps", "tech_stack", "architecture", "api_design", "database_schema"],
 "description": "要生成的章节类型",
 },
 },
 "required": ["repo_url", "branch", "requirement", "session_id"],
 },
 requires_suspension=True,
)
async def generate_tech_plan_section(
 repo_url: str,
 branch: str,
 requirement: str,
 session_id: str,
 section_type: str | None = None,
) -> ToolResult:
 """Generate a technical plan section via SubAgent.
 Submits a plan generation task to Claude Code SubAgent and suspends
 the main Agent until the plan is ready.
 Args:
 repo_url: Git repository URL
 branch: Branch name
 requirement: Requirement description
 session_id: Main Agent session ID
 section_type: Type of section to generate (optional)
 Returns:
 ToolResult with task_id and suspension metadata
 """
 log = logger.bind(
 session_id=session_id,
 repo_url=repo_url,
 requirement=requirement[:50],
 section_type=section_type,
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
 # Map section types to descriptions
 section_descriptions = {
 "implementation_steps": "详细的实现步骤，包括任务拆分和优先级",
 "tech_stack": "技术栈选型建议，包括框架、库和工具",
 "architecture": "架构设计方案，包括组件划分和交互流程",
 "api_design": "API 接口设计，包括端点、请求/响应格式",
 "database_schema": "数据库表结构设计，包括字段和关系",
 }
 section_desc = section_descriptions.get(section_type or "", "完整技术方案")
 # Build prompt
 prompt = f"""基于以下需求，生成技术方案：
## 需求描述
{requirement}
## 仓库信息
- URL: {repo_url}
- 分支: {branch}
## 输出要求
请生成: {section_desc}
要求：
1. 分析现有代码库结构和约定
2. 确保方案与现有架构一致
3. 给出具体、可执行的建议
4. 考虑边界情况和错误处理
"""
 # 使用 ContainerManager 启动容器
 try:
 manager = ContainerManager
 config = ContainerConfig(
 session_id=subagent_session_id,
 task_type="plan",
 repo_url=repo_url,
 branch=branch,
 prompt=prompt,
 main_session_id=session_id,
 timeout=TASK_TIMEOUTS.get("plan", 600),
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
 "task_type": SubAgentSession.TaskType.PLAN,
 "status": SubAgentSession.Status.RUNNING,
 "container_id": container_id,
 },
 )
 # Store mapping in main session temp_data
 temp_data = main_session.temp_data or {}
 subagent_sessions = temp_data.setdefault("subagent_sessions", {})
 subagent_sessions[subagent_session_id] = {
 "task_type": "plan",
 "status": "running",
 "requirement": requirement[:100],
 "section_type": section_type,
 }
 main_session.temp_data = temp_data
 await main_session.asave(update_fields=["temp_data"])
 return ToolResult(
 success=True,
 output={
 "subagent_session_id": subagent_session_id,
 "status": "running",
 "section_type": section_type or "full_plan",
 "message": "已提交技术方案生成任务，等待 SubAgent 完成",
 },
 metadata={
 "suspension": True,
 "suspension_reason": "subagent_task",
 "subagent_session_id": subagent_session_id,
 },
 )
