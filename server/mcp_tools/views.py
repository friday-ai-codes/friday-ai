"""Friday MCP read tools HTTP endpoints."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable
from typing import Any

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from agents.tools.chat_tools import _list_indexed_paths, _scroll_file_from_collection
from code_relations.models import ChunkRegistry
from codegraph.models import Symbol
from common.authentication import CookieJWTAuthentication
from common.log_context import LogSource, bind_source
from common.request_metrics import arecord_request_metric
from interactions.entry import AccessTokenAuthentication, begin_interaction_run
from interactions.ledger import (
    arecord_event,
    arecord_model_usage,
    arecord_retrieval_trace,
    arecord_tool_call,
)
from interactions.models import InteractionEvent, InteractionRun, RetrievalTrace, ToolCallRecord
from knowledge.exposure import (
    parse_as_of,
    serialize_related,
    serialize_search_results,
    serialize_timeline,
)
from knowledge.retrieval import DeliveryKnowledgeSearchService
from repositories.models import FileIndex, IndexStatus, Repository
from services.branch_utils import resolve_branch_for_query
from services.exclusion import build_matcher_for_repo, log_exclusion_blocked
from services.qdrant_service import QdrantService
from services.repo_mirror import (
    MirrorError,
    ensure_mirror_commit,
    grep_mirror,
    list_mirror_paths,
    read_mirror_file,
)

from .errors import error_response
from .execution_service import (
    ExecutionDispatchError,
    dispatch_execution,
    execution_trace_payload,
    refresh_execution_trace,
)
from .learning_case_service import (
    LearningCaseError,
    create_learning_case_from_technical_plan,
    search_learning_cases,
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
from .orchestration_delegate import delegate_process_runtime, map_canonical_to_coding_plan
from .repository_analysis_service import build_repository_analysis
from .serializers import (
    AnalyzeRepositoryRequestSerializer,
    CreateCodingPlanRequestSerializer,
    CreateFeishuTechnicalPlanRequestSerializer,
    CreateLearningCaseRequestSerializer,
    CreateMergeRequestRequestSerializer,
    CreateWorkItemRepoTasksRequestSerializer,
    ExecuteCodingPlanRequestSerializer,
    ExecuteWorkItemRepoTasksRequestSerializer,
    FindRelatedChunksRequestSerializer,
    GetCodingExecutionRequestSerializer,
    GetEntityTimelineRequestSerializer,
    GetFeishuWorkItemContextRequestSerializer,
    GetRelatedEntitiesRequestSerializer,
    GetRepositoryFileRequestSerializer,
    GetRepositoryRequestSerializer,
    GrepProjectRequestSerializer,
    GrepRepositoryRequestSerializer,
    ImproveCodingPlanRequestSerializer,
    ListRepositoryFilesRequestSerializer,
    LookupProjectByBranchRequestSerializer,
    ReadProjectDocRequestSerializer,
    ReportProjectKnowledgeRequestSerializer,
    ReportProjectStateRequestSerializer,
    ReverseLookupRequestSerializer,
    RouteRepositoriesRequestSerializer,
    SearchDeliveryKnowledgeRequestSerializer,
    SearchLearningCasesRequestSerializer,
    SearchProjectContextRequestSerializer,
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

_delivery_knowledge_service = DeliveryKnowledgeSearchService()


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
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
        return {key: _first_error_detail(value) for key, value in errors.items()}
    if isinstance(errors, list):
        return [_first_error_detail(value) for value in errors]
    return str(errors)


class _FailClosedMatcher:
    """匹配器构造失败时的兜底：判定一切路径为「已排除」（fail-closed，T-22-25）。"""

    def is_excluded(self, rel_path: str) -> bool:  # noqa: ARG002
        return True


async def _exclusion_matcher(repository_id: str) -> Any:
    """获取仓库排除匹配器（EXCL-02 单一匹配器）；构造异常 → fail-closed 兜底匹配器。

    所有 MCP 直读 bare 镜像 / 索引的工具（grep / get_file / list / find_related）
    都经此入口取匹配器，再对读出路径做 ``is_excluded`` 拦截，绝不各自另写过滤。
    """
    try:
        return await build_matcher_for_repo(repository_id)
    except Exception:  # noqa: BLE001 — 构造失败一律 fail-closed（宁可多排不可漏）
        logger.warning("exclusion.matcher_build_failed", repository_id=repository_id)
        return _FailClosedMatcher()


_MIRROR_ERROR_STATUS = {
    "repository_not_found": status.HTTP_404_NOT_FOUND,
    "invalid_params": status.HTTP_400_BAD_REQUEST,
    "mirror_disabled": status.HTTP_400_BAD_REQUEST,
    "mirror_unavailable": status.HTTP_400_BAD_REQUEST,
    "grep_failed": status.HTTP_400_BAD_REQUEST,
    "mirror_fetch_failed": status.HTTP_502_BAD_GATEWAY,
    "git_timeout": status.HTTP_502_BAD_GATEWAY,
}


def _mirror_error_response(exc: MirrorError) -> Response:
    return error_response(
        exc.code,
        exc.detail,
        status_code=_MIRROR_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
    )


_EXT_LANG_MAP = {
    "py": "python",
    "js": "javascript",
    "jsx": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "go": "go",
    "css": "css",
    "html": "html",
    "json": "json",
    "vue": "vue",
    "md": "markdown",
}


def _language_from_path(file_path: str) -> str:
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    return _EXT_LANG_MAP.get(ext, "")


def _traces_from_evidence(evidence: Iterable[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    traces: list[tuple[str, dict[str, Any]]] = []
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

    authentication_classes = [AccessTokenAuthentication, CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]
    tool_name = ""

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
            return error_response(
                "authentication_failed",
                str(exc.detail) if hasattr(exc, "detail") else str(exc),
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        return super().handle_exception(exc)

    async def _begin(self, request: Request) -> tuple[InteractionRun | None, Response | None]:
        # source 改写为 mcp（覆盖中间件 rest 占位）：让本入口日志/指标归到 mcp 维度，
        # 并让 RequestLogContextMiddleware 跳过兜底记录（避免与 _record 的 mcp 指标行重复计数）。
        bind_source(LogSource.MCP)
        # 基类已是 IsAuthenticated，未认证请求在权限层即被 handle_exception 拒为
        # authentication_failed（401），此处不再可能为匿名。保留该 guard 作为纵深防御
        # （兜底「已认证但 request.auth 为 None」的边缘态），错误码对齐 handle_exception 的
        # authentication_failed，避免同一「无可用 token」语义出现两个分叉码。
        if request.auth is None:
            return None, error_response(
                "authentication_failed",
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
        duration_ms = max(int((time.perf_counter() - started_at) * 1000), 0)
        # 指标旁路（RATE-01 / SLA-04）：在 ToolCallRecord 留痕旁记一行 RequestMetric
        # （source=mcp，labels.call_source=工具名 + run_id），best-effort 绝不反噬。
        await arecord_request_metric(
            source=LogSource.MCP.value,
            route=f"mcp:{self.tool_name}",
            method="POST",
            status_code=200 if call_status == "ok" else 500,
            error_class="none" if call_status == "ok" else "system",
            duration_ms=duration_ms,
            labels={"call_source": self.tool_name, "run_id": str(run.run_id)},
        )
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
        paths: list[str] = []
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
        started_at = time.perf_counter()

        from codegraph.services.repo_router_v2 import RepoRouterV2

        query = str(input_data["query"])
        top_k = int(input_data.get("top_k", 3))
        route_result = await RepoRouterV2.route(query, top_k=top_k)
        route_ids = [str(c.repo_id) for c in route_result.candidates]
        repos = {
            str(repo.id): repo
            async for repo in Repository.objects.filter(id__in=route_ids, is_deleted=False)
        }
        ranked_repos: list[dict[str, Any]] = []
        traces: list[tuple[str, dict[str, Any]]] = []
        for candidate in route_result.candidates:
            repo_id = str(candidate.repo_id)
            repo = repos.get(repo_id)
            if repo is None:
                continue
            item = {
                "repo_id": repo_id,
                "name": repo.name,
                "description": repo.overview_text,
                "score": float(candidate.score),
                "reason": candidate.reasoning,
                "confidence": candidate.confidence,
                "sub_project": candidate.sub_project,
                "sub_project_paths": candidate.sub_project_paths,
                "matched_node_paths": candidate.matched_node_paths,
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
            "router_version": route_result.router_version,
            "auto_selected": route_result.auto_selected,
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
        started_at = time.perf_counter()

        # 目标范围解析（mirror grep_repository）：target_repository_ids 来自 serializer
        # （repository_id 单仓便捷参数已并入头部）；all_repositories 时列已索引非删除仓。
        # 访问范围 = 存在 + INDEXED + 非删除仓（复用既有权限模型，不新增 ACL）。
        max_repos = int(input_data.get("max_repos", 10))
        target_ids = [str(rid) for rid in input_data.get("target_repository_ids") or []]
        if not target_ids and input_data.get("all_repositories"):
            target_ids = [
                str(rid)
                async for rid in Repository.objects.filter(
                    is_deleted=False, index_status=IndexStatus.INDEXED
                )
                .order_by("name")
                .values_list("id", flat=True)[:max_repos]
            ]
            if not target_ids:
                return error_response(
                    "repository_not_found",
                    "没有可检索的已索引仓库",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
        target_ids = target_ids[:max_repos]
        single_target = len(target_ids) == 1

        # 逐仓校验：单仓失败保留旧 404/400 行为；多仓某仓不存在/未索引则跳过
        # （不越权、不致命），仅对通过校验的仓检索。
        repos: dict[str, Repository] = {}
        for repository_id in target_ids:
            repo, repo_err = await self._get_indexed_repo(repository_id)
            if repo_err is not None:
                if single_target:
                    return repo_err
                continue
            assert repo is not None
            repos[repository_id] = repo
        valid_ids = list(repos.keys())
        if not valid_ids:
            return error_response(
                "repository_not_found",
                "没有可检索的已索引仓库",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # branch：单仓沿用既有图谱分支解析；多仓各仓走 base 分支
        # （serializer 已禁多仓传 branch），故 branch_name=None。
        graph_branch: str | None = None
        if single_target:
            only_id = valid_ids[0]
            graph_branch, _collection_name = await self._resolve_graph_branch(
                only_id, repos[only_id], input_data.get("branch")
            )

        from services.code_intel import get_provider
        from services.retrieval import HybridSearchService

        # 一次性多仓检索：search_rag 内部已逐仓 build_matcher_for_repo fail-closed 排除
        # + 跨仓合并去重 + 每项打 repository_id，view 不再循环各仓、绝不绕过该 chokepoint。
        result = await HybridSearchService(get_provider()).search(
            str(input_data["query"]),
            repository_ids=valid_ids,
            branch_name=graph_branch,
            max_tokens=int(input_data["max_tokens"]),
            top_k=int(input_data["top_k"]),
        )

        def _branch_for(repo_id: str) -> str | None:
            """每项来源仓库的分支标签：单仓取 graph_branch，多仓取该仓 base 分支。"""
            repo = repos.get(repo_id)
            base = (repo.base_branch or repo.default_branch) if repo is not None else None
            return (graph_branch or base) if single_target else base

        results: list[dict[str, Any]] = []
        for layer in getattr(result, "layers", []) or []:
            if getattr(layer, "layer", None) != "L3":
                continue
            for item in getattr(layer, "items", []) or []:
                payload = item.get("payload", {}) or {}
                # 来源仓库取 item 自带 repository_id（search_rag 已逐项打）；
                # 单仓兼容旧 mock（无该字段）回退到唯一仓 id。
                item_repo_id = str(
                    item.get("repository_id") or (valid_ids[0] if single_target else "")
                )
                results.append({
                    "chunk_id": str(item.get("id") or payload.get("chunk_id", "")),
                    "repo_id": item_repo_id,
                    "branch": _branch_for(item_repo_id),
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
                getattr(result, "hop1_neighbors", []) or [],
                getattr(result, "hop2_neighbors", []) or [],
                getattr(result, "cross_repo_neighbors", []) or [],
            )
            for neighbor in neighbors
        ]
        traces: list[tuple[str, dict[str, Any]]] = [
            (RetrievalTrace.Kind.CHUNK, chunk) for chunk in results
        ]
        traces.extend((RetrievalTrace.Kind.EDGE, edge) for edge in related_edges)
        # 向后兼容：单仓保留既有 repository_id / branch 标量字段；多仓置 None。
        # 新增 repository_ids 回显实际检索的来源仓范围（valid_ids）。
        output_data = {
            "query": input_data["query"],
            "repository_id": valid_ids[0] if single_target else None,
            "repository_ids": valid_ids,
            "branch": _branch_for(valid_ids[0]) if single_target else None,
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


def _estimate_match_tokens(match: dict[str, Any]) -> int:
    """匹配记录的 token 估算（字符数/4 + 结构开销），用于 max_tokens 预算。"""
    chars = len(str(match.get("file_path", ""))) + len(str(match.get("content", "")))
    return max(1, chars // 4) + 8


class GrepRepositoryView(McpToolView):
    """精确文本检索（grep 语义）。

    与 search_rag_chunks 的语义召回互补：对「穷举所有出现位置」类问题
    （字面量 / 符号引用 / 跳转路径枚举），在仓库本地 bare 镜像快照上执行
    ripgrep（缺省回退 git grep），保证确定性全量结果。

    范围：默认单仓（repository_id）；跨仓显式 opt-in（repository_ids 数组
    或 all_repositories=true，受 max_repos 限制），结果按仓库分组返回。
    base 分支默认 pin 到索引 commit，与其余 MCP 工具看到同一快照
    （matches_index=True）。

    输出模式：content（命中行 + 可配置上下文，受 max_tokens 预算约束）/
    files_only（逐文件命中计数，看分布）/ count（仅统计）。
    """

    tool_name = "grep_repository"

    async def _filter_grep_result(
        self,
        result: dict[str, Any],
        repository_id: str,
    ) -> dict[str, Any]:
        """按排除匹配器过滤 grep_mirror 结果，重算计数（fail-closed）。"""
        matcher = await _exclusion_matcher(repository_id)
        orig_matches = result.get("matches") or []
        orig_counts = result.get("file_counts") or []
        kept_matches = [
            m for m in orig_matches if not matcher.is_excluded(str(m.get("file_path", "")))
        ]
        kept_counts = [
            f for f in orig_counts if not matcher.is_excluded(str(f.get("file_path", "")))
        ]
        if len(kept_matches) != len(orig_matches) or len(kept_counts) != len(orig_counts):
            log_exclusion_blocked(
                surface="grep_repository",
                repository_id=repository_id,
                rel_path="",
            )
        total_matches = sum(int(f.get("match_count", 0)) for f in kept_counts)
        return {
            **result,
            "matches": kept_matches,
            "file_counts": kept_counts,
            "total_matches": total_matches,
            "files_with_matches": len(kept_counts),
        }

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(GrepRepositoryRequestSerializer, request)
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()

        max_repos = int(input_data.get("max_repos", 10))
        target_ids = [str(rid) for rid in input_data.get("target_repository_ids") or []]
        if not target_ids and input_data.get("all_repositories"):
            target_ids = [
                str(rid)
                async for rid in Repository.objects.filter(
                    is_deleted=False, index_status=IndexStatus.INDEXED
                )
                .order_by("name")
                .values_list("id", flat=True)[:max_repos]
            ]
            if not target_ids:
                return error_response(
                    "repository_not_found",
                    "没有可检索的已索引仓库",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
        target_ids = target_ids[:max_repos]
        single_target = len(target_ids) == 1

        output_mode = str(input_data.get("output_mode", "content"))
        context_lines = int(input_data.get("context_lines", 0)) if output_mode == "content" else 0
        remaining_tokens = int(input_data.get("max_tokens", 8000))

        repo_results: list[dict[str, Any]] = []
        traces: list[tuple[str, dict[str, Any]]] = []
        grand_total = 0
        any_truncated = False

        for repository_id in target_ids:
            repo, repo_err = await self._get_indexed_repo(repository_id)
            if repo_err is not None:
                if single_target:
                    return repo_err
                repo_results.append({
                    "repository_id": repository_id,
                    "error_code": "repository_unavailable",
                    "error": "仓库不存在或尚未建立索引",
                })
                continue
            assert repo is not None

            try:
                snapshot = await ensure_mirror_commit(repository_id, input_data.get("branch"))
                result = await grep_mirror(
                    snapshot,
                    pattern=str(input_data["pattern"]),
                    regex=bool(input_data.get("regex", False)),
                    case_sensitive=bool(input_data.get("case_sensitive", True)),
                    paths=[str(p) for p in input_data.get("paths") or []],
                    include_globs=[str(g) for g in input_data.get("include_globs") or []],
                    exclude_globs=[str(g) for g in input_data.get("exclude_globs") or []],
                    context_lines=context_lines,
                    max_matches=int(input_data.get("max_matches", 100)),
                )
            except MirrorError as exc:
                if single_target:
                    await self._record(
                        run,
                        input_data=input_data,
                        output_data={"error_code": exc.code, "detail": exc.detail},
                        traces=[],
                        started_at=started_at,
                        call_status="failed",
                        error=exc.detail,
                    )
                    return _mirror_error_response(exc)
                # 跨仓检索：单仓失败不毁掉整次调用，记录后继续
                repo_results.append({
                    "repository_id": repository_id,
                    "name": repo.name,
                    "error_code": exc.code,
                    "error": exc.detail,
                })
                continue

            # fail-closed 排除过滤（EXCL-02 / T-22-22）：剔除被排除文件的命中行与计数，
            # total_matches / files_with_matches 用过滤后口径，避免泄漏被排除文件存在性。
            result = await self._filter_grep_result(result, repository_id)

            entry: dict[str, Any] = {
                "repository_id": repository_id,
                "name": repo.name,
                "branch": snapshot.ref,
                "commit_sha": snapshot.commit_sha,
                "matches_index": snapshot.matches_index,
                "engine": result["engine"],
                "total_matches": result["total_matches"],
                "files_with_matches": result["files_with_matches"],
                "truncated": bool(result["truncated"]),
            }
            if output_mode == "content":
                matches: list[dict[str, Any]] = []
                for match in result["matches"]:
                    cost = _estimate_match_tokens(match)
                    if remaining_tokens - cost < 0:
                        entry["truncated"] = True
                        break
                    remaining_tokens -= cost
                    matches.append(match)
                entry["matches"] = matches
            elif output_mode == "files_only":
                entry["files"] = result["file_counts"]
            grand_total += int(result["total_matches"])
            any_truncated = any_truncated or bool(entry["truncated"])
            repo_results.append(entry)

            matched_files = sorted(
                {str(f["file_path"]) for f in result["file_counts"]}
            )
            traces.extend(
                (
                    RetrievalTrace.Kind.FILE,
                    {
                        "source": "grep_repository",
                        "repository_id": repository_id,
                        "file_path": file_path,
                        "commit_sha": snapshot.commit_sha,
                    },
                )
                for file_path in matched_files[:20]
            )

        output_data = {
            "pattern": input_data["pattern"],
            "output_mode": output_mode,
            "repositories": repo_results,
            "total_matches": grand_total,
            "truncated": any_truncated,
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
        started_at = time.perf_counter()

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
            "description": repo.overview_text,
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
        started_at = time.perf_counter()

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

        # fail-closed 排除过滤（EXCL-02 / T-22-23）：被排除文件不进 items；纯由被排除
        # 文件构成的目录因其文件全部移除而不再生成目录项。
        matcher = await _exclusion_matcher(repository_id)
        kept_paths = [p for p in paths if not matcher.is_excluded(str(p))]
        if len(kept_paths) != len(paths):
            log_exclusion_blocked(
                surface="list_repository_files",
                repository_id=repository_id,
                rel_path="",
            )
        paths = kept_paths

        items: list[dict[str, Any]] = []
        if recursive:
            for path in paths:
                items.append({"path": path, "name": path.rsplit("/", 1)[-1], "type": "file"})
        else:
            seen_dirs: set[str] = set()
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
        paged_items = items[offset : offset + page_size]
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
    """读取仓库单文件。

    优先走本地 bare 镜像（git show，行号精确、内容全量、source="git"）；
    镜像不可用（未启用 / fetch 失败 / 文件不在快照中）时回退 Qdrant 索引
    chunk 拼接路径（source="index"），保持旧行为不回退。
    """

    tool_name = "get_repository_file"

    async def _excluded_response(
        self,
        repository_id: str,
        *paths: str,
    ) -> Response | None:
        """对 requested / resolved 路径做 fail-closed 排除判定；命中 → 「已排除」错误。

        resolved_path 必须复判（防后缀解析绕过，T-22-21）。命中绝不返回任何 content。
        """
        matcher = await _exclusion_matcher(repository_id)
        for path in paths:
            if path and matcher.is_excluded(str(path)):
                log_exclusion_blocked(
                    surface="get_repository_file",
                    repository_id=repository_id,
                    rel_path=str(path),
                )
                return error_response(
                    "file_excluded",
                    "文件已被排除策略屏蔽",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
        return None

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(GetRepositoryFileRequestSerializer, request)
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()

        repository_id = str(input_data["repository_id"])
        repo, err = await self._get_indexed_repo(repository_id)
        if err is not None:
            return err
        assert repo is not None
        graph_branch, collection_name = await self._resolve_graph_branch(
            repository_id, repo, input_data.get("branch")
        )
        file_path = str(input_data["file_path"])
        start_line = input_data.get("start_line")
        end_line = input_data.get("end_line")
        max_lines = int(input_data.get("max_lines", 500))
        branch_label = graph_branch or (repo.base_branch or repo.default_branch)

        mirror_hit = await self._read_from_mirror(
            repository_id, input_data.get("branch"), file_path
        )
        if mirror_hit is not None:
            resolved_path, full_text, snapshot = mirror_hit
            excluded = await self._excluded_response(repository_id, file_path, resolved_path)
            if excluded is not None:
                return excluded
            all_lines = full_text.splitlines()
            total_lines = len(all_lines)
            slice_start = int(start_line) - 1 if start_line is not None else 0
            slice_end = int(end_line) if end_line is not None else total_lines
            selected_lines = all_lines[slice_start:slice_end]
            truncated = len(selected_lines) > max_lines
            returned_lines = selected_lines[:max_lines]
            output_data = {
                "repository_id": repository_id,
                "branch": branch_label,
                "file_path": resolved_path,
                "requested_file_path": file_path,
                "line_start": start_line,
                "line_end": end_line,
                "language": _language_from_path(resolved_path),
                "content": "\n".join(returned_lines),
                "truncated": truncated,
                "total_chunks": 0,
                "returned_lines": len(returned_lines),
                "max_lines": max_lines,
                "source": "git",
                "commit_sha": snapshot.commit_sha,
                "total_lines": total_lines,
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

        excluded = await self._excluded_response(repository_id, file_path, resolved_path)
        if excluded is not None:
            return excluded

        chunks_raw.sort(key=lambda chunk: chunk.get("chunk_index", 0))
        selected: list[dict[str, Any]] = []
        for chunk in chunks_raw:
            chunk_start = chunk.get("start_line", 0) or 0
            chunk_end = chunk.get("end_line", float("inf")) or float("inf")
            if start_line is not None and chunk_end < int(start_line):
                continue
            if end_line is not None and chunk_start > int(end_line):
                continue
            selected.append(chunk)

        lines: list[str] = []
        language = ""
        for chunk in selected:
            if not language:
                language = str(chunk.get("language") or "")
            lines.extend(str(chunk.get("content") or "").splitlines())
        truncated = len(lines) > max_lines
        returned_lines = lines[:max_lines]
        output_data = {
            "repository_id": repository_id,
            "branch": branch_label,
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
            "source": "index",
            "commit_sha": "",
            "total_lines": len(lines),
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

    async def _read_from_mirror(
        self,
        repository_id: str,
        branch: str | None,
        file_path: str,
    ) -> tuple[str, str, Any] | None:
        """尝试从本地镜像读文件；任何不可用情形返回 None 走索引回退。"""
        try:
            snapshot = await ensure_mirror_commit(repository_id, branch)
            text = await read_mirror_file(snapshot, file_path)
            resolved_path = file_path
            if text is None:
                candidates = [
                    path for path in await list_mirror_paths(snapshot)
                    if path.endswith(file_path)
                ]
                if len(candidates) == 1:
                    resolved_path = candidates[0]
                    text = await read_mirror_file(snapshot, resolved_path)
            if text is None:
                return None
            return resolved_path, text, snapshot
        except MirrorError as exc:
            logger.info(
                "repo_mirror_file_fallback_index",
                repository_id=repository_id,
                file_path=file_path,
                code=exc.code,
                detail=exc.detail,
            )
            return None


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
        started_at = time.perf_counter()

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
        # fail-closed 排除过滤（EXCL-02 / T-22-24）：返回邻居前剔除被排除文件（防御性
        # 兜底，与 22-03 hybrid_search 邻居过滤同口径，此 view 自行组装故需独立过滤）。
        matcher = await _exclusion_matcher(repository_id)
        kept_chunks = [
            chunk
            for chunk in related_chunks
            if not matcher.is_excluded(str(chunk.get("file_path", "")))
        ]
        if len(kept_chunks) != len(related_chunks):
            log_exclusion_blocked(
                surface="find_related_chunks",
                repository_id=repository_id,
                rel_path="",
            )
        related_chunks = kept_chunks
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
            ).order_by("branch_name", "chunk_index").afirst()
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
        ).order_by("branch_name", "file_path", "start_line").afirst()
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


class ReverseLookupView(McpToolView):
    """片段→需求反查 MCP 工具（Phase 34 RREF-01）。

    与 REST `repositories.reverse_lookup_views.ReverseLookupView` 同形返回，复用
    `services.reverse_lookup.reverse_lookup`（纯读、fail-closed、默认当前视图）。
    鉴权沿用基类 AccessToken/CookieJWT + IsAuthenticated。
    """

    tool_name = "reverse_lookup_requirements"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(ReverseLookupRequestSerializer, request)
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()

        from services.reverse_lookup import reverse_lookup

        file_path = str(input_data.get("file_path") or "").strip() or None
        chunk_id = str(input_data["chunk_id"]) if input_data.get("chunk_id") else None
        result = await reverse_lookup(
            str(input_data["repository_id"]),
            file_path=file_path,
            line=input_data.get("line"),
            chunk_id=chunk_id,
            branch_name=str(input_data.get("branch") or ""),
        )
        output_data = {**result, "run_id": str(run.run_id)}
        traces: list[tuple[str, dict[str, Any]]] = [
            (RetrievalTrace.Kind.EDGE, {"source": "reverse_lookup", **item})
            for item in result["related_work_items"]
        ]
        traces.extend(
            (RetrievalTrace.Kind.EDGE, {"source": "reverse_lookup", **item})
            for item in result["related_documents"]
        )
        await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=traces,
            started_at=started_at,
        )
        return Response(output_data, status=status.HTTP_200_OK)


def _project_summary(project: Any) -> dict[str, Any]:
    """项目摘要（候选/命中回显，纯标量）。"""
    return {
        "id": str(project.id),
        "name": project.name,
        "status": project.status,
        "space_id": str(project.space_id),
        "feishu_project_key": project.feishu_project_key,
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
        started_at = time.perf_counter()

        try:
            result = await build_work_item_context(
                run=run,
                project_id=str(input_data["project_id"]) if input_data.get("project_id") else None,
                project_key=str(input_data.get("project_key") or ""),
                work_item_type=str(input_data.get("work_item_type") or "story"),
                work_item_id=int(input_data["work_item_id"]),
                fields=list(input_data.get("fields") or []),
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
        started_at = time.perf_counter()

        # actor 解析（T-94-03-ELEV）：从 request.user 取发起编排用户透传 delegate（召回权限 actor）；
        # 非真实用户 → None，召回 stage fail-closed 空召回（文档化降级，不绕权限）。
        user = request.user
        actor = (
            user
            if getattr(user, "is_authenticated", False) and getattr(user, "id", None) is not None
            else None
        )

        try:
            result = await build_work_item_technical_plan(
                run=run,
                context_id=str(input_data["context_id"]),
                repository_ids=[str(repo_id) for repo_id in input_data.get("repository_ids") or []],
                repo_hints=[str(hint) for hint in input_data.get("repo_hints") or []],
                context_chunks=list(input_data.get("context_chunks") or []),
                similar_cases=list(input_data.get("similar_cases") or []),
                title=str(input_data.get("title") or ""),
                folder_token=str(input_data.get("folder_token") or ""),
                create_document=bool(input_data.get("create_document", True)),
                write_comment=bool(input_data.get("write_comment", True)),
                actor=actor,
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
        started_at = time.perf_counter()

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
        started_at = time.perf_counter()

        try:
            result = await execute_work_item_repo_tasks(
                run=run,
                technical_plan_id=str(input_data.get("technical_plan_id") or ""),
                task_ids=[str(task_id) for task_id in input_data.get("task_ids") or []],
                create_missing=bool(input_data.get("create_missing", True)),
                dispatch=bool(input_data.get("dispatch", True)),
                create_merge_requests=bool(input_data.get("create_merge_requests", True)),
                write_back=bool(input_data.get("write_back", True)),
                timeout_seconds=int(input_data.get("timeout_seconds") or 3600),
                reviewer_usernames=list(input_data.get("reviewer_usernames") or []),
                # 观测归因（101 WR-01）：MCP 链真实触发用户 = PAT 所有者（request.user）；
                # InteractionRun 无 user 字段，必须由入口显式透传。
                initiated_by_user_id=(
                    str(request.user.id) if getattr(request.user, "id", None) else None
                ),
                # Phase 103 AGENT-01：ORM User 实例（桥接会话 created_by → mint 任务 token），
                # 与上面的字符串归因并行不混用。
                initiating_user=(
                    request.user if getattr(request.user, "id", None) else None
                ),
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


class CreateLearningCaseView(McpToolView):
    tool_name = "create_learning_case"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(CreateLearningCaseRequestSerializer, request)
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()

        try:
            result = await create_learning_case_from_technical_plan(
                run=run,
                technical_plan_id=str(input_data["technical_plan_id"]),
                outcome=str(input_data.get("outcome") or "unknown"),
                root_cause=str(input_data.get("root_cause") or ""),
                solution_notes=str(input_data.get("solution_notes") or ""),
                tests=[str(item) for item in input_data.get("tests") or []],
            )
        except LearningCaseError as exc:
            status_map = {"technical_plan_not_found": status.HTTP_404_NOT_FOUND}
            return error_response(
                exc.code,
                exc.detail,
                status_code=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
            )

        await self._record_agent_decision(
            run,
            action="learning_case_created",
            payload={
                "learning_case_id": result.output["learning_case_id"],
                "technical_plan_id": str(input_data["technical_plan_id"]),
                "outcome": result.output["case"]["outcome"],
            },
        )
        tool_call = await self._record(
            run,
            input_data=input_data,
            output_data=result.output,
            traces=result.traces,
            started_at=started_at,
        )
        if tool_call is not None:
            result.artifact.tool_call = tool_call
            await result.artifact.asave(update_fields=["tool_call"])
        return Response(result.output, status=status.HTTP_200_OK)


class SearchLearningCasesView(McpToolView):
    tool_name = "search_learning_cases"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(SearchLearningCasesRequestSerializer, request)
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()

        results = await search_learning_cases(
            query=str(input_data.get("query") or ""),
            work_item_type=str(input_data.get("work_item_type") or ""),
            repo_hints=[str(item) for item in input_data.get("repo_hints") or []],
            file_hints=[str(item) for item in input_data.get("file_hints") or []],
            symbol_hints=[str(item) for item in input_data.get("symbol_hints") or []],
            limit=int(input_data.get("limit") or 5),
            user=request.user,
        )
        output_data = {
            "query": str(input_data.get("query") or ""),
            "results": results,
            "total": len(results),
            "run_id": str(run.run_id),
        }
        await self._record_agent_decision(
            run,
            action="learning_cases_searched",
            payload={
                "query": output_data["query"],
                "result_count": len(results),
            },
        )
        traces = [
            (
                "file",
                {
                    "source": "learning_case",
                    "case_id": result.get("case_id", ""),
                    "score": result.get("score", 0),
                    "title": result.get("title", ""),
                },
            )
            for result in results
        ]
        await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=traces,
            started_at=started_at,
        )
        return Response(output_data, status=status.HTTP_200_OK)


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
        started_at = time.perf_counter()

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
            context_chunks=list(input_data.get("context_chunks") or []),
        )
        artifact = await McpRepositoryAnalysis.objects.acreate(
            run=run,
            repository=repo,
            branch=branch,
            focus=str(input_data.get("focus") or ""),
            summary=result.payload,
            evidence=result.evidence,
        )
        from knowledge import ingestion  # lazy import 防循环

        # KNOW-03：MCP 产物入统一知识库（INV-6 唯一通路，on_commit + 后台，异常自吞不阻塞）；
        # initiated_by_user_id 绑定触发用户，后台摄取日志可归因（无触发用户的调用点缺省 system）。
        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest(
                "mcp_repository_analysis", str(artifact.id), "mcp_analysis_created"
            ),
            initiated_by_user_id=str(request.user.id),
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
        started_at = time.perf_counter()

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

        # actor 解析（T-94-04-ELEV）：从 request.user 取发起编排用户透传 delegate（召回权限 actor）；
        # 非真实用户 → None，召回 stage fail-closed 空召回（文档化降级，不绕权限）。
        user = request.user
        actor = (
            user
            if getattr(user, "is_authenticated", False) and getattr(user, "id", None) is not None
            else None
        )

        # UNIFY-04：方案生成 delegate 到统一编排，include_repos=[repository_id] 约束**只跑单仓**
        # （Open Q2 决议）；绝不在 MCP 层重写拆分/路由/调研/融合（复用 Plan 03 共享核心）。
        # UNIFY-02：带 analysis 时把 summary 作为编排输入证据注入（analysis_id 从"仅挂 FK"
        # 升级为真实证据输入，merge 阶段消费）。
        requirement = str(input_data["requirement"])
        extra_evidence = (
            [
                {
                    "kind": "repository_analysis",
                    "analysis_id": str(analysis.id),
                    "summary": analysis.summary,
                }
            ]
            if analysis
            else None
        )
        delegate = await delegate_process_runtime(
            requirement_text=requirement,
            work_item=None,
            include_repos=[repository_id],
            created_by=actor,
            extra_evidence=extra_evidence,
        )
        content = delegate.content if isinstance(delegate.content, dict) else {}
        # WR-03：恢复 MCP run 维度 token/成本归因——delegate 回传本次编排聚合用量，落本 run
        # （编排 adapters 的 call_source 维度记录仍在原行保留，不重复 / 不互相复制）。best-effort，
        # 无用量则跳过（不落零行）。
        if delegate.model_usage:
            await self._record_model_usage(run, delegate.model_usage)
        # canonical execution_plan 该仓 task → 旧单仓响应/落库字段映射（显式白名单，T-94-04-INFO）。
        plan_payload = map_canonical_to_coding_plan(
            content=content,
            repository=repo,
            branch=branch,
            requirement=requirement,
        )
        evidence = [
            {"kind": "file", "file_path": path, "reason": "方案影响文件候选"}
            for path in plan_payload["affected_files"]
        ]

        # McpCodingPlan / McpCodingPlanVersion 继续落库（兼容旧调用方，A5 字段全保留）；
        # plan_body 优先 canonical content（挂起/失败态为 {} 时回退映射后单仓 payload）。
        plan = await McpCodingPlan.objects.acreate(
            run=run,
            repository=repo,
            analysis=analysis,
            branch=branch,
            requirement=requirement,
            title=str(plan_payload.get("title") or repo.name)[:240],
            current_version=1,
        )
        version = await McpCodingPlanVersion.objects.acreate(
            plan=plan,
            run=run,
            version=1,
            plan_body=content or plan_payload,
            affected_files=list(plan_payload.get("affected_files") or []),
            steps=list(plan_payload.get("steps") or []),
            test_plan=list(plan_payload.get("test_plan") or []),
            risks=list(plan_payload.get("risks") or []),
            evidence=evidence,
            change_summary="Initial MCP coding plan",
            risk_delta={"added": [], "reduced": []},
        )
        from knowledge import ingestion  # lazy import 防循环

        # KNOW-03：MCP 产物入统一知识库（INV-6 唯一通路，on_commit + 后台，异常自吞不阻塞）；
        # initiated_by_user_id 绑定触发用户，后台摄取日志可归因（无触发用户的调用点缺省 system）。
        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest("mcp_coding_plan", str(plan.id), "mcp_coding_plan_created"),
            initiated_by_user_id=str(request.user.id),
        )
        # 响应外形兼容：保留全部既有键（plan_id/version_id/version/repository_id/branch/plan/
        # evidence/run_id）+ 新增可选 session_id（partial 续推钥匙）+ status（delegate 终态映射）。
        output_data = {
            "plan_id": str(plan.id),
            "version_id": str(version.id),
            "version": version.version,
            "repository_id": repository_id,
            "branch": branch,
            "plan": plan_payload,
            "evidence": evidence,
            "run_id": str(run.run_id),
            "session_id": str(delegate.session.id),
            "status": delegate.status,
        }
        await self._record_agent_decision(
            run,
            action="coding_plan_created",
            payload={
                "plan_id": str(plan.id),
                "version_id": str(version.id),
                "repository_id": repository_id,
                "branch": branch,
                "affected_files": plan_payload.get("affected_files") or [],
            },
        )
        tool_call = await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=_traces_from_evidence(evidence),
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
        started_at = time.perf_counter()

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
        latest = await plan.versions.order_by("-version").afirst()
        if latest is None:
            return error_response(
                "coding_plan_not_found",
                "编码方案没有可改进的版本",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        repo = plan.repository
        branch = plan.branch or (repo.base_branch or repo.default_branch)
        feedback = str(input_data["feedback"])

        # actor 解析（T-104-02，照抄 create 先例）：从 request.user 取发起编排用户透传 delegate
        # （召回权限 actor）；非真实用户 → None，召回 stage fail-closed 空召回（不绕权限）。
        user = request.user
        actor = (
            user
            if getattr(user, "is_authenticated", False) and getattr(user, "id", None) is not None
            else None
        )

        # UNIFY-01：改版语义 = 携带 feedback 的编排重跑。requirement_text 三段结构（per CONTEXT
        # 锁定）：原始需求 + 最新版本方案摘要（version 表列，形态稳定）+ 用户 feedback；
        # context_chunks 若提供则以 JSON 行折入第四段（request 键集不变的兑现方式）。
        latest_summary = json.dumps(
            {
                "title": latest.plan_body.get("title") if isinstance(latest.plan_body, dict) else "",
                "affected_files": latest.affected_files,
                "steps": latest.steps,
            },
            ensure_ascii=False,
        )[:2000]
        sections = [
            f"## 原始需求\n\n{plan.requirement}",
            f"## 最新方案摘要（v{latest.version}）\n\n{latest_summary}",
            f"## 用户改版反馈\n\n{feedback}",
        ]
        context_chunks = list(input_data.get("context_chunks") or [])
        if context_chunks:
            chunk_lines = "\n".join(
                json.dumps(chunk, ensure_ascii=False, default=str) for chunk in context_chunks
            )
            sections.append(f"## 补充上下文\n\n{chunk_lines}")
        requirement_text = "\n\n".join(sections)

        # 收敛到统一编排（镜像 create 先例）：include_repos=[repository_id] 单仓约束。
        # UNIFY-02：plan 挂有 analysis 时把 summary 作为编排输入证据注入（同 create 同型）。
        extra_evidence = None
        if plan.analysis_id:
            analysis = await McpRepositoryAnalysis.objects.filter(id=plan.analysis_id).afirst()
            if analysis is not None:
                extra_evidence = [
                    {
                        "kind": "repository_analysis",
                        "analysis_id": str(analysis.id),
                        "summary": analysis.summary,
                    }
                ]
        delegate = await delegate_process_runtime(
            requirement_text=requirement_text,
            work_item=None,
            include_repos=[str(plan.repository_id)],
            created_by=actor,
            extra_evidence=extra_evidence,
        )
        content = delegate.content if isinstance(delegate.content, dict) else {}
        # WR-03：delegate 回传本次编排聚合用量，落 MCP run 维度（归因不回退）。best-effort。
        if delegate.model_usage:
            await self._record_model_usage(run, delegate.model_usage)
        # canonical execution_plan 该仓 task → 旧单仓响应/落库字段映射（显式白名单）。
        # requirement 传原需求、非 feedback 块——响应外形兼容。
        plan_payload = map_canonical_to_coding_plan(
            content=content,
            repository=repo,
            branch=branch,
            requirement=plan.requirement,
        )
        evidence = [
            {"kind": "file", "file_path": path, "reason": "方案影响文件候选"}
            for path in plan_payload["affected_files"]
        ]

        # WR-01（review 104）：failed 态不产退化版本、不推进 current_version——
        # execute_coding_plan 不带 version_id 时默认取最新版本，一次瞬时编排失败不得把
        # "当前可执行方案"静默替换成空方案。响应键集保持 snapshot 不变：version/version_id
        # 回填改版前最新版本，status="failed" + session_id 供排障；不触发 ingestion。
        if delegate.status == "failed":
            output_data = {
                "plan_id": str(plan.id),
                "version_id": str(latest.id),
                "version": latest.version,
                "repository_id": str(repo.id),
                "branch": branch,
                "plan": plan_payload,
                "change_summary": f"编排改版失败（未产新版本）：{feedback[:200]}",
                "risk_delta": {"added": [], "reduced": []},
                "evidence": evidence,
                "run_id": str(run.run_id),
                "session_id": str(delegate.session.id),
                "status": delegate.status,
            }
            await self._record_agent_decision(
                run,
                action="coding_plan_improve_failed",
                payload={
                    "plan_id": str(plan.id),
                    "version": latest.version,
                    "feedback_preview": feedback[:240],
                },
            )
            await self._record(
                run,
                input_data=input_data,
                output_data=output_data,
                traces=[],
                started_at=started_at,
                call_status="failed",
                error="编排失败，未产新版本（current_version 未推进）",
            )
            return Response(output_data, status=status.HTTP_200_OK)

        # 版本递增语义不变：current_version+1；plan_body 优先 canonical content
        # （partial 为 {} 时回退映射后单仓 payload，镜像 create 回退语义）。
        next_version = int(plan.current_version) + 1
        version = await McpCodingPlanVersion.objects.acreate(
            plan=plan,
            run=run,
            version=next_version,
            plan_body=content or plan_payload,
            affected_files=list(plan_payload.get("affected_files") or []),
            steps=list(plan_payload.get("steps") or []),
            test_plan=list(plan_payload.get("test_plan") or []),
            risks=list(plan_payload.get("risks") or []),
            evidence=evidence,
            change_summary=f"编排改版 v{next_version}（status={delegate.status}）：{feedback[:200]}",
            risk_delta={"added": [], "reduced": []},
        )
        plan.current_version = next_version
        await plan.asave(update_fields=["current_version", "updated_at"])
        from knowledge import ingestion  # lazy import 防循环

        # KNOW-03：MCP 产物入统一知识库（INV-6 唯一通路，on_commit + 后台，异常自吞不阻塞）；
        # 同一 plan 重摄：content 变更走版本翻转，未变走 hash 短路，天然幂等；
        # initiated_by_user_id 绑定触发用户，后台摄取日志可归因（无触发用户的调用点缺省 system）。
        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest("mcp_coding_plan", str(plan.id), "mcp_coding_plan_improved"),
            initiated_by_user_id=str(request.user.id),
        )

        output_data = {
            "plan_id": str(plan.id),
            "version_id": str(version.id),
            "version": version.version,
            "repository_id": str(repo.id),
            "branch": branch,
            "plan": plan_payload,
            "change_summary": version.change_summary,
            "risk_delta": version.risk_delta,
            "evidence": evidence,
            "run_id": str(run.run_id),
            "session_id": str(delegate.session.id),
            "status": delegate.status,
        }
        await self._record_agent_decision(
            run,
            action="coding_plan_improved",
            payload={
                "plan_id": str(plan.id),
                "version_id": str(version.id),
                "version": version.version,
                "feedback_preview": feedback[:240],
            },
        )
        tool_call = await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=_traces_from_evidence(evidence),
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
        started_at = time.perf_counter()

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
            ).afirst()
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
                # Phase 103 AGENT-01：发起用户（PAT 所有者）透传为桥接会话 created_by，
                # 使 MCP 链 mint 任务级短 TTL token（与 initiated_by_user_id 归因并行不混用）。
                initiating_user=(
                    request.user if getattr(request.user, "id", None) else None
                ),
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
        from knowledge import ingestion  # lazy import 防循环

        # KNOW-03：MCP 产物入统一知识库（INV-6 唯一通路，on_commit + 后台，异常自吞不阻塞）；
        # 放 refresh_execution_trace 之后——摄取时刻 trace 状态更完整；
        # initiated_by_user_id 绑定触发用户，后台摄取日志可归因（无触发用户的调用点缺省 system）。
        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest(
                "mcp_execution_trace", str(trace.id), "mcp_execution_created"
            ),
            initiated_by_user_id=str(request.user.id),
        )
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
            traces=[],
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
            version = await plan.versions.order_by("-version").afirst()
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
        started_at = time.perf_counter()

        trace = await McpCodingExecutionTrace.objects.filter(
            id=input_data["execution_id"]
        ).afirst()
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
            traces=[],
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
        started_at = time.perf_counter()

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
                traces=[],
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
                "file_count": len(summary.get("files") or []),
            },
        )
        await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=[],
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
            ).afirst()
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
        started_at = time.perf_counter()

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
                reviewer_usernames=list(input_data.get("reviewer_usernames") or []),
                remove_source_branch=bool(input_data.get("remove_source_branch", True)),
                trace=trace,
            )
        except MergeRequestToolError as exc:
            error_output_data = {"error_code": "git_platform_error", "detail": str(exc)}
            await self._record(
                run,
                input_data=input_data,
                output_data=error_output_data,
                traces=[],
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
            traces=[],
            started_at=started_at,
            call_status="ok" if mr.get("success") else "failed",
            error=str(mr.get("error") or ""),
        )
        return Response(output_data, status=status.HTTP_200_OK)


class SearchDeliveryKnowledgeView(McpToolView):
    tool_name = "search_delivery_knowledge"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(SearchDeliveryKnowledgeRequestSerializer, request)
        if err is not None:
            return err
        assert input_data is not None
        try:
            as_of = parse_as_of(input_data.get("as_of"))
        except ValueError as exc:
            return error_response("invalid_params", str(exc), status_code=status.HTTP_400_BAD_REQUEST)
        started_at = time.perf_counter()

        results = await _delivery_knowledge_service.search_similar(
            str(input_data["query"]),
            user=request.user,
            top_k=int(input_data.get("top_k") or 5),
            project_ids=[str(p) for p in input_data.get("project_ids") or []] or None,
            repository_ids=[str(r) for r in input_data.get("repository_ids") or []] or None,
            entity_kinds=[str(k) for k in input_data.get("entity_kinds") or []] or None,
            as_of=as_of,
            include_superseded=bool(input_data.get("include_superseded")),
        )
        serialized = serialize_search_results(results)
        output_data = {
            "query": str(input_data["query"]),
            "results": serialized,
            "total": len(serialized),
            "as_of": as_of.isoformat() if as_of else None,
            "run_id": str(run.run_id),
        }
        await self._record_agent_decision(
            run,
            action="delivery_knowledge_searched",
            payload={"query": output_data["query"], "result_count": len(serialized)},
        )
        traces = [
            (
                RetrievalTrace.Kind.FILE,
                {
                    "source": "delivery_knowledge",
                    "entity_id": item.get("entity_id", ""),
                    "score": item.get("score", 0),
                    "title": item.get("title", ""),
                },
            )
            for item in serialized
        ]
        await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=traces,
            started_at=started_at,
        )
        return Response(output_data, status=status.HTTP_200_OK)


class GetEntityTimelineView(McpToolView):
    tool_name = "get_entity_timeline"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(GetEntityTimelineRequestSerializer, request)
        if err is not None:
            return err
        assert input_data is not None
        try:
            as_of = parse_as_of(input_data.get("as_of"))
        except ValueError as exc:
            return error_response("invalid_params", str(exc), status_code=status.HTTP_400_BAD_REQUEST)
        started_at = time.perf_counter()

        entity_id = input_data["entity_id"]
        nodes = await _delivery_knowledge_service.get_timeline(
            entity_id,
            user=request.user,
            include_superseded=bool(input_data.get("include_superseded")),
            as_of=as_of,
        )
        serialized = serialize_timeline(nodes)
        output_data = {
            "entity_id": str(entity_id),
            "nodes": serialized,
            "total": len(serialized),
            "run_id": str(run.run_id),
        }
        await self._record_agent_decision(
            run,
            action="entity_timeline_fetched",
            payload={"entity_id": str(entity_id), "node_count": len(serialized)},
        )
        traces = [
            (
                RetrievalTrace.Kind.FILE,
                {
                    "source": "delivery_timeline",
                    "entity_id": str(entity_id),
                    "version": item.get("version"),
                },
            )
            for item in serialized
        ]
        await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=traces,
            started_at=started_at,
        )
        return Response(output_data, status=status.HTTP_200_OK)


class GetRelatedEntitiesView(McpToolView):
    tool_name = "get_related_entities"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(GetRelatedEntitiesRequestSerializer, request)
        if err is not None:
            return err
        assert input_data is not None
        try:
            as_of = parse_as_of(input_data.get("as_of"))
        except ValueError as exc:
            return error_response("invalid_params", str(exc), status_code=status.HTTP_400_BAD_REQUEST)
        started_at = time.perf_counter()

        entity_id = input_data["entity_id"]
        related = await _delivery_knowledge_service.get_related(
            entity_id,
            user=request.user,
            direction=str(input_data.get("direction") or "both"),
            max_hops=int(input_data.get("max_hops") or 2),
            as_of=as_of,
        )
        serialized = serialize_related(related)
        output_data = {
            "entity_id": str(entity_id),
            "related": serialized,
            "total": len(serialized),
            "as_of": as_of.isoformat() if as_of else None,
            "run_id": str(run.run_id),
        }
        await self._record_agent_decision(
            run,
            action="related_entities_fetched",
            payload={"entity_id": str(entity_id), "related_count": len(serialized)},
        )
        traces = [
            (
                RetrievalTrace.Kind.EDGE,
                {
                    "source": "delivery_related",
                    "entity_id": item.get("entity_id", ""),
                    "relation": item.get("relation", ""),
                    "depth": item.get("depth", 0),
                },
            )
            for item in serialized
        ]
        await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=traces,
            started_at=started_at,
        )
        return Response(output_data, status=status.HTTP_200_OK)


class LookupProjectByBranchView(McpToolView):
    """分支名 → 项目反查 + 召回（CURSOR-01）。

    从 ``feat/xxxx-m{work_item_id}-slug`` 抽取 work_item_id（复用
    ``services.branch_parsing``），经 ``ProjectWorkItemLink`` → ``Project`` 反查；**单命中**
    经 Phase-80 ``pack_project_context`` 召回需求/工件/记忆，并写 ``RetrievalTrace``
    （补齐 Phase-80 标注的 MCP 链）。多/无命中 fail-soft（返回候选列表或空，绝不抛）。

    召回经 packer 内置 fail-closed（调用用户非项目成员时零召回），不绕过权限。
    """

    tool_name = "lookup_project_by_branch"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(
            LookupProjectByBranchRequestSerializer, request
        )
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()

        from services.branch_parsing import parse_work_item_id_from_branch

        branch_name = str(input_data["branch_name"])
        repository_id = input_data.get("repository_id")
        repository_id_str = str(repository_id) if repository_id else None
        work_item_id = parse_work_item_id_from_branch(branch_name)

        output_data: dict[str, Any] = {
            "branch_name": branch_name,
            "work_item_id": work_item_id,
            "repository_id": repository_id_str,
            "matched": False,
            "project": None,
            "candidates": [],
            "context": "",
            "included_layers": [],
            "run_id": str(run.run_id),
        }
        traces: list[tuple[str, dict[str, Any]]] = []

        # 反查两源（fail-soft，绝不抛、绝不阻断编码）：
        # 1) work_item_id 反查（v0.15.0 既有：分支名解析 work_item_id → Project）；
        # 2) ProjectBranch 显式多绑定反查（BIND-02：branch_name[+repository_id] → Project）。
        work_item_projects: list[Any] = []
        if work_item_id is not None:
            work_item_projects = await self._lookup_projects(work_item_id)
        binding_projects = await self._lookup_by_branch_binding(
            branch_name, repository_id
        )

        # 合并去重（work_item 源优先保留实例；绑定源补充未出现的项目）。
        merged: dict[Any, Any] = {p.id: p for p in work_item_projects}
        work_item_ids = set(merged.keys())
        for p in binding_projects:
            merged.setdefault(p.id, p)
        binding_ids = {p.id for p in binding_projects}
        projects = list(merged.values())
        output_data["candidates"] = [_project_summary(p) for p in projects]

        if len(projects) == 1:
            from services.project_context_packer import pack_project_context

            project = projects[0]
            # 标记命中来源（work_item / branch_binding / both），便于排障。
            in_wi = project.id in work_item_ids
            in_binding = project.id in binding_ids
            binding_source = (
                "both" if in_wi and in_binding
                else "work_item" if in_wi
                else "branch_binding"
            )
            packed = await pack_project_context(
                project, request.user, query=branch_name
            )
            output_data["matched"] = True
            output_data["project"] = _project_summary(project)
            output_data["context"] = packed.text
            output_data["included_layers"] = packed.included_layers
            # 补齐 MCP 链 RetrievalTrace（条数/分层耗时/score）。
            traces.append(
                (
                    RetrievalTrace.Kind.CHUNK,
                    {
                        "source": "mcp_lookup_project_by_branch",
                        "branch_name": branch_name,
                        "work_item_id": work_item_id,
                        "repository_id": repository_id_str,
                        "binding_source": binding_source,
                        "project_id": str(project.id),
                        "included_layers": packed.included_layers,
                        "counts": packed.counts,
                        "layer_timing_ms": packed.layer_timing_ms,
                        "scores": packed.scores,
                        "degraded": packed.degraded,
                        "total_tokens": packed.total_tokens,
                    },
                )
            )
        # 多命中 / 无命中：matched 保持 False，仅回候选列表（fail-soft）。

        await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=traces,
            started_at=started_at,
        )
        return Response(output_data, status=status.HTTP_200_OK)

    @sync_to_async
    def _lookup_projects(self, work_item_id: int) -> list[Any]:
        from initiatives.models import Project

        return list(
            Project.objects.filter(work_items__work_item_id=work_item_id)
            .select_related("space")
            .distinct()
        )

    @sync_to_async
    def _lookup_by_branch_binding(
        self, branch_name: str, repository_id: Any = None
    ) -> list[Any]:
        """ProjectBranch 显式绑定反查（BIND-02）。

        按 ``branch_name`` 查显式绑定项目；传 ``repository_id`` 则追加收窄（跨仓同名分支
        定位到具体仓）。返回去重 ``Project`` 列表（ORM 参数化，无注入）。
        """
        from initiatives.models import ProjectBranch

        qs = ProjectBranch.objects.filter(branch_name=branch_name)
        if repository_id:
            qs = qs.filter(repository_id=repository_id)
        seen: dict[Any, Any] = {}
        for binding in qs.select_related("project__space"):
            project = binding.project
            if project is not None:
                seen.setdefault(project.id, project)
        return list(seen.values())


@sync_to_async
def _resolve_projects_by_branch(branch_name: str, repository_id: Any = None) -> list[Any]:
    """按分支名(+可选 repository_id)反查项目（两源合并：work_item 解析 + ProjectBranch 显式绑定）。

    与 ``lookup_project_by_branch`` 同源逻辑，供 report_* 工具在未传 ``project_id`` 时按当前
    分支解析唯一项目用（通用规则/hook 不写死项目）。返回去重 ``Project`` 列表，调用方据数量判定。
    """
    from initiatives.models import Project, ProjectBranch
    from services.branch_parsing import parse_work_item_id_from_branch

    merged: dict[Any, Any] = {}
    work_item_id = parse_work_item_id_from_branch(branch_name)
    if work_item_id is not None:
        for p in (
            Project.objects.filter(work_items__work_item_id=work_item_id)
            .select_related("space")
            .distinct()
        ):
            merged.setdefault(p.id, p)
    qs = ProjectBranch.objects.filter(branch_name=branch_name)
    if repository_id:
        qs = qs.filter(repository_id=repository_id)
    for binding in qs.select_related("project__space"):
        if binding.project is not None:
            merged.setdefault(binding.project.id, binding.project)
    return list(merged.values())


async def _resolve_report_project_id(
    input_data: dict[str, Any],
) -> tuple[Any | None, str | None]:
    """report_* 工具统一项目解析：优先 ``project_id``；否则按 ``branch_name`` 反查唯一项目。

    解析成功把 ``project_id`` 注回 ``input_data`` 并返回 ``(project_id, None)``；无/多命中
    返回 ``(None, "branch_unresolved")``，调用方据此 fail-soft 跳过（不写、不报错、不阻断）。
    """
    project_id = input_data.get("project_id")
    if project_id:
        return project_id, None
    branch_name = str(input_data.get("branch_name") or "").strip()
    if not branch_name:
        return None, "branch_unresolved"
    projects = await _resolve_projects_by_branch(
        branch_name, input_data.get("repository_id")
    )
    if len(projects) == 1:
        pid = projects[0].id
        input_data["project_id"] = pid
        return pid, None
    return None, "branch_unresolved"


class ReportProjectKnowledgeView(McpToolView):
    """Cursor / IDE stop hook 沉淀上报写回（CURSOR-03 + HOOK-02）。

    认证（PAT/JWT）→ 归因（``request.user`` 触发用户 + initiated_by_user_id）→
    **质量门槛防噪音**（长度/低信息量/与既有 active 记忆重复，阈值可配）→ **脱敏不可绕过**
    + **成员校验**。

    两条写路径：

    - ``writeback_mode=draft``（默认，CURSOR-03 不回退）：写入 **pending 草稿**（绝不直接
      active，与 MEM-04 一致），成员校验 fail-closed（非成员 403），人工确认后才入库。
    - ``writeback_mode=active``（IDE stop hook，**用户授权 accepted deviation 2026-06-26**）：
      MEMORY/RESEARCH **直写生效（active）不落 draft、不需人工确认**。四道兜底绝不绕过：
      质量门槛 + 脱敏不可绕过 + 成员校验静默跳过（非成员/未认证/未绑项目 → accepted=false
      200，绝不抛、绝不阻断编码）+ 审计可回滚。可选 ``distill``（call_source=ide_hook_distill）
      best-effort 精炼，失败回退原文。全程 fail-soft（任何异常 → accepted=false 200）。
    """

    tool_name = "report_project_knowledge"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(
            ReportProjectKnowledgeRequestSerializer, request
        )
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()

        # 项目解析：未传 project_id 时按 branch_name 反查唯一项目（通用规则不写死项目）。
        resolved_pid, resolve_reason = await _resolve_report_project_id(input_data)
        if resolved_pid is None:
            output_data = {
                "accepted": False,
                "draft_id": None,
                "memory_id": None,
                "reason": resolve_reason,
                "run_id": str(run.run_id),
            }
            await self._record(
                run,
                input_data=input_data,
                output_data=output_data,
                traces=[],
                started_at=started_at,
            )
            return Response(output_data, status=status.HTTP_200_OK)

        if input_data.get("writeback_mode") == "active":
            # 用户授权 accepted deviation：active 直写。全程 fail-soft 包裹，绝不 5xx/阻断编码。
            return await self._handle_active_writeback(
                run, request, input_data, started_at
            )

        from initiatives.services import MemoryPermissionError, MemoryService
        from services.cursor_writeback import evaluate_writeback_quality

        project_id = input_data["project_id"]
        content = str(input_data["content"])
        source_conversation_id = input_data.get("source_conversation_id")

        # 质量门槛：低信息量/过短/重复 → 拒收（accepted=False，200，不入库不报错）。
        existing = await self._active_memory_contents(project_id)
        ok, reason = await evaluate_writeback_quality(content, existing)
        if not ok:
            output_data = {
                "accepted": False,
                "draft_id": None,
                "reason": reason,
                "run_id": str(run.run_id),
            }
            await self._record(
                run,
                input_data=input_data,
                output_data=output_data,
                traces=[],
                started_at=started_at,
            )
            return Response(output_data, status=status.HTTP_200_OK)

        try:
            draft = await MemoryService().create_draft(
                project_id=project_id,
                content=content,
                proposed_by=request.user,
                source_conversation_id=source_conversation_id,
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except MemoryPermissionError as exc:
            return error_response(
                "forbidden", str(exc), status_code=status.HTTP_403_FORBIDDEN
            )

        output_data = {
            "accepted": True,
            "draft_id": str(draft.id),
            "reason": "",
            "run_id": str(run.run_id),
        }
        await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=[],
            started_at=started_at,
        )
        return Response(output_data, status=status.HTTP_201_CREATED)

    async def _handle_active_writeback(
        self,
        run: Any,
        request: Request,
        input_data: dict[str, Any],
        started_at: float,
    ) -> Response:
        """IDE stop hook active 直写（accepted deviation）。全程 fail-soft：任何异常 →
        accepted=false 200，绝不 5xx、绝不阻断编码（T-86-01-04）。"""
        from initiatives.services import (
            MemoryService,
            ProjectDocService,
        )
        from services.cursor_writeback import evaluate_writeback_quality

        async def _reject(reason: str) -> Response:
            output_data = {
                "accepted": False,
                "memory_id": None,
                "reason": reason,
                "run_id": str(run.run_id),
            }
            await self._record(
                run,
                input_data=input_data,
                output_data=output_data,
                traces=[],
                started_at=started_at,
            )
            return Response(output_data, status=status.HTTP_200_OK)

        try:
            project_id = input_data["project_id"]
            content = str(input_data["content"])
            target = input_data.get("target") or "memory"
            distill = bool(input_data.get("distill"))

            # 未认证 / request.user 非真实用户 → 静默跳过（_begin 已挡匿名，此处纵深防御）。
            user = request.user
            if not getattr(user, "is_authenticated", False) or getattr(
                user, "id", None
            ) is None:
                return await _reject("unauthenticated")

            # 可选 distill（best-effort，失败回退原文，绝不反噬）。
            if distill:
                content = await self._maybe_distill(content)

            # 质量门槛（distill 后内容再过）：低质/空/重复 → accepted=false（与 draft 路径一致）。
            existing = await self._active_memory_contents(project_id)
            ok, reason = await evaluate_writeback_quality(content, existing)
            if not ok:
                return await _reject(reason)

            if target == "research":
                result = await ProjectDocService().append_research_note(
                    project_id=project_id,
                    content=content,
                    contributor=user,
                    initiated_by_user_id=user.id,
                )
            else:
                result = await MemoryService().record_hook_writeback(
                    project_id=project_id,
                    content=content,
                    contributor=user,
                    initiated_by_user_id=user.id,
                )

            if not result.get("applied"):
                # 非成员（绝不抛、不写库）→ accepted=false 200。
                return await _reject(result.get("reason") or "not_member")

            output_data = {
                "accepted": True,
                "memory_id": result.get("memory_id"),
                "doc_id": result.get("doc_id"),
                "reason": "",
                "run_id": str(run.run_id),
            }
            await self._record(
                run,
                input_data=input_data,
                output_data=output_data,
                traces=[],
                started_at=started_at,
            )
            return Response(output_data, status=status.HTTP_200_OK)
        except Exception:  # noqa: BLE001 — active 路径全 fail-soft，绝不 5xx/阻断编码
            return await _reject("error")

    @staticmethod
    async def _maybe_distill(content: str) -> str:
        """best-effort LLM 精炼（call_source=ide_hook_distill）；失败/无候选回退原文。"""
        try:
            from initiatives.services import MemoryDistiller

            refined = await MemoryDistiller().distill_hook_writeback(text=content)
            return refined or content
        except Exception:  # noqa: BLE001 — 蒸馏 best-effort，绝不反噬主流程
            return content

    @sync_to_async
    def _active_memory_contents(self, project_id: Any) -> list[str]:
        from initiatives.models import ProjectMemory, ProjectMemoryStatus

        return list(
            ProjectMemory.objects.filter(
                project_id=project_id, status=ProjectMemoryStatus.ACTIVE
            ).values_list("content", flat=True)[:200]
        )


# ============================================================================
# IDE stop hook STATE 结构化回写 MCP 工具（HOOK-03，Phase 86-04）
# ============================================================================


async def _assert_project_member(project_id: Any, user: Any) -> bool:
    """写权限成员判定（写仅成员，与 ``MemoryService`` / ``ProjectDocService`` 同口径）。

    fail-closed：无 user / 未认证 / 非成员 → False（调用方据此静默跳过，绝不抛、不阻断编码）。
    """
    from initiatives.models import ProjectMember

    uid = getattr(user, "id", None)
    if uid is None or not getattr(user, "is_authenticated", False):
        return False
    return await ProjectMember.objects.filter(
        project_id=project_id, user_id=uid
    ).aexists()


class ReportProjectStateView(McpToolView):
    """IDE stop hook STATE 结构化 API 清单直写（HOOK-03）。

    会话结束把新增/改动的 API 以**结构化清单**（method/path/params/status）经
    ``ProjectDocService.upsert_state_api`` **直接写入** ``ProjectStateApi``（source=HOOK，
    不经 draft），跨会话/跨角色（前后端）即时可读。写入收口于 INV-6 service（已内置
    ``(project, method, path)`` 幂等 upsert + 审计 ``state_api_added`` + 可经
    ``remove_state_api`` 撤销，审计可回滚）。

    四道兜底绝不绕过（与 86-01 active 路径口径一致）：

    - **成员校验静默跳过**：非成员 / 未认证 / 未绑项目 → ``applied=false`` 200，不写库、
      绝不抛、绝不阻断编码（T-86-04-01）。
    - **幂等 upsert**：重复回写同 ``(method, path)`` 不产生重复行（按唯一约束更新既有行，
      T-86-04-02）。
    - **逐条 fail-soft**：批量内单条非法/失败不影响其余（T-86-04-04）；全路径 fail-soft，
      任何异常 → 200 + ``applied=false``（绝不 5xx、不阻断编码）。
    - **审计可回滚 + 脱敏**：写入经 AuditService 留痕（``params`` 入口强制脱敏，T-86-04-03）。
    """

    tool_name = "report_project_state"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(
            ReportProjectStateRequestSerializer, request
        )
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()
        return await self._handle(run, request, input_data, started_at)

    async def _handle(
        self,
        run: Any,
        request: Request,
        input_data: dict[str, Any],
        started_at: float,
    ) -> Response:
        """STATE 结构化清单直写（全路径 fail-soft：任何异常 → applied=false 200）。"""
        from initiatives.models import ApiSource, ApiStatus
        from initiatives.services import ProjectDocService

        async def _finish(output_data: dict[str, Any]) -> Response:
            await self._record(
                run,
                input_data=input_data,
                output_data=output_data,
                traces=[],
                started_at=started_at,
            )
            return Response(output_data, status=status.HTTP_200_OK)

        def _skip(reason: str) -> dict[str, Any]:
            return {
                "applied": False,
                "reason": reason,
                "results": [],
                "total_applied": 0,
                "run_id": str(run.run_id),
            }

        try:
            # 项目解析：未传 project_id 时按 branch_name 反查唯一项目（通用规则不写死项目）。
            project_id, resolve_reason = await _resolve_report_project_id(input_data)
            if project_id is None:
                return await _finish(_skip(resolve_reason or "branch_unresolved"))
            apis = input_data.get("apis") or []
            user = request.user

            # 未认证 / request.user 非真实用户 → 静默跳过（_begin 已挡匿名，此处纵深防御）。
            if not getattr(user, "is_authenticated", False) or (
                getattr(user, "id", None) is None
            ):
                return await _finish(_skip("unauthenticated"))

            # 成员校验 fail-closed：非成员 / 未绑项目 → 静默跳过（不写、不抛、不阻断编码）。
            if not await _assert_project_member(project_id, user):
                return await _finish(_skip("not_member"))

            service = ProjectDocService()
            valid_status = {choice[0] for choice in ApiStatus.choices}
            results: list[dict[str, Any]] = []
            total_applied = 0

            for item in apis:
                if not isinstance(item, dict):
                    results.append(
                        {
                            "method": "",
                            "path": "",
                            "applied": False,
                            "action": "skipped",
                            "reason": "invalid_item",
                        }
                    )
                    continue
                method = str(item.get("method") or "").strip().upper()
                path = str(item.get("path") or "").strip()
                params = item.get("params")
                if not isinstance(params, dict):
                    params = {}
                item_status = str(item.get("status") or ApiStatus.IMPLEMENTED)
                if item_status not in valid_status:
                    item_status = ApiStatus.IMPLEMENTED

                # 逐条校验：缺 method/path → 标失败、不影响其余（fail-soft）。
                if not method or not path:
                    results.append(
                        {
                            "method": method,
                            "path": path,
                            "applied": False,
                            "action": "skipped",
                            "reason": "missing_method_or_path",
                        }
                    )
                    continue

                try:
                    api, created = await service.upsert_state_api(
                        project_id=project_id,
                        method=method,
                        path=path,
                        params=params,
                        status=item_status,
                        source=ApiSource.HOOK,
                        actor=user,
                        initiated_by_user_id=user.id,
                        # 102-REVIEW MED-01：批量路径逐条不物化，循环后合并调度一次
                        defer_materialize=True,
                    )
                    # 既有行：经 INV-6 service 更新 params/status（幂等回写按约束更新既有行）。
                    if not created:
                        await service.update_state_api(
                            project_id=project_id,
                            api_id=api.id,
                            fields={"params": params, "status": item_status},
                            actor=user,
                            initiated_by_user_id=user.id,
                        )
                    results.append(
                        {
                            "method": method,
                            "path": path,
                            "applied": True,
                            "action": "created" if created else "updated",
                        }
                    )
                    total_applied += 1
                except Exception:  # noqa: BLE001 — 逐条 fail-soft，单条失败不影响其余
                    logger.warning(
                        "report_project_state_item_failed",
                        project_id=str(project_id),
                        method=method,
                        path=path,
                        initiated_by_user_id=str(getattr(user, "id", "")) or "system",
                        component="mcp_tools",
                        category="caller",
                    )
                    results.append(
                        {
                            "method": method,
                            "path": path,
                            "applied": False,
                            "action": "failed",
                            "reason": "error",
                        }
                    )

            # 102-REVIEW MED-01：批量上报合并为一次 STATE 物化调度——避免 N 条
            # API 触发 N 次互不短路（内容逐次变化）的全量重摄取。
            if total_applied > 0:
                await service.schedule_state_materialization(project_id, user.id)

            output_data = {
                "applied": total_applied > 0,
                "reason": "",
                "results": results,
                "total_applied": total_applied,
                "run_id": str(run.run_id),
            }
            return await _finish(output_data)
        except Exception:  # noqa: BLE001 — 全路径 fail-soft，绝不 5xx/阻断编码
            return await _finish(_skip("error"))


# ============================================================================
# 项目上下文读半 MCP 工具（CTX-01/02，Phase 85-02）
# ============================================================================


async def _aget_project(project_id: Any) -> Any:
    """取 initiatives.Project（含 space，供 visibility 读校验）；不存在返回 None。"""
    from initiatives.models import Project

    return (
        await Project.objects.filter(id=project_id).select_related("space").afirst()
    )


async def _assert_project_readable(project: Any, user: Any) -> bool:
    """项目上下文读校验（与 ``pack_project_context`` 同口径，members_only fail-closed）。

    单一可读口径（CTX A3 within-phase 校验结论）：

    - 成员（``ProjectMember``，任意 visibility）→ 放行（与 AI 对话链 packer ``_is_member`` 一致）；
    - 非成员 + ``public_org`` → 放行（全员可读，visibility 对称）；
    - 非成员 + ``members_only`` → 拒绝（零召回零泄漏）。

    口径直接判 ``initiatives.Project.visibility``（而非 Space 维度），因此即便同一 Space
    内含混合可见性项目也不泄漏：grep/read 服务按 ``Project.id`` 维度过滤正文，RAG 经
    ``search_similar`` 的 ``resolve_allowed_project_ids`` caller-intersect 二次收口。
    """
    from initiatives.models import ProjectMember, ProjectVisibility

    uid = getattr(user, "id", None)
    if uid is None or not getattr(user, "is_authenticated", False):
        return False
    is_member = await ProjectMember.objects.filter(
        project_id=project.id, user_id=uid
    ).aexists()
    if is_member:
        return True
    return getattr(project, "visibility", "") == ProjectVisibility.PUBLIC_ORG


class SearchProjectContextView(McpToolView):
    """项目上下文语义召回（RAG，CTX-01 读半 + CTX-02 MCP 链 RetrievalTrace）。

    复用 ``DeliveryKnowledgeSearchService.search_similar``（已 visibility 感知）；读校验经
    ``_assert_project_readable``（members_only 非成员零召回，不抛、不泄漏）。每次召回写一条
    ``RetrievalTrace``（``Kind.CHUNK``，含条数 / score / **分层耗时 duration_ms**）。
    """

    tool_name = "search_project_context"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(
            SearchProjectContextRequestSerializer, request
        )
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()

        project_id = str(input_data["project_id"])
        query = str(input_data["query"])
        top_k = int(input_data.get("top_k") or 5)
        entity_kinds = [str(k) for k in (input_data.get("entity_kinds") or [])] or None

        results: list[Any] = []
        recall_ms = 0.0
        project = await _aget_project(project_id)
        if project is not None and await _assert_project_readable(project, request.user):
            recall_started = time.perf_counter()
            results = await _delivery_knowledge_service.search_similar(
                query,
                user=request.user,
                project_ids=[project_id],
                entity_kinds=entity_kinds,
                top_k=top_k,
                # CTX-01：项目上下文读路径纳入 DOCUMENT 召回（项目 5 文件/记忆/工件物化），
                # 不放宽 visibility/access 闸（仍由 search_similar 内 project_ids 收口）。
                include_document_kind=True,
            )
            recall_ms = round((time.perf_counter() - recall_started) * 1000, 2)

        serialized = serialize_search_results(results)
        output_data = {
            "project_id": project_id,
            "query": query,
            "results": serialized,
            "total": len(serialized),
            "run_id": str(run.run_id),
        }
        await self._record_agent_decision(
            run,
            action="project_context_searched",
            payload={"project_id": project_id, "result_count": len(serialized)},
        )
        scores = [item.get("score", 0) for item in serialized]
        traces = [
            (
                RetrievalTrace.Kind.CHUNK,
                {
                    "source": "mcp_search_project_context",
                    "project_id": project_id,
                    "result_count": len(serialized),
                    "scores": scores,
                    "top_score": max(scores) if scores else 0,
                    "duration_ms": recall_ms,
                },
            )
        ]
        await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=traces,
            started_at=started_at,
        )
        return Response(output_data, status=status.HTTP_200_OK)


class GrepProjectView(McpToolView):
    """项目上下文关键词 grep（CTX-01 读半）。

    复用 ``ProjectSearchService.search``（关键词命中 work_item/state_api/artifact/记忆正文/
    **ProjectDoc 正文** + locator，并在 service 内部写带 ``local_ms``/``knowledge_ms`` 分层耗时的
    ``RetrievalTrace``）。读校验经 ``_assert_project_readable``（members_only 非成员零结果，不泄漏）。
    本 view 不重复写召回 trace（service 已覆盖），仅 ``_record`` 留 ToolCallRecord + RequestMetric。
    """

    tool_name = "grep_project"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(GrepProjectRequestSerializer, request)
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()

        project_id = str(input_data["project_id"])
        query = str(input_data["query"])
        top_k = int(input_data.get("top_k") or 10)

        project = await _aget_project(project_id)
        if project is None:
            return error_response(
                "project_not_found", "项目不存在", status_code=status.HTTP_404_NOT_FOUND
            )

        results: list[Any] = []
        if await _assert_project_readable(project, request.user):
            from initiatives.services.project_search_service import ProjectSearchService

            results = await ProjectSearchService().search(
                project=project, query=query, user=request.user, top_k=top_k
            )

        output_data = {
            "project_id": project_id,
            "query": query,
            "results": results,
            "total": len(results),
            "run_id": str(run.run_id),
        }
        await self._record_agent_decision(
            run,
            action="project_grepped",
            payload={"project_id": project_id, "result_count": len(results)},
        )
        # 分层耗时（local_ms/knowledge_ms）由 ProjectSearchService 内部 trace 满足，
        # 此处不重复写 RetrievalTrace。
        await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=[],
            started_at=started_at,
        )
        return Response(output_data, status=status.HTTP_200_OK)


class ReadProjectDocView(McpToolView):
    """项目工作区单文档 file-read（CTX-01 读半 + CTX-02 MCP 链 RetrievalTrace）。

    复用 ``DocContentService.get_doc_render``（渲染 markdown + block 分区，不改其签名/行为）。
    读校验经 ``_assert_project_readable``（members_only 非成员返回空文档，**不泄漏存在性**）；
    doc 不存在同样返回空文档（与无权读对外同形，防存在性探测）。写一条 ``RetrievalTrace``
    （``Kind.FILE``，含 ``block_count`` + **分层耗时 duration_ms**）。
    """

    tool_name = "read_project_doc"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(ReadProjectDocRequestSerializer, request)
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()

        project_id = str(input_data["project_id"])
        doc_type = str(input_data["doc_type"])

        project = await _aget_project(project_id)
        if project is None:
            return error_response(
                "project_not_found", "项目不存在", status_code=status.HTTP_404_NOT_FOUND
            )

        rendered_markdown = ""
        blocks: list[Any] = []
        read_ms = 0.0
        if await _assert_project_readable(project, request.user):
            from initiatives.services.doc_content_service import DocContentService

            read_started = time.perf_counter()
            rendered = await DocContentService().get_doc_render(
                project_id=project_id, doc_type=doc_type
            )
            read_ms = round((time.perf_counter() - read_started) * 1000, 2)
            if rendered is not None:
                rendered_markdown = rendered.get("rendered_markdown", "") or ""
                blocks = rendered.get("blocks", []) or []

        output_data = {
            "project_id": project_id,
            "doc_type": doc_type,
            "rendered_markdown": rendered_markdown,
            "blocks": blocks,
            "run_id": str(run.run_id),
        }
        await self._record_agent_decision(
            run,
            action="project_doc_read",
            payload={"project_id": project_id, "doc_type": doc_type, "block_count": len(blocks)},
        )
        traces = [
            (
                RetrievalTrace.Kind.FILE,
                {
                    "source": "mcp_read_project_doc",
                    "project_id": project_id,
                    "doc_type": doc_type,
                    "block_count": len(blocks),
                    "duration_ms": read_ms,
                },
            )
        ]
        await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=traces,
            started_at=started_at,
        )
        return Response(output_data, status=status.HTTP_200_OK)
