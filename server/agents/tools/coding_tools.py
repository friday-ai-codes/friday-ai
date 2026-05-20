"""编码会话工具 — create_coding_plan / update_coding_plan @tool。
Phase：工具落库切换到 `CodingPlan` 独立领域；返回 payload 同时携带
`coding_plan_id` 和 `coding_session_id`（兼容期保留旧 `session_id` alias）。
"""
from __future__ import annotations
import structlog
from agents.tools.base import ToolResult, tool
logger = structlog.get_logger(__name__)
def _normalize_affected_files(
 raw: list[dict[str, str]],
) -> list[dict[str, str]]:
 """统一 affected_files schema 为 ``{file_path, change_type}``。
 - 兼容旧 schema：``path`` 键自动迁移到 ``file_path``
 - 未知键名透传保留（不主动 strip 避免误删元数据）
 - 缺 ``change_type`` 时回退 ``modify``
 """
 normalized: list[dict[str, str]] =
 for entry in raw:
 item: dict[str, str] = dict(entry)
 if "file_path" not in item and "path" in item:
 item["file_path"] = item.pop("path")
 item.setdefault("change_type", "modify")
 normalized.append(item)
 return normalized
@tool(
 name="create_coding_plan",
 description=(
 "创建编码技术方案。当用户描述了具体的代码变更需求时调用。"
 "传入结构化技术方案（影响文件列表 + 实现步骤），后端创建 CodingPlan + CodingSession 记录。"
 ),
 category="PROJECT",
 parameters={
 "type": "object",
 "properties": {
 "space_id": {
 "type": "string",
 "description": "空间 UUID (auto-injected)",
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
 "file_path": {"type": "string"},
 "change_type": {
 "type": "string",
 "enum": ["add", "modify", "delete"],
 },
 },
 "required": ["file_path", "change_type"],
 },
 "description": (
 "影响文件列表（schema: [{file_path: str, "
 "change_type: 'add'|'modify'|'delete'}]）"
 ),
 },
 },
 "required": [
 "space_id",
 "conversation_id",
 "repository_id",
 "tech_plan",
 "affected_files",
 ],
 },
)
async def create_coding_plan(
 space_id: str,
 conversation_id: str,
 repository_id: str,
 tech_plan: str,
 affected_files: list[dict[str, str]],
) -> ToolResult:
 """创建编码技术方案，生成 CodingPlan + CodingSession 记录（Phase）。"""
 from chat.models import CodingPlan, CodingSession, Conversation
 from projects.models import Project
 from repositories.models import Repository
 logger.info(
 "create_coding_plan_requested",
 space_id=space_id,
 repository_id=repository_id,
 affected_files_count=len(affected_files),
 )
 try:
 project = await Project.objects.aget(id=space_id)
 except Project.DoesNotExist:
 return ToolResult(
 success=False,
 error=f"Space not found: {space_id}",
 )
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
 error=f"Repository {repository_id} does not belong to space {space_id}",
 )
 try:
 conversation = await Conversation.objects.aget(id=conversation_id)
 except Conversation.DoesNotExist:
 return ToolResult(
 success=False,
 error=f"Conversation not found: {conversation_id}",
 )
 # Phase： schema 归一化（兼容旧 path 入参）
 normalized_files = _normalize_affected_files(affected_files)
 # 生成模板格式分支名 (, per /)
 from chat.branch_service import generate_default_branch_name
 branch_name, branch_type, short_desc = generate_default_branch_name(tech_plan)
 logger.info(
 "branch_name_generated",
 branch_name=branch_name,
 branch_type=branch_type,
 short_desc=short_desc,
 )
 # Phase：先 get/create CodingPlan，再创建 CodingSession 关联
 plan, plan_created = await CodingPlan.aget_or_create_for_conversation(
 conversation=conversation,
 tech_plan=tech_plan,
 affected_files=normalized_files,
 title="",
 )
 # Phase：(coding_plan, repository) 部分唯一约束限制
 # 同时只能 1 个 active session。LLM 重复调用同 plan + 同 repo 时返回既有
 # active session（真正幂等），避免 IntegrityError 噪声。
 active_statuses = [
 CodingSession.Status.DRAFT,
 CodingSession.Status.CONFIRMED,
 CodingSession.Status.RUNNING,
 CodingSession.Status.AWAITING_CONFIRMATION,
 ]
 existing_active = await CodingSession.objects.filter(
 coding_plan=plan,
 repository=repo,
 status__in=active_statuses,
 ).afirst
 if existing_active is not None:
 logger.info(
 "create_coding_plan_returning_existing_active",
 coding_plan_id=str(plan.id),
 coding_session_id=str(existing_active.id),
 repository_id=repository_id,
 )
 return ToolResult(
 success=True,
 output={
 "coding_plan_id": str(plan.id),
 "coding_session_id": str(existing_active.id),
 "session_id": str(existing_active.id),
 "status": existing_active.status,
 "branch_name": existing_active.branch_name,
 "message": (
 f"已存在进行中的编码会话，plan_id={plan.id}、"
 f"session_id={existing_active.id}。"
 ),
 },
 )
 session = await CodingSession.objects.acreate(
 conversation=conversation,
 coding_plan=plan,
 repository=repo,
 tech_plan=tech_plan, # 兼容期保留同步写入（v26.1 清理）
 affected_files=normalized_files, # 兼容期保留同步写入
 branch_name=branch_name,
 status=CodingSession.Status.DRAFT,
 )
 logger.info(
 "create_coding_plan_completed",
 coding_plan_id=str(plan.id),
 coding_session_id=str(session.id),
 created=plan_created,
 branch_name=branch_name,
 )
 return ToolResult(
 success=True,
 output={
 "coding_plan_id": str(plan.id),
 "coding_session_id": str(session.id),
 # 兼容期旧 key alias，v26.1 deprecate（外部 LLM 工具调用仍按 session_id 读）
 "session_id": str(session.id),
 "status": "draft",
 "branch_name": branch_name,
 "message": (
 f"技术方案已创建，plan_id={plan.id}、session_id={session.id}。"
 "用户确认后可执行编码。"
 ),
 },
 )
