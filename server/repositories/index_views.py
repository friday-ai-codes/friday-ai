"""Index management views for repositories."""
import asyncio
from typing import Any
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from repositories.models import (
 IndexHistory,
 IndexHistoryStatus,
 IndexStatus,
 Repository,
 TriggerType,
)
from services.embedding import EmbeddingService
from services.indexer import clone_and_index_repository
from services.qdrant_service import QdrantService
# 模块级强引用集合：防止 asyncio.create_task 任务被 GC 静默回收
# 参考：https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
# 注意：Django dev server 热重载时集合会重置，生产环境不受影响
_index_tasks: set[asyncio.Task[dict[str, Any]]] = set
def _acquire_index_lock(repository_id: str) -> Repository | None:
 """尝试获取仓库索引 DB 锁。返回 None 表示已被其他进程持有（skip_locked）。"""
 with transaction.atomic:
 try:
 return (
 Repository.objects
 .select_for_update(skip_locked=True)
 .get(id=repository_id, is_deleted=False)
 )
 except Repository.DoesNotExist:
 return None
_acquire_index_lock_async = sync_to_async(_acquire_index_lock)
def _schedule_index(repository_id: str, history_id: str) -> asyncio.Task[dict[str, Any]]:
 """创建索引任务并用强引用保护，防止 GC 回收。"""
 task: asyncio.Task[dict[str, Any]] = asyncio.create_task(
 clone_and_index_repository(repository_id, history_id=history_id),
 name=f"index-{repository_id}",
 )
 _index_tasks.add(task)
 task.add_done_callback(_index_tasks.discard)
 return task
class IndexStatusSerializer(serializers.Serializer):
 """Serializer for index status response."""
 index_status = serializers.CharField
 last_indexed_at = serializers.DateTimeField(allow_null=True)
 index_error = serializers.CharField(allow_null=True)
 index_total_chunks = serializers.IntegerField
 index_processed_chunks = serializers.IntegerField
 index_write_total = serializers.IntegerField
 index_write_processed = serializers.IntegerField
 #: 统一进度字段
 overall_progress = serializers.IntegerField
 overall_stage = serializers.CharField
class SearchRequestSerializer(serializers.Serializer):
 """Serializer for search request."""
 query = serializers.CharField(max_length=1000)
 top_k = serializers.IntegerField(default=10, min_value=1, max_value=50)
 filters = serializers.DictField(required=False, default=dict)
class SearchResultSerializer(serializers.Serializer):
 """Serializer for search result item."""
 file_path = serializers.CharField
 score = serializers.FloatField
 content = serializers.CharField
 language = serializers.CharField
 start_line = serializers.IntegerField
 end_line = serializers.IntegerField
 context_header = serializers.CharField
