"""Context retrieval node for RAG-based code search."""
from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING, Any
import structlog
from asgiref.sync import sync_to_async
if TYPE_CHECKING:
 from repositories.models import Repository
from services.embedding import EmbeddingService
from services.qdrant_service import QdrantService
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
 normalize_repositories,
)
from workflows.nodes.registry import register_node
logger = structlog.get_logger(__name__)
@register_node
class ContextRetrievalNode(BaseNode):
 """召回上下文节点
 根据查询文本从代码库向量索引中检索相关代码片段，
 用于为后续 AI 编码节点提供上下文。
 """
 node_type = "context_retrieval"
 display_name = "召回上下文"
 description = "从代码库中检索与需求相关的代码片段，为 AI 编码提供上下文"
 icon = "search-code"
 category = NodeCategory.AI
 execution_mode = "server_local"
 config_schema = {
 "type": "object",
 "properties": {
 "query": {
 "type": "string",
 "title": "检索查询",
 "description": "用于检索的文本，支持模板变量如 {{global.requirement_text}}",
 },
 "repositories": {
 "oneOf": [
 {
 "type": "array",
 "title": "仓库列表",
 "description": "代码仓库 ID 列表或模板变量",
 "items": {"type": "string"},
 },
 {
 "type": "string",
 "title": "仓库引用",
 "description": "单个仓库 ID 或模板变量如 {{global.repositories}}",
 },
 ],
 },
 "top_k": {
 "type": "integer",
 "title": "返回数量",
 "description": "返回的代码片段数量",
 "default": 10,
 "minimum": 1,
 "maximum": 50,
 },
 "score_threshold": {
 "type": "number",
 "title": "相似度阈值",
 "description": "最低相似度分数，低于此分数的结果将被过滤",
 "default": 0.5,
 "minimum": 0,
 "maximum": 1,
 },
 "language_filter": {
 "type": "string",
 "title": "语言过滤",
 "description": "可选，按编程语言过滤（如 python, typescript）",
 "default": "",
 },
 "include_content": {
 "type": "boolean",
 "title": "包含代码内容",
 "description": "是否在输出中包含完整代码内容",
 "default": True,
 },
 "format_as_markdown": {
 "type": "boolean",
 "title": "格式化为 Markdown",
 "description": "是否将结果格式化为 Markdown 代码块",
 "default": True,
 },
 },
 "required": ["query"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT, required=False)]
 outputs = [
 NodePort(
 name="default",
 label="检索结果",
 port_type=PortType.OBJECT,
 schema={
 "type": "object",
 "properties": {
 "query": {"type": "string", "description": "检索查询文本"},
 "total": {"type": "integer", "description": "检索到的总数量"},
 "formatted_context": {"type": "string", "description": "格式化的上下文（Markdown）"},
 "contexts": {
 "type": "array",
 "description": "代码片段列表",
 "items": {
 "type": "object",
 "properties": {
 "repository_id": {"type": "string", "description": "仓库 ID"},
 "repository_name": {"type": "string", "description": "仓库名称"},
 "file_path": {"type": "string", "description": "文件路径"},
 "content": {"type": "string", "description": "代码内容"},
 "language": {"type": "string", "description": "编程语言"},
 "score": {"type": "number", "description": "相关度分数"},
 "start_line": {"type": "integer", "description": "起始行号"},
 "end_line": {"type": "integer", "description": "结束行号"},
 },
 },
 },
 "repositories": {
 "type": "array",
 "description": "检索的仓库列表",
 "items": {"type": "string"},
 },
 },
 },
 ),
 NodePort(name="error", label="失败", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 # 渲染模板变量
 query = context.render_template(config.get("query", ""))
 top_k = config.get("top_k", 10) # Default 10 per repo
 score_threshold = config.get("score_threshold", 0.5)
 language_filter = context.render_template(config.get("language_filter", ""))
 include_content = config.get("include_content", True)
 format_as_markdown = config.get("format_as_markdown", True)
 timeout = config.get("timeout", 30.0)
 # 规范化仓库配置（支持单个/列表、模板变量）
 repo_configs = normalize_repositories(config, context)
 # 处理空仓库列表（静默跳过）
 if not repo_configs:
 return NodeResult(
 status="completed",
 output={
 "repositories":,
 "contexts":,
 "formatted_context": "",
 "total": 0,
 "query": query,
 "skipped": "empty_repository_list",
 },
 next_handle="default",
 )
 # 验证查询
 if not query:
 return NodeResult(
 status="failed",
 error="检索查询不能为空",
 next_handle="error",
 )
 # 解析仓库 ID 并验证存在性
 from repositories.models import Repository
 valid_repos: list[Repository] =
 invalid_ids: list[str] =
 for repo_info in repo_configs:
 repo_id = repo_info.get("id") or repo_info.get("name")
 if not repo_id:
 continue
 # 查找仓库
 repo = await Repository.objects.filter(
 id=repo_id, is_deleted=False
 ).afirst
 if not repo:
 repo = await Repository.objects.filter(
 name=repo_id, is_deleted=False
 ).afirst
 if repo:
 valid_repos.append(repo)
 else:
 invalid_ids.append(str(repo_id))
 # 记录无效仓库警告
 if invalid_ids:
 logger.warning(
 "skipped_invalid_repositories",
 invalid_ids=invalid_ids,
 valid_count=len(valid_repos),
 )
 # 处理全部无效的情况
 if not valid_repos:
 return NodeResult(
 status="completed",
 output={
 "repositories":,
 "contexts":,
 "formatted_context": "",
 "total": 0,
 "query": query,
 "skipped_repositories": invalid_ids,
 },
 next_handle="default",
 )
 logger.info(
 "context_retrieval_start",
 query=query[:100],
 repository_count=len(valid_repos),
 top_k=top_k,
 )
 try:
 # 生成查询向量
 query_embedding = await EmbeddingService.generate_embedding(query)
 if not query_embedding:
 return NodeResult(
 status="failed",
 error="生成查询向量失败，请检查 Embedding 服务配置",
 next_handle="error",
 )
 # 构建过滤条件
 filters: dict[str, Any] | None = None
 if language_filter:
 filters = {"language": language_filter}
 # 并行搜索所有仓库
 search_results = await self._search_all_repositories(
 valid_repos, query_embedding, top_k, filters, timeout
 )
 # 聚合结果（按仓库分组）
 aggregated = self._aggregate_results(
 search_results, score_threshold, top_k, include_content
 )
 # 格式化为 Markdown
 formatted_context = ""
 if format_as_markdown and aggregated["total"] > 0:
 formatted_context = self._format_as_markdown_grouped(aggregated)
 logger.info(
 "context_retrieval_completed",
 total=aggregated["total"],
 repository_count=len(aggregated["repositories"]),
 failed_count=len(aggregated.get("failed_repositories") or ),
 )
 # 构建输出（包含新的 repositories 结构和向后兼容的 contexts）
 output: dict[str, Any] = {
 "repositories": aggregated["repositories"],
 "contexts": self._flatten_contexts(aggregated),
 "formatted_context": formatted_context,
 "total": aggregated["total"],
 "query": query,
 }
 if aggregated.get("failed_repositories"):
 output["failed_repositories"] = aggregated["failed_repositories"]
 if invalid_ids:
 output["skipped_repositories"] = invalid_ids
 return NodeResult(
 status="completed",
 output=output,
 next_handle="default",
 )
 except Exception as e:
 logger.error("context_retrieval_failed", error=str(e))
 return NodeResult(
 status="failed",
 error=f"上下文召回失败: {e!s}",
 next_handle="error",
 )
 def _format_as_markdown(self, contexts: list[dict]) -> str:
 """将检索结果格式化为 Markdown 代码块"""
 parts = ["## 相关代码上下文\n"]
 for i, ctx in enumerate(contexts, 1):
 file_path = ctx.get("file_path", "unknown")
 repo_name = ctx.get("repository_name", "")
 start_line = ctx.get("start_line", 0)
 end_line = ctx.get("end_line", 0)
 language = ctx.get("language", "")
 content = ctx.get("content", "")
 score = ctx.get("score", 0)
 context_header = ctx.get("context_header", "")
 # 标题行（多仓库时包含仓库名）
 line_info = f"L{start_line}-{end_line}" if start_line and end_line else ""
 if repo_name:
 header = f"### {i}. [{repo_name}] {file_path}"
 else:
 header = f"### {i}. {file_path}"
 if line_info:
 header += f" ({line_info})"
 header += f" [相似度: {score:.2f}]"
 parts.append(header)
 # 上下文头（如函数/类名）
 if context_header:
 parts.append(f"> {context_header}")
 # 代码块
 if content:
 parts.append(f"```{language}")
 parts.append(content.strip)
 parts.append("```")
 parts.append("") # 空行分隔
 return "\n".join(parts)
 def _format_as_markdown_grouped(self, aggregated: dict[str, Any]) -> str:
 """将分组检索结果格式化为 Markdown，按仓库分节展示"""
 parts = ["## 相关代码上下文\n"]
 for repo_group in aggregated["repositories"]:
 repo_name = repo_group["repository_name"]
 result_count = repo_group["result_count"]
 parts.append(f"### [{repo_name}] ({result_count} 条结果)\n")
 for i, ctx in enumerate(repo_group["contexts"], 1):
 file_path = ctx.get("file_path", "unknown")
 start_line = ctx.get("start_line", 0)
 end_line = ctx.get("end_line", 0)
 language = ctx.get("language", "")
 content = ctx.get("content", "")
 score = ctx.get("score", 0)
 context_header = ctx.get("context_header", "")
 # 标题行
 line_info = f"L{start_line}-{end_line}" if start_line and end_line else ""
 header = f"#### {i}. {file_path}"
 if line_info:
 header += f" ({line_info})"
 header += f" [相似度: {score:.2f}]"
 parts.append(header)
 # 上下文头（如函数/类名）
 if context_header:
 parts.append(f"> {context_header}")
 # 代码块
 if content:
 parts.append(f"```{language}")
 parts.append(content.strip)
 parts.append("```")
 parts.append("") # 空行分隔
 # 添加失败仓库信息
 if aggregated.get("failed_repositories"):
 parts.append("---\n")
 parts.append("**检索失败的仓库:**")
 for fail in aggregated["failed_repositories"]:
 parts.append(f"- {fail['repository_name']}: {fail['error']}")
 return "\n".join(parts)
 def _aggregate_results(
 self,
 search_results: list[dict[str, Any]],
 score_threshold: float,
 top_k: int,
 include_content: bool,
 ) -> dict[str, Any]:
 """Aggregate results grouped by repository.
 Returns a dict with repositories, total, and failed_repositories (if any).
 """
 repository_groups: list[dict[str, Any]] =
 failed_repositories: list[dict[str, Any]] =
 total_results = 0
 for repo_result in search_results:
 if repo_result["status"] != "success":
 failed_repositories.append(
 {
 "repository_id": repo_result["repository_id"],
 "repository_name": repo_result["repository_name"],
 "error": repo_result.get("error", "Unknown error"),
 }
 )
 continue
 # Filter by score threshold and limit per repo
 filtered = [r for r in repo_result["results"] if r["score"] >= score_threshold][:top_k]
 if not filtered:
 continue
 # Build context items sorted by score (descending)
 contexts: list[dict[str, Any]] =
 for r in sorted(filtered, key=lambda x: x["score"], reverse=True):
 payload = r["payload"]
 ctx: dict[str, Any] = {
 "repository_id": repo_result["repository_id"],
 "repository_name": repo_result["repository_name"],
 "file_path": payload.get("file_path"),
 "score": r["score"],
 "language": payload.get("language"),
 "start_line": payload.get("start_line"),
 "end_line": payload.get("end_line"),
 "context_header": payload.get("context_header", ""),
 }
 if include_content:
 ctx["content"] = payload.get("content", "")
 contexts.append(ctx)
 repository_groups.append(
 {
 "repository_id": repo_result["repository_id"],
 "repository_name": repo_result["repository_name"],
 "result_count": len(contexts),
 "contexts": contexts,
 }
 )
 total_results += len(contexts)
 return {
 "repositories": repository_groups,
 "total": total_results,
 "failed_repositories": failed_repositories if failed_repositories else None,
 }
 def _flatten_contexts(self, aggregated: dict[str, Any]) -> list[dict[str, Any]]:
 """Flatten grouped results into a single sorted list for backward compatibility."""
 all_contexts: list[dict[str, Any]] =
 for repo_group in aggregated["repositories"]:
 all_contexts.extend(repo_group["contexts"])
 # Sort by score descending across all repositories
 all_contexts.sort(key=lambda x: x["score"], reverse=True)
 return all_contexts
 async def _search_repository(
 self,
 repository: "Repository",
 query_embedding: list[float],
 top_k: int,
 filters: dict[str, Any] | None,
 timeout: float = 30.0,
 ) -> dict[str, Any]:
 """Search single repository with timeout.
 Returns a dict with repository_id, repository_name, status, results, and error (if any).
 """
 repo_id = str(repository.id)
 try:
 search_coro = sync_to_async(QdrantService.search, thread_sensitive=True)(
 repo_id,
 query_embedding,
 top_k=top_k,
 filters=filters,
 )
 results = await asyncio.wait_for(search_coro, timeout=timeout)
 return {
 "repository_id": repo_id,
 "repository_name": repository.name,
 "status": "success",
 "results": results or,
 }
 except asyncio.TimeoutError:
 return {
 "repository_id": repo_id,
 "repository_name": repository.name,
 "status": "timeout",
 "error": f"Search timed out after {timeout}s",
 "results":,
 }
 except Exception as e:
 return {
 "repository_id": repo_id,
 "repository_name": repository.name,
 "status": "error",
 "error": str(e),
 "results":,
 }
 async def _search_all_repositories(
 self,
 repositories: list["Repository"],
 query_embedding: list[float],
 top_k: int,
 filters: dict[str, Any] | None,
 timeout: float = 30.0,
 ) -> list[dict[str, Any]]:
 """Search all repositories in parallel.
 Uses asyncio.gather with return_exceptions=True to ensure all tasks complete.
 Any unexpected exceptions are converted to error dicts.
 """
 search_tasks = [
 self._search_repository(repo, query_embedding, top_k, filters, timeout)
 for repo in repositories
 ]
 # gather with return_exceptions=True ensures all tasks complete
 results = await asyncio.gather(*search_tasks, return_exceptions=True)
 # Convert any unexpected exceptions to error dicts
 processed: list[dict[str, Any]] =
 for i, result in enumerate(results):
 if isinstance(result, Exception):
 processed.append(
 {
 "repository_id": str(repositories[i].id),
 "repository_name": repositories[i].name,
 "status": "error",
 "error": str(result),
 "results":,
 }
 )
 else:
 processed.append(result)
 return processed
