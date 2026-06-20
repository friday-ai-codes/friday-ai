"""delivery 最小 REST（adrf APIView，IsAuthenticated）。

- ``WorkItemUpsertView.post``：校验三元组 → ``WorkItemService().upsert(source="manual")``
  落库（回源失败 fail-soft，仍返回当前行 + facet 完整度）→ 返回 ``WorkItemSerializer``。
- ``WorkItemDetailView.get``：按三元组 query params 读取已落库 WorkItem，不旁路 fetch；
  不存在 → 404。

写端点经单一 upsert（INV-6，无直接 ORM 写）；T-28-08：``IsAuthenticated`` 守卫。
"""

from __future__ import annotations

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from delivery.api.serializers import (
    CommentTreeNodeSerializer,
    CrawlRequestSerializer,
    DocumentSnapshotSerializer,
    IngestBatchDispatchRequestSerializer,
    IngestBatchRunSerializer,
    IngestDispatchRequestSerializer,
    IngestQueueItemSerializer,
    IngestRunSerializer,
    JsonIngestRequestSerializer,
    ScreenshotRecallResultSerializer,
    WorkItemArtifactsQuerySerializer,
    WorkItemSerializer,
    WorkItemUpsertRequestSerializer,
)
from delivery.models import Document, DocumentType, IngestRun, WorkItem, default_steps
from delivery.services import (
    WorkItemIdentity,
    WorkItemService,
    aproject_comment_tree,
    ingest_from_urls,
    parse_board_url,
)
from services.background_runner import run_in_background

logger = structlog.get_logger(__name__)


class WorkItemUpsertView(APIView):
    """按三元组手动 upsert WorkItem（origin=manual）。"""

    permission_classes = [IsAuthenticated]

    async def post(self, request):
        serializer = WorkItemUpsertRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        identity = WorkItemIdentity(
            feishu_project_key=data["feishu_project_key"],
            work_item_type=data["work_item_type"],
            work_item_id=data["work_item_id"],
        )
        work_item = await WorkItemService().upsert(identity, source="manual", fetch=True)
        # 序列化触发 sync_states 反向查询 → sync_to_async 桥接（async ORM 约定）
        payload = await sync_to_async(lambda: WorkItemSerializer(work_item).data)()
        return Response(payload, status=status.HTTP_200_OK)


