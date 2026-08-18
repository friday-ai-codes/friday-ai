"""仓库章程 REST API（111-03，CHARTER-01 / DESIGN §5.7；append-only 修订）。

三端点（``IsAuthenticated``）：

- ``GET  /api/repositories/<uuid:repository_id>/charter/``：读取章程（含
  appendices / change_proposals / fingerprint）；无章程 → 404。
- ``POST .../charter/draft/``：AI 起草；无行建基线；已有行仅侧信道
  （自动化永不写 ``draft_content``）。
- ``POST .../charter/confirm/``：人工确认（``edits`` /
  ``approve_proposal_ids`` / ``reject_proposal_ids``）；正式字段唯一变更口。

写入纪律（INV-6）：视图零 RepoCharter 写操作，全部委托 ``charter_service``。
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

    委托 :func:`charter_service.adraft_charter`：无行 → 建基线；已有行 →
    appendices/proposals 侧信道（正式字段与 ``draft_content`` 不变）。
    LLM 不可用 → 503；``CharterPersistError`` → 500。
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
        except charter_service.CharterPersistError:
            return Response(
                {"detail": "章程草案保存失败，请稍后重试或联系管理员"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if charter is None:
            return Response(
                {"detail": "AI 起草暂不可用：模型调用失败或未配置可用供应商"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        data = await sync_to_async(lambda: RepoCharterSerializer(charter).data)()
        return Response(data)


class RepoCharterConfirmView(APIView):
    """POST /api/repositories/<uuid:repository_id>/charter/confirm/ —— 人工确认生效。

    body 可带 ``edits`` / ``approve_proposal_ids`` / ``reject_proposal_ids``。
    批准提案会写入正式字段；拒绝仅改提案状态。无章程 + 非空 edits → 创建；
    空确认仍 404。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, repository_id: Any) -> Response:
        from repositories.serializers import RepoCharterSerializer
        from repositories.services import charter_service

        body = request.data if isinstance(request.data, dict) else {}
        raw_edits = body.get("edits")
        edits = raw_edits if isinstance(raw_edits, dict) else None

        def _id_list(key: str) -> list[str] | None:
            raw = body.get(key)
            if not isinstance(raw, list):
                return None
            return [str(x) for x in raw if str(x).strip()]

        try:
            charter = await charter_service.aconfirm_charter(
                str(repository_id),
                request.user,
                edits=edits,
                approve_proposal_ids=_id_list("approve_proposal_ids"),
                reject_proposal_ids=_id_list("reject_proposal_ids"),
            )
        except ValueError:
            return Response({"detail": "章程不存在"}, status=status.HTTP_404_NOT_FOUND)

        data = await sync_to_async(lambda: RepoCharterSerializer(charter).data)()
        return Response(data)
