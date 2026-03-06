"""Chat 对话工具 — 项目知识检索。
Phase 新增的 3 个检索工具，数据全部来自 Qdrant 已索引内容：
- browse_file_content: 浏览已索引文件内容（按 chunk 返回）
- list_project_structure: 查看项目文件树结构
- get_project_overview: 获取项目概览信息
"""
from __future__ import annotations
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
 return [{"path": p, "language": l} for p, l in sorted(file_info.items)]
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