class WorkItemDetailView(APIView):
    """按三元组读取已落库 WorkItem（只读，不旁路 fetch）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request):
        project_key = request.query_params.get("feishu_project_key")
        work_item_type = request.query_params.get("work_item_type")
        raw_id = request.query_params.get("work_item_id")
        if not (project_key and work_item_type and raw_id):
            return Response(
                {
                    "detail": (
                        "缺少三元组参数（feishu_project_key / work_item_type / work_item_id）"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            work_item_id = int(raw_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "work_item_id 必须为整数"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        work_item = await WorkItem.objects.filter(
            feishu_project_key=project_key,
            work_item_type=work_item_type,
            work_item_id=work_item_id,
        ).afirst()
        if work_item is None:
            return Response({"detail": "WorkItem 不存在"}, status=status.HTTP_404_NOT_FOUND)

        payload = await sync_to_async(lambda: WorkItemSerializer(work_item).data)()
        return Response(payload, status=status.HTTP_200_OK)


class WorkItemCommentTreeView(APIView):
    """按三元组返回当前评论树投影（只读，IsAuthenticated）。

    只读端点：按三元组命中**已落库** WorkItem（不旁路 fetch / 不落库），经
    ``project_comment_tree`` 从事件流读时投影当前评论树（CMT-02）。不存在 → 404。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request):
        project_key = request.query_params.get("feishu_project_key")
        work_item_type = request.query_params.get("work_item_type")
        raw_id = request.query_params.get("work_item_id")
        if not (project_key and work_item_type and raw_id):
            return Response(
                {
                    "detail": (
                        "缺少三元组参数（feishu_project_key / work_item_type / work_item_id）"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            work_item_id = int(raw_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "work_item_id 必须为整数"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        work_item = await WorkItem.objects.filter(
            feishu_project_key=project_key,
            work_item_type=work_item_type,
            work_item_id=work_item_id,
        ).afirst()
        if work_item is None:
            return Response({"detail": "WorkItem 不存在"}, status=status.HTTP_404_NOT_FOUND)

        tree = await aproject_comment_tree(work_item)
        comments = await sync_to_async(lambda: CommentTreeNodeSerializer(tree, many=True).data)()
        return Response(
            {"work_item_id": work_item.work_item_id, "comments": comments},
            status=status.HTTP_200_OK,
        )


class WorkItemPrdDocumentView(APIView):
    """按三元组只读检索 WorkItem 的 PRD 正文快照（IsAuthenticated，DOC-02 成功标准 3）。

    只读端点：按三元组命中**已落库** WorkItem（不旁路 fetch / 不写表），经独立操作态
    ``Document`` 实体（``filter(work_item, document_type=prd)`` →
    ``current_version.content``）检索 PRD 正文快照。同 WorkItem 多份 PRD 取最近更新一条。
    可选 ``?document_type=`` 复用同端点取技术方案等其他类型快照（默认 prd，非法值 400）。

    未命中语义明确：WorkItem 不存在 → 404；WorkItem 存在但无对应 Document → 404
    （不臆造空文档）。``select_related("current_version")`` 预取防 async 隐式同步访问。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request):
        project_key = request.query_params.get("feishu_project_key")
        work_item_type = request.query_params.get("work_item_type")
        raw_id = request.query_params.get("work_item_id")
        if not (project_key and work_item_type and raw_id):
            return Response(
                {
                    "detail": (
                        "缺少三元组参数（feishu_project_key / work_item_type / work_item_id）"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            work_item_id = int(raw_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "work_item_id 必须为整数"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        document_type = request.query_params.get("document_type", DocumentType.PRD)
        if document_type not in DocumentType.values:
            return Response(
                {"detail": "document_type 非法"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        work_item = await WorkItem.objects.filter(
            feishu_project_key=project_key,
            work_item_type=work_item_type,
            work_item_id=work_item_id,
        ).afirst()
        if work_item is None:
            return Response({"detail": "WorkItem 不存在"}, status=status.HTTP_404_NOT_FOUND)

        document = (
            await Document.objects.filter(work_item=work_item, document_type=document_type)
            .select_related("current_version")
            .order_by("-updated_at")
            .afirst()
        )
        if document is None:
            return Response(
                {"detail": "该 WorkItem 暂无对应文档快照"},
                status=status.HTTP_404_NOT_FOUND,
            )

        payload = await sync_to_async(lambda: DocumentSnapshotSerializer(document).data)()
        return Response(payload, status=status.HTTP_200_OK)


class IngestDispatchView(APIView):
    """一键摄取触发端点（POST，IsAuthenticated，ING-01）。

    校验 ``(board_url, mr_url)`` → 解析看板 URL 留痕 Project（可空）→ 建 running
    ``IngestRun`` → 经 ``run_in_background`` 派发 ``ingest_from_urls`` 脱离请求生命周期
    → 立即 202 返回 ``{run_id, dispatched}``（长摄取异步，避免请求阻塞，T-32-03/04）。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request):
        serializer = IngestDispatchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        board_url = serializer.validated_data["board_url"]
        mr_url = serializer.validated_data["mr_url"]

        # 看板 URL 解析出的 Project 留痕（解析不出/未配置 → None，不阻断派发）
        project = None
        board = parse_board_url(board_url)
        if board is not None:
            from projects.models import Project

            project = await Project.objects.filter(
                feishu_project_key=board.feishu_project_key
            ).afirst()

        run = await sync_to_async(IngestRun.objects.create)(
            board_url=board_url,
            mr_url=mr_url,
            status=IngestRun.Status.RUNNING,
            steps=default_steps(),
            project=project,
        )

        run_id = str(run.id)
        run_in_background(
            lambda: ingest_from_urls(run_id, board_url, mr_url),
            name=f"ingest:{run_id}",
        )
        return Response(
            {"run_id": run_id, "dispatched": True},
            status=status.HTTP_202_ACCEPTED,
        )


class IngestRunDetailView(APIView):
    """一键摄取状态回流端点（GET，IsAuthenticated，只读不旁路触发，T-32-03）。

    按 ``run_id`` 命中 ``IngestRun`` → ``IngestRunSerializer`` 回流真实步骤结果；
    不存在 → 404。

    归属/范围说明（IN-01）：``IngestRun`` 无 owner/created_by 字段，本端点对所有已
    登录用户开放读取，与同 app 其余只读详情端点（``WorkItemDetailView`` 等按业务键
    命中、不按 ``request.user`` 过滤）的既有范式一致——内部团队工具 + 不可猜
    UUIDv4 主键，威胁面有限；回流内容已脱敏（``steps[*].error`` / ``error`` 经
    ``_safe_error``，不含明文凭证）。如未来引入按用户/项目的多租隔离，应在 ``IngestRun``
    增 ``created_by`` 并在此按 ``request.user`` 过滤（当前刻意不过度设计）。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request, run_id):
        run = await IngestRun.objects.filter(id=run_id).afirst()
        if run is None:
            return Response(
                {"detail": "IngestRun 不存在"}, status=status.HTTP_404_NOT_FOUND
            )
        payload = await sync_to_async(lambda: IngestRunSerializer(run).data)()
        return Response(payload, status=status.HTTP_200_OK)


async def _resolve_board_project(board_url: str):
    """看板 URL 解析出的 Project 留痕（解析不出/未配置 → None，不阻断派发）。"""
    board = parse_board_url(board_url)
    if board is None:
        return None
    from projects.models import Project

    return await Project.objects.filter(
        feishu_project_key=board.feishu_project_key
    ).afirst()


class IngestBatchDispatchView(APIView):
    """批量摄取触发端点（POST，IsAuthenticated）。

    校验 ``items`` 列表（1..50 组 ``(board_url, mr_url)``）→ 生成共享 ``batch_id`` →
    每组建一条 running ``IngestRun`` 并经 ``run_in_background`` 派发既有单组编排
    ``ingest_from_urls``（不新建编排机制，纯分组并行复用）→ 立即 202 返回
    ``{batch_id, runs:[{run_id, board_url, mr_url}]}``。

    各组独立隔离：任一组解析/摄取失败只落该 run，互不阻断（沿用单组 best-effort）。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request):
        serializer = IngestBatchDispatchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["items"]

        import uuid

        batch_id = uuid.uuid4()
        runs_payload: list[dict] = []
        for item in items:
            board_url = item["board_url"]
            mr_url = item["mr_url"]
            project = await _resolve_board_project(board_url)

            run = await sync_to_async(IngestRun.objects.create)(
                batch_id=batch_id,
                board_url=board_url,
                mr_url=mr_url,
                status=IngestRun.Status.RUNNING,
                steps=default_steps(),
                project=project,
            )
            run_id = str(run.id)
            run_in_background(
                lambda rid=run_id, b=board_url, m=mr_url: ingest_from_urls(rid, b, m),
                name=f"ingest:{run_id}",
            )
            runs_payload.append(
                {"run_id": run_id, "board_url": board_url, "mr_url": mr_url}
            )

        return Response(
            {"batch_id": str(batch_id), "runs": runs_payload},
            status=status.HTTP_202_ACCEPTED,
        )


class IngestBatchDetailView(APIView):
    """批量摄取状态回流端点（GET，IsAuthenticated，只读不旁路触发）。

    按 ``batch_id`` 命中该批所有 ``IngestRun`` → 返回聚合状态
    （任一 run 仍 running 则批 ``running``，否则 ``completed``——run 级 failed 由
    前端从 run.status/steps 推导 partial，与单组语义一致）+ 各 run 结构化结果。
    该批无任何 run → 404。归属/范围说明同 ``IngestRunDetailView``（内部团队工具 +
    不可猜 UUIDv4）。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request, batch_id):
        runs = [
            run
            async for run in IngestRun.objects.filter(batch_id=batch_id).order_by(
                "started_at"
            )
        ]
        if not runs:
            return Response(
                {"detail": "批量摄取记录不存在"}, status=status.HTTP_404_NOT_FOUND
            )

        batch_status = (
            "running"
            if any(r.status == IngestRun.Status.RUNNING for r in runs)
            else "completed"
        )
        runs_payload = await sync_to_async(
            lambda: IngestBatchRunSerializer(runs, many=True).data
        )()
        return Response(
            {"batch_id": str(batch_id), "status": batch_status, "runs": runs_payload},
            status=status.HTTP_200_OK,
        )


class JsonIngestResolveView(APIView):
    """JSON 批量摄取预览解析端点（POST，IsAuthenticated，只读不落库）。

    把粘贴的若干 ``{space, work_item_id, work_item_type?, mr_url?}`` 逐项解析空间
    （UUID / 飞书 key / 模糊名）→ 拼工作项三元组 + 详情 URL + 逐项校验，供前端预览/编辑。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request):
        from delivery.services.json_ingest import aresolve_items

        serializer = JsonIngestRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["items"]
        resolved = await aresolve_items(items)
        return Response({"items": resolved}, status=status.HTTP_200_OK)


class IngestCrawlView(APIView):
    """URL 爬取端点（POST，IsAuthenticated）。

    给一个链接（飞书文档 / 多维表格 / wiki / 通用 URL），后端 agent 抓取内容并用
    系统默认 LLM 抽成 ``{space, work_item_id, work_item_type, mr_url}`` 列表，回填到
    前端「待爬取」编辑表（再走既有 resolve/dispatch 流水线）。

    同步返回（抓取 + 单次 AI 调用，秒级~数十秒）。结果 status：
    ``ok`` / ``feishu_not_configured``（带系统设置深链）/ ``empty`` / ``error``。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request):
        from delivery.services.crawl_service import crawl_url

        serializer = CrawlRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        url = serializer.validated_data["url"]
        result = await crawl_url(url)
        return Response(result.to_dict(), status=status.HTTP_200_OK)


class JsonIngestBatchView(APIView):
    """JSON 批量摄取派发端点（POST，IsAuthenticated）。

    逐项解析空间 → 对「可解析」项各建 running ``IngestRun``（共享 batch_id，
    steps=work_item/document/mr_diff）→ 单后台协调器 ``run_json_batch`` 有界并发跑
    （默认 3、最大 10）→ 202。不可解析项以 ``skipped`` 回报，不建 run。

    进度复用 ``GET /delivery/ingest/batch/{batch_id}/``；runs 带回三元组供前端拉关联文档。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request):
        import uuid

        from delivery.services.json_ingest import aresolve_items, run_json_batch

        serializer = JsonIngestRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["items"]
        concurrency = serializer.validated_data["concurrency"]

        resolved = await aresolve_items(items)

        batch_id = uuid.uuid4()
        runs_payload: list[dict] = []
        skipped: list[dict] = []
        specs: list[dict] = []
        for item in resolved:
            if not item["resolved"]:
                skipped.append(
                    {
                        "space": item["space"],
                        "work_item_id": item["work_item_id"],
                        "error": item["error"],
                    }
                )
                continue
            run = await sync_to_async(IngestRun.objects.create)(
                batch_id=batch_id,
                board_url=item["board_url"],
                mr_url=item["mr_url"],
                status=IngestRun.Status.RUNNING,
                steps=default_steps(),
            )
            run_id = str(run.id)
            specs.append(
                {
                    "run_id": run_id,
                    "feishu_project_key": item["feishu_project_key"],
                    "work_item_type": item["work_item_type"],
                    "work_item_id": item["work_item_id"],
                    "mr_url": item["mr_url"],
                    "board_url": item["board_url"],
                }
            )
            runs_payload.append(
                {
                    "run_id": run_id,
                    "feishu_project_key": item["feishu_project_key"],
                    "work_item_type": item["work_item_type"],
                    "work_item_id": item["work_item_id"],
                    "mr_url": item["mr_url"],
                    "board_url": item["board_url"],
                    "space_name": item["space_name"],
                }
            )

        if specs:
            run_in_background(
                lambda s=specs, c=concurrency: run_json_batch(s, c),
                name=f"json-ingest:{batch_id}",
            )

        return Response(
            {"batch_id": str(batch_id), "runs": runs_payload, "skipped": skipped},
            status=status.HTTP_202_ACCEPTED,
        )


