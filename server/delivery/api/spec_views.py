"""spec 治理 REST views（Phase 50-03，SPECST-01/02/03，D-50-3/D-50-4）。

独立 ``/api/specs/`` 端点（adrf，镜像 chunk_at_views / admin_views 范式）：

- ``SpecListView.get``（IsAuthenticated）：list + ``?status=`` / ``?repository_id=`` 过滤；
  非法 status / 非 UUID repository_id 前置 400（不触 service，T-50-11）。
- ``SpecDetailView.get``（IsAuthenticated）：spec + 正文 + 评审历史 + 关联摘要；不存在 404
  中性消息（T-50-08）。
- ``SpecTransitionView.post``：body ``{action, comment?}`` 经 ``SddSpecService`` 流转。
  权限按 action 动态分流（D-50-3 fail-closed）——approve/reject/archive/mark_implemented
  须 superuser（非 superuser 403，T-50-07）；submit_for_review 仅需认证。reviewer 强制取
  ``request.user``（不接受 body，T-50-10）。非法流转 → 400；spec 不存在 → 404。

async 序列化纪律：``.data`` 一律 ``sync_to_async`` 包裹，避免 async 上下文
SynchronousOnlyOperation；关联经 select_related/prefetch 预取。
"""

from __future__ import annotations

import uuid

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.db.models import Prefetch
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from delivery.api.serializers import SddSpecDetailSerializer, SddSpecListSerializer
from delivery.models import SddSpec, SddSpecReview, SddSpecStatus
from delivery.services import SddSpecService, SddSpecTransitionError

logger = structlog.get_logger(__name__)

# transition action → 是否要求 superuser（D-50-3）。submit_for_review 仅需认证。
_RESTRICTED_ACTIONS = frozenset(
    {"approve", "reject", "archive", "mark_implemented"}
)
_ALL_ACTIONS = frozenset({"submit_for_review", *_RESTRICTED_ACTIONS})

# detail 关联预取（select_related document__current_version + repository/work_item/plan_version；
# prefetch reviews 含 reviewer，避免 N+1 与 async 隐式同步访问）。
_DETAIL_PREFETCH = Prefetch(
    "reviews", queryset=SddSpecReview.objects.select_related("reviewer")
)


def _detail_queryset():
    return SddSpec.objects.select_related(
        "document__current_version",
        "repository",
        "work_item",
        "artifact_version",
    ).prefetch_related(_DETAIL_PREFETCH)


class SpecListView(APIView):
    """spec 列表（IsAuthenticated）：GET /api/specs/?status=&repository_id=。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request):
        status_filter = request.query_params.get("status") or None
        if status_filter is not None and status_filter not in SddSpecStatus.values:
            return Response(
                {"error": "status 取值无效"}, status=status.HTTP_400_BAD_REQUEST
            )

        repository_id = request.query_params.get("repository_id") or None
        if repository_id is not None:
            # repository_id 为 UUIDField：非 UUID 在 ORM 求值会抛 ValueError→500，
            # query param 无 <uuid:...> 转换器兜底，故显式前置 400（T-50-11）。
            try:
                repository_id = str(uuid.UUID(repository_id))
            except (ValueError, TypeError, AttributeError):
                return Response(
                    {"error": "repository_id 格式无效（需为 UUID）"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        queryset = SddSpec.objects.select_related("repository", "work_item").order_by(
            "-updated_at"
        )
        if status_filter is not None:
            queryset = queryset.filter(status=status_filter)
        if repository_id is not None:
            queryset = queryset.filter(repository_id=repository_id)

        specs = [spec async for spec in queryset]
        data = await sync_to_async(
            lambda: SddSpecListSerializer(specs, many=True).data
        )()
        return Response(data)


class SpecDetailView(APIView):
    """spec 详情（IsAuthenticated）：GET /api/specs/<uuid>/。

    **只定义 get**——状态仅经 transition action 改，禁 PATCH（DRF 自动 405）。
    不存在 → 404 中性消息（T-50-08）。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request, spec_id):
        spec = await _detail_queryset().filter(id=spec_id).afirst()
        if spec is None:
            return Response(
                {"error": "spec 不存在"}, status=status.HTTP_404_NOT_FOUND
            )
        data = await sync_to_async(lambda: SddSpecDetailSerializer(spec).data)()
        return Response(data)


class SpecTransitionView(APIView):
    """spec 状态流转（IsAuthenticated + action 级 superuser 分流，D-50-3）。

    POST /api/specs/<uuid>/transition/  body={action, comment?}
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request, spec_id):
        action = request.data.get("action")
        if action not in _ALL_ACTIONS:
            return Response(
                {"error": "action 取值无效"}, status=status.HTTP_400_BAD_REQUEST
            )

        # 权限按 action 动态分流：受限 action 须 superuser（fail-closed，T-50-07）。
        # DRF permission_classes 在读 body 前评估，故在此读 action 后显式判定。
        if action in _RESTRICTED_ACTIONS and not request.user.is_superuser:
            return Response(
                {"error": "仅超级管理员可执行该操作"},
                status=status.HTTP_403_FORBIDDEN,
            )

        comment = request.data.get("comment") or ""
        # WR-01：comment 须为字符串——非字符串（数字/列表等）下 .strip() 会抛 500，显式 400 兜底。
        if not isinstance(comment, str):
            return Response(
                {"error": "comment 必须为字符串"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if action == "reject" and not comment.strip():
            return Response(
                {"error": "驳回必须填写评审意见"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # spec 不存在 → 404（与流转非法 400 区分，不混淆）。
        exists = await SddSpec.objects.filter(id=spec_id).aexists()
        if not exists:
            return Response(
                {"error": "spec 不存在"}, status=status.HTTP_404_NOT_FOUND
            )

        service = SddSpecService()
        try:
            if action == "submit_for_review":
                await service.submit_for_review(spec_id)
            elif action == "approve":
                await service.approve(spec_id, reviewer=request.user, comment=comment)
            elif action == "reject":
                await service.reject(spec_id, reviewer=request.user, comment=comment)
            elif action == "mark_implemented":
                await service.mark_implemented(spec_id)
            elif action == "archive":
                await service.archive(spec_id)
        except SddSpecTransitionError as exc:
            return Response(
                {"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )

        # 成功：返回更新后的 detail（前端可直接刷新）。
        spec = await _detail_queryset().filter(id=spec_id).afirst()
        data = await sync_to_async(lambda: SddSpecDetailSerializer(spec).data)()
        return Response(data)
