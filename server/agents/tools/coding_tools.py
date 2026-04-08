"""编码会话工具 — create_coding_plan / update_coding_plan @tool。
让 AI 在对话中创建和更新技术方案，后端创建 CodingSession 记录
追踪从方案草稿到 PR 的全流程。
"""
from __future__ import annotations
import uuid
import structlog
from agents.tools.base import ToolResult, tool
logger = structlog.get_logger(__name__)
@tool(
 name="create_coding_plan",
 description=(
 "创建编码技术方案。当用户描述了具体的代码变更需求时调用。"
 "传入结构化技术方案（影响文件列表 + 实现步骤），后端创建 CodingSession 记录。"
 ),
 category="PROJECT",
 parameters={
 "type": "object",
 "properties": {
 "project_id": {
 "type": "string",
 "description": "项目 UUID (auto-injected)",
 },
 "conversation_id": {
 "type": "string",
 "description": "会话 UUID (auto-injected)",
 },
 "repository_id": {
 "type": "string",
 "description": "目标仓库 UUID",
 },
 "tech_plan": {
 "type": "string",
 "description": "Markdown 格式的技术方案，包含影响文件列表和分步实现步骤",
 },
 "affected_files": {
 "type": "array",
 "items": {
 "type": "object",
 "properties": {
 "path": {"type": "string"},
 "change_type": {
 "type": "string",
 "enum": ["add", "modify", "delete"],
 },
 },
 "required": ["path", "change_type"],
 },
 "description": "影响文件列表（文件路径 + 变更类型）",
 },
 },
 "required": [
 "project_id",
 "conversation_id",
 "repository_id",
 "tech_plan",
 "affected_files",
 ],
 },
)
async def create_coding_plan(
 project_id: str,
 conversation_id: str,
 repository_id: str,
 tech_plan: str,
 affected_files: list[dict[str, str]],
) -> ToolResult:
 """创建编码技术方案，生成 CodingSession 记录。"""
 from chat.models import CodingSession, Conversation
 from projects.models import Project
 from repositories.models import Repository
 logger.info(
 "create_coding_plan_requested",
 project_id=project_id,
 repository_id=repository_id,
 affected_files_count=len(affected_files),
 )
 # 验证 Project 存在
 try:
 project = await Project.objects.aget(id=project_id)
 except Project.DoesNotExist:
 return ToolResult(
 success=False,
 error=f"Project not found: {project_id}",
 )
 # 验证 Repository 存在且属于该 Project
 try:
 repo = await Repository.objects.aget(id=repository_id)
 except Repository.DoesNotExist:
 return ToolResult(
 success=False,
 error=f"Repository not found: {repository_id}",
 )
 repo_in_project = await project.repositories.filter(id=repository_id).aexists
 if not repo_in_project:
 return ToolResult(
 success=False,
 error=f"Repository {repository_id} does not belong to project {project_id}",
 )
 # 获取 Conversation
 try:
 conversation = await Conversation.objects.aget(id=conversation_id)
 except Conversation.DoesNotExist:
 return ToolResult(
 success=False,
 error=f"Conversation not found: {conversation_id}",
 )
 # 生成 branch_name
 branch_name = f"coding-{uuid.uuid4.hex[:8]}"
 # 创建 CodingSession
 session = await CodingSession.objects.acreate(
 conversation=conversation,
 repository=repo,
 tech_plan=tech_plan,
 affected_files=affected_files,
 branch_name=branch_name,
 status=CodingSession.Status.DRAFT,
 )
 logger.info(
 "coding_session_created",
 session_id=str(session.id),
 branch_name=branch_name,
 status="draft",
 )
 return ToolResult(
 success=True,
 output={
 "session_id": str(session.id),
 "status": "draft",
 "branch_name": branch_name,
 "message": f"技术方案已创建，session_id={session.id}。用户确认后可执行编码。",
 },
 )