def _aggregate_queue_status(runs: list[IngestRun]) -> str:
    """按优先级 running>queued>stopped>failed>completed 聚合该批 status。

    任一行 RUNNING → running；否则任一 QUEUED → queued；依次 stopped/failed；全
    COMPLETED → completed。供 list 聚合与 detail 聚合共用同一判定（DB 真相源、不依赖内存）。
    """
    statuses = {run.status for run in runs}
    if IngestRun.Status.RUNNING in statuses:
        return "running"
    if IngestRun.Status.QUEUED in statuses:
        return "queued"
    if IngestRun.Status.STOPPED in statuses:
        return "stopped"
    if IngestRun.Status.FAILED in statuses:
        return "failed"
    return "completed"


# list 端点按最近 N 批返回（OQ-4 per-batch 粒度；A4 内部工具无分页，N=50 上限避免大查询）
_QUEUE_LIST_LIMIT = 50


class IngestQueueView(APIView):
    """爬取入库队列端点（GET=list / POST=enqueue，IsAuthenticated，CRAWL-01）。

    同一 path ``ingest/queue/`` 由单一 view 承载两动作（同 path 两 view 不可，故合并）：

    - ``get``（list）：从 ``IngestRun``（DB）按 ``batch_id`` 分组重建队列列表（聚合
      status/progress/durable_job_id/时间戳）——CRAWL-01 断点恢复命门，**不依赖任何内存态**，
      刷新 / 容器重建后队列可恢复。
    - ``post``（enqueue）：镜像 ``JsonIngestBatchView``——``aresolve_items`` 解析 → 对
      resolved 项建 ``IngestRun(QUEUED)`` 共享 batch_id → ``DurableTaskService.defer``
      （``QUEUE_CRAWL_INGEST``，deterministic ``idempotency_key="crawl_ingest:{batch_id}"``）
      → 回写 durable_job_id/idempotency_key → 202。不可解析项以 ``skipped`` 回报不建行。

    归属/范围说明沿用 ``IngestRunDetailView``（``IngestRun`` 无 owner + 不可猜 UUIDv4，
    内部团队工具，全端点 IsAuthenticated）。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request):
        @sync_to_async
        def _build() -> list[dict]:
            from collections import OrderedDict

            groups: "OrderedDict[object, list[IngestRun]]" = OrderedDict()
            for run in IngestRun.objects.filter(batch_id__isnull=False).order_by(
                "-started_at"
            ):
                groups.setdefault(run.batch_id, []).append(run)

            items: list[dict] = []
            for batch_id, batch_runs in list(groups.items())[:_QUEUE_LIST_LIMIT]:
                total = len(batch_runs)
                done = sum(
                    1 for r in batch_runs if r.status == IngestRun.Status.COMPLETED
                )
                items.append(
                    {
                        "batch_id": batch_id,
                        "status": _aggregate_queue_status(batch_runs),
                        "total": total,
                        "done": done,
                        "url_count": total,
                        "durable_job_id": next(
                            (r.durable_job_id for r in batch_runs if r.durable_job_id),
                            "",
                        ),
                        "idempotency_key": next(
                            (r.idempotency_key for r in batch_runs if r.idempotency_key),
                            "",
                        ),
                        "started_at": min(r.started_at for r in batch_runs),
                        "updated_at": max(r.updated_at for r in batch_runs),
                        "error": next((r.error for r in batch_runs if r.error), ""),
                    }
                )
            return IngestQueueItemSerializer(items, many=True).data

        items = await _build()
        return Response({"items": items}, status=status.HTTP_200_OK)

    async def post(self, request):
        import uuid

        from delivery.services.json_ingest import aresolve_items
        from durable import QUEUE_CRAWL_INGEST, DurableTaskService

        serializer = JsonIngestRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["items"]
        concurrency = serializer.validated_data["concurrency"]

        resolved = await aresolve_items(items)

        batch_id = uuid.uuid4()
        key = f"crawl_ingest:{batch_id}"
        runs_payload: list[dict] = []
        skipped: list[dict] = []
        created_ids: list = []
        for item in resolved:
            if not item["resolved"]:
                skipped.append(
                    {
                        "space": item["space"],
                        "work_item_id": item["work_item_id"],
                        "error": item["error"],
                    }
                )
                continue
            run = await sync_to_async(IngestRun.objects.create)(
                batch_id=batch_id,
                board_url=item["board_url"],
                mr_url=item["mr_url"],
                status=IngestRun.Status.QUEUED,
                steps=default_steps(),
                idempotency_key=key,
            )
            created_ids.append(run.id)
            runs_payload.append(
                {
                    "run_id": str(run.id),
                    "feishu_project_key": item["feishu_project_key"],
                    "work_item_type": item["work_item_type"],
                    "work_item_id": item["work_item_id"],
                    "mr_url": item["mr_url"],
                    "board_url": item["board_url"],
                    "space_name": item["space_name"],
                }
            )

        if not created_ids:
            # 全部不可解析：不派发，返回 202 + skipped（前端据此提示逐项错误）。
            return Response(
                {
                    "batch_id": str(batch_id),
                    "runs": [],
                    "skipped": skipped,
                    "dispatched": False,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        # delivery 端点为 async，直接 await defer（无需 async_to_sync，研究 Pitfall 6）。
        job_id = await DurableTaskService.defer(
            "durable_crawl_ingest",
            {"batch_id": str(batch_id), "concurrency": concurrency},
            queue=QUEUE_CRAWL_INGEST,
            idempotency_key=key,
        )
        await sync_to_async(
            lambda: IngestRun.objects.filter(id__in=created_ids).update(
                durable_job_id=job_id
            )
        )()

        return Response(
            {
                "batch_id": str(batch_id),
                "runs": runs_payload,
                "skipped": skipped,
                "dispatched": True,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class IngestQueueDetailView(APIView):
    """队列单批明细端点（GET，IsAuthenticated，只读，CRAWL-01）。

    复用 ``IngestBatchDetailView`` 聚合范式：按 ``batch_id`` 返回该批各 run 明细
    （``IngestBatchRunSerializer``）+ 聚合 status（同 list 优先级判定）。该批无 run → 404。
    归属/范围说明同 ``IngestRunDetailView``。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request, batch_id):
        runs = [
            run
            async for run in IngestRun.objects.filter(batch_id=batch_id).order_by(
                "started_at"
            )
        ]
        if not runs:
            return Response(
                {"detail": "队列批次不存在"}, status=status.HTTP_404_NOT_FOUND
            )
        runs_payload = await sync_to_async(
            lambda: IngestBatchRunSerializer(runs, many=True).data
        )()
        return Response(
            {
                "batch_id": str(batch_id),
                "status": _aggregate_queue_status(runs),
                "runs": runs_payload,
            },
            status=status.HTTP_200_OK,
        )


