"""Chat 对话工具 — 项目知识检索 + 深度分析。
检索工具（数据来自 Qdrant 已索引内容）：
- browse_file_content: 浏览已索引文件内容（按 chunk 返回）
- list_project_structure: 查看项目文件树结构
- get_project_overview: 获取项目概览信息
深度分析工具：
- deep_analysis: 将复杂分析任务 dispatch 到 Runner 上的 Claude Code 执行
"""
from __future__ import annotations
import asyncio
import uuid
from collections import defaultdict
from typing import Any
import structlog
from asgiref.sync import sync_to_async
from qdrant_client.http import models as qdrant_models
from qdrant_client.http.exceptions import UnexpectedResponse
from agents.tools.base import ToolResult, tool
from projects.models import Project
from repositories.models import Repository
from services.qdrant_service import QdrantService
logger = structlog.get_logger(__name__)
@tool(
 name="browse_file_content",
 description=(
 "Browse the content of an indexed file by file path. "
 "Returns file content as chunks ordered by position. "
 "Optionally filter by line range to reduce output."
 ),
 category="PROJECT",
 parameters={
 "type": "object",
 "properties": {
 "repository_id": {
 "type": "string",
 "description": "UUID of the repository containing the file",
 },
 "file_path": {
 "type": "string",
 "description": "Full file path within the repository",
 },
 "start_line": {
 "type": "integer",
 "description": "Start line number (1-based, optional)",
 },
 "end_line": {
 "type": "integer",
 "description": "End line number (1-based, optional)",
 },
 },
 "required": ["repository_id", "file_path"],
 },
)
async def browse_file_content(
 repository_id: str,
 file_path: str,
 start_line: int | None = None,
 end_line: int | None = None,
) -> ToolResult:
 """浏览已索引文件的内容。
 从 Qdrant 按 file_path 过滤获取所有 chunk，
 按 chunk_index 排序后返回。支持行范围过滤。
 """
 logger.info(
 "browse_file_content",
 repository_id=repository_id,
 file_path=file_path,
 start_line=start_line,
 end_line=end_line,
 )
 @sync_to_async # KEEP: Qdrant SDK 同步限制
 def _scroll_file -> list[dict[str, Any]]:
 try:
 client = QdrantService.get_client
 collection = QdrantService.get_collection_name(repository_id)
 all_points: list[dict[str, Any]] =
 offset = None
 while True:
 result = client.scroll(
 collection_name=collection,
 scroll_filter=qdrant_models.Filter(
 must=[
 qdrant_models.FieldCondition(
 key="file_path",
 match=qdrant_models.MatchValue(value=file_path),
 )
 ]
 ),
 limit=100,
 offset=offset,
 with_payload=True,
 with_vectors=False,
 )
 points, next_offset = result
 for point in points:
 if point.payload:
 all_points.append(point.payload)
 if next_offset is None:
 break
 offset = next_offset
 return all_points
 except UnexpectedResponse:
 return
 chunks_raw = await _scroll_file
 if not chunks_raw:
 return ToolResult(
 success=True,
 output={
 "data": {
 "file_path": file_path,
 "repository_id": repository_id,
 "chunks":,
 "total_chunks": 0,
 },
 "error": f"File not found in index: {file_path}",
 },
 )
 # 按 chunk_index 排序
 chunks_raw.sort(key=lambda c: c.get("chunk_index", 0))
 # 行范围过滤
 chunks =
 for chunk in chunks_raw:
 chunk_start = chunk.get("start_line", 0)
 chunk_end = chunk.get("end_line", float("inf"))
 if start_line is not None and chunk_end < start_line:
 continue
 if end_line is not None and chunk_start > end_line:
 continue
 chunks.append({
 "content": chunk.get("content", ""),
 "chunk_index": chunk.get("chunk_index", 0),
 "start_line": chunk.get("start_line"),
 "end_line": chunk.get("end_line"),
 "language": chunk.get("language", ""),
 })
 logger.info(
 "browse_file_content_success",
 file_path=file_path,
 total_chunks=len(chunks),
 )
 return ToolResult(
 success=True,
 output={
 "data": {
 "file_path": file_path,
 "repository_id": repository_id,
 "chunks": chunks,
 "total_chunks": len(chunks),
 },
 },
 )
