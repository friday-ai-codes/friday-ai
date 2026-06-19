"""Index management views for repositories."""

import asyncio
import json
from dataclasses import asdict
from typing import Any

import httpx
import structlog
from adrf.views import APIView
from asgiref.sync import async_to_sync, sync_to_async
from django.conf import settings
from django.db import transaction
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response

from durable import QUEUE_INDEX, DurableTaskService


class ServerSentEventRenderer(BaseRenderer):
    """绕过 DRF content negotiation 的 SSE renderer。

    DRF APIView 默认 renderer 只接受 application/json 之类，浏览器 fetch SSE 时
    送的是 Accept: text/event-stream → 协商失败直接 406。给 SSE 端点显式声明这个
    renderer 后 DRF 不再校验 Accept，View 自己用 StreamingHttpResponse 直出。
    """

    media_type = "text/event-stream"
    format = "txt"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        # 实际响应由 StreamingHttpResponse 直出，render() 不会被调用
        return data


from repositories.models import (
    FileIndex,
    GraphBuildHistory,
    GraphBuildHistoryStatus,
    IndexHistory,
    IndexHistoryStatus,
    IndexStatus,
    Repository,
    RepositoryBranchIndex,
    RepositoryGraphStatus,
    TriggerType,
)
from repositories.services.index_cleanup import cleanup_index
from services.background_runner import cancel_background_task
from services.embedding import EmbeddingService
from services.qdrant_service import QdrantService

logger = structlog.get_logger(__name__)

INDEX_CANCEL_MESSAGE = "用户已停止索引"


def _compute_index_progress(repository: Repository) -> dict[str, Any]:
    """根据 Repository 字段计算 overall_progress / overall_stage。

    进度口径（contract 续传重构后）：
      1. **文件级优先**：若 ``indexed_files_total > 0``，使用
         ``indexed_files_processed / indexed_files_total`` 作为百分比。
         这一口径在按文件批 _flush_batch 模式下严格单调递增，且中断续传时
         processed 从已 skip 数起步，百分比天然不归零。
      2. **chunks 级兜底**：仅当文件级字段未设置（老记录或未走重构路径）时，
         回退到旧的"embed × 0.7 + write × 0.3"加权口径。

    stage 文案：优先采用 indexer 显式上报的 ``index_stage``，缺省时按 chunks 计数推断。
    """
    total_chunks = repository.index_total_chunks
    processed_chunks = repository.index_processed_chunks
    write_total = repository.index_write_total
    write_processed = repository.index_write_processed
    explicit_stage = (repository.index_stage or "").strip()

    files_total = repository.indexed_files_total or 0
    files_processed = repository.indexed_files_processed or 0

    if total_chunks > 0:
        embedding_pct = (processed_chunks / total_chunks * 100) if total_chunks > 0 else 0
        write_pct = (write_processed / write_total * 100) if write_total > 0 else 0
        overall_progress = min(int(embedding_pct * 0.7 + write_pct * 0.3), 100)
    elif files_total > 0:
        # 文件计数只代表 scan/parse/checkpoint 判断完成，不代表 embedding/upsert 完成。
        # 因此在 chunk 总量尚未建立前最多显示到 90%，避免"100% 索引文件中..."
        # 这种误导性状态。
        overall_progress = min(int(files_processed / files_total * 100), 90)
    else:
        overall_progress = 0

    if explicit_stage:
        overall_stage = explicit_stage
    elif total_chunks == 0:
        overall_stage = "解析文件中..."
    elif write_total == 0:
        overall_stage = "生成向量中..."
    elif write_processed < write_total:
        overall_stage = "写入向量库..."
    else:
        overall_stage = "完成"

    return {
        "overall_progress": overall_progress,
        "overall_stage": overall_stage,
        "index_total_chunks": total_chunks,
        "index_processed_chunks": processed_chunks,
        "index_write_total": write_total,
        "index_write_processed": write_processed,
        # contract：文件级实时进度（同时承担 overall_progress 计算口径）
        "current_indexing_file": repository.current_indexing_file or "",
        "indexed_files_processed": files_processed,
        "indexed_files_total": files_total,
    }


# NOTE: 历史上这里维护一个 _index_tasks set 配合 asyncio.create_task
# 防 GC，但这种做法把后台 task 绑死在请求生命周期 → asgiref CurrentThreadExecutor
# 关闭后 ORM 全炸。改走 services.background_runner 的常驻 worker loop。


def _acquire_index_lock(repository_id: str) -> Repository | None:
    """尝试获取仓库索引 DB 锁。返回 None 表示已被其他进程持有（skip_locked）。"""
    with transaction.atomic():
        try:
            return Repository.objects.select_for_update(skip_locked=True).get(
                id=repository_id, is_deleted=False
            )
        except Repository.DoesNotExist:
            return None


_acquire_index_lock_async = sync_to_async(_acquire_index_lock)


def _schedule_index(
    repository_id: str,
    history_id: str,
    *,
    branch: str | None = None,
    trigger: str = "manual",
) -> str:
    """把索引任务投递到 durable 队列（QUEUE_INDEX），返回 durable job id。

    durable 入队 + deterministic idempotency_key（``index:{repo_id}``）做队列层去重，
    与 ``_acquire_index_lock`` 的 select_for_update 业务防抖互补：同 repo 重复投递经
    key 在途去重不产生重复 durable job；IndexHistory 仍在入队点创建并作进度真相源，
    FileIndex hash checkpoint 在任务体内复用（重复执行不产生重复数据）。

    本函数为**同步上下文** helper，经 ``async_to_sync`` 桥接 async 的
    ``DurableTaskService.defer``；调用方在 async view 中以
    ``sync_to_async(_schedule_index)`` 包裹后 await（同 ``_acquire_index_lock_async`` 范式），
    避免在事件循环线程上直接 ``async_to_sync``。返回值仅作可观测，调用方不再依赖 Future。
    """
    return async_to_sync(DurableTaskService.defer)(
        "durable_index",
        {
            "repository_id": str(repository_id),
            "history_id": history_id,
            "branch": branch,
            "trigger": trigger,
        },
        queue=QUEUE_INDEX,
        idempotency_key=f"index:{repository_id}",
    )


class IndexStatusSerializer(serializers.Serializer):
    """Serializer for index status response."""

    index_status = serializers.CharField()
    last_indexed_at = serializers.DateTimeField(allow_null=True)
    index_error = serializers.CharField(allow_null=True)
    index_total_chunks = serializers.IntegerField()
    index_processed_chunks = serializers.IntegerField()
    index_write_total = serializers.IntegerField()
    index_write_processed = serializers.IntegerField()
    # 统一进度字段
    overall_progress = serializers.IntegerField()
    overall_stage = serializers.CharField()
    # contract：文件级实时进度
    current_indexing_file = serializers.CharField(allow_blank=True, default="")
    indexed_files_processed = serializers.IntegerField(default=0)
    indexed_files_total = serializers.IntegerField(default=0)


