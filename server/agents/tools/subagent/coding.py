"""Dispatch coding task tool for SubAgent.
Allows the main Agent to delegate coding tasks to Claude Code SubAgent.
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
 name="dispatch_coding_task",
 description="分派编码任务给 Claude Code SubAgent。SubAgent 将在指定分支上执行代码修改，完成后通过回调通知主 Agent。",
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
 使用 ContainerManager 启动容器，返回 suspension 元数据，
 容器完成后通过回调恢复 AgentLoop。
 Args:
 repo_url: Git repository URL
 from_branch: Source branch to base work on
 target_branch: Target branch for SubAgent to work on
 task_description: Detailed description of the coding task
 session_id: Main Agent session ID
 files_to_modify: Optional list of files to modify
 Returns:
 ToolResult with subagent_session_id and suspension metadata
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
 # 生成唯一执行 ID
 subagent_session_id = generate_execution_id
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
 # 使用 ContainerManager 启动容器
 try:
 manager = ContainerManager
 config = ContainerConfig(
 session_id=subagent_session_id,
 task_type="coding",
 repo_url=repo_url,
 branch=from_branch,
 target_branch=target_branch,
 prompt=prompt,
 main_session_id=session_id,
 timeout=TASK_TIMEOUTS.get("coding", 1800),
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
 "task_type": SubAgentSession.TaskType.CODING,
 "status": SubAgentSession.Status.RUNNING,
 "container_id": container_id,
 "target_branch": target_branch,
 },
 )
 return ToolResult(
 success=True,
 output={
 "subagent_session_id": subagent_session_id,
 "status": "running",
 "message": "已分派编码任务，SubAgent 正在执行",
 },
 metadata={
 "suspension": True,
 "suspension_reason": "subagent_task",
 "subagent_session_id": subagent_session_id,
 "container_id": container_id,
 },
 )