@tool(
 name="update_coding_plan",
 description=(
 "更新编码技术方案。当用户要求调整方案时调用。"
 "传入更新后的方案内容；后端更新 CodingPlan，所有关联的 draft CodingSession 同步刷新。"
 ),
 category="PROJECT",
 parameters={
 "type": "object",
 "properties": {
 "coding_plan_id": {
 "type": "string",
 "description": "CodingPlan UUID（v26.0 起首选）",
 },
 "session_id": {
 "type": "string",
 "description": "CodingSession UUID（v25.x 兼容路径，已 deprecated）",
 },
 "tech_plan": {
 "type": "string",
 "description": "更新后的 Markdown 技术方案",
 },
 "affected_files": {
 "type": "array",
 "items": {
 "type": "object",
 "properties": {
 "file_path": {"type": "string"},
 "change_type": {
 "type": "string",
 "enum": ["add", "modify", "delete"],
 },
 },
 "required": ["file_path", "change_type"],
 },
 "description": (
 "更新后的影响文件列表"
 "（schema: [{file_path: str, change_type: str}]）"
 ),
 },
 },
 # coding_plan_id / session_id 二选一（在 handler 内校验）
 "required": ["tech_plan", "affected_files"],
 },
)
async def update_coding_plan(
 tech_plan: str,
 affected_files: list[dict[str, str]],
 coding_plan_id: str = "",
 session_id: str = "",
) -> ToolResult:
 """更新 CodingPlan + 同步 draft session 的 deprecated 字段（Phase）。"""
 from chat.models import CodingPlan, CodingSession
 logger.info(
 "update_coding_plan_requested",
 coding_plan_id=coding_plan_id,
 session_id=session_id,
 )
 if not coding_plan_id and not session_id:
 return ToolResult(
 success=False,
 error="必须提供 coding_plan_id 或 session_id",
 )
 # 路由：优先按 coding_plan_id 走新签名；旧 session_id 走兼容路径
 plan: CodingPlan | None = None
 # REVIEW：legacy session_id 路径下补回 plan 的 session id（用于
 # fan-out 同步阶段跳过它，避免重复 write）
 legacy_session_to_skip: str | None = None
 if coding_plan_id:
 try:
 plan = await CodingPlan.objects.aget(id=coding_plan_id)
 except CodingPlan.DoesNotExist:
 return ToolResult(
 success=False,
 error=f"CodingPlan not found: {coding_plan_id}",
 )
 else:
 try:
 session = await CodingSession.objects.select_related(
 "coding_plan", "conversation"
 ).aget(id=session_id)
 except CodingSession.DoesNotExist:
 return ToolResult(
 success=False,
 error=f"CodingSession not found: {session_id}",
 )
 if session.coding_plan_id is None:
 # 旧数据未迁移：临时建/拿 plan 并把反向 FK 补回去
 plan, _created = await CodingPlan.aget_or_create_for_conversation(
 conversation=session.conversation,
 tech_plan=session.tech_plan,
 affected_files=session.affected_files or,
 title="",
 )
 # REVIEW：补回 plan 时合并写入更新后的 tech_plan / affected_files，
 # 否则下一段 fan-out 同步会重复写一次（无谓 IO + updated_at 被刷两次）。
 # 这里先暂存目标值，等下方归一化完成后一并写入。
 session.coding_plan = plan
 await session.asave(update_fields=["coding_plan", "updated_at"])
 legacy_session_to_skip = str(session.id)
 else:
 plan = session.coding_plan
 assert plan is not None # 已被前面分支覆盖
 normalized_files = _normalize_affected_files(affected_files)
 await plan.aupdate_plan(tech_plan=tech_plan, affected_files=normalized_files)
 # 同步关联的 draft session 的兼容字段（不污染 running/completed）。
 # REVIEW：若刚刚通过 legacy session_id 路径补回过 plan，这条 session
 # 已经在补回的同一事务里写入了 plan 的最新内容，跳过避免重复 write。
 synced = 0
 async for s in plan.coding_sessions.filter( # type: ignore[attr-defined]
 status=CodingSession.Status.DRAFT
 ).aiterator:
 if legacy_session_to_skip is not None and str(s.id) == legacy_session_to_skip:
 # legacy 路径补回时已把目标值写进 session（见下方 fix block），跳过
 continue
 s.tech_plan = tech_plan
 s.affected_files = normalized_files
 await s.asave(update_fields=["tech_plan", "affected_files", "updated_at"])
 synced += 1
 # legacy 路径下，把 update 后的目标值合并写到刚补回 plan 的 session
 if legacy_session_to_skip is not None:
 await CodingSession.objects.filter(id=legacy_session_to_skip).aupdate(
 tech_plan=tech_plan,
 affected_files=normalized_files,
 )
 synced += 1
 logger.info(
 "update_coding_plan_completed",
 coding_plan_id=str(plan.id),
 synced_sessions_count=synced,
 )
 return ToolResult(
 success=True,
 output={
 "coding_plan_id": str(plan.id),
 "synced_sessions_count": synced,
 "message": (
 f"技术方案已更新（plan_id={plan.id}）；"
 f"同步刷新了 {synced} 个 draft session 的兼容字段。"
 ),
 },
 )
