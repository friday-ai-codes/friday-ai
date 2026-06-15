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
    DocumentSnapshotSerializer,
    IngestDispatchRequestSerializer,
    IngestRunSerializer,
    ScreenshotRecallResultSerializer,
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