@tool(
 name="list_project_structure",
 description=(
 "List the file tree structure of a project's indexed repositories. "
 "Returns an indented tree view with file names and language types."
 ),
 category="PROJECT",
 parameters={
 "type": "object",
 "properties": {
 "project_id": {
 "type": "string",
 "description": "UUID of the project to query",
 },
 },
 "required": ["project_id"],
 },
)
async def list_project_structure(project_id: str) -> ToolResult:
 """查看项目文件树结构。
 查询项目关联的所有已索引仓库，从 Qdrant 获取文件路径列表，
 构建缩进格式的树状结构。
 """
 logger.info("list_project_structure", project_id=project_id)
 # 获取已索引仓库
 indexed_repos = [
 repo
 async for repo in Repository.objects.filter(
 projects__id=project_id,
 index_status="indexed",
 is_deleted=False,
 )
 ]
 if not indexed_repos:
 return ToolResult(
 success=True,
 output={
 "data": {
 "project_id": project_id,
 "structure": "",
 "total_files": 0,
 },
 "error": "No indexed repositories found for this project",
 },
 )
 @sync_to_async # KEEP: Qdrant SDK 同步限制
 def _get_file_paths(repo_id: str) -> list[dict[str, str]]:
 try:
 client = QdrantService.get_client
 collection = QdrantService.get_collection_name(repo_id)
 file_info: dict[str, str] = {} # path -> language
 offset = None
 while True:
 result = client.scroll(
 collection_name=collection,
 scroll_filter=None,
 limit=1000,
 offset=offset,
 with_payload=["file_path", "language"],
 with_vectors=False,
 )
 points, next_offset = result
 for point in points:
 if point.payload:
 fp = point.payload.get("file_path", "")
 lang = point.payload.get("language", "")
 if fp and fp not in file_info:
 file_info[fp] = lang
 if next_offset is None:
 break
 offset = next_offset
 return [{"path": p, "language": lang} for p, lang in sorted(file_info.items)]
 except UnexpectedResponse:
 return
 # 收集所有仓库的文件信息
 all_files: list[dict[str, str]] =
 repo_names: dict[str, str] = {}
 for repo in indexed_repos:
 repo_id = str(repo.id)
 repo_names[repo_id] = repo.name
 files = await _get_file_paths(repo_id)
 for f in files:
 f["repo_name"] = repo.name
 all_files.extend(files)
 # 构建树状结构
 tree_lines: list[str] =
 for repo in indexed_repos:
 repo_files = [f for f in all_files if f["repo_name"] == repo.name]
 if not repo_files:
 continue
 tree_lines.append(f"{repo.name}/")
 tree_lines.extend(_build_tree(repo_files))
 structure = "\n".join(tree_lines)
 total_files = len(all_files)
 logger.info(
 "list_project_structure_success",
 project_id=project_id,
 total_files=total_files,
 )
 return ToolResult(
 success=True,
 output={
 "data": {
 "project_id": project_id,
 "structure": structure,
 "total_files": total_files,
 },
 },
 )
def _build_tree(files: list[dict[str, str]]) -> list[str]:
 """从文件列表构建缩进格式的树状结构。"""
 # 按路径分组到目录
 tree: dict[str, list[tuple[str, str]]] = defaultdict(list)
 for f in files:
 path = f["path"]
 parts = path.rsplit("/", 1)
 if len(parts) == 2:
 directory, filename = parts
 else:
 directory, filename = "", parts[0]
 lang = f.get("language", "")
 tree[directory].append((filename, lang))
 # 排序：收集所有目录路径
 all_dirs = sorted(tree.keys)
 lines: list[str] =
 for d in all_dirs:
 # 目录行（缩进级别 = 路径深度）
 if d:
 depth = d.count("/") + 1
 indent = " " * depth
 dir_name = d.rsplit("/", 1)[-1]
 lines.append(f"{indent}{dir_name}/")
 # 文件行
 file_depth = (d.count("/") + 2) if d else 1
 file_indent = " " * file_depth
 for filename, lang in sorted(tree[d]):
 lang_tag = f" [{lang}]" if lang else ""
 lines.append(f"{file_indent}{filename}{lang_tag}")
 return lines