class IngestQueueActionView(APIView):
    """队列动作端点（POST，IsAuthenticated，start/stop/retry，CRAWL-01）。

    ``action`` ∈ {start, stop, retry}，非法值 400；该批不存在 → 404。

    - ``stop``：``DurableTaskService.cancel(durable_job_id)``（best-effort，仅 todo 可取消，
      **不承诺中断 doing**，研究 Pitfall 2）+ 把非终态行（QUEUED/RUNNING）置 ``STOPPED``
      （终态可重投）。
    - ``start`` / ``retry``：把 QUEUED/STOPPED/FAILED 行置回 QUEUED，以同
      ``idempotency_key="crawl_ingest:{batch_id}"`` 重新 ``defer``（queueing_lock 命中即
      幂等吞并，终态则建新 job，研究 Pattern 3），回写 durable_job_id。
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    async def _redefer_batch(batch_id, runs: list[IngestRun]) -> str:
        from delivery.services.json_ingest import DEFAULT_CONCURRENCY
        from durable import QUEUE_CRAWL_INGEST, DurableTaskService

        redefer_ids = [
            r.id
            for r in runs
            if r.status
            in {
                IngestRun.Status.QUEUED,
                IngestRun.Status.STOPPED,
                IngestRun.Status.FAILED,
            }
        ]
        await sync_to_async(
            lambda: IngestRun.objects.filter(id__in=redefer_ids).update(
                status=IngestRun.Status.QUEUED
            )
        )()

        key = f"crawl_ingest:{batch_id}"
        job_id = await DurableTaskService.defer(
            "durable_crawl_ingest",
            {"batch_id": str(batch_id), "concurrency": DEFAULT_CONCURRENCY},
            queue=QUEUE_CRAWL_INGEST,
            idempotency_key=key,
        )
        all_ids = [r.id for r in runs]
        await sync_to_async(
            lambda: IngestRun.objects.filter(id__in=all_ids).update(
                durable_job_id=job_id, idempotency_key=key
            )
        )()
        return job_id

    async def post(self, request, batch_id, action):
        from durable import DurableTaskService

        if action not in {"start", "stop", "retry"}:
            return Response(
                {"detail": "非法 action（仅 start/stop/retry）"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        runs = [run async for run in IngestRun.objects.filter(batch_id=batch_id)]
        if not runs:
            return Response(
                {"detail": "队列批次不存在"}, status=status.HTTP_404_NOT_FOUND
            )

        if action == "stop":
            job_id = next((r.durable_job_id for r in runs if r.durable_job_id), "")
            if job_id:
                await DurableTaskService.cancel(job_id)
            nonterminal_ids = [
                r.id
                for r in runs
                if r.status in {IngestRun.Status.QUEUED, IngestRun.Status.RUNNING}
            ]
            await sync_to_async(
                lambda: IngestRun.objects.filter(id__in=nonterminal_ids).update(
                    status=IngestRun.Status.STOPPED
                )
            )()
            return Response(
                {"batch_id": str(batch_id), "action": "stop", "stopped": len(nonterminal_ids)},
                status=status.HTTP_200_OK,
            )

        # start / retry：同 key 重新 defer（queueing_lock 幂等）。
        job_id = await self._redefer_batch(batch_id, runs)
        return Response(
            {
                "batch_id": str(batch_id),
                "action": action,
                "durable_job_id": job_id,
                "dispatched": True,
            },
            status=status.HTTP_200_OK,
        )


class WorkItemArtifactsView(APIView):
    """工作项关联文档端点（GET，IsAuthenticated，只读，按三元组）。

    返回工作项摘要 + 关联文档（PRD / 技术方案等）列表，供 JSON 批量摄取卡片在工作项
    摄取后实时展开「关联内容」。只读：不旁路 fetch、不写库；正文走 ``WorkItemPrdDocumentView``。
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    @sync_to_async
    def _build_payload(work_item) -> dict:
        documents: list[dict] = []
        for doc in (
            Document.objects.filter(work_item=work_item)
            .select_related("current_version")
            .order_by("-updated_at")
        ):
            current = doc.current_version
            documents.append(
                {
                    "document_type": doc.document_type,
                    "canonical_url": doc.canonical_url,
                    "external_ref": doc.external_ref,
                    "version": current.version if current is not None else None,
                    "has_content": bool(current is not None and current.content),
                    "last_synced_at": (
                        doc.last_synced_at.isoformat() if doc.last_synced_at else None
                    ),
                }
            )
        return {
            "work_item": {
                "id": str(work_item.id),
                "title": work_item.title,
                "status_display_name": work_item.status_display_name,
                "prd_url": work_item.prd_url,
                "tech_doc_url": work_item.tech_doc_url,
            },
            "documents": documents,
        }

    async def get(self, request):
        serializer = WorkItemArtifactsQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        work_item = await WorkItem.objects.filter(
            feishu_project_key=data["feishu_project_key"],
            work_item_type=data["work_item_type"],
            work_item_id=data["work_item_id"],
        ).afirst()
        if work_item is None:
            return Response(
                {"detail": "WorkItem 不存在"}, status=status.HTTP_404_NOT_FOUND
            )

        payload = await self._build_payload(work_item)
        return Response(payload, status=status.HTTP_200_OK)


