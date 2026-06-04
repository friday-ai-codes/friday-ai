"""Friday MCP read tools HTTP endpoints."""
from __future__ import annotations
import time
import uuid
from collections.abc import Iterable
from typing import Any
import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from agents.tools.chat_tools import _list_indexed_paths, _scroll_file_from_collection
from code_relations.models import ChunkRegistry
from codegraph.models import Symbol
from interactions.entry import AccessTokenAuthentication, begin_interaction_run
from interactions.ledger import (
 arecord_event,
 arecord_model_usage,
 arecord_retrieval_trace,
 arecord_tool_call,
)
from interactions.models import InteractionEvent, InteractionRun, RetrievalTrace, ToolCallRecord
from repositories.models import FileIndex, IndexStatus, Repository
from services.branch_utils import resolve_branch_for_query
from services.qdrant_service import QdrantService
from .errors import error_response
from .execution_service import (
 ExecutionDispatchError,
 dispatch_execution,
 execution_trace_payload,
 refresh_execution_trace,
)
from .merge_request_service import (
 MergeRequestToolError,
 create_merge_request,
 summarize_branch,
)
from .models import (
 McpCodingExecutionTrace,
 McpCodingPlan,
 McpCodingPlanVersion,
 McpRepositoryAnalysis,
)
from .planning_service import (
 build_coding_plan,
 build_repository_analysis,
 improve_coding_plan,
)
from .serializers import (
 AnalyzeRepositoryRequestSerializer,
 CreateFeishuTechnicalPlanRequestSerializer,
 CreateMergeRequestRequestSerializer,
 CreateCodingPlanRequestSerializer,
 CreateWorkItemRepoTasksRequestSerializer,
 ExecuteCodingPlanRequestSerializer,
 ExecuteWorkItemRepoTasksRequestSerializer,
 FindRelatedChunksRequestSerializer,
 GetCodingExecutionRequestSerializer,
 GetFeishuWorkItemContextRequestSerializer,
 GetRepositoryFileRequestSerializer,
 GetRepositoryRequestSerializer,
 ImproveCodingPlanRequestSerializer,
 ListRepositoryFilesRequestSerializer,
 RouteRepositoriesRequestSerializer,
 SearchRagChunksRequestSerializer,
 SummarizeBranchRequestSerializer,
)
from .technical_plan_service import TechnicalPlanError, build_work_item_technical_plan
from .work_item_context_service import WorkItemContextError, build_work_item_context
from .work_item_execution_service import (
 WorkItemExecutionError,
 create_repo_tasks_from_technical_plan,
 execute_work_item_repo_tasks,
 repo_task_payload,
)
logger = structlog.get_logger(__name__)
def _jsonable(value: Any) -> Any:
 if isinstance(value, uuid.UUID):
 return str(value)
 if isinstance(value, dict):
 return {str(k): _jsonable(v) for k, v in value.items}
 if isinstance(value, (list, tuple, set)):
 return [_jsonable(v) for v in value]
 return value
def _serialize_neighbor(neighbor: Any) -> dict[str, Any]:
 return {
 "chunk_id": str(getattr(neighbor, "chunk_id", "")),
 "file_path": getattr(neighbor, "file_path", ""),
 "line_start": getattr(neighbor, "line_start", None),
 "line_end": getattr(neighbor, "line_end", None),
 "edge_type": getattr(neighbor, "edge_type", ""),
 "weight": getattr(neighbor, "weight", 0.0),
 "score": getattr(neighbor, "weight", 0.0),
 "reason": getattr(neighbor, "reason", ""),
 "hop": getattr(neighbor, "hop", 0),
 }
def _first_error_detail(errors: Any) -> Any:
 if isinstance(errors, dict):
 return {key: _first_error_detail(value) for key, value in errors.items}
 if isinstance(errors, list):
 return [_first_error_detail(value) for value in errors]
 return str(errors)