@tool(
 name="get_project_overview",
 description=(
 "Get an overview of a project including name, description, "
 "linked repositories with their index status, file counts, "
 "and language distribution."
 ),
 category="PROJECT",
 parameters={
 "type": "object",
 "properties": {
 "project_id": {
 "type": "string",
 "description": "UUID of the project to query",
 },
 },
 "required": ["project_id"],
 },
)
async def get_project_overview(project_id: str) -> ToolResult:
 """获取项目概览信息。
 返回项目基本信息、关联仓库列表（含索引状态、文件数、语言分布）。
 """
 logger.info("get_project_overview", project_id=project_id)
 try:
 project = await Project.objects.aget(id=project_id)
 except Project.DoesNotExist:
 return ToolResult(
 success=True,
 output={
 "data": None,
 "error": f"Project not found: {project_id}",
 },
 )
 # 获取关联仓库
 repositories = [
 repo
 async for repo in Repository.objects.filter(
 projects=project,
 is_deleted=False,
 )
 ]
 @sync_to_async # KEEP: Qdrant SDK 同步限制
 def _get_repo_stats(repo_id: str) -> dict[str, Any]:
 """获取仓库的文件数和语言分布。"""
 try:
 client = QdrantService.get_client
 collection = QdrantService.get_collection_name(repo_id)
 file_paths: set[str] = set
 language_counts: dict[str, int] = defaultdict(int)
 offset = None
 while True:
 result = client.scroll(
 collection_name=collection,
 scroll_filter=None,
 limit=1000,
 offset=offset,
 with_payload=["file_path", "language"],
 with_vectors=False,
 )
 points, next_offset = result
 for point in points:
 if point.payload:
 fp = point.payload.get("file_path", "")
 lang = point.payload.get("language", "")
 if fp:
 file_paths.add(fp)
 if lang:
 language_counts[lang] += 1
 if next_offset is None:
 break
 offset = next_offset
 return {
 "file_count": len(file_paths),
 "languages": dict(sorted(
 language_counts.items,
 key=lambda x: x[1],
 reverse=True,
 )),
 }
 except UnexpectedResponse:
 return {"file_count": 0, "languages": {}}
 repo_data =
 for repo in repositories:
 repo_info: dict[str, Any] = {
 "id": str(repo.id),
 "name": repo.name,
 "index_status": repo.index_status,
 }
 if repo.index_status == "indexed":
 stats = await _get_repo_stats(str(repo.id))
 repo_info["file_count"] = stats["file_count"]
 repo_info["languages"] = stats["languages"]
 else:
 repo_info["file_count"] = 0
 repo_info["languages"] = {}
 repo_data.append(repo_info)
 logger.info(
 "get_project_overview_success",
 project_id=project_id,
 repo_count=len(repo_data),
 )
 return ToolResult(
 success=True,
 output={
 "data": {
 "project_name": project.name,
 "description": project.description or "",
 "project_id": str(project.id),
 "repositories": repo_data,
 "total_repositories": len(repo_data),
 },
 },
 )