class RepositoryBranchIndexRowSerializer(serializers.ModelSerializer):
    """只读：分支索引行（与 RepositoryBranchIndex 字段对齐）。"""

    class Meta:
        model = RepositoryBranchIndex
        fields = (
            "branch_name",
            "is_base_branch",
            "is_stale",
            "last_indexed_at",
            "last_indexed_commit_sha",
            "effective_chunks_count",
        )


class SearchRequestSerializer(serializers.Serializer):
    """Serializer for search request."""

    query = serializers.CharField(max_length=1000)
    top_k = serializers.IntegerField(default=10, min_value=1, max_value=50)
    filters = serializers.DictField(required=False, default=dict)
    branch = serializers.CharField(required=False, allow_blank=True, default="")


class SearchResultSerializer(serializers.Serializer):
    """Serializer for search result item."""

    file_path = serializers.CharField()
    score = serializers.FloatField()
    content = serializers.CharField()
    language = serializers.CharField()
    start_line = serializers.IntegerField()
    end_line = serializers.IntegerField()
    context_header = serializers.CharField()


class BranchIndexListView(APIView):
    """GET 仓库下全部分支索引行（只读）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, repository_id: str) -> Response:
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        try:
            qs = RepositoryBranchIndex.objects.filter(repository_id=repository_id).order_by(
                "branch_name"
            )
            items = [obj async for obj in qs]
            serializer = RepositoryBranchIndexRowSerializer(items, many=True)
            data = await sync_to_async(lambda: serializer.data)()
            return Response(data)
        except Exception as exc:
            logger.error(
                "branch_index_list_failed",
                repository_id=repository_id,
                exc_info=exc,
            )
            return Response(
                {"detail": "加载分支索引失败"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class IndexTriggerView(APIView):
    """Trigger indexing for a repository."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    async def post(self, request: Any, repository_id: str) -> Response:
        """触发仓库索引（手动），支持可选 branch 参数触发分支索引。"""
        # 快速状态检查（无锁开销，快速路径）
        try:
            repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response(
                {"detail": "仓库不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        branch: str | None = request.data.get("branch")

        if repository.index_status == IndexStatus.INDEXING:
            return Response(
                {"detail": "索引正在进行中"},
                status=status.HTTP_409_CONFLICT,
            )

        # DB 级并发保护（消除快速检查之后的竞态窗口）
        locked_repo = await _acquire_index_lock_async(str(repository_id))
        if locked_repo is None:
            return Response(
                {"detail": "索引正在进行中"},
                status=status.HTTP_409_CONFLICT,
            )

        # 重置上一轮索引的进度残留，避免 UI 在 INDEXING 初期读到旧的 N/N → 误显示 100%
        await Repository.objects.filter(id=repository_id).aupdate(
            index_total_chunks=0,
            index_processed_chunks=0,
            index_write_total=0,
            index_write_processed=0,
            index_error=None,
            current_indexing_file="",
            indexed_files_processed=0,
            indexed_files_total=0,
        )

        # 创建 IndexHistory 记录（获锁之后，任务启动之前）
        history = await IndexHistory.objects.acreate(
            repository_id=repository_id,
            trigger_type=TriggerType.MANUAL,
            status=IndexHistoryStatus.RUNNING,
            started_at=timezone.now(),
        )

        # 投递 durable 索引任务（同步 helper 经 sync_to_async 桥接，避免在事件循环线程上
        # 直接 async_to_sync）。job_id 仅作可观测，调用方不依赖返回值。
        await sync_to_async(_schedule_index)(str(repository_id), str(history.id), branch=branch)

        return Response(
            {
                "message": "索引任务已启动",
                "repository_id": str(repository_id),
                "history_id": str(history.id),
                "status": IndexStatus.INDEXING,
                "branch": branch,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class IndexCancelView(APIView):
    """停止正在运行的仓库索引任务。"""

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, repository_id: str) -> Response:
        try:
            repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response(
                {"detail": "仓库不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if repository.index_status != IndexStatus.INDEXING:
            return Response(
                {"detail": "当前没有正在运行的索引任务"},
                status=status.HTTP_409_CONFLICT,
            )

        repo_id = str(repository_id)
        cancelled = cancel_background_task(f"index-{repo_id}")
        cancelled = cancel_background_task(f"auto-index-{repo_id}") or cancelled

        await Repository.objects.filter(id=repository_id).aupdate(
            index_status=IndexStatus.CANCELLED,
            index_error=INDEX_CANCEL_MESSAGE,
            index_stage="",
            current_indexing_file="",
        )
        await IndexHistory.objects.filter(
            repository_id=repository_id,
            status=IndexHistoryStatus.RUNNING,
        ).aupdate(
            status=IndexHistoryStatus.CANCELLED,
            finished_at=timezone.now(),
            error_message=INDEX_CANCEL_MESSAGE,
        )

        logger.info(
            "index_cancelled",
            repository_id=repo_id,
            background_task_cancelled=cancelled,
        )
        return Response(
            {
                "message": INDEX_CANCEL_MESSAGE,
                "repository_id": repo_id,
                "status": IndexStatus.CANCELLED,
                "cancelled": cancelled,
            }
        )


class GraphRagStatusView(APIView):
    """GraphRAG（ChunkEdge）真实状态——以 ChunkEdge 表计数为**权威事实来源**。

    修复前端"0 语义边"误显示：旧前端读最近一条 ``IndexHistory.edge_count`` 快照，
    该快照由 lifecycle 在边构建完成时回写，时序边缘场景（如完成回调时已无 RUNNING
    历史行可定位）下可能漏写而停在 0，但真实 ``ChunkEdge`` 表可能有数万条。本端点
    直接 count ``ChunkEdge`` 表，不依赖快照，从根上消除"建了边却显示 0"。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, repository_id: str) -> Response:
        """返回真实 ChunkEdge 计数 + 综合状态 + 最近同步时间。

        可选 ``?branch=`` 参数支持 branch-aware 计数。归一化复用
        ``resolve_branch_for_query``（读侧标准归一化，绝不自己写
        ``if branch == default_branch``）。base 行 ``branch_name=""``、feature 行
        ``branch_name=<分支名>``，feature 查询走 base+overlay 合并。
        """
        from code_relations.models import ChunkEdge
        from services.branch_utils import resolve_branch_for_query

        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response(
                {"detail": "仓库不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # branch 归一化：传入分支与 base（branch=None）各解析一次，二者相等即视为
        # ==base，统一吸收 "" vs default_branch 二义（不自己判 default_branch）。
        branch = request.query_params.get("branch")
        effective_branch, _ = await resolve_branch_for_query(repository_id, branch)
        base_branch_name, _ = await resolve_branch_for_query(repository_id, None)

        if not effective_branch or effective_branch == base_branch_name:
            # 缺省/==base：只算 branch_name="" 的干净 base 计数（向后兼容）。存量纯
            # base 仓库全部 branch_name=""（293 迁移 + checkpoint 清污前置保证），该过滤
            # 等价于旧全表 count，缺省口径不漂移（Pitfall B）。
            edge_count = await ChunkEdge.objects.filter(
                repository_id=repository_id, branch_name=""
            ).acount()
        else:
            # feature：base + overlay 合并计数（base 行 "" + 该分支 overlay 行）。
            edge_count = await ChunkEdge.objects.filter(
                repository_id=repository_id,
                branch_name__in=["", effective_branch],
            ).acount()

        # 最近一条索引历史：取 graph_build_status（兜底状态）与 payload_synced_at（时间戳展示）
        latest = (
            await IndexHistory.objects.filter(repository_id=repository_id)
            .order_by("-created_at")
            .afirst()
        )

        # status 权威化：真实有边即 completed（不被漏写的快照误导）；无边时回退
        # 最近一次构建状态（running/failed/pending），无历史则 pending。
        if edge_count > 0:
            graph_status = "completed"
        elif latest is not None and latest.graph_build_status:
            graph_status = latest.graph_build_status
        else:
            graph_status = "pending"

        last_synced_at = latest.payload_synced_at if latest is not None else None

        return Response(
            {
                "edge_count": edge_count,
                "status": graph_status,
                "last_synced_at": (last_synced_at.isoformat() if last_synced_at else None),
            }
        )


class IndexStatusView(APIView):
    """Get index status for a repository."""

    permission_classes = [IsAuthenticated]

    async def get(self, request, repository_id):
        """Get current index status."""
        try:
            repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response(
                {"detail": "仓库不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 索引进行中 → 进度信息从 DB 读取（indexer 实时更新这些字段 + index_stage）
        if repository.index_status == IndexStatus.INDEXING:
            progress = _compute_index_progress(repository)
            serializer = IndexStatusSerializer(
                {
                    "index_status": IndexStatus.INDEXING,
                    "last_indexed_at": repository.last_indexed_at,
                    "index_error": None,
                    **progress,
                }
            )
            return Response(serializer.data)

        if repository.index_status in (IndexStatus.FAILED, IndexStatus.CANCELLED):
            serializer = IndexStatusSerializer(
                {
                    "index_status": repository.index_status,
                    "last_indexed_at": repository.last_indexed_at,
                    "index_error": repository.index_error,
                    "index_total_chunks": repository.index_total_chunks,
                    "index_processed_chunks": repository.index_processed_chunks,
                    "index_write_total": repository.index_write_total,
                    "index_write_processed": repository.index_write_processed,
                    "overall_progress": 0,
                    "overall_stage": "",
                    "current_indexing_file": repository.current_indexing_file or "",
                    "indexed_files_processed": repository.indexed_files_processed or 0,
                    "indexed_files_total": repository.indexed_files_total or 0,
                }
            )
            return Response(serializer.data)

        # 非索引中 → Qdrant 是唯一事实来源（Qdrant 不可用时安全降级，避免 500）
        try:
            health = await sync_to_async(QdrantService.check_collection_health)(str(repository_id))
        except Exception as exc:
            logger.warning(
                "index_status_qdrant_unavailable",
                repository_id=str(repository_id),
                error=str(exc),
            )
            # 降级到 DB 自身记录状态，不抛 500
            serializer = IndexStatusSerializer(
                {
                    "index_status": repository.index_status,
                    "last_indexed_at": repository.last_indexed_at,
                    "index_error": repository.index_error,
                    "index_total_chunks": repository.index_total_chunks,
                    "index_processed_chunks": repository.index_processed_chunks,
                    "index_write_total": repository.index_write_total,
                    "index_write_processed": repository.index_write_processed,
                    "overall_progress": 0,
                    "overall_stage": "",
                    "current_indexing_file": "",
                    "indexed_files_processed": repository.indexed_files_processed or 0,
                    "indexed_files_total": repository.indexed_files_total or 0,
                }
            )
            return Response(serializer.data)
        qdrant_has_data = health.get("collection_exists") and health.get("points_count", 0) > 0

        if qdrant_has_data:
            points_count = health.get("points_count", 0)
            actual_status = IndexStatus.INDEXED
            # DB 状态落后时同步一下
            if repository.index_status != IndexStatus.INDEXED:
                repository.index_status = IndexStatus.INDEXED
                repository.index_error = None
                if not repository.last_indexed_at:
                    repository.last_indexed_at = timezone.now()
                await repository.asave(
                    update_fields=["index_status", "index_error", "last_indexed_at"]
                )
        else:
            points_count = 0
            actual_status = IndexStatus.NOT_INDEXED
            if repository.index_status == IndexStatus.INDEXED:
                repository.index_status = IndexStatus.NOT_INDEXED
                repository.last_indexed_at = None
                repository.index_error = None
                await repository.asave(
                    update_fields=["index_status", "last_indexed_at", "index_error"]
                )

        serializer = IndexStatusSerializer(
            {
                "index_status": actual_status,
                "last_indexed_at": repository.last_indexed_at,
                "index_error": repository.index_error
                if actual_status == IndexStatus.FAILED
                else None,
                "index_total_chunks": points_count,
                "index_processed_chunks": points_count,
                "index_write_total": points_count,
                "index_write_processed": points_count,
                "overall_progress": 100 if qdrant_has_data else 0,
                "overall_stage": "完成" if qdrant_has_data else "",
                "current_indexing_file": "",
                "indexed_files_processed": repository.indexed_files_processed or 0,
                "indexed_files_total": repository.indexed_files_total or 0,
            }
        )

        return Response(serializer.data)


class IndexDeleteView(APIView):
    """Delete index for a repository."""

    permission_classes = [IsAuthenticated]

    async def delete(self, request, repository_id):
        """Delete the index for the repository."""
        try:
            repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response(
                {"detail": "仓库不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 级联清理：Qdrant collection + FileIndex + Symbol/ImportEdge/Endpoint
        # + ChunkEdge/ChunkRegistry。模块内每步独立 try/except + 字段降级
        # （per implementation context contract 异常隔离），不向上抛 → 删除请求始终 204。
        # implementation-02：可通过 ?keep_graph=true|1|yes 跳过图谱三件套
        # 清理（仅清向量轨），用于"清向量但保图谱"的运维场景。兼容 DRF Request
        # （生产经 dispatch 走入）与 WSGIRequest（旧测试用 APIRequestFactory 直
        # 调 view）：前者读 ``query_params``，后者回退 ``GET``。
        query_params = getattr(request, "query_params", None) or request.GET
        keep_graph = query_params.get("keep_graph", "").strip().lower() in ("true", "1", "yes")
        report = await cleanup_index(str(repository.id), keep_graph=keep_graph)
        logger.info(
            "index_delete_cleanup_complete",
            repository_id=str(repository.id),
            keep_graph=keep_graph,
            report=asdict(report),
        )

        # Reset repository status
        repository.index_status = IndexStatus.NOT_INDEXED
        repository.last_indexed_at = None
        repository.index_error = None
        repository.index_total_chunks = 0
        repository.index_processed_chunks = 0
        repository.index_write_total = 0
        repository.index_write_processed = 0
        repository.index_stage = ""
        repository.current_indexing_file = ""
        repository.indexed_files_processed = 0
        repository.indexed_files_total = 0
        repository.last_indexed_commit_sha = ""
        repository.remote_head_sha = ""
        repository.remote_head_checked_at = None
        repository.behind_commits = None
        repository.behind_commits_calculated_at = None
        await repository.asave(
            update_fields=[
                "index_status",
                "last_indexed_at",
                "index_error",
                "index_total_chunks",
                "index_processed_chunks",
                "index_write_total",
                "index_write_processed",
                "index_stage",
                "current_indexing_file",
                "indexed_files_processed",
                "indexed_files_total",
                "last_indexed_commit_sha",
                "remote_head_sha",
                "remote_head_checked_at",
                "behind_commits",
                "behind_commits_calculated_at",
            ],
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


class CodeSearchView(APIView):
    """Search code in repository index."""

    permission_classes = [IsAuthenticated]

    async def post(self, request, repository_id):
        """Search for code in the repository."""
        try:
            repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response(
                {"detail": "仓库不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if indexed
        if repository.index_status != IndexStatus.INDEXED:
            return Response(
                {"detail": "仓库尚未建立索引，请先执行索引操作"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate request
        serializer = SearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        query = serializer.validated_data["query"]
        top_k = serializer.validated_data["top_k"]
        filters = serializer.validated_data.get("filters", {})
        branch = serializer.validated_data.get("branch", "") or None

        # Run search
        results = await self._search(repository_id, query, top_k, filters, branch=branch)

        return Response(
            {
                "query": query,
                "results": results,
                "total": len(results),
            }
        )

    async def _search(
        self,
        repository_id: str,
        query: str,
        top_k: int,
        filters: dict[str, Any],
        *,
        branch: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute vector search with optional hybrid search and reranker."""
        from services.branch_search import BranchAwareSearchService
        from services.reranker import RerankerService
        from system.models import SettingKeys, SystemSetting

        reranker_enabled = await RerankerService.is_enabled()
        fetch_k = min(top_k * 3, 50) if reranker_enabled else top_k

        query_embedding = await EmbeddingService.generate_embedding(query)
        if not query_embedding:
            return []

        hybrid_setting = await SystemSetting.objects.filter(
            key=SettingKeys.HYBRID_SEARCH_ENABLED
        ).afirst()
        hybrid_enabled = hybrid_setting.value == "true" if hybrid_setting else True

        query_sparse = None
        if hybrid_enabled:
            from services.sparse_encoder import SparseEncoderService

            query_sparse = await sync_to_async(SparseEncoderService.encode)(query)

        search_results = await BranchAwareSearchService.search(
            repository_id,
            query_embedding,
            query_sparse=query_sparse,
            branch_name=branch,
            top_k=fetch_k,
            filters=filters,
        )

        if not search_results:
            return []

        # Reranker 精排（在 overlay+base 合并后统一执行一次）
        if reranker_enabled and len(search_results) > top_k:
            documents = [r["payload"].get("content", "") for r in search_results]
            reranked = await RerankerService.rerank(query, documents, top_n=top_k)
            # fail-open：rerank 返回空（未配置 / 调用失败 / 响应不可解析）时保留召回原序。
            if reranked:
                reranked_results = []
                for item in reranked:
                    idx = item["index"]
                    if idx < len(search_results):
                        entry = search_results[idx]
                        entry["score"] = item["relevance_score"]
                        reranked_results.append(entry)
                search_results = reranked_results

        # EXCL-02 fail-closed：这是 frontend-reachable 的认证 REST RAG 读取面
        # （POST /api/repositories/<id>/search/，前端 searchCode 在用），不经统一
        # search_rag chokepoint，必须在返回 content/file_path 前自挂同一匹配器过滤，
        # 否则被排除文件明文与路径会原样泄漏。matcher 构造失败 → 整仓库结果不可见
        # （fail-closed）；单项 file_path 缺失 / 判定异常 → 丢弃该项（fail-closed）。
        from services.exclusion import build_matcher_for_repo, log_exclusion_blocked

        try:
            matcher = await build_matcher_for_repo(str(repository_id))
        except Exception as exc:  # noqa: BLE001 — 构造失败一律 fail-closed（不泄漏存在性）
            logger.warning(
                "code_search_matcher_build_failed",
                repository_id=str(repository_id),
                error=str(exc),
            )
            log_exclusion_blocked(
                surface="code_search", repository_id=str(repository_id), rel_path=""
            )
            return []

        results = []
        for r in search_results:
            payload = r["payload"]
            file_path = payload.get("file_path")
            try:
                # file_path 缺失 → is_excluded(None) 归一失败即 fail-closed（返回 True）。
                excluded = matcher.is_excluded(file_path)
            except Exception:  # noqa: BLE001 — 判定异常 → 丢弃该项（fail-closed）
                excluded = True
            if excluded:
                log_exclusion_blocked(
                    surface="code_search",
                    repository_id=str(repository_id),
                    rel_path=str(file_path),
                )
                continue
            results.append(
                {
                    "file_path": file_path,
                    "score": r["score"],
                    "content": payload.get("content"),
                    "language": payload.get("language"),
                    "start_line": payload.get("start_line"),
                    "end_line": payload.get("end_line"),
                    "context_header": payload.get("context_header"),
                }
            )

        return results


class QdrantHealthView(APIView):
    """Check Qdrant service health."""

    permission_classes = [IsAuthenticated]

    async def get(self, request):
        """Get Qdrant health status."""
        health = await sync_to_async(QdrantService.health_check)()  # KEEP: Qdrant SDK 同步限制
        return Response(health)

    async def post(self, request):
        """Test Qdrant connection with provided config (before saving)."""
        from common.encryption import decrypt_value
        from system.models import SettingKeys, SystemSetting

        url = request.data.get("url")
        api_key = request.data.get("api_key")

        # If api_key not provided, try to get from saved settings
        if not api_key:
            api_key_setting = await SystemSetting.objects.filter(
                key=SettingKeys.QDRANT_API_KEY
            ).afirst()
            if api_key_setting and api_key_setting.value:
                if api_key_setting.is_encrypted:
                    api_key = decrypt_value(api_key_setting.value)
                else:
                    api_key = api_key_setting.value

        health = await sync_to_async(QdrantService.health_check_with_config)(
            url, api_key
        )  # KEEP: Qdrant SDK 同步限制
        return Response(health)


class EmbeddingHealthView(APIView):
    """Check Embedding API health."""

    permission_classes = [IsAuthenticated]

    async def get(self, request):
        """Get Embedding API health status using saved config."""
        health = await EmbeddingService.test_connection()
        return Response(health)

    async def post(self, request):
        """Test Embedding API with provided config (before saving).

        If api_key is not provided, use the saved api_key from system settings.
        """
        from common.encryption import decrypt_value
        from system.models import SettingKeys, SystemSetting

        api_url = request.data.get("api_url")
        model = request.data.get("model", "BAAI/bge-m3")
        api_key = request.data.get("api_key")
        dimension = request.data.get("dimension")

        if not api_url:
            return Response(
                {
                    "status": "error",
                    "message": "Embedding API URL is required",
                }
            )

        # If api_key not provided, try to get from saved settings
        if not api_key:
            api_key_setting = await SystemSetting.objects.filter(
                key=SettingKeys.EMBEDDING_API_KEY
            ).afirst()
            if api_key_setting and api_key_setting.value:
                if api_key_setting.is_encrypted:
                    api_key = decrypt_value(api_key_setting.value)
                else:
                    api_key = api_key_setting.value

        health = await EmbeddingService.test_connection_with_config(
            api_url, model, api_key, int(dimension) if dimension else None
        )
        return Response(health)


class RerankerHealthView(APIView):
    """Check Reranker API health."""

    permission_classes = [IsAuthenticated]

    async def get(self, request):
        """使用已保存配置测试 reranker 连接。"""
        from services.reranker import RerankerService

        health = await RerankerService.test_connection()
        return Response(health)

    async def post(self, request):
        """使用提供的配置测试 reranker（保存前测试）。"""
        from common.encryption import decrypt_value
        from services.reranker import RerankerService
        from system.models import SettingKeys, SystemSetting

        api_url = request.data.get("api_url")
        model = request.data.get("model", "BAAI/bge-reranker-v2-m3")
        api_key = request.data.get("api_key")

        if not api_url:
            return Response({"status": "error", "message": "Reranker API URL is required"})

        # 未提供 api_key 时，尝试使用已保存的
        if not api_key:
            api_key_setting = await SystemSetting.objects.filter(
                key=SettingKeys.RERANKER_API_KEY
            ).afirst()
            if api_key_setting and api_key_setting.value:
                if api_key_setting.is_encrypted:
                    api_key = decrypt_value(api_key_setting.value)
                else:
                    api_key = api_key_setting.value

        health = await RerankerService.test_connection_with_config(api_url, model, api_key)
        return Response(health)


# ---------------------------------------------------------------------------
# 索引可观测性 API
# ---------------------------------------------------------------------------


class IndexHistorySerializer(serializers.Serializer):
    """IndexHistory 记录序列化器。"""

    id = serializers.UUIDField()
    trigger_type = serializers.CharField()
    status = serializers.CharField()
    from_sha = serializers.CharField(allow_null=True)
    to_sha = serializers.CharField(allow_null=True)
    files_added = serializers.IntegerField()
    files_modified = serializers.IntegerField()
    files_deleted = serializers.IntegerField()
    # 变更文件路径列表 — 增量索引完成或 RUNNING partial-update 后由 indexer 写入
    # 形如 {"added": [...], "modified": [...], "deleted": [...]}；全量索引时为空 dict
    changed_files = serializers.JSONField()
    summary_text = serializers.CharField(allow_null=True)
    error_message = serializers.CharField(allow_null=True)
    started_at = serializers.DateTimeField(allow_null=True)
    finished_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    # implementation contract：GraphRAG 增量构建可观测字段
    graph_build_status = serializers.CharField()
    edge_count = serializers.IntegerField()
    payload_synced_at = serializers.DateTimeField(allow_null=True)
    # 跨仓 API 匹配状态（implementation migration 0023 已落字段）
    cross_repo_match_count = serializers.IntegerField()
    cross_repo_built_at = serializers.DateTimeField(allow_null=True)
    # per-run delta（本次索引新增，区别于累计 edge_count）
    # 加字段后 SSE running_history 段（running_payload）天然携带 delta，供 checkpoint 展示。
    symbols_added = serializers.IntegerField()
    imports_added = serializers.IntegerField()
    calls_added = serializers.IntegerField()
    endpoints_added = serializers.IntegerField()
    chunk_edges_added = serializers.IntegerField()
    # 行级 diff（nullable，null 原样透传给前端显示 "—"）
    lines_added = serializers.IntegerField(allow_null=True)
    lines_deleted = serializers.IntegerField(allow_null=True)


class IndexedFileSerializer(serializers.Serializer):
    """contract：已索引文件清单单行序列化。"""

    file_path = serializers.CharField()
    file_hash = serializers.CharField()
    last_commit_sha = serializers.CharField(allow_blank=True)
    last_commit_authored_at = serializers.DateTimeField(allow_null=True)
    indexed_at = serializers.DateTimeField()


class IndexedFilesListView(APIView):
    """contract：已索引文件清单查询 API（搜索 + 分页）。

    GET /api/repositories/{id}/indexed-files/?search=&page=&page_size=

    返回 base 分支 FileIndex 记录，按 indexed_at 倒序。search 走
    `file_path__icontains`；page_size 默认 30，硬上限 200。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, repository_id: str) -> Response:
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        search = (request.query_params.get("search") or "").strip()
        try:
            page = max(int(request.query_params.get("page", 1)), 1)
            page_size = min(max(int(request.query_params.get("page_size", 30)), 1), 200)
        except (TypeError, ValueError):
            return Response(
                {"detail": "page / page_size 必须为正整数"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = FileIndex.objects.filter(repository_id=repository_id)
        if search:
            qs = qs.filter(file_path__icontains=search)
        qs = qs.order_by("-indexed_at", "file_path")

        total = await qs.acount()
        offset = (page - 1) * page_size
        items = [item async for item in qs[offset : offset + page_size]]

        serializer = IndexedFileSerializer(items, many=True)
        data = await sync_to_async(lambda: serializer.data)()

        return Response(
            {
                "items": data,
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        )


class IndexHistoryListView(APIView):
    """IndexHistory 操作记录查询 API（分页）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, repository_id: str) -> Response:
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        limit = min(int(request.query_params.get("limit", 20)), 100)
        offset = int(request.query_params.get("offset", 0))
        status_filter = request.query_params.get("status")

        qs = IndexHistory.objects.filter(repository_id=repository_id)
        if status_filter:
            qs = qs.filter(status=status_filter)

        total = await qs.acount()
        items = [item async for item in qs[offset : offset + limit]]

        serializer = IndexHistorySerializer(items, many=True)
        data = await sync_to_async(lambda: serializer.data)()

        return Response({"items": data, "total": total})


class IndexProgressStreamView(APIView):
    """SSE 端点：实时推送索引进度 + 当前 RUNNING IndexHistory。

    GET /api/repositories/{id}/index/stream/  (text/event-stream)

    每帧形如：
        data: {"type": "progress",
               "ts": "...",
               "repository": {index_status, overall_progress, overall_stage,
                              index_total_chunks, ...},
               "running_history": null | {id, status, from_sha, to_sha,
                                          files_added, files_modified,
                                          files_deleted, changed_files,
                                          summary_text, ...}}

    终止条件：
    1. 仓库不在 INDEXING 状态且无 RUNNING IndexHistory → 推 done 关闭
    2. 达到 max_ticks 上限（防止后端长连接泄漏）→ 推 done 关闭
    3. 客户端断开 → ASGI 自动取消 generator
    """

    permission_classes = [IsAuthenticated]
    # 显式声明 SSE renderer，避免 DRF 因 Accept: text/event-stream 而 406
    renderer_classes = [ServerSentEventRenderer]

    async def get(self, request: Any, repository_id: str) -> Any:
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        tick_interval = float(getattr(settings, "INDEX_STREAM_TICK_INTERVAL", 1.0))
        max_ticks = int(getattr(settings, "INDEX_STREAM_MAX_TICKS", 300))

        async def event_stream():
            ticks = 0
            while ticks < max_ticks:
                try:
                    repo = await Repository.objects.aget(id=repository_id)
                except Repository.DoesNotExist:
                    yield _format_sse({"type": "done", "reason": "repo_deleted"})
                    return

                running_history = (
                    await IndexHistory.objects.filter(
                        repository_id=repository_id,
                        status=IndexHistoryStatus.RUNNING,
                    )
                    .order_by("-created_at")
                    .afirst()
                )

                progress = _compute_index_progress(repo)
                repo_payload = {
                    "index_status": repo.index_status,
                    "last_indexed_at": (
                        repo.last_indexed_at.isoformat() if repo.last_indexed_at else None
                    ),
                    "index_error": repo.index_error,
                    **progress,
                }

                running_payload = None
                if running_history is not None:
                    running_payload = await sync_to_async(
                        lambda: IndexHistorySerializer(running_history).data
                    )()

                # work item-03：在帧 payload 顶层追加 graph 字段
                # 与 ``repository`` / ``running_history`` 平级，老消费者忽略未知字段
                # 不破坏 implementation 既有 schema。
                graph_payload = await _build_graph_payload(repo)

                yield _format_sse(
                    {
                        "type": "progress",
                        "ts": timezone.now().isoformat(),
                        "repository": repo_payload,
                        "running_history": running_payload,
                        "graph": graph_payload,
                    }
                )

                # 终止条件：仓库非 INDEXING + 无 RUNNING IndexHistory + graph 非 RUNNING
                # 三条件均满足才推 done idle 关闭流；任一活跃路径仍在跑（向量轨或
                # 图谱轨）都继续推 progress 帧——避免手动触发的纯 graph 构建场景
                # 原终止判定立刻关闭流让前端拿不到进度（implementation CONTEXT Grey Area 2
                # 终止条件决议）。
                if (
                    repo.index_status != IndexStatus.INDEXING
                    and running_history is None
                    and repo.graph_build_status != RepositoryGraphStatus.RUNNING
                ):
                    yield _format_sse({"type": "done", "reason": "idle"})
                    return

                ticks += 1
                if ticks >= max_ticks:
                    break

                if tick_interval > 0:
                    await asyncio.sleep(tick_interval)

            yield _format_sse({"type": "done", "reason": "max_ticks"})

        response = StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


def _format_sse(payload: dict[str, Any]) -> str:
    """格式化为 SSE data 行。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _build_graph_payload(repo: Repository) -> dict[str, Any]:
    """构造 SSE 帧的 graph 段 payload（9 字段，implementation-03）。

    字段口径（CONTEXT Grey Area 2 锁定）：

    - ``status`` / ``stage`` / ``files_processed`` / ``files_total`` /
      ``current_file``：直接取 ``Repository`` 4 字段快照
    - ``percent``：``min(100, int(files_processed / files_total * 100))``
      ``files_total <= 0`` 兜底 0（避免除零）
    - ``started_at``：优先 RUNNING ``GraphBuildHistory.started_at``，无 RUNNING
      时取 ``Repository.graph_last_built_at`` 兜底，便于 completed/failed/cancelled
      态前端展示"上次构建于 ..."
    - ``edge_count_so_far``：最新一条 ``GraphBuildHistory`` 的
      ``symbols_count + imports_count + calls_count + endpoints_count`` 求和；
      运行态可能为 0 或上次构建残值——前端在 running 态可隐藏该字段
    - ``error_message``：最新 FAILED ``GraphBuildHistory.error_message``，
      无则空串，便于失败态前端展示

    本 helper 由 ``IndexProgressStreamView`` 与 ``CodegraphProgressStreamView``
    共享（避免双写）；3 个 ``GraphBuildHistory`` 查询合计 ≤ 3 次 ORM IO，命中
    ``idx_gbh_repo_started`` 索引。
    """
    repository_id = str(repo.id)
    latest_running_graph = (
        await GraphBuildHistory.objects.filter(
            repository_id=repository_id,
            status=GraphBuildHistoryStatus.RUNNING,
        )
        .order_by("-started_at")
        .afirst()
    )
    latest_any_graph = (
        await GraphBuildHistory.objects.filter(repository_id=repository_id)
        .order_by("-started_at")
        .afirst()
    )
    latest_failed_graph = (
        await GraphBuildHistory.objects.filter(
            repository_id=repository_id,
            status=GraphBuildHistoryStatus.FAILED,
        )
        .order_by("-started_at")
        .afirst()
    )

    files_processed = int(repo.graph_files_processed or 0)
    files_total = int(repo.graph_files_total or 0)
    percent = min(100, int(files_processed / files_total * 100)) if files_total > 0 else 0

    edge_count_so_far = 0
    if latest_any_graph is not None:
        edge_count_so_far = (
            (latest_any_graph.symbols_count or 0)
            + (latest_any_graph.imports_count or 0)
            + (latest_any_graph.calls_count or 0)
            + (latest_any_graph.endpoints_count or 0)
        )

    started_at: str | None
    if latest_running_graph is not None and latest_running_graph.started_at:
        started_at = latest_running_graph.started_at.isoformat()
    elif repo.graph_last_built_at:
        started_at = repo.graph_last_built_at.isoformat()
    else:
        started_at = None

    error_message = latest_failed_graph.error_message if latest_failed_graph is not None else ""

    return {
        "status": repo.graph_build_status,
        "stage": repo.graph_stage,
        "files_processed": files_processed,
        "files_total": files_total,
        "percent": percent,
        "current_file": repo.current_graph_file,
        "started_at": started_at,
        "edge_count_so_far": edge_count_so_far,
        "error_message": error_message,
    }


class IndexStatsView(APIView):
    """统计 API（chunk 数、语言分布、覆盖率）。

    Qdrant 偶发慢 / 超时 / 不可用时返回 200 + 降级数据（避免前端轮询持续报 500）。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, repository_id: str) -> Response:
        from code_relations.models import ChunkEdge
        from services.branch_utils import resolve_branch_for_query

        try:
            repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        # 文件计数统一以 FileIndex 为唯一事实源（与 IndexedFilesListView 同源），
        # 不再依赖 Qdrant scroll 出来的 distinct file_path：那个会在多次重建后
        # 与 FileIndex 漂移（Qdrant 不删旧 + 累积写新），导致"索引统计"和
        # "已索引文件清单"两个面板的数字对不上。
        indexed_files = await FileIndex.objects.filter(
            repository_id=repository_id,
        ).acount()

        # 图谱/ChunkEdge 维度 branch-aware。归一化复用
        # resolve_branch_for_query（与 GraphRagStatusView 同口径，不自写
        # default_branch 判定）：缺省/==base → branch_name="" 干净 base 计数
        # （向后兼容）；feature → branch_name__in=["", effective_branch] 合并。
        branch = request.query_params.get("branch")
        effective_branch, _ = await resolve_branch_for_query(repository_id, branch)
        base_branch_name, _ = await resolve_branch_for_query(repository_id, None)
        if not effective_branch or effective_branch == base_branch_name:
            edge_count = await ChunkEdge.objects.filter(
                repository_id=repository_id, branch_name=""
            ).acount()
        else:
            edge_count = await ChunkEdge.objects.filter(
                repository_id=repository_id,
                branch_name__in=["", effective_branch],
            ).acount()

        # 口径裁定（Open Question 2 / security mitigation-04 DoS 防御）：chunks_total 来自
        # Qdrant base collection points，overlay 合并需双 collection scroll（比
        # ChunkEdge 纯 ORM count 重得多，且 Qdrant 已有不可用降级路径）。本 phase
        # **收窄**——chunks_total 始终保 base collection points，仅图谱/ChunkEdge
        # 维度（edge_count）做 branch-aware 合并。overlay 向量合并 deferred。

        try:
            stats = await sync_to_async(QdrantService.get_collection_stats)(str(repository_id))
        except Exception as exc:
            logger.warning(
                "index_stats_qdrant_unavailable",
                repository_id=repository_id,
                error=str(exc),
            )
            # 降级：用 Repository 自身的 chunks 计数器作为近似值，
            # language_distribution 直接置空，coverage 为 None
            return Response(
                {
                    "chunks_total": repository.index_total_chunks,
                    "language_distribution": {},
                    "indexed_files_count": indexed_files,
                    "edge_count": edge_count,
                    "coverage_percent": None,
                    "qdrant_unavailable": True,
                    "warning": "Qdrant 暂时不可用，已返回缓存计数；请稍后重试以获取最新统计",
                }
            )

        # 覆盖率：已写入 chunks / 本次 run 预期 chunks（不强对比文件，避免
        # Qdrant 累积 vs Repository 单次预期的口径混淆）
        total_chunks = repository.index_total_chunks
        coverage = 0.0
        if total_chunks > 0:
            coverage = round(stats.get("points_count", 0) / total_chunks * 100, 1)

        return Response(
            {
                "chunks_total": stats.get("points_count", 0),
                "language_distribution": stats.get("language_distribution", {}),
                "indexed_files_count": indexed_files,
                "edge_count": edge_count,
                "coverage_percent": coverage,
            }
        )


class RepositoryCollectionHealthView(APIView):
    """仓库 Qdrant 集合健康校验 API。

    Qdrant 不可用时返回 200 + status=unhealthy，便于前端 UI 提示而非整页报错。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, repository_id: str) -> Response:
        try:
            repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        # FileIndex 是文件级唯一事实源；与 IndexedFilesListView 对齐
        indexed_files = await FileIndex.objects.filter(
            repository_id=repository_id,
        ).acount()

        try:
            health = await sync_to_async(QdrantService.check_collection_health)(str(repository_id))
        except Exception as exc:
            logger.warning(
                "index_health_qdrant_unavailable",
                repository_id=repository_id,
                error=str(exc),
            )
            return Response(
                {
                    "status": "unhealthy",
                    "collection_exists": False,
                    "points_count": 0,
                    "indexed_files_count": indexed_files,
                    "error": f"Qdrant 暂时不可用：{exc}",
                }
            )

        # 注意：曾经在这里把 ``Repository.index_total_chunks`` 当 expected_points
        # 与 Qdrant points_count 强对比 → 前端永远显示"数量不匹配（预期 N）"。
        # 实际上：
        #   - ``index_total_chunks`` 是"本次 run 的预期 chunks"（增量/续传时也只
        #     反映本批，不是 collection 累积）。
        #   - Qdrant points_count 是历史累积（per-file delete 只在 git_diff 路径
        #     做，全量重建时不会清旧 points），两者天然会漂移。
        # 改为只展示绝对值 + 文件计数，让 UI 不再做错误对比。
        health["indexed_files_count"] = indexed_files

        return Response(health)


class IndexFreshnessView(APIView):
    """索引新鲜度指示 API。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, repository_id: str) -> Response:
        try:
            repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        local_sha = repository.last_indexed_commit_sha or ""
        remote_sha = ""
        error = None

        if repository.git_url:
            try:
                remote_sha = await self._get_remote_head(repository.git_url)
            except Exception as e:
                error = str(e)

        is_fresh = bool(local_sha and local_sha == remote_sha) if remote_sha else None

        return Response(
            {
                "local_sha": local_sha,
                "remote_sha": remote_sha,
                "is_fresh": is_fresh,
                "last_indexed_at": repository.last_indexed_at,
                "error": error,
            }
        )

    @staticmethod
    async def _get_remote_head(git_url: str) -> str:
        """通过 git ls-remote 获取远端 HEAD SHA（无需 clone）。"""
        proc = await asyncio.create_subprocess_exec(
            "git",
            "ls-remote",
            git_url,
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        if proc.returncode != 0:
            msg = "git ls-remote 失败"
            raise RuntimeError(msg)
        output = stdout.decode().strip()
        if output:
            return output.split()[0]
        return ""


# ---------------------------------------------------------------------------
# 索引快照导入导出
# ---------------------------------------------------------------------------


class IndexSnapshotExportView(APIView):
    """导出索引快照（备份）。

    POST /api/repositories/{id}/index/snapshot/export/
    创建 Qdrant 快照并以流式响应返回文件下载。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, repository_id: str) -> StreamingHttpResponse | Response:
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        health = await sync_to_async(QdrantService.check_collection_health)(str(repository_id))
        if not health.get("collection_exists") or health.get("points_count", 0) == 0:
            return Response({"detail": "索引不存在或为空"}, status=status.HTTP_404_NOT_FOUND)

        snapshot_name = await sync_to_async(QdrantService.create_snapshot)(str(repository_id))
        if not snapshot_name:
            return Response(
                {"detail": "创建快照失败"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        config = await QdrantService.get_config()
        base_url = config.get("url", "http://localhost:6333")
        collection_name = QdrantService.get_collection_name(str(repository_id))
        download_url = f"{base_url}/collections/{collection_name}/snapshots/{snapshot_name}"

        qdrant_headers: dict[str, str] = {}
        if config.get("api_key"):
            qdrant_headers["api-key"] = config["api_key"]

        async def stream_snapshot():
            async with httpx.AsyncClient(timeout=httpx.Timeout(300)) as client:
                async with client.stream("GET", download_url, headers=qdrant_headers) as resp:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        yield chunk

        response = StreamingHttpResponse(
            stream_snapshot(),
            content_type="application/octet-stream",
        )
        response["Content-Disposition"] = f'attachment; filename="{snapshot_name}"'
        return response


class IndexSnapshotImportView(APIView):
    """导入索引快照（恢复）。

    POST /api/repositories/{id}/index/snapshot/import/
    上传 Qdrant 快照文件，恢复到对应 collection。
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    async def post(self, request: Any, repository_id: str) -> Response:
        try:
            repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        snapshot_file = request.FILES.get("snapshot")
        if not snapshot_file:
            return Response({"detail": "请上传快照文件"}, status=status.HTTP_400_BAD_REQUEST)

        config = await QdrantService.get_config()
        base_url = config.get("url", "http://localhost:6333")
        collection_name = QdrantService.get_collection_name(str(repository_id))
        upload_url = f"{base_url}/collections/{collection_name}/snapshots/upload"

        qdrant_headers: dict[str, str] = {}
        if config.get("api_key"):
            qdrant_headers["api-key"] = config["api_key"]

        file_content = await sync_to_async(snapshot_file.read)()

        async with httpx.AsyncClient(timeout=httpx.Timeout(600)) as client:
            resp = await client.post(
                upload_url,
                params={"priority": "snapshot"},
                content=file_content,
                headers={**qdrant_headers, "Content-Type": "application/octet-stream"},
            )

        if resp.status_code not in (200, 201):
            return Response(
                {"detail": f"恢复快照失败: {resp.text}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        health = await sync_to_async(QdrantService.check_collection_health)(str(repository_id))
        points_count = health.get("points_count", 0)

        if points_count > 0:
            repository.index_status = IndexStatus.INDEXED
            repository.index_error = None
            repository.index_total_chunks = points_count
            repository.index_processed_chunks = points_count
            repository.index_write_total = points_count
            repository.index_write_processed = points_count
            if not repository.last_indexed_at:
                repository.last_indexed_at = timezone.now()
            await repository.asave(
                update_fields=[
                    "index_status",
                    "last_indexed_at",
                    "index_error",
                    "index_total_chunks",
                    "index_processed_chunks",
                    "index_write_total",
                    "index_write_processed",
                ]
            )

        return Response({"message": "索引快照已恢复", "points_count": points_count})


# ---------------------------------------------------------------------------
# 自动索引触发
# ---------------------------------------------------------------------------


class RepositoryWebhookView(APIView):
    """Webhook 端点接收 push 事件并触发增量索引。

    支持 GitHub、GitLab、Gitea 三种平台的签名验证。
    此端点无需 JWT 认证（使用 webhook secret 验证）。
    """

    from rest_framework.permissions import AllowAny

    permission_classes = [AllowAny]
    authentication_classes: list = []

    async def post(self, request: Any, repository_id: str) -> Response:
        from tasks.index_trigger_tasks import (
            cleanup_branch_index,
            parse_push_event,
            trigger_auto_index,
            trigger_branch_rebuild,
            verify_gitlab_token,
            verify_webhook_signature,
        )

        try:
            repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        # 检查开关
        if not repository.auto_index_enabled:
            return Response(
                {"detail": "自动索引未启用"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # 签名验证
        if repository.webhook_secret:
            payload_bytes = request.body
            platform = repository.git_platform or "github"

            if platform == "gitlab":
                token = request.headers.get("X-Gitlab-Token", "")
                if not verify_gitlab_token(repository.webhook_secret, token):
                    return Response(
                        {"detail": "签名验证失败"},
                        status=status.HTTP_401_UNAUTHORIZED,
                    )
            else:
                # GitHub / Gitea 使用 work item
                signature = request.headers.get(
                    "X-Hub-Signature-256",
                    request.headers.get("X-Gitea-Signature", ""),
                )
                if not verify_webhook_signature(
                    payload_bytes, repository.webhook_secret, signature
                ):
                    return Response(
                        {"detail": "签名验证失败"},
                        status=status.HTTP_401_UNAUTHORIZED,
                    )

        # 解析 push 事件
        platform = repository.git_platform or "github"
        event_data = parse_push_event(platform, request.data)
        commit_sha = event_data.get("after", "")
        branch_name = str(event_data.get("branch_name", "") or "")
        is_delete = bool(event_data.get("is_delete", False))
        base_branch = repository.default_branch

        if is_delete and branch_name and branch_name != base_branch:
            result = await cleanup_branch_index(repository, branch_name)
        elif branch_name == base_branch:
            result = await trigger_auto_index(
                repository,
                "webhook",
                commit_sha,
                dedup_branch_name=base_branch,
            )
        elif branch_name:
            result = await trigger_branch_rebuild(repository, branch_name, commit_sha)
        else:
            result = await trigger_auto_index(repository, "webhook", commit_sha)

        status_code = (
            status.HTTP_202_ACCEPTED if result["status"] == "triggered" else status.HTTP_200_OK
        )
        return Response(result, status=status_code)
