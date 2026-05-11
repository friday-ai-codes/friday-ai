"""同步状态查询 API。
GET /api/repositories/{id}/sync-status/
返回仓库的上次同步信息、下次计划同步时间及最近 5 条历史记录。
"""
from __future__ import annotations
import uuid
import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from repositories.models import IndexHistory, IndexHistoryStatus, Repository
logger = structlog.get_logger(__name__)
class SyncStatusView(APIView):
 """GET /api/repositories/{id}/sync-status/ — 同步状态查询。"""
 permission_classes = [IsAuthenticated]
 async def get(self, request: Request, repository_id: uuid.UUID) -> Response:
 try:
 repo = await Repository.objects.aget(id=repository_id, is_deleted=False)
 except Repository.DoesNotExist:
 return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)
 # 最近一次同步记录（用于 last_sync_result）
 latest_history = await IndexHistory.objects.filter(
 repository=repo,
 ).order_by("-created_at").afirst
 # 最近 5 条历史（ recent_history[5]）
 recent_history = [
 {
 "id": str(h.id),
 "trigger_type": h.trigger_type,
 "status": h.status,
 "from_sha": h.from_sha,
 "to_sha": h.to_sha,
 "files_added": h.files_added,
 "files_modified": h.files_modified,
 "files_deleted": h.files_deleted,
 "started_at": h.started_at,
 "finished_at": h.finished_at,
 "created_at": h.created_at,
 }
 async for h in IndexHistory.objects.filter(
 repository=repo,
 ).order_by("-created_at")[:5]
 ]
 # 倒计时数据源：DjangoJob.next_run_time
 next_sync_at = None
 try:
 from django_apscheduler.models import DjangoJob
 job = await sync_to_async(DjangoJob.objects.get)(id="poll_repository_updates")
 next_sync_at = job.next_run_time
 except Exception:
 logger.debug("sync_status_no_job", repository_id=str(repository_id))
 logger.info(
 "sync_status_queried",
 repository_id=str(repository_id),
 last_sync_result=_last_sync_result(latest_history),
 )
 return Response(
 {
 "repository_id": str(repo.id),
 "last_synced_sha": repo.last_indexed_commit_sha or "",
 "last_synced_at": repo.last_indexed_at,
 "last_sync_result": _last_sync_result(latest_history),
 "next_sync_at": next_sync_at,
 "interval_seconds": settings.SYNC_INTERVAL_SECONDS,
 "recent_history": recent_history,
 }
 )
_STATUS_MAP: dict[str, str] = {
 IndexHistoryStatus.COMPLETED: "success",
 IndexHistoryStatus.FAILED: "failed",
 IndexHistoryStatus.RUNNING: "running",
 IndexHistoryStatus.PENDING: "pending",
}
def _last_sync_result(history: IndexHistory | None) -> str:
 """将 IndexHistoryStatus 映射为前端友好字符串。"""
 if history is None:
 return "never"
 return _STATUS_MAP.get(history.status, "unknown")