def _traces_from_evidence(evidence: Iterable[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
 traces: list[tuple[str, dict[str, Any]]] =
 for item in evidence:
 kind = str(item.get("kind") or "file")
 if kind == "chunk":
 trace_kind = RetrievalTrace.Kind.CHUNK
 elif kind == "edge":
 trace_kind = RetrievalTrace.Kind.EDGE
 else:
 trace_kind = RetrievalTrace.Kind.FILE
 traces.append((trace_kind, item))
 return traces
class McpToolView(APIView):
 """MCP tool 基类：token-only、统一错误、run/tool-call/trace helper。"""
 authentication_classes = [AccessTokenAuthentication]
 permission_classes = [AllowAny]
 tool_name = ""
 def handle_exception(self, exc: Exception) -> Response:
 if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
 return error_response(
 "authentication_failed",
 str(exc.detail) if hasattr(exc, "detail") else str(exc),
 status_code=status.HTTP_401_UNAUTHORIZED,
 )
 return super.handle_exception(exc)
 async def _begin(self, request: Request) -> tuple[InteractionRun | None, Response | None]:
 if request.auth is None:
 return None, error_response(
 "authentication_required",
 "缺少 Friday Access Token",
 status_code=status.HTTP_401_UNAUTHORIZED,
 )
 return await begin_interaction_run(request, source="mcp"), None
 async def _validate(
 self,
 serializer_class: type[serializers.Serializer],
 request: Request,
 ) -> tuple[dict[str, Any] | None, Response | None]:
 serializer = serializer_class(data=request.data)
 try:
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 except serializers.ValidationError as exc:
 return None, error_response(
 "invalid_params",
 _first_error_detail(exc.detail),
 status_code=status.HTTP_400_BAD_REQUEST,
 )
 return _jsonable(serializer.validated_data), None
 async def _record(
 self,
 run: InteractionRun,
 *,
 input_data: dict[str, Any],
 output_data: dict[str, Any],
 traces: Iterable[tuple[str, dict[str, Any]]],
 started_at: float,
 call_status: str = "ok",
 error: str = "",
 ) -> ToolCallRecord | None:
 duration_ms = max(int((time.perf_counter - started_at) * 1000), 0)
 tool_call = await arecord_tool_call(
 run,
 tool_name=self.tool_name,
 input=input_data,
 output=output_data,
 status=call_status,
 duration_ms=duration_ms,
 error=error,
 )
 for kind, payload in traces:
 await arecord_retrieval_trace(
 run,
 kind=kind,
 payload=payload,
 tool_call=tool_call,
 )
 return tool_call
 async def _record_agent_decision(
 self,
 run: InteractionRun,
 *,
 action: str,
 payload: dict[str, Any],
 ) -> None:
 await arecord_event(
 run,
 InteractionEvent.EventType.AGENT_DECISION,
 {
 "tool_name": self.tool_name,
 "action": action,
 **payload,
 },
 )
 async def _record_model_usage(
 self,
 run: InteractionRun,
 usage: dict[str, Any],
 ) -> None:
 await arecord_model_usage(
 run,
 provider=str(usage.get("provider") or "friday"),
 model=str(usage.get("model") or "unknown"),
 prompt_version=str(usage.get("prompt_version") or ""),
 system_prompt_version=str(usage.get("system_prompt_version") or ""),
 prompt_tokens=int(usage.get("prompt_tokens") or 0),
 completion_tokens=int(usage.get("completion_tokens") or 0),
 total_tokens=int(usage.get("total_tokens") or 0),
 duration_ms=int(usage.get("duration_ms") or 0),
 )
 async def _collect_indexed_paths(
 self,
 repository_id: str,
 *,
 limit: int,
 ) -> list[str]:
 paths: list[str] =
 async for file_path in FileIndex.objects.filter(
 repository_id=repository_id
 ).order_by("file_path").values_list("file_path", flat=True):
 paths.append(str(file_path))
 if len(paths) >= limit:
 break
 return paths
 async def _get_indexed_repo(
 self,
 repository_id: str,
 ) -> tuple[Repository | None, Response | None]:
 try:
 repo = await Repository.objects.aget(id=repository_id, is_deleted=False)
 except Repository.DoesNotExist:
 return None, error_response(
 "repository_not_found",
 "仓库不存在",
 status_code=status.HTTP_404_NOT_FOUND,
 )
 if repo.index_status != IndexStatus.INDEXED:
 return None, error_response(
 "repository_not_indexed",
 "仓库尚未建立索引",
 status_code=status.HTTP_400_BAD_REQUEST,
 )
 return repo, None
 async def _resolve_graph_branch(
 self,
 repository_id: str,
 repo: Repository,
 branch: str | None,
 ) -> tuple[str | None, str | None]:
 effective_branch, branch_index = await resolve_branch_for_query(
 repository_id, branch or None
 )
 base_branch = repo.base_branch or repo.default_branch
 graph_branch = (
 effective_branch
 if effective_branch and effective_branch != base_branch
 else None
 )
 collection_name = (
 branch_index.collection_name
 if graph_branch and branch_index and branch_index.collection_name
 else QdrantService.get_collection_name(repository_id)
 )
 return graph_branch, collection_name
class RouteRepositoriesView(McpToolView):
 tool_name = "route_repositories"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(RouteRepositoriesRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 from codegraph.services.repo_router import RepoRouter
 query = str(input_data["query"])
 top_k = int(input_data.get("top_k", 3))
 route_results = await RepoRouter.route(query, top_k=top_k)
 route_ids = [str(r.repo_id) for r in route_results]
 repos = {
 str(repo.id): repo
 async for repo in Repository.objects.filter(id__in=route_ids, is_deleted=False)
 }
 ranked_repos: list[dict[str, Any]] =
 traces: list[tuple[str, dict[str, Any]]] =
 for result in route_results:
 repo_id = str(result.repo_id)
 repo = repos.get(repo_id)
 if repo is None:
 continue
 item = {
 "repo_id": repo_id,
 "name": repo.name,
 "description": repo.description or "",
 "score": float(getattr(result, "final_score", 0.0)),
 "reason": getattr(result, "match_reason", ""),
 "index_status": repo.index_status,
 "default_branch": repo.default_branch,
 "ai_summary": repo.ai_summary or "",
 }
 ranked_repos.append(item)
 traces.append((RetrievalTrace.Kind.ROUTING, item))
 output_data = {
 "query": query,
 "ranked_repos": ranked_repos,
 "total": len(ranked_repos),
 "run_id": str(run.run_id),
 }
 await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=traces,
 started_at=started_at,
 )
 return Response(output_data, status=status.HTTP_200_OK)
class SearchRagChunksView(McpToolView):
 tool_name = "search_rag_chunks"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(SearchRagChunksRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 repository_id = str(input_data["repository_id"])
 repo, err = await self._get_indexed_repo(repository_id)
 if err is not None:
 return err
 assert repo is not None
 graph_branch, _collection_name = await self._resolve_graph_branch(
 repository_id, repo, input_data.get("branch")
 )
 from services.code_intel import get_provider
 from services.retrieval import HybridSearchService
 result = await HybridSearchService(get_provider).search(
 str(input_data["query"]),
 repository_ids=[repository_id],
 branch_name=graph_branch,
 max_tokens=int(input_data["max_tokens"]),
 top_k=int(input_data["top_k"]),
 )
 results: list[dict[str, Any]] =
 for layer in getattr(result, "layers", ) or:
 if getattr(layer, "layer", None) != "L3":
 continue
 for item in getattr(layer, "items", ) or:
 payload = item.get("payload", {}) or {}
 results.append({
 "chunk_id": str(item.get("id") or payload.get("chunk_id", "")),
 "repo_id": repository_id,
 "branch": graph_branch or (repo.base_branch or repo.default_branch),
 "file_path": payload.get("file_path", ""),
 "line_start": payload.get("start_line"),
 "line_end": payload.get("end_line"),
 "content": payload.get("content", ""),
 "score": item.get("score", 0.0),
 "language": payload.get("language", ""),
 })
 related_edges = [
 _serialize_neighbor(neighbor)
 for neighbors in (
 getattr(result, "hop1_neighbors", ) or,
 getattr(result, "hop2_neighbors", ) or,
 getattr(result, "cross_repo_neighbors", ) or,
 )
 for neighbor in neighbors
 ]
 traces: list[tuple[str, dict[str, Any]]] = [
 (RetrievalTrace.Kind.CHUNK, chunk) for chunk in results
 ]
 traces.extend((RetrievalTrace.Kind.EDGE, edge) for edge in related_edges)
 output_data = {
 "query": input_data["query"],
 "repository_id": repository_id,
 "branch": graph_branch or (repo.base_branch or repo.default_branch),
 "results": results,
 "related_edges": related_edges,
 "total_tokens": getattr(result, "total_tokens", 0) or 0,
 "run_id": str(run.run_id),
 }
 await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=traces,
 started_at=started_at,
 )
 return Response(output_data, status=status.HTTP_200_OK)
class GetRepositoryView(McpToolView):
 tool_name = "get_repository"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(GetRepositoryRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 repository_id = str(input_data["repository_id"])
 try:
 repo = await Repository.objects.aget(id=repository_id, is_deleted=False)
 except Repository.DoesNotExist:
 return error_response(
 "repository_not_found",
 "仓库不存在",
 status_code=status.HTTP_404_NOT_FOUND,
 )
 repository = {
 "repo_id": repository_id,
 "name": repo.name,
 "description": repo.description or "",
 "default_branch": repo.default_branch,
 "base_branch": repo.base_branch or "",
 "index_status": repo.index_status,
 "last_indexed_commit_sha": repo.last_indexed_commit_sha or "",
 "ai_summary": repo.ai_summary or "",
 "ai_summary_status": repo.ai_summary_status,
 }
 output_data = {"repository": repository, "run_id": str(run.run_id)}
 await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=[(RetrievalTrace.Kind.FILE, repository)],
 started_at=started_at,
 )
 return Response(output_data, status=status.HTTP_200_OK)
class ListRepositoryFilesView(McpToolView):
 tool_name = "list_repository_files"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(ListRepositoryFilesRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 repository_id = str(input_data["repository_id"])
 repo, err = await self._get_indexed_repo(repository_id)
 if err is not None:
 return err
 assert repo is not None
 graph_branch, _collection_name = await self._resolve_graph_branch(
 repository_id, repo, input_data.get("branch")
 )
 requested_path = str(input_data.get("path") or "").strip("/")
 recursive = bool(input_data.get("recursive", False))
 page = int(input_data.get("page", 1))
 page_size = int(input_data.get("page_size", 50))
 file_rows = [
 row
 async for row in FileIndex.objects.filter(repository_id=repository_id).order_by("file_path")
 ]
 paths = [row.file_path for row in file_rows]
 if requested_path:
 prefix = requested_path.rstrip("/") + "/"
 paths = [p for p in paths if p == requested_path or p.startswith(prefix)]
 items: list[dict[str, Any]] =
 if recursive:
 for path in paths:
 items.append({"path": path, "name": path.rsplit("/", 1)[-1], "type": "file"})
 else:
 seen_dirs: set[str] = set
 prefix_len = len(requested_path.rstrip("/") + "/") if requested_path else 0
 for path in paths:
 relative = path[prefix_len:] if prefix_len else path
 if "/" in relative:
 dirname = relative.split("/", 1)[0]
 dir_path = f"{requested_path}/{dirname}".strip("/")
 if dir_path not in seen_dirs:
 seen_dirs.add(dir_path)
 items.append({"path": dir_path, "name": dirname, "type": "directory"})
 else:
 items.append({"path": path, "name": relative, "type": "file"})
 total = len(items)
 offset = (page - 1) * page_size
 paged_items = items[offset: offset + page_size]
 output_data = {
 "repository_id": repository_id,
 "branch": graph_branch or (repo.base_branch or repo.default_branch),
 "path": requested_path,
 "items": paged_items,
 "total": total,
 "page": page,
 "page_size": page_size,
 "run_id": str(run.run_id),
 }
 await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=[(RetrievalTrace.Kind.FILE, {"repository_id": repository_id, "path": requested_path, "total": total})],
 started_at=started_at,
 )
 return Response(output_data, status=status.HTTP_200_OK)
class GetRepositoryFileView(McpToolView):
 tool_name = "get_repository_file"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(GetRepositoryFileRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 repository_id = str(input_data["repository_id"])
 repo, err = await self._get_indexed_repo(repository_id)
 if err is not None:
 return err
 assert repo is not None
 graph_branch, collection_name = await self._resolve_graph_branch(
 repository_id, repo, input_data.get("branch")
 )
 file_path = str(input_data["file_path"])
 chunks_raw = await _scroll_file_from_collection(collection_name, file_path)
 resolved_path = file_path
 if not chunks_raw:
 candidates = [
 path for path in await _list_indexed_paths(collection_name)
 if path.endswith(file_path)
 ]
 if len(candidates) == 1:
 resolved_path = candidates[0]
 chunks_raw = await _scroll_file_from_collection(collection_name, resolved_path)
 if not chunks_raw:
 return error_response(
 "file_not_found",
 f"索引中找不到文件: {file_path}",
 status_code=status.HTTP_404_NOT_FOUND,
 )
 chunks_raw.sort(key=lambda chunk: chunk.get("chunk_index", 0))
 start_line = input_data.get("start_line")
 end_line = input_data.get("end_line")
 selected: list[dict[str, Any]] =
 for chunk in chunks_raw:
 chunk_start = chunk.get("start_line", 0) or 0
 chunk_end = chunk.get("end_line", float("inf")) or float("inf")
 if start_line is not None and chunk_end < int(start_line):
 continue
 if end_line is not None and chunk_start > int(end_line):
 continue
 selected.append(chunk)
 lines: list[str] =
 language = ""
 for chunk in selected:
 if not language:
 language = str(chunk.get("language") or "")
 lines.extend(str(chunk.get("content") or "").splitlines)
 max_lines = int(input_data.get("max_lines", 500))
 truncated = len(lines) > max_lines
 returned_lines = lines[:max_lines]
 output_data = {
 "repository_id": repository_id,
 "branch": graph_branch or (repo.base_branch or repo.default_branch),
 "file_path": resolved_path,
 "requested_file_path": file_path,
 "line_start": start_line,
 "line_end": end_line,
 "language": language,
 "content": "\n".join(returned_lines),
 "truncated": truncated,
 "total_chunks": len(chunks_raw),
 "returned_lines": len(returned_lines),
 "max_lines": max_lines,
 "run_id": str(run.run_id),
 }
 await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=[(RetrievalTrace.Kind.FILE, output_data)],
 started_at=started_at,
 )
 return Response(output_data, status=status.HTTP_200_OK)
class FindRelatedChunksView(McpToolView):
 tool_name = "find_related_chunks"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(FindRelatedChunksRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 repository_id = str(input_data["repository_id"])
 repo, err = await self._get_indexed_repo(repository_id)
 if err is not None:
 return err
 assert repo is not None
 graph_branch, _collection_name = await self._resolve_graph_branch(
 repository_id, repo, input_data.get("branch")
 )
 source = await self._resolve_source_chunk(input_data, repository_id, graph_branch)
 if isinstance(source, Response):
 return source
 from services.retrieval.find_related import find_related
 try:
 neighbors = await find_related(
 source["chunk_id"],
 repo_ids=[repository_id],
 relation_types=input_data.get("relation_types") or None,
 hops=int(input_data.get("hops", 1)),
 direction=input_data.get("direction", "both"),
 limit=int(input_data.get("limit", 20)),
 )
 except ValueError as exc:
 return error_response(
 "invalid_params",
 str(exc),
 status_code=status.HTTP_400_BAD_REQUEST,
 )
 related_chunks = [_serialize_neighbor(neighbor) for neighbor in neighbors]
 output_data = {
 "repository_id": repository_id,
 "branch": graph_branch or (repo.base_branch or repo.default_branch),
 "source": source,
 "related_chunks": related_chunks,
 "run_id": str(run.run_id),
 }
 traces = [(RetrievalTrace.Kind.EDGE, item) for item in related_chunks]
 await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=traces,
 started_at=started_at,
 )
 return Response(output_data, status=status.HTTP_200_OK)
 async def _resolve_source_chunk(
 self,
 input_data: dict[str, Any],
 repository_id: str,
 graph_branch: str | None,
 ) -> dict[str, Any] | Response:
 if input_data.get("chunk_id"):
 return {"type": "chunk_id", "chunk_id": str(input_data["chunk_id"])}
 branch_names = ["", graph_branch] if graph_branch else [""]
 if input_data.get("file_path"):
 file_path = str(input_data["file_path"])
 entry = await ChunkRegistry.objects.filter(
 repository_id=repository_id,
 branch_name__in=branch_names,
 file_path=file_path,
 ).order_by("branch_name", "chunk_index").afirst
 if entry is None:
 return error_response(
 "chunk_not_found",
 "指定文件没有可用 chunk",
 status_code=status.HTTP_400_BAD_REQUEST,
 )
 return {
 "type": "file_path",
 "file_path": file_path,
 "chunk_id": str(entry.chunk_id),
 }
 symbol_name = str(input_data.get("symbol_name") or "")
 symbol = await Symbol.objects.filter(
 repository_id=repository_id,
 branch_name__in=branch_names,
 name__iexact=symbol_name,
 chunk_id__isnull=False,
 ).order_by("branch_name", "file_path", "start_line").afirst
 if symbol is None:
 return error_response(
 "symbol_not_found",
 "指定符号没有可用 chunk",
 status_code=status.HTTP_400_BAD_REQUEST,
 )
 return {
 "type": "symbol_name",
 "symbol_name": symbol_name,
 "file_path": symbol.file_path,
 "line_start": symbol.start_line,
 "line_end": symbol.end_line,
 "chunk_id": str(symbol.chunk_id),
 }
class GetFeishuWorkItemContextView(McpToolView):
 tool_name = "get_feishu_work_item_context"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(GetFeishuWorkItemContextRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 try:
 result = await build_work_item_context(
 run=run,
 project_id=str(input_data["project_id"]) if input_data.get("project_id") else None,
 project_key=str(input_data.get("project_key") or ""),
 work_item_type=str(input_data.get("work_item_type") or "story"),
 work_item_id=int(input_data["work_item_id"]),
 fields=list(input_data.get("fields") or ),
 include_comments=bool(input_data.get("include_comments", False)),
 )
 except WorkItemContextError as exc:
 status_map = {
 "project_not_found": status.HTTP_404_NOT_FOUND,
 "feishu_project_not_configured": status.HTTP_400_BAD_REQUEST,
 "feishu_work_item_error": status.HTTP_502_BAD_GATEWAY,
 }
 return error_response(
 exc.code,
 exc.detail,
 status_code=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
 )
 await self._record_agent_decision(
 run,
 action="work_item_context_created",
 payload={
 "context_id": str(result.artifact.id),
 "project_key": result.output["work_item"]["project_key"],
 "work_item_type": result.output["work_item"]["work_item_type"],
 "work_item_id": result.output["work_item"]["id"],
 "document_count": len(result.output["documents"]),
 },
 )
 tool_call = await self._record(
 run,
 input_data=input_data,
 output_data=result.output,
 traces=result.traces,
 started_at=started_at,
 call_status=result.output["status"],
 )
 if tool_call is not None:
 result.artifact.tool_call = tool_call
 await result.artifact.asave(update_fields=["tool_call"])
 return Response(result.output, status=status.HTTP_200_OK)
class CreateFeishuTechnicalPlanView(McpToolView):
 tool_name = "create_feishu_technical_plan"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(CreateFeishuTechnicalPlanRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 try:
 result = await build_work_item_technical_plan(
 run=run,
 context_id=str(input_data["context_id"]),
 repository_ids=[str(repo_id) for repo_id in input_data.get("repository_ids") or ],
 repo_hints=[str(hint) for hint in input_data.get("repo_hints") or ],
 context_chunks=list(input_data.get("context_chunks") or ),
 similar_cases=list(input_data.get("similar_cases") or ),
 title=str(input_data.get("title") or ""),
 folder_token=str(input_data.get("folder_token") or ""),
 create_document=bool(input_data.get("create_document", True)),
 write_comment=bool(input_data.get("write_comment", True)),
 )
 except TechnicalPlanError as exc:
 status_map = {
 "work_item_context_not_found": status.HTTP_404_NOT_FOUND,
 "repository_not_found": status.HTTP_404_NOT_FOUND,
 }
 return error_response(
 exc.code,
 exc.detail,
 status_code=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
 )
 await self._record_agent_decision(
 run,
 action="feishu_technical_plan_created",
 payload={
 "technical_plan_id": str(result.artifact.id),
 "context_id": result.output["context_id"],
 "status": result.output["status"],
 "repository_task_count": len(result.output["repository_tasks"]),
 "document_url": result.output["feishu_document"].get("url", ""),
 },
 )
 tool_call = await self._record(
 run,
 input_data=input_data,
 output_data=result.output,
 traces=result.traces,
 started_at=started_at,
 call_status=result.output["status"],
 )
 if tool_call is not None:
 result.artifact.tool_call = tool_call
 await result.artifact.asave(update_fields=["tool_call"])
 return Response(result.output, status=status.HTTP_200_OK)
class CreateWorkItemRepoTasksView(McpToolView):
 tool_name = "create_work_item_repo_tasks"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(CreateWorkItemRepoTasksRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 try:
 result = await create_repo_tasks_from_technical_plan(
 run=run,
 technical_plan_id=str(input_data["technical_plan_id"]),
 )
 except WorkItemExecutionError as exc:
 status_map = {
 "technical_plan_not_found": status.HTTP_404_NOT_FOUND,
 "repository_not_found": status.HTTP_404_NOT_FOUND,
 }
 return error_response(
 exc.code,
 exc.detail,
 status_code=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
 )
 output_data = {
 "technical_plan_id": str(result.technical_plan.id),
 "tasks": [repo_task_payload(task) for task in result.tasks],
 "total": len(result.tasks),
 "run_id": str(run.run_id),
 }
 await self._record_agent_decision(
 run,
 action="work_item_repo_tasks_created",
 payload={
 "technical_plan_id": str(result.technical_plan.id),
 "task_count": len(result.tasks),
 },
 )
 traces = [
 (
 "file",
 {
 "source": "work_item_repo_task",
 "task_id": str(task.id),
 "repository_id": str(task.repository_id),
 "branch_name": task.branch_name,
 },
 )
 for task in result.tasks
 ]
 tool_call = await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=traces,
 started_at=started_at,
 )
 if tool_call is not None:
 for task in result.tasks:
 task.tool_call = tool_call
 await task.asave(update_fields=["tool_call"])
 return Response(output_data, status=status.HTTP_200_OK)
class ExecuteWorkItemRepoTasksView(McpToolView):
 tool_name = "execute_work_item_repo_tasks"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(ExecuteWorkItemRepoTasksRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 try:
 result = await execute_work_item_repo_tasks(
 run=run,
 technical_plan_id=str(input_data.get("technical_plan_id") or ""),
 task_ids=[str(task_id) for task_id in input_data.get("task_ids") or ],
 create_missing=bool(input_data.get("create_missing", True)),
 dispatch=bool(input_data.get("dispatch", True)),
 create_merge_requests=bool(input_data.get("create_merge_requests", True)),
 write_back=bool(input_data.get("write_back", True)),
 timeout_seconds=int(input_data.get("timeout_seconds") or 3600),
 reviewer_usernames=list(input_data.get("reviewer_usernames") or ),
 )
 except WorkItemExecutionError as exc:
 status_map = {
 "technical_plan_not_found": status.HTTP_404_NOT_FOUND,
 "repo_task_not_found": status.HTTP_404_NOT_FOUND,
 }
 return error_response(
 exc.code,
 exc.detail,
 status_code=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
 )
 await self._record_agent_decision(
 run,
 action="work_item_repo_tasks_executed",
 payload={
 "technical_plan_id": str(result.technical_plan.id),
 "status": result.output["status"],
 "task_count": len(result.tasks),
 "completed": result.output["summary"]["completed"],
 "partial": result.output["summary"]["partial"],
 "failed": result.output["summary"]["failed"],
 },
 )
 traces = [
 (
 "file",
 {
 "source": "work_item_repo_task_execution",
 "task_id": str(task.id),
 "repository_id": str(task.repository_id),
 "status": task.status,
 "mr_url": task.mr_url,
 },
 )
 for task in result.tasks
 ]
 tool_call = await self._record(
 run,
 input_data=input_data,
 output_data=result.output,
 traces=traces,
 started_at=started_at,
 call_status=result.output["status"],
 )
 if tool_call is not None:
 for task in result.tasks:
 task.tool_call = tool_call
 await task.asave(update_fields=["tool_call"])
 return Response(result.output, status=status.HTTP_200_OK)
class AnalyzeRepositoryView(McpToolView):
 tool_name = "analyze_repository"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(AnalyzeRepositoryRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 repository_id = str(input_data["repository_id"])
 repo, err = await self._get_indexed_repo(repository_id)
 if err is not None:
 return err
 assert repo is not None
 graph_branch, _collection_name = await self._resolve_graph_branch(
 repository_id, repo, input_data.get("branch")
 )
 branch = graph_branch or (repo.base_branch or repo.default_branch)
 file_paths = await self._collect_indexed_paths(
 repository_id,
 limit=int(input_data.get("max_files") or 80),
 )
 result = build_repository_analysis(
 repository=repo,
 branch=branch,
 focus=str(input_data.get("focus") or ""),
 file_paths=file_paths,
 context_chunks=list(input_data.get("context_chunks") or ),
 )
 artifact = await McpRepositoryAnalysis.objects.acreate(
 run=run,
 repository=repo,
 branch=branch,
 focus=str(input_data.get("focus") or ""),
 summary=result.payload,
 evidence=result.evidence,
 )
 output_data = {
 "analysis_id": str(artifact.id),
 "repository_id": repository_id,
 "branch": branch,
 "analysis": result.payload,
 "evidence": result.evidence,
 "run_id": str(run.run_id),
 }
 await self._record_agent_decision(
 run,
 action="repository_analysis_created",
 payload={
 "analysis_id": str(artifact.id),
 "repository_id": repository_id,
 "branch": branch,
 "evidence_count": len(result.evidence),
 },
 )
 await self._record_model_usage(run, result.model_usage)
 tool_call = await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=_traces_from_evidence(result.evidence),
 started_at=started_at,
 )
 if tool_call is not None:
 artifact.tool_call = tool_call
 await artifact.asave(update_fields=["tool_call"])
 return Response(output_data, status=status.HTTP_200_OK)
class CreateCodingPlanView(McpToolView):
 tool_name = "create_coding_plan"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(CreateCodingPlanRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 repository_id = str(input_data["repository_id"])
 repo, err = await self._get_indexed_repo(repository_id)
 if err is not None:
 return err
 assert repo is not None
 graph_branch, _collection_name = await self._resolve_graph_branch(
 repository_id, repo, input_data.get("branch")
 )
 branch = graph_branch or (repo.base_branch or repo.default_branch)
 analysis: McpRepositoryAnalysis | None = None
 analysis_summary: dict[str, Any] | None = None
 if input_data.get("analysis_id"):
 try:
 analysis = await McpRepositoryAnalysis.objects.aget(
 id=input_data["analysis_id"],
 repository_id=repository_id,
 )
 except McpRepositoryAnalysis.DoesNotExist:
 return error_response(
 "analysis_not_found",
 "分析 artifact 不存在或不属于该仓库",
 status_code=status.HTTP_404_NOT_FOUND,
 )
 analysis_summary = dict(analysis.summary or {})
 file_paths = await self._collect_indexed_paths(repository_id, limit=120)
 result = build_coding_plan(
 repository=repo,
 branch=branch,
 requirement=str(input_data["requirement"]),
 analysis_summary=analysis_summary,
 file_paths=file_paths,
 context_chunks=list(input_data.get("context_chunks") or ),
 max_steps=int(input_data.get("max_steps") or 8),
 )
 plan = await McpCodingPlan.objects.acreate(
 run=run,
 repository=repo,
 analysis=analysis,
 branch=branch,
 requirement=str(input_data["requirement"]),
 title=str(result.payload.get("title") or repo.name)[:240],
 current_version=1,
 )
 version = await McpCodingPlanVersion.objects.acreate(
 plan=plan,
 run=run,
 version=1,
 plan_body=result.payload,
 affected_files=list(result.payload.get("affected_files") or ),
 steps=list(result.payload.get("steps") or ),
 test_plan=list(result.payload.get("test_plan") or ),
 risks=list(result.payload.get("risks") or ),
 evidence=result.evidence,
 change_summary="Initial MCP coding plan",
 risk_delta={"added":, "reduced": },
 )
 output_data = {
 "plan_id": str(plan.id),
 "version_id": str(version.id),
 "version": version.version,
 "repository_id": repository_id,
 "branch": branch,
 "plan": result.payload,
 "evidence": result.evidence,
 "run_id": str(run.run_id),
 }
 await self._record_agent_decision(
 run,
 action="coding_plan_created",
 payload={
 "plan_id": str(plan.id),
 "version_id": str(version.id),
 "repository_id": repository_id,
 "branch": branch,
 "affected_files": result.payload.get("affected_files") or,
 },
 )
 await self._record_model_usage(run, result.model_usage)
 tool_call = await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=_traces_from_evidence(result.evidence),
 started_at=started_at,
 )
 if tool_call is not None:
 version.tool_call = tool_call
 await version.asave(update_fields=["tool_call"])
 return Response(output_data, status=status.HTTP_200_OK)
class ImproveCodingPlanView(McpToolView):
 tool_name = "improve_coding_plan"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(ImproveCodingPlanRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 try:
 plan = await McpCodingPlan.objects.select_related("repository").aget(
 id=input_data["plan_id"]
 )
 except McpCodingPlan.DoesNotExist:
 return error_response(
 "coding_plan_not_found",
 "编码方案不存在",
 status_code=status.HTTP_404_NOT_FOUND,
 )
 latest = await plan.versions.order_by("-version").afirst
 if latest is None:
 return error_response(
 "coding_plan_not_found",
 "编码方案没有可改进的版本",
 status_code=status.HTTP_404_NOT_FOUND,
 )
 repo = plan.repository
 branch = plan.branch or (repo.base_branch or repo.default_branch)
 result = improve_coding_plan(
 repository=repo,
 branch=branch,
 existing_plan=dict(latest.plan_body or {}),
 feedback=str(input_data["feedback"]),
 context_chunks=list(input_data.get("context_chunks") or ),
 max_steps=int(input_data.get("max_steps") or 10),
 )
 next_version = int(plan.current_version) + 1
 updated_plan = dict(result.payload.get("plan") or {})
 version = await McpCodingPlanVersion.objects.acreate(
 plan=plan,
 run=run,
 version=next_version,
 plan_body=updated_plan,
 affected_files=list(updated_plan.get("affected_files") or ),
 steps=list(updated_plan.get("steps") or ),
 test_plan=list(updated_plan.get("test_plan") or ),
 risks=list(updated_plan.get("risks") or ),
 evidence=result.evidence,
 change_summary=str(result.payload.get("change_summary") or ""),
 risk_delta=dict(result.payload.get("risk_delta") or {}),
 )
 plan.current_version = next_version
 await plan.asave(update_fields=["current_version", "updated_at"])
 output_data = {
 "plan_id": str(plan.id),
 "version_id": str(version.id),
 "version": version.version,
 "repository_id": str(repo.id),
 "branch": branch,
 "plan": updated_plan,
 "change_summary": version.change_summary,
 "risk_delta": version.risk_delta,
 "evidence": result.evidence,
 "run_id": str(run.run_id),
 }
 await self._record_agent_decision(
 run,
 action="coding_plan_improved",
 payload={
 "plan_id": str(plan.id),
 "version_id": str(version.id),
 "version": version.version,
 "feedback_preview": str(input_data["feedback"])[:240],
 },
 )
 await self._record_model_usage(run, result.model_usage)
 tool_call = await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=_traces_from_evidence(result.evidence),
 started_at=started_at,
 )
 if tool_call is not None:
 version.tool_call = tool_call
 await version.asave(update_fields=["tool_call"])
 return Response(output_data, status=status.HTTP_200_OK)
class ExecuteCodingPlanView(McpToolView):
 tool_name = "execute_coding_plan"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(ExecuteCodingPlanRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 plan, version, err = await self._resolve_plan_version(input_data)
 if err is not None:
 return err
 assert plan is not None
 assert version is not None
 retry_of: McpCodingExecutionTrace | None = None
 if input_data.get("retry_of_execution_id"):
 retry_of = await McpCodingExecutionTrace.objects.filter(
 id=input_data["retry_of_execution_id"],
 plan=plan,
 ).afirst
 if retry_of is None:
 return error_response(
 "execution_not_found",
 "重试来源 execution 不存在或不属于该方案",
 status_code=status.HTTP_404_NOT_FOUND,
 )
 trace = await McpCodingExecutionTrace.objects.acreate(
 run=run,
 plan=plan,
 plan_version=version,
 repository=plan.repository,
 retry_of=retry_of,
 retry_count=(retry_of.retry_count + 1) if retry_of else 0,
 branch_name=str(input_data.get("branch_name") or ""),
 target_branch=str(input_data.get("target_branch") or plan.repository.default_branch),
 timeout_seconds=int(input_data.get("timeout_seconds") or 3600),
 )
 dispatch_error = ""
 try:
 await dispatch_execution(
 trace=trace,
 plan=plan,
 version=version,
 branch_name=str(input_data.get("branch_name") or ""),
 target_branch=str(input_data.get("target_branch") or ""),
 timeout_seconds=int(input_data.get("timeout_seconds") or 3600),
 )
 except ExecutionDispatchError as exc:
 dispatch_error = str(exc)
 trace.status = McpCodingExecutionTrace.Status.FAILED
 trace.error = dispatch_error
 trace.recovery_state = {
 "retryable": True,
 "status": trace.status,
 "branch_name": trace.branch_name,
 "target_branch": trace.target_branch,
 "error": dispatch_error,
 }
 await trace.asave(update_fields=["status", "error", "recovery_state", "updated_at"])
 await refresh_execution_trace(trace)
 output_data = {
 **execution_trace_payload(trace),
 "run_id": str(run.run_id),
 }
 await self._record_agent_decision(
 run,
 action="coding_execution_dispatched",
 payload={
 "execution_id": str(trace.id),
 "plan_id": str(plan.id),
 "version_id": str(version.id),
 "status": trace.status,
 "retry_of_execution_id": str(trace.retry_of_id or ""),
 },
 )
 tool_call = await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=,
 started_at=started_at,
 call_status="failed" if trace.status == McpCodingExecutionTrace.Status.FAILED else "ok",
 error=dispatch_error or trace.error,
 )
 if tool_call is not None:
 trace.tool_call = tool_call
 await trace.asave(update_fields=["tool_call"])
 response_status = (
 status.HTTP_200_OK
 if trace.status == McpCodingExecutionTrace.Status.FAILED
 else status.HTTP_202_ACCEPTED
 )
 return Response(output_data, status=response_status)
 async def _resolve_plan_version(
 self,
 input_data: dict[str, Any],
 ) -> tuple[McpCodingPlan | None, McpCodingPlanVersion | None, Response | None]:
 try:
 plan = await McpCodingPlan.objects.select_related("repository").aget(
 id=input_data["plan_id"]
 )
 except McpCodingPlan.DoesNotExist:
 return None, None, error_response(
 "coding_plan_not_found",
 "编码方案不存在",
 status_code=status.HTTP_404_NOT_FOUND,
 )
 if input_data.get("version_id"):
 try:
 version = await McpCodingPlanVersion.objects.aget(
 id=input_data["version_id"],
 plan=plan,
 )
 except McpCodingPlanVersion.DoesNotExist:
 return None, None, error_response(
 "coding_plan_version_not_found",
 "编码方案版本不存在或不属于该方案",
 status_code=status.HTTP_404_NOT_FOUND,
 )
 else:
 version = await plan.versions.order_by("-version").afirst
 if version is None:
 return None, None, error_response(
 "coding_plan_version_not_found",
 "编码方案没有可执行版本",
 status_code=status.HTTP_404_NOT_FOUND,
 )
 return plan, version, None
class GetCodingExecutionView(McpToolView):
 tool_name = "get_coding_execution"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(GetCodingExecutionRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 trace = await McpCodingExecutionTrace.objects.filter(
 id=input_data["execution_id"]
 ).afirst
 if trace is None:
 return error_response(
 "execution_not_found",
 "执行记录不存在",
 status_code=status.HTTP_404_NOT_FOUND,
 )
 await refresh_execution_trace(trace)
 output_data = {
 **execution_trace_payload(trace),
 "run_id": str(run.run_id),
 }
 await self._record_agent_decision(
 run,
 action="coding_execution_status_refreshed",
 payload={
 "execution_id": str(trace.id),
 "status": trace.status,
 "commit_sha": trace.commit_sha,
 },
 )
 tool_call = await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=,
 started_at=started_at,
 )
 if tool_call is not None:
 trace.tool_call = tool_call
 await trace.asave(update_fields=["tool_call"])
 return Response(output_data, status=status.HTTP_200_OK)
class SummarizeBranchView(McpToolView):
 tool_name = "summarize_branch"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(SummarizeBranchRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 resolved = await self._resolve_branch_request(input_data)
 if isinstance(resolved, Response):
 return resolved
 trace, repo, source_branch, target_branch = resolved
 try:
 summary = await summarize_branch(
 repository=repo,
 source_branch=source_branch,
 target_branch=target_branch,
 max_files=int(input_data.get("max_files") or 50),
 trace=trace,
 )
 except MergeRequestToolError as exc:
 error_output_data = {"error_code": "git_platform_error", "detail": str(exc)}
 await self._record(
 run,
 input_data=input_data,
 output_data=error_output_data,
 traces=,
 started_at=started_at,
 call_status="failed",
 error=str(exc),
 )
 return error_response(
 "git_platform_error",
 str(exc),
 status_code=status.HTTP_400_BAD_REQUEST,
 )
 output_data: dict[str, Any] = {
 "execution_id": str(trace.id) if trace is not None else "",
 "repository_id": str(repo.id),
 "source_branch": source_branch,
 "target_branch": target_branch,
 "summary": summary,
 "mr_draft": summary.get("mr_draft") or {},
 "run_id": str(run.run_id),
 }
 await self._record_agent_decision(
 run,
 action="branch_summary_created",
 payload={
 "execution_id": output_data["execution_id"],
 "repository_id": str(repo.id),
 "source_branch": source_branch,
 "target_branch": target_branch,
 "file_count": len(summary.get("files") or ),
 },
 )
 await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=,
 started_at=started_at,
 )
 return Response(output_data, status=status.HTTP_200_OK)
 async def _resolve_branch_request(
 self,
 input_data: dict[str, Any],
 ) -> tuple[McpCodingExecutionTrace | None, Repository, str, str] | Response:
 if input_data.get("execution_id"):
 trace = await McpCodingExecutionTrace.objects.select_related("repository").filter(
 id=input_data["execution_id"]
 ).afirst
 if trace is None:
 return error_response(
 "execution_not_found",
 "执行记录不存在",
 status_code=status.HTTP_404_NOT_FOUND,
 )
 repo = trace.repository
 source_branch = str(input_data.get("source_branch") or trace.branch_name)
 target_branch = str(
 input_data.get("target_branch") or trace.target_branch or repo.default_branch
 )
 return trace, repo, source_branch, target_branch
 try:
 repo = await Repository.objects.aget(
 id=input_data["repository_id"],
 is_deleted=False,
 )
 except Repository.DoesNotExist:
 return error_response(
 "repository_not_found",
 "仓库不存在",
 status_code=status.HTTP_404_NOT_FOUND,
 )
 return (
 None,
 repo,
 str(input_data.get("source_branch") or ""),
 str(input_data.get("target_branch") or repo.default_branch),
 )
class CreateMergeRequestView(SummarizeBranchView):
 tool_name = "create_merge_request"
 async def post(self, request: Request) -> Response:
 run, err = await self._begin(request)
 if err is not None:
 return err
 assert run is not None
 input_data, err = await self._validate(CreateMergeRequestRequestSerializer, request)
 if err is not None:
 return err
 assert input_data is not None
 started_at = time.perf_counter
 resolved = await self._resolve_branch_request(input_data)
 if isinstance(resolved, Response):
 return resolved
 trace, repo, source_branch, target_branch = resolved
 try:
 mr = await create_merge_request(
 repository=repo,
 source_branch=source_branch,
 target_branch=target_branch,
 title=str(input_data.get("title") or ""),
 description=str(input_data.get("description") or ""),
 reviewer_usernames=list(input_data.get("reviewer_usernames") or ),
 remove_source_branch=bool(input_data.get("remove_source_branch", True)),
 trace=trace,
 )
 except MergeRequestToolError as exc:
 error_output_data = {"error_code": "git_platform_error", "detail": str(exc)}
 await self._record(
 run,
 input_data=input_data,
 output_data=error_output_data,
 traces=,
 started_at=started_at,
 call_status="failed",
 error=str(exc),
 )
 return error_response(
 "git_platform_error",
 str(exc),
 status_code=status.HTTP_400_BAD_REQUEST,
 )
 execution_status = trace.status if trace is not None else ""
 output_data: dict[str, Any] = {
 "execution_id": str(trace.id) if trace is not None else "",
 "repository_id": str(repo.id),
 "source_branch": source_branch,
 "target_branch": target_branch,
 "mr": mr,
 "execution_status": execution_status,
 "run_id": str(run.run_id),
 }
 await self._record_agent_decision(
 run,
 action="merge_request_created" if mr.get("success") else "merge_request_failed",
 payload={
 "execution_id": output_data["execution_id"],
 "repository_id": str(repo.id),
 "source_branch": source_branch,
 "target_branch": target_branch,
 "success": bool(mr.get("success")),
 "mr_url": mr.get("mr_url") or "",
 },
 )
 await self._record(
 run,
 input_data=input_data,
 output_data=output_data,
 traces=,
 started_at=started_at,
 call_status="ok" if mr.get("success") else "failed",
 error=str(mr.get("error") or ""),
 )
 return Response(output_data, status=status.HTTP_200_OK)
