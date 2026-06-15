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
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from delivery.api.serializers import (
    CommentTreeNodeSerializer,
    DocumentSnapshotSerializer,
    WorkItemSerializer,
    WorkItemUpsertRequestSerializer,
)
from delivery.models import Document, DocumentType, WorkItem
from delivery.services import WorkItemIdentity, WorkItemService, aproject_comment_tree

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
