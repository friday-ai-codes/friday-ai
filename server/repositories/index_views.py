"""Index management views for repositories."""
import asyncio
import concurrent.futures
import threading
from typing import Any
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from repositories.models import IndexStatus, Repository
from services.embedding import EmbeddingService
from services.indexer import clone_and_index_repository
from services.qdrant_service import QdrantService
def run_async(coro):
 """Run async coroutine in a new event loop within a thread pool."""
 with concurrent.futures.ThreadPoolExecutor as pool:
 future = pool.submit(asyncio.run, coro)
 return future.result
def run_async_background(coro):
 """Run async coroutine in a background thread (non-blocking)."""
 def run_in_thread:
 asyncio.run(coro)
 thread = threading.Thread(target=run_in_thread, daemon=True)
 thread.start
class IndexStatusSerializer(serializers.Serializer):
 """Serializer for index status response."""
 index_status = serializers.CharField
 last_indexed_at = serializers.DateTimeField(allow_null=True)
 index_error = serializers.CharField(allow_null=True)
 index_total_chunks = serializers.IntegerField
 index_processed_chunks = serializers.IntegerField
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
 def post(self, request, repository_id):
 """Trigger indexing for the repository."""
 try:
 repository = Repository.objects.get(id=repository_id)
 except Repository.DoesNotExist:
 return Response(
 {"detail": "仓库不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # Check if already indexing
 if repository.index_status == IndexStatus.INDEXING:
 return Response(
 {"detail": "索引正在进行中"},
 status=status.HTTP_409_CONFLICT,
 )
 # Run indexing in background
 run_async_background(clone_and_index_repository(str(repository.id)))
 return Response(
 {
 "message": "索引任务已启动",
 "repository_id": str(repository.id),
 "status": IndexStatus.INDEXING,
 },
 status=status.HTTP_202_ACCEPTED,
 )
class IndexStatusView(APIView):
 """Get index status for a repository."""
 def get(self, request, repository_id):
 """Get current index status."""
 try:
 repository = Repository.objects.get(id=repository_id)
 except Repository.DoesNotExist:
 return Response(
 {"detail": "仓库不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
 serializer = IndexStatusSerializer(
 {
 "index_status": repository.index_status,
 "last_indexed_at": repository.last_indexed_at,
 "index_error": repository.index_error,
 "index_total_chunks": repository.index_total_chunks,
 "index_processed_chunks": repository.index_processed_chunks,
 }
 )
 return Response(serializer.data)
class IndexDeleteView(APIView):
 """Delete index for a repository."""
 def delete(self, request, repository_id):
 """Delete the index for the repository."""
 try:
 repository = Repository.objects.get(id=repository_id)
 except Repository.DoesNotExist:
 return Response(
 {"detail": "仓库不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # Delete collection from Qdrant
 QdrantService.delete_collection(str(repository.id))
 # Reset repository status
 repository.index_status = IndexStatus.NOT_INDEXED
 repository.last_indexed_at = None
 repository.index_error = None
 repository.save(update_fields=["index_status", "last_indexed_at", "index_error"])
 return Response(status=status.HTTP_204_NO_CONTENT)
class CodeSearchView(APIView):
 """Search code in repository index."""
 def post(self, request, repository_id):
 """Search for code in the repository."""
 try:
 repository = Repository.objects.get(id=repository_id)
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
 results = run_async(self._search(repository_id, query, top_k, filters))
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
 """Execute vector search."""
 # Generate query embedding
 query_embedding = await EmbeddingService.generate_embedding(query)
 if not query_embedding:
 return
 # Search in Qdrant
 search_results = QdrantService.search(
 repository_id,
 query_embedding,
 top_k=top_k,
 filters=filters,
 )
 if not search_results:
 return
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
 def get(self, request):
 """Get Qdrant health status."""
 health = QdrantService.health_check
 return Response(health)
class EmbeddingHealthView(APIView):
 """Check Embedding API health."""
 def get(self, request):
 """Get Embedding API health status using saved config."""
 health = run_async(EmbeddingService.test_connection)
 return Response(health)
 def post(self, request):
 """Test Embedding API with provided config (before saving)."""
 api_url = request.data.get("api_url")
 model = request.data.get("model", "BAAI/bge-m3")
 if not api_url:
 return Response(
 {
 "status": "error",
 "message": "Embedding API URL is required",
 }
 )
 health = run_async(EmbeddingService.test_connection_with_config(api_url, model))
 return Response(health)
