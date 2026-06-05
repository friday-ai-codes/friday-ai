"""Hash 新鲜度立即刷新端点（initial implementation contract）。

POST /api/repositories/{id}/refresh-remote-head/ — 立即触发 git ls-remote 并更新 DB。
"""

from __future__ import annotations

import structlog
from adrf.views import APIView
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from repositories.models import Repository
from tasks.index_trigger_tasks import _get_remote_head_sha

from .freshness_service import compute_freshness_status

logger = structlog.get_logger(__name__)


class RefreshRemoteHeadView(APIView):
    """POST /api/repositories/{id}/refresh-remote-head/ — 立即检查远端 HEAD（contract）。"""

    permission_classes = [IsAuthenticated]

    async def post(self, request, repository_id: str) -> Response:
        try:
            repo = await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        if not repo.git_url:
            return Response(
                {"detail": "仓库无 git_url"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        remote_sha = await _get_remote_head_sha(repo.git_url)
        if remote_sha:
            checked_at = timezone.now()
            await Repository.objects.filter(id=repository_id).aupdate(
                remote_head_sha=remote_sha,
                remote_head_checked_at=checked_at,
            )
            repo.remote_head_sha = remote_sha
            repo.remote_head_checked_at = checked_at

        freshness = compute_freshness_status(repo)
        logger.info(
            "refresh_remote_head_done",
            repo_id=str(repository_id),
            freshness=freshness,
        )
        return Response(
            {
                "remote_head_sha": remote_sha or "",
                "freshness": freshness,
            }
        )