class ScreenshotRecallView(APIView):
    """截图识别需求端点（POST multipart，IsAuthenticated，VIS-01 + 35-UI-SPEC）。

    流程：multipart 上传截图（字段 ``screenshot``，兼容回退 ``image`` / ``file``）→ 后端
    权威双校验（``validate_image_bytes`` 非持久化校验，仅 png/jpeg/webp ≤10MB，非图片/超大
    即 400，不进 LLM，T-35-01）→ 调 ``recall_from_screenshot``（vision 提语义 → 文本 query →
    既有交付知识检索召回 work_item，访问域经 ``request.user`` fail-closed，T-35-03）→ 200 透传
    服务 result（``degraded`` 亦以 200 透传，由前端区分，非错误态）。

    不持久化原图（瞬态 bytes → base64 inline，T-35-02）：校验/服务均不写盘、不建图片向量库。
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        summary="截图识别需求",
        description=(
            "上传界面/原型截图，经多模态 LLM 提取语义并召回相关 work_item 需求。"
            "后端权威校验图片类型（PNG/JPEG/WebP）与大小（≤10MB）；无 vision 模型时返回 "
            "degraded=true（200，非错误）。"
        ),
        responses={
            200: ScreenshotRecallResultSerializer,
            400: {"description": "缺文件 / 非图片 / 超大（code + error）"},
        },
        tags=["Delivery"],
    )
    async def post(self, request):
        from chat.multimodal import (
            SCREENSHOT_RECALL_MIME_TYPES,
            ImageValidationError,
            validate_image_bytes,
        )
        from services import screenshot_recall

        uploaded = (
            request.FILES.get("screenshot")
            or request.FILES.get("image")
            or request.FILES.get("file")
        )
        if uploaded is None:
            return Response(
                {"code": "missing_image", "error": "请上传截图文件"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = await sync_to_async(uploaded.read)()
        try:
            mime_type, _size = validate_image_bytes(
                data,
                declared_mime_type=getattr(uploaded, "content_type", "") or "",
                allowed_mime_types=SCREENSHOT_RECALL_MIME_TYPES,
            )
        except ImageValidationError as exc:
            return Response(
                {"code": exc.code, "error": exc.message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = await screenshot_recall.recall_from_screenshot(
            data, mime_type, user=request.user
        )
        return Response(result, status=status.HTTP_200_OK)
