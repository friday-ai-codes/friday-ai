"""Dispatch coding task tool for SubAgent.
Allows the main Agent to delegate coding tasks to Claude Code SubAgent.
"""
import structlog
from agents.models import AgentSession
from agents.tools.base import ToolResult, tool
from agents.tools.subagent.context import build_subagent_context
from subagent.client import SubAgentClient, SubAgentRequest
from subagent.models import SubAgentSession, generate_subagent_session_id
logger = structlog.get_logger(__name__)
@tool(
 name="dispatch_coding_task",
 description="分派编码任务给 Claude Code SubAgent。SubAgent 将在指定分支上执行代码修改，完成后通知主 Agent。",
 category="SUBAGENT",
 parameters={
 "type": "object",
 "properties": {
 "repo_url": {
 "type": "string",
 "description": "Git 仓库 URL",
 },
 "from_branch": {
 "type": "string",
 "description": "源分支名称（基于此分支创建工作分支）",
 },
 "target_branch": {
 "type": "string",
 "description": "目标分支名称（SubAgent 创建/切换到此分支进行开发）",
 },
 "task_description": {
 "type": "string",
 "description": "编码任务的详细描述",
 },
 "session_id": {
 "type": "string",
 "description": "主 Agent 会话 ID（由系统自动提供）",
 },
 "files_to_modify": {
 "type": "array",
 "items": {"type": "string"},
 "description": "建议修改的文件路径列表（可选）",
 },
 },
 "required": ["repo_url", "from_branch", "target_branch", "task_description", "session_id"],
 },
 requires_suspension=True,
)
async def dispatch_coding_task(
 repo_url: str,
 from_branch: str,
 target_branch: str,
 task_description: str,
 session_id: str,
 files_to_modify: list[str] | None = None,
) -> ToolResult:
 """Dispatch a coding task to SubAgent.
 Submits a coding task to Claude Code SubAgent which will:
 1. Clone/update the repository
 2. Create/checkout the target branch from from_branch
 3. Execute the coding task
 4. Commit changes
 5. Notify the main Agent via callback
 Args:
 repo_url: Git repository URL
 from_branch: Source branch to base work on
 target_branch: Target branch for SubAgent to work on
 task_description: Detailed description of the coding task
 session_id: Main Agent session ID
 files_to_modify: Optional list of files to modify
 Returns:
 ToolResult with task_id and suspension metadata
 """
 log = logger.bind(
 session_id=session_id,
 repo_url=repo_url,
 from_branch=from_branch,
 target_branch=target_branch,
 task_description=task_description[:50],
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
 # Generate SubAgent session ID
 subagent_session_id = generate_subagent_session_id(
 main_session_id=session_id,
 repo_url=repo_url,
 task_type="coding",
 )
 # Build context for SubAgent
 context = await build_subagent_context(main_session)
 context["branch_info"] = {
 "from_branch": from_branch,
 "target_branch": target_branch,
 }
 if files_to_modify:
 context["files_to_modify"] = files_to_modify
 # Build prompt
 prompt = f"""执行以下编码任务：
## 任务描述
{task_description}
## 分支信息
- 源分支: {from_branch}
- 目标分支: {target_branch}
## 操作步骤
1. 基于 {from_branch} 创建/切换到 {target_branch} 分支
2. 执行代码修改
3. 确保代码通过测试和类型检查
4. 提交更改（使用清晰的 commit message）
"""
 if files_to_modify:
 prompt += f"\n## 建议修改的文件\n{chr(10).join(f'- {f}' for f in files_to_modify)}"
 prompt += """
## 要求
- 遵循项目代码风格和约定
- 添加必要的注释
- 确保向后兼容
- 完成后提交所有更改
"""
 # Create SubAgent request
 request = SubAgentRequest(
 session_id=subagent_session_id,
 task_type="coding",
 repo_url=repo_url,
 branch=from_branch,
 target_branch=target_branch,
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
 "task_type": SubAgentSession.TaskType.CODING,
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
 "task_type": "coding",
 "status": "running",
 "from_branch": from_branch,
 "target_branch": target_branch,
 "task_description": task_description[:200],
 }
 main_session.temp_data = temp_data
 await main_session.asave(update_fields=["temp_data"])
 return ToolResult(
 success=True,
 output={
 "task_id": task_id,
 "subagent_session_id": subagent_session_id,
 "status": "running",
 "from_branch": from_branch,
 "target_branch": target_branch,
 "message": "已分派编码任务，SubAgent 正在执行",
 },
 metadata={
 "suspension": True,
 "suspension_reason": "subagent_task",
 "subagent_session_id": subagent_session_id,
 "task_id": task_id,
 },
 )
