"""
Project and repository query tools for the Agent.
Provides tools for querying project data, repository information,
and semantic code search via Qdrant vectors.
"""
from datetime import datetime, timezone
from typing import Any
import structlog
from agents.tools.base import ToolResult, tool
from projects.models import Project
from repositories.models import Repository
logger = structlog.get_logger(__name__)
@tool(
 name="list_project_repositories",
 description=(
 "List all repositories linked to a project. "
 "Use this to discover available code repositories before searching code."
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
async def list_project_repositories(project_id: str) -> ToolResult:
 """
 List all repositories associated with a project.
 Args:
 project_id: UUID of the project
 Returns:
 ToolResult with list of repositories and their metadata
 """
 logger.info("list_project_repositories", project_id=project_id)
 try:
 # Async query for project
 project = await Project.objects.aget(id=project_id)
 except Project.DoesNotExist:
 logger.warning("project_not_found", project_id=project_id)
 return ToolResult(
 success=True,
 output={
 "data": {"repositories": },
 "error": f"Project not found: {project_id}",
 },
 )
 # Use async for M2M query
 repositories = [
 {
 "id": str(repo.id),
 "name": repo.name,
 "git_url": repo.git_url,
 "platform": repo.git_platform,
 "default_branch": repo.default_branch,
 "description": repo.description or "",
 "index_status": repo.index_status,
 }
 async for repo in Repository.objects.filter(
 projects=project,
 is_deleted=False,
 ).select_related
 ]
 logger.info(
 "list_project_repositories_success",
 project_id=project_id,
 count=len(repositories),
 )
 return ToolResult(
 success=True,
 output={
 "data": {
 "project_id": str(project_id),
 "project_name": project.name,
 "repositories": repositories,
 },
 "metadata": {
 "count": len(repositories),
 "fetched_at": datetime.now(timezone.utc).isoformat,
 },
 },
 )
@tool(
 name="get_repository_info",
 description=(
 "Get detailed information about a specific repository. "
 "Includes index status, project associations, and metadata."
 ),
 category="PROJECT",
 parameters={
 "type": "object",
 "properties": {
 "repository_id": {
 "type": "string",
 "description": "UUID of the repository to query",
 },
 },
 "required": ["repository_id"],
 },
)
async def get_repository_info(repository_id: str) -> ToolResult:
 """
 Get detailed information about a repository.
 Args:
 repository_id: UUID of the repository
 Returns:
 ToolResult with repository details and project associations
 """
 logger.info("get_repository_info", repository_id=repository_id)
 try:
 # Async query for repository
 repo = await Repository.objects.aget(id=repository_id, is_deleted=False)
 except Repository.DoesNotExist:
 logger.warning("repository_not_found", repository_id=repository_id)
 return ToolResult(
 success=True,
 output={
 "data": None,
 "error": f"Repository not found: {repository_id}",
 },
 )
 # Use async for M2M project query
 projects = [{"id": str(p.id), "name": p.name} async for p in repo.projects.all]
 logger.info(
 "get_repository_info_success",
 repository_id=repository_id,
 project_count=len(projects),
 )
 return ToolResult(
 success=True,
 output={
 "data": {
 "id": str(repo.id),
 "name": repo.name,
 "git_url": repo.git_url,
 "git_platform": repo.git_platform,
 "default_branch": repo.default_branch,
 "description": repo.description or "",
 "index_status": repo.index_status,
 "last_indexed_at": (
 repo.last_indexed_at.isoformat if repo.last_indexed_at else None
 ),
 "created_at": repo.created_at.isoformat,
 "updated_at": repo.updated_at.isoformat,
 "projects": projects,
 },
 "metadata": {
 "fetched_at": datetime.now(timezone.utc).isoformat,
 },
 },
 )
@tool(
 name="search_repository_code",
 description=(
 "Semantic search for code across indexed repositories. "
 "Returns full code blocks matching the query. "
 "Requires at least one of repository_id or project_id."
 ),
 category="PROJECT",
 parameters={
 "type": "object",
 "properties": {
 "query": {
 "type": "string",
 "description": "Semantic search query describing the code to find",
 },
 "repository_id": {
 "type": "string",
 "description": "UUID of a specific repository to search (optional)",
 },
 "project_id": {
 "type": "string",
 "description": "UUID of project to search all repositories (optional)",
 },
 "limit": {
 "type": "integer",
 "description": "Maximum number of results (default: 20)",
 "default": 20,
 },
 "min_score": {
 "type": "number",
 "description": "Minimum similarity score threshold (default: 0.5)",
 "default": 0.5,
 },
 "branch": {
 "type": "string",
 "description": "Branch name for branch-aware search (optional, defaults to base_branch)",
 },
 },
 "required": ["query"],
 },
)
async def search_repository_code(
 query: str,
 repository_id: str | None = None,
 project_id: str | None = None,
 limit: int = 20,
 min_score: float = 0.5,
 branch: str | None = None,
) -> ToolResult:
 """
 Perform semantic code search across repositories.
 Args:
 query: Semantic search query
 repository_id: Optional specific repository to search
 project_id: Optional project to search all its repositories
 limit: Maximum results to return
 min_score: Minimum similarity score threshold
 Returns:
 ToolResult with matching code blocks and metadata
 """
 logger.info(
 "search_repository_code",
 query=query[:100],
 repository_id=repository_id,
 project_id=project_id,
 limit=limit,
 min_score=min_score,
 )
 # Validate: at least one scope must be provided
 if not repository_id and not project_id:
 return ToolResult(
 success=False,
 output={"data": {"results": }, "error": None},
 error="At least one of repository_id or project_id is required",
 )
 # Collect repository IDs to search
 repo_ids: list[str] =
 if repository_id:
 # Verify repository exists
 try:
 await Repository.objects.aget(id=repository_id, is_deleted=False)
 repo_ids.append(repository_id)
 except Repository.DoesNotExist:
 return ToolResult(
 success=True,
 output={
 "data": {"results": },
 "error": f"Repository not found: {repository_id}",
 },
 )
 if project_id:
 # Get all repositories for the project
 try:
 project = await Project.objects.aget(id=project_id)
 except Project.DoesNotExist:
 return ToolResult(
 success=True,
 output={
 "data": {"results": },
 "error": f"Project not found: {project_id}",
 },
 )
 project_repo_ids = [
 str(rid)
 async for rid in Repository.objects.filter(
 projects=project,
 is_deleted=False,
 index_status="indexed",
 ).values_list("id", flat=True)
 ]
 # Add to list (avoid duplicates)
 for rid in project_repo_ids:
 rid_str = str(rid)
 if rid_str not in repo_ids:
 repo_ids.append(rid_str)
 if not repo_ids:
 return ToolResult(
 success=True,
 output={
 "data": {"results": },
 "metadata": {
 "query": query,
 "total_results": 0,
 "searched_repositories": 0,
 },
 "error": "No indexed repositories found to search",
 },
 )
 # 统一调用 LayeredSearchService (per )
 from codegraph.services.layered_search import LayeredSearchService
 result = await LayeredSearchService.search(
 query,
 repository_ids=repo_ids if repo_ids else None,
 branch_name=branch,
 top_k=limit,
 )
 all_results: list[dict[str, Any]] =
 final_context = result.final_context
 # 从 L3 层结果提取向量搜索结果 (保持向后兼容的返回格式)
 for layer in result.layers:
 if layer.layer == "L3" and layer.status == "ok":
 for item in layer.items:
 payload = item.get("payload", {})
 score = item.get("score", 0.0)
 if score >= min_score:
 all_results.append(
 {
 "file_path": payload.get("file_path", ""),
 "content": payload.get("content", ""),
 "language": payload.get("language", ""),
 "score": score,
 "repository_id": item.get("repository_id", ""),
 }
 )
 # 如果 L3 为空，回退到 L2 精确匹配
 if not all_results:
 for layer in result.layers:
 if layer.layer == "L2" and layer.status == "ok":
 for item in layer.items:
 all_results.append(
 {
 "file_path": item.get("file_path", ""),
 "content": f"Symbol: {item['name']} ({item['symbol_type']}) - {item.get('signature', '')}",
 "language": "",
 "score": 1.0, # 精确匹配给最高分
 "repository_id": item.get("repository_id", ""),
 }
 )
 # Sort by score and limit
 all_results.sort(key=lambda x: x["score"], reverse=True)
 all_results = all_results[:limit]
 logger.info(
 "search_repository_code_success",
 query=query[:50],
 result_count=len(all_results),
 searched_repos=len(repo_ids),
 )
 return ToolResult(
 success=True,
 output={
 "data": {"results": all_results},
 "metadata": {
 "query": query,
 "total_results": len(all_results),
 "searched_repositories": len(repo_ids),
 "min_score": min_score,
 "context": final_context, # NEW: L5 裁剪后的结构化上下文
 "fetched_at": datetime.now(timezone.utc).isoformat,
 },
 },
 )
