"""仓库章程 REST API（111-03，CHARTER-01 / DESIGN §5.7）。

三端点（``IsAuthenticated``，T-111-06——repositories 既有 view 同级低门槛）：

- ``GET  /api/repositories/<uuid:repository_id>/charter/``：读取章程（含
  ``draft_content``，供前端预览 pending 修订草案）；无章程 → 404 中性消息。
- ``POST /api/repositories/<uuid:repository_id>/charter/draft/``：触发 AI 三源
  蒸馏起草（``call_source=blueprint_charter_draft``）；LLM 不可用 → 503。
- ``POST /api/repositories/<uuid:repository_id>/charter/confirm/``：人工确认
  生效（可带 ``{"edits": {...}}``），署名 ``request.user``。

写入纪律（INV-6）：视图零 RepoCharter 写操作，起草/确认全部委托
``services/charter_service``（charter_service 测试的源码扫描守护会扫本文件）；
读路径允许视图直接查询。serializer ``.data`` 一律 ``sync_to_async`` 包裹。
"""

from typing import Any

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

logger = structlog.get_logger(__name__)


class RepoCharterDetailView(APIView):
    """GET /api/repositories/<uuid:repository_id>/charter/ —— 章程读取。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, repository_id: Any) -> Response:
        from repositories.models import RepoCharter
        from repositories.serializers import RepoCharterSerializer

        try:
            charter = await RepoCharter.objects.select_related("repository").aget(
                repository_id=repository_id
            )
        except RepoCharter.DoesNotExist:
            return Response({"detail": "章程不存在"}, status=status.HTTP_404_NOT_FOUND)

        data = await sync_to_async(lambda: RepoCharterSerializer(charter).data)()
        return Response(data)


class RepoCharterDraftView(APIView):
    """POST /api/repositories/<uuid:repository_id>/charter/draft/ —— 触发 AI 起草。

    委托 :func:`charter_service.adraft_charter`（best-effort）：仓库不存在 → 404；
    返回 ``None``（无 provider/default_model、LLM 失败、解析失败）→ 503；
    成功 → 200 序列化（human_confirmed 章程的新草案只落 ``draft_content``）。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, repository_id: Any) -> Response:
        from repositories.models import Repository
        from repositories.serializers import RepoCharterSerializer
        from repositories.services import charter_service

        try:
            charter = await charter_service.adraft_charter(
                str(repository_id), initiated_by_user_id=str(request.user.id)
            )
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        if charter is None:
            return Response(
                {"detail": "AI 起草暂不可用，请检查模型供应商配置"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        data = await sync_to_async(lambda: RepoCharterSerializer(charter).data)()
        return Response(data)


class RepoCharterConfirmView(APIView):
    """POST /api/repositories/<uuid:repository_id>/charter/confirm/ —— 人工确认生效。

    body 可带 ``{"edits": {...}}``（无 body 允许；非 dict 的 edits 按无 edits
    处理——白名单归一在 service 层，T-111-07）。章程不存在 → 404。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, repository_id: Any) -> Response:
        from repositories.serializers import RepoCharterSerializer
        from repositories.services import charter_service

        body = request.data if isinstance(request.data, dict) else {}
        raw_edits = body.get("edits")
        edits = raw_edits if isinstance(raw_edits, dict) else None

        try:
            charter = await charter_service.aconfirm_charter(
                str(repository_id), request.user, edits=edits
            )
        except ValueError:
            return Response({"detail": "章程不存在"}, status=status.HTTP_404_NOT_FOUND)

        data = await sync_to_async(lambda: RepoCharterSerializer(charter).data)()
        return Response(data)