# ============================================================================
# 深度分析工具 — dispatch 到 Runner 上的 Claude Code
# ============================================================================
DEEP_ANALYSIS_TIMEOUT = 1800 # 30 分钟
@tool(
 name="deep_analysis",
 description=(
 "Dispatch a deep code analysis task to Claude Code running on a remote Runner. "
 "Use for complex tasks: architecture analysis, cross-module tracing, "
 "understanding complex business logic. Claude Code has full repository access. "
 "This tool dispatches the task and returns immediately. Results will be provided "
 "when the analysis completes."
 ),
 category="PROJECT",
 parameters={
 "type": "object",
 "properties": {
 "project_id": {
 "type": "string",
 "description": "UUID of the project (auto-injected)",
 },
 "task_description": {
 "type": "string",
 "description": "Analysis task description, e.g. 'Analyze the authentication module architecture'",
 },
 "repository_id": {
 "type": "string",
 "description": "Target repository UUID (optional, analyzes first indexed repo if omitted)",
 },
 "conversation_id": {
 "type": "string",
 "description": "Conversation UUID (auto-injected)",
 },
 },
 "required": ["project_id", "task_description"],
 },
)
async def deep_analysis(
 project_id: str,
 task_description: str,
 repository_id: str | None = None,
 conversation_id: str = "",
) -> ToolResult:
 """将复杂分析任务 dispatch 到 Runner 上的 Claude Code。
 Fire-and-forget 模式：dispatch 后立即返回 __blocking_task__ 标记，
 等待和恢复由 graph interrupt/resume 机制处理。
 """
 from runners.dispatcher import DispatchTask, get_dispatcher
 from subagent.models import SubAgentSession
 logger.info(
 "deep_analysis_requested",
 project_id=project_id,
 task_description=task_description[:100],
 repository_id=repository_id,
 )
 # 1. 查找目标仓库
 try:
 project = await Project.objects.aget(id=project_id)
 except Project.DoesNotExist:
 return ToolResult(success=False, error=f"Project not found: {project_id}")
 if repository_id:
 repos = [
 repo async for repo in Repository.objects.filter(
 id=repository_id, projects=project, is_deleted=False, index_status="indexed",
 )
 ]
 else:
 repos = [
 repo async for repo in Repository.objects.filter(
 projects=project, is_deleted=False, index_status="indexed",
 )[:1]
 ]
 if not repos:
 return ToolResult(
 success=False,
 error="No indexed repositories found. Deep analysis requires at least one indexed repository.",
 )
 repo = repos[0]
 # 2.1 同一会话内若已有未结束的深度分析，直接复用等待，避免重复开容器
 existing_session = None
 async for candidate in SubAgentSession.objects.filter(
 task_type=SubAgentSession.TaskType.EXPLORE,
 status__in=[SubAgentSession.Status.PENDING, SubAgentSession.Status.RUNNING],
 ).select_related("main_session"):
 output = candidate.last_output or {}
 if (
 isinstance(output, dict)
 and output.get("source") == "chat_deep_analysis"
 and output.get("conversation_id") == conversation_id
 ):
 existing_session = candidate
 break
 # 2. 检查是否有在线 Runner（重试 3 次，每次等 5 秒，应对 server reload 后 Runner 重连间隙）
 from django.utils import timezone as tz
 from runners.models import Runner
 online_runners = 0
 for _attempt in range(3):
 heartbeat_threshold = tz.now - __import__("datetime").timedelta(seconds=120)
 online_runners = await Runner.objects.filter(
 status="online", last_heartbeat__gte=heartbeat_threshold,
 ).acount
 if online_runners > 0:
 break
 await asyncio.sleep(5)
 if online_runners == 0:
 return ToolResult(success=False, error="没有可用的 Runner（等待 15 秒后仍无心跳）")
 # 3. 创建 AgentSession（SubAgentSession 的 main_session 外键）
 from agents.models import AgentSession
 if existing_session is not None:
 session = existing_session
 session_id = session.session_id
 logger.info(
 "deep_analysis_reuse_existing_session",
 session_id=session_id,
 conversation_id=conversation_id,
 )
 output = session.last_output or {}
 output["task_description"] = task_description
 session.last_output = output
 await session.asave(update_fields=["last_output", "updated_at"])
 else:
 session_id = f"deep-{uuid.uuid4.hex[:12]}"
 agent_session = await AgentSession.objects.acreate(
 session_id=f"agent-{session_id}",
 project=project,
 status=AgentSession.Status.RUNNING,
 metadata={"source": "chat_deep_analysis", "conversation_id": conversation_id},
 )
 session = await SubAgentSession.objects.acreate(
 session_id=session_id,
 main_session=agent_session,
 task_type=SubAgentSession.TaskType.EXPLORE,
 status=SubAgentSession.Status.PENDING,
 last_output={
 "task_type": "explore",
 "source": "chat_deep_analysis",
 "project_id": project_id,
 "conversation_id": conversation_id,
 "repository_id": str(repo.id),
 "task_description": task_description,
 },
 )
 # 4. 构建 prompt
 prompt = (
 f"你正在分析项目「{project.name}」的代码仓库「{repo.name}」。\n\n"
 f"任务：{task_description}\n\n"
 f"请深入分析代码，给出详细的技术分析结果。用中文回答。"
 )
 # 5. 从系统设置获取 API 凭据 + Git 凭据，通过 metadata 注入容器
 from chat.services import aget_setting_value
 from common.encryption import decrypt_value
 from repositories.models import GitCredential
 from system.models import SettingKeys
 api_key = await aget_setting_value(SettingKeys.ANTHROPIC_API_KEY) or ""
 base_url = await aget_setting_value(SettingKeys.ANTHROPIC_BASE_URL) or ""
 system_model = await aget_setting_value(SettingKeys.ANTHROPIC_MODEL) or ""
 small_model = await aget_setting_value(SettingKeys.ANTHROPIC_SMALL_MODEL) or ""
 env_metadata: dict[str, str] = {
 "repository_id": str(repo.id),
 "env_FRIDAY_TASK_CLAUDE_API_KEY": api_key,
 "env_FRIDAY_TASK_CLAUDE_BASE_URL": base_url,
 "env_FRIDAY_TASK_CLAUDE_MODEL": system_model,
 "env_FRIDAY_TASK_CLAUDE_SMALL_MODEL": small_model,
 }
 repo_url = repo.git_url
 try:
 cred = await GitCredential.objects.aget(repository=repo)
 if cred.encrypted_token:
 token = decrypt_value(cred.encrypted_token)
 env_metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] = token
 env_metadata["env_FRIDAY_TASK_GIT_AUTH_TYPE"] = "token"
 env_metadata["env_FRIDAY_TASK_GIT_SSL_VERIFY"] = "false"
 # SSH URL → HTTPS（token 认证需要 HTTPS）
 if repo_url.startswith("git@"):
 import re
 m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", repo_url)
 if m:
 repo_url = f"https://{m.group(1)}/{m.group(2)}.git"
 except GitCredential.DoesNotExist:
 pass
 dispatch_task = DispatchTask(
 task_id=session_id,
 task_type="explore",
 tags=,
 image="",
 repo_url=repo_url,
 branch=repo.default_branch,
 target_branch="",
 prompt=prompt,
 timeout=DEEP_ANALYSIS_TIMEOUT,
 node_execution_id="",
 session_id=session_id,
 metadata=env_metadata,
 )
 if existing_session is None:
 await get_dispatcher.dispatch(dispatch_task)
 logger.info(
 "deep_analysis_dispatched",
 session_id=session_id,
 repo_name=repo.name,
 repo_url=repo.git_url,
 )
 # 6. Fire-and-forget: 注册到 blocking_task_registry 后立即返回
 from agents.tools.blocking_task_registry import register_blocking_task
 blocking_info: dict[str, Any] = {
 "task_id": session_id,
 "task_type": "deep_analysis",
 "params": {
 "task_description": task_description,
 "project_id": project_id,
 "repository_id": str(repo.id),
 },
 }
 await register_blocking_task(conversation_id, blocking_info)
 return ToolResult(
 success=True,
 output={
 "__blocking_task__": True,
 "task_id": session_id,
 "task_type": "deep_analysis",
 "params": {
 "task_description": task_description,
 "project_id": project_id,
 "repository_id": str(repo.id),
 },
 "placeholder": f"已启动深度分析任务 ({session_id})，分析完成后将自动返回结果。",
 },
 )
