"""
Project and repository query tools for the Agent.
Provides tools for querying space data, repository information,
and semantic code search via Qdrant vectors.
"""
from datetime import datetime, timezone
from typing import Any
import structlog
from agents.tools.base import ToolResult, tool
from projects.models import Project
from repositories.models import Repository
from services.embedding import EmbeddingService
logger = structlog.get_logger(__name__)
@tool(
 name="list_space_repositories",
 description=(
 "List all repositories linked to a space. "
 "Use this to discover available code repositories before searching code."
 ),
 category="PROJECT",
 parameters={
 "type": "object",
 "properties": {
 "space_id": {
 "type": "string",
 "description": "UUID of the space to query",
 },
 },
 "required": ["space_id"],
 },
)
async def list_space_repositories(space_id: str) -> ToolResult:
 """
 List all repositories associated with a space.
 Args:
 space_id: UUID of the space
 Returns:
 ToolResult with list of repositories and their metadata
 """
 logger.info("list_space_repositories", space_id=space_id)
 try:
 # Async query for space
 project = await Project.objects.aget(id=space_id)
 except Project.DoesNotExist:
 logger.warning("project_not_found", space_id=space_id)
 return ToolResult(
 success=True,
 output={
 "data": {"repositories": },
 "error": f"Space not found: {space_id}",
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
 "list_space_repositories_success",
 space_id=space_id,
 count=len(repositories),
 )
 return ToolResult(
 success=True,
 output={
 "data": {
 "space_id": str(space_id),
 "space_name": project.name,
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
 "Includes index status, space associations, and metadata."
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
 ToolResult with repository details and space associations
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
 # Use async for M2M space query
 projects = [{"id": str(p.id), "name": p.name} async for p in repo.projects.all]
 logger.info(
 "get_repository_info_success",
 repository_id=repository_id,
 space_count=len(projects),
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
 "Requires at least one of repository_id or space_id."
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
 "space_id": {
 "type": "string",
 "description": "UUID of space to search all repositories (optional)",
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
 space_id: str | None = None,
 limit: int = 20,
 min_score: float = 0.5,
 branch: str | None = None,
) -> ToolResult:
 """
 Perform semantic code search across repositories.
 Args:
 query: Semantic search query
 repository_id: Optional specific repository to search
 space_id: Optional space to search all its repositories
 limit: Maximum results to return
 min_score: Minimum similarity score threshold
 Returns:
 ToolResult with matching code blocks and metadata
 """
 logger.info(
 "search_repository_code",
 query=query[:100],
 repository_id=repository_id,
 space_id=space_id,
 limit=limit,
 min_score=min_score,
 )
 # Validate: at least one scope must be provided
 if not repository_id and not space_id:
 return ToolResult(
 success=False,
 output={"data": {"results": }, "error": None},
 error="At least one of repository_id or space_id is required",
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
 if space_id:
 # Get all repositories for the space
 try:
 project = await Project.objects.aget(id=space_id)
 except Project.DoesNotExist:
 return ToolResult(
 success=True,
 output={
 "data": {"results": },
 "error": f"Space not found: {space_id}",
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
 # Generate query embedding
 query_vector = await EmbeddingService.generate_embedding(query)
 if not query_vector:
 return ToolResult(
 success=False,
 output={"data": {"results": }},
 error="Failed to generate query embedding",
 )
 # Search across all repositories
 from services.branch_search import BranchAwareSearchService
 all_results: list[dict[str, Any]] =
 for repo_id in repo_ids:
 search_results = await BranchAwareSearchService.search(
 repo_id,
 query_vector,
 branch_name=branch,
 top_k=limit,
 )
 for r in search_results:
 if r["score"] >= min_score:
 payload = r.get("payload", {})
 all_results.append(
 {
 "file_path": payload.get("file_path", ""),
 "content": payload.get("content", ""),
 "language": payload.get("language", ""),
 "score": r["score"],
 "repository_id": repo_id,
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
 "fetched_at": datetime.now(timezone.utc).isoformat,
 },
 },
 )