class IndexTriggerView(APIView):
 """Trigger indexing for a repository."""
 permission_classes = [IsAuthenticated]
 async def post(self, request: Any, repository_id: str) -> Response:
 """触发仓库索引（手动）。"""
 # 快速状态检查（无锁开销，快速路径）
 try:
 repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
 except Repository.DoesNotExist:
 return Response(
 {"detail": "仓库不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
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
 # 创建 IndexHistory 记录（获锁之后，任务启动之前）
 history = await IndexHistory.objects.acreate(
 repository_id=repository_id,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.RUNNING,
 started_at=timezone.now,
 )
 # 启动后台索引任务（强引用保护）
 _schedule_index(str(repository_id), str(history.id))
 return Response(
 {
 "message": "索引任务已启动",
 "repository_id": str(repository_id),
 "history_id": str(history.id),
 "status": IndexStatus.INDEXING,
 },
 status=status.HTTP_202_ACCEPTED,
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
 #: 计算统一进度
 total_chunks = repository.index_total_chunks
 processed_chunks = repository.index_processed_chunks
 write_total = repository.index_write_total
 write_processed = repository.index_write_processed
 embedding_pct = (processed_chunks / total_chunks * 100) if total_chunks > 0 else 0
 write_pct = (write_processed / write_total * 100) if write_total > 0 else 0
 # 加权合并：Embedding 权重 70%，Qdrant 写入权重 30%
 overall_progress = min(int(embedding_pct * 0.7 + write_pct * 0.3), 100)
 if total_chunks == 0:
 overall_stage = "解析文件中..."
 elif write_total == 0:
 overall_stage = "生成向量中..."
 elif write_processed < write_total:
 overall_stage = "写入向量库..."
 else:
 overall_stage = "完成"
 serializer = IndexStatusSerializer(
 {
 "index_status": repository.index_status,
 "last_indexed_at": repository.last_indexed_at,
 "index_error": repository.index_error,
 "index_total_chunks": total_chunks,
 "index_processed_chunks": processed_chunks,
 "index_write_total": write_total,
 "index_write_processed": write_processed,
 "overall_progress": overall_progress,
 "overall_stage": overall_stage,
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
 # KEEP: Qdrant SDK 同步限制
 await sync_to_async(QdrantService.delete_collection)(str(repository.id))
 # Reset repository status
 repository.index_status = IndexStatus.NOT_INDEXED
 repository.last_indexed_at = None
 repository.index_error = None
 await repository.asave(update_fields=["index_status", "last_indexed_at", "index_error"])
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
 # Run search
 results = await self._search(repository_id, query, top_k, filters)
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
 ) -> list[dict[str, Any]]:
 """Execute vector search with optional hybrid search and reranker."""
 from services.reranker import RerankerService
 from system.models import SettingKeys, SystemSetting
 # 检查 reranker 是否启用，决定初筛数量
 reranker_enabled = await RerankerService.is_enabled
 fetch_k = min(top_k * 3, 50) if reranker_enabled else top_k
 # Generate query embedding (async)
 query_embedding = await EmbeddingService.generate_embedding(query)
 if not query_embedding:
 return
 # 检查是否启用 hybrid search
 hybrid_setting = await SystemSetting.objects.filter(
 key=SettingKeys.HYBRID_SEARCH_ENABLED
 ).afirst
 hybrid_enabled = bool(hybrid_setting and hybrid_setting.value == "true")
 if hybrid_enabled:
 # 生成 sparse query vector
 from services.sparse_encoder import SparseEncoderService
 sparse_vector = await sync_to_async(SparseEncoderService.encode)(query)
 # KEEP: Qdrant SDK 同步限制
 search_results = await sync_to_async(QdrantService.hybrid_search)(
 repository_id,
 query_embedding,
 sparse_vector,
 top_k=fetch_k,
 filters=filters,
 )
 else:
 # KEEP: Qdrant SDK 同步限制
 search_results = await sync_to_async(QdrantService.search)(
 repository_id,
 query_embedding,
 top_k=fetch_k,
 filters=filters,
 )
 if not search_results:
 return
 # Reranker 精排
 if reranker_enabled and len(search_results) > top_k:
 documents = [r["payload"].get("content", "") for r in search_results]
 reranked = await RerankerService.rerank(query, documents, top_n=top_k)
 reranked_results =
 for item in reranked:
 idx = item["index"]
 if idx < len(search_results):
 entry = search_results[idx]
 entry["score"] = item["relevance_score"]
 reranked_results.append(entry)
 search_results = reranked_results
 # Build results
 results =
 for r in search_results:
 payload = r["payload"]
 results.append(
 {
 "file_path": payload.get("file_path"),
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
 health = await sync_to_async(QdrantService.health_check) # KEEP: Qdrant SDK 同步限制
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
 ).afirst
 if api_key_setting and api_key_setting.value:
 if api_key_setting.is_encrypted:
 api_key = decrypt_value(api_key_setting.value)
 else:
 api_key = api_key_setting.value
 health = await sync_to_async(QdrantService.health_check_with_config)(url, api_key) # KEEP: Qdrant SDK 同步限制
 return Response(health)
class EmbeddingHealthView(APIView):
 """Check Embedding API health."""
 permission_classes = [IsAuthenticated]
 async def get(self, request):
 """Get Embedding API health status using saved config."""
 health = await EmbeddingService.test_connection
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
 ).afirst
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
 health = await RerankerService.test_connection
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
 ).afirst
 if api_key_setting and api_key_setting.value:
 if api_key_setting.is_encrypted:
 api_key = decrypt_value(api_key_setting.value)
 else:
 api_key = api_key_setting.value
 health = await RerankerService.test_connection_with_config(api_url, model, api_key)
 return Response(health)
# ---------------------------------------------------------------------------
# Phase: 索引可观测性 API
# ---------------------------------------------------------------------------
class IndexHistorySerializer(serializers.Serializer):
 """IndexHistory 记录序列化器。"""
 id = serializers.UUIDField
 trigger_type = serializers.CharField
 status = serializers.CharField
 from_sha = serializers.CharField(allow_null=True)
 to_sha = serializers.CharField(allow_null=True)
 files_added = serializers.IntegerField
 files_modified = serializers.IntegerField
 files_deleted = serializers.IntegerField
 summary_text = serializers.CharField(allow_null=True)
 error_message = serializers.CharField(allow_null=True)
 started_at = serializers.DateTimeField(allow_null=True)
 finished_at = serializers.DateTimeField(allow_null=True)
 created_at = serializers.DateTimeField
class IndexHistoryListView(APIView):
 """: IndexHistory 操作记录查询 API（分页）。"""
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
 total = await qs.acount
 items = [item async for item in qs[offset: offset + limit]]
 serializer = IndexHistorySerializer(items, many=True)
 data = await sync_to_async(lambda: serializer.data)
 return Response({"items": data, "total": total})
class IndexStatsView(APIView):
 """: 统计 API（chunk 数、语言分布、覆盖率）。"""
 permission_classes = [IsAuthenticated]
 async def get(self, request: Any, repository_id: str) -> Response:
 try:
 repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
 except Repository.DoesNotExist:
 return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)
 stats = await sync_to_async(QdrantService.get_collection_stats)(str(repository_id))
 # 覆盖率：已索引文件数 / 总可索引文件数
 indexed_files = stats.get("indexed_files_count", 0)
 total_chunks = repository.index_total_chunks
 coverage = 0.0
 if total_chunks > 0:
 coverage = round(stats.get("points_count", 0) / total_chunks * 100, 1)
 return Response({
 "chunks_total": stats.get("points_count", 0),
 "language_distribution": stats.get("language_distribution", {}),
 "indexed_files_count": indexed_files,
 "coverage_percent": coverage,
 })
class RepositoryCollectionHealthView(APIView):
 """: 仓库 Qdrant 集合健康校验 API。"""
 permission_classes = [IsAuthenticated]
 async def get(self, request: Any, repository_id: str) -> Response:
 try:
 repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
 except Repository.DoesNotExist:
 return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)
 health = await sync_to_async(QdrantService.check_collection_health)(str(repository_id))
 # 对比 Repository 记录的预期 chunk 数
 expected = repository.index_total_chunks
 actual = health.get("points_count", 0)
 health["expected_points"] = expected
 health["points_match"] = actual == expected if expected > 0 else None
 return Response(health)
class IndexFreshnessView(APIView):
 """: 索引新鲜度指示 API。"""
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
 return Response({
 "local_sha": local_sha,
 "remote_sha": remote_sha,
 "is_fresh": is_fresh,
 "last_indexed_at": repository.last_indexed_at,
 "error": error,
 })
 @staticmethod
 async def _get_remote_head(git_url: str) -> str:
 """通过 git ls-remote 获取远端 HEAD SHA（无需 clone）。"""
 proc = await asyncio.create_subprocess_exec(
 "git", "ls-remote", git_url, "HEAD",
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 stdout, _ = await asyncio.wait_for(proc.communicate, timeout=15.0)
 if proc.returncode != 0:
 msg = "git ls-remote 失败"
 raise RuntimeError(msg)
 output = stdout.decode.strip
 if output:
 return output.split[0]
 return ""
# ---------------------------------------------------------------------------
# Phase: 自动索引触发
# ---------------------------------------------------------------------------
class RepositoryWebhookView(APIView):
 """: Webhook 端点接收 push 事件并触发增量索引。
 支持 GitHub、GitLab、Gitea 三种平台的签名验证。
 此端点无需 JWT 认证（使用 webhook secret 验证）。
 """
 from rest_framework.permissions import AllowAny
 permission_classes = [AllowAny]
 authentication_classes: list = # type: ignore[assignment]
 async def post(self, request: Any, repository_id: str) -> Response:
 from tasks.index_trigger_tasks import (
 parse_push_event,
 trigger_auto_index,
 verify_gitlab_token,
 verify_webhook_signature,
 )
 try:
 repository = await Repository.objects.aget(id=repository_id, is_deleted=False)
 except Repository.DoesNotExist:
 return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)
 #: 检查开关
 if not repository.auto_index_enabled:
 return Response(
 {"detail": "自动索引未启用"},
 status=status.HTTP_403_FORBIDDEN,
 )
 #: 签名验证
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
 # 触发索引
 result = await trigger_auto_index(repository, "webhook", commit_sha)
 status_code = (
 status.HTTP_202_ACCEPTED
 if result["status"] == "triggered"
 else status.HTTP_200_OK
 )
 return Response(result, status=status_code)
