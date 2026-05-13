"""仓库摘要索引构建服务 —— per //。
从 codegraph 四模型（Symbol/CallEdge/Endpoint/FileIndex）提取仓库级别摘要，
生成 dense + sparse 向量后写入独立 Qdrant collection `repo_summaries`。
"""
from __future__ import annotations
import json
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any
import structlog
from asgiref.sync import sync_to_async
from django.db.models import Count
from codegraph.models import Endpoint, Symbol
from repositories.models import FileIndex, Repository
from services.embedding import EmbeddingService
from services.qdrant_service import QdrantService
from services.sparse_encoder import SparseEncoderService
logger = structlog.get_logger(__name__)
class RepoSummaryBuilder:
 """仓库摘要索引构建服务 —— per //。
 纯 @classmethod async 服务类，无实例状态。
 """
 @classmethod
 async def build(cls, repository_id: str) -> bool:
 """构建或刷新仓库摘要索引，upsert 到 Qdrant repo_summaries collection。
 从 codegraph 模型提取：
 - primary_symbols: Top-30 高频符号（按 outgoing_calls count）
 - api_domains: URL 前缀聚类（Top-10）
 - tech_stack: 文件扩展名百分比分布（Top-10）
 - description: 复用 Repository.ai_summary 或 name + git_url 降级
 生成 dense + sparse 向量后写入 Qdrant repo_summaries collection。
 失败时记录 warning 并返回 False，不回滚已完成的索引。
 Args:
 repository_id: 仓库 UUID 字符串
 Returns:
 True 表示摘要构建成功并写入 Qdrant
 """
 try:
 # 确保 repo_summaries collection 存在（幂等）
 await sync_to_async(
 QdrantService.ensure_repo_summaries_collection,
 thread_sensitive=False,
 )
 # 把仓库元数据汇聚收口到一个 sync 函数里，跑在独立线程池上
 # （thread_sensitive=False）—— 否则 4 次 ORM 查询全部抢占 ASGI 进程的
 # thread_sensitive 单线程，索引收尾阶段所有 HTTP 接口"待处理"。
 def _aggregate_metadata -> dict[str, Any]:
 symbols_list = list(
 Symbol.objects.filter(repository_id=repository_id)
 .annotate(outgoing_count=Count("outgoing_calls"))
 .order_by("-outgoing_count")[:30]
 )
 primary_symbols_local = [s.name for s in symbols_list]
 endpoints_list = list(
 Endpoint.objects.filter(
 repository_id=repository_id,
 ).values_list("url_path", flat=True)
 )
 domains_local: Counter[str] = Counter
 for path in endpoints_list:
 parts = path.strip("/").split("/")
 if parts and parts[0]:
 domains_local[parts[0]] += 1
 api_domains_local = [d for d, _ in domains_local.most_common(10)]
 file_indexes_list = list(
 FileIndex.objects.filter(
 repository_id=repository_id,
 ).values_list("file_path", flat=True)
 )
 ext_counter_local: Counter[str] = Counter
 for fp in file_indexes_list:
 ext_local = fp.rsplit(".", 1)[-1].lower if "." in fp else "unknown"
 ext_counter_local[ext_local] += 1
 total_local = sum(ext_counter_local.values) or 1
 tech_stack_local = {
 ext_name: round(count / total_local * 100, 1)
 for ext_name, count in ext_counter_local.most_common(10)
 }
 repo_obj = Repository.objects.get(id=repository_id)
 return {
 "primary_symbols": primary_symbols_local,
 "api_domains": api_domains_local,
 "tech_stack": tech_stack_local,
 "description": repo_obj.ai_summary
 or f"{repo_obj.name} - {repo_obj.git_url}",
 "repo_name": repo_obj.name,
 }
 metadata = await sync_to_async(
 _aggregate_metadata, thread_sensitive=False,
 )
 primary_symbols = metadata["primary_symbols"]
 api_domains = metadata["api_domains"]
 tech_stack = metadata["tech_stack"]
 description = metadata["description"]
 repo_name = metadata["repo_name"]
 # 5. 构建 summary text —— 拼接为单条文本用于 embedding + sparse 编码
 summary_text = (
 f"Repository: {repo_name}\n"
 f"Description: {description}\n"
 f"Tech Stack: {json.dumps(tech_stack)}\n"
 f"API Domains: {', '.join(api_domains)}\n"
 f"Key Symbols: {', '.join(primary_symbols)}"
 )
 # 6. 生成向量
 dense_vector = await EmbeddingService.generate_embedding(summary_text)
 if dense_vector is None:
 logger.warning(
 "repo_summary_dense_embedding_failed",
 repository_id=repository_id,
 )
 return False
 sparse_vector = await sync_to_async(
 SparseEncoderService.encode, thread_sensitive=False,
 )(summary_text)
 if not sparse_vector or not sparse_vector.get("indices"):
 logger.warning(
 "repo_summary_sparse_encoding_failed",
 repository_id=repository_id,
 )
 return False
 # 7. Upsert 到 Qdrant (per: 独立 collection `repo_summaries`)
 point_id = str(
 uuid.uuid5(uuid.NAMESPACE_DNS, f"repo_summary:{repository_id}")
 )
 point = {
 "id": point_id,
 "vector": {
 "dense": dense_vector,
 "sparse": sparse_vector,
 },
 "payload": {
 "repository_id": repository_id,
 "repo_name": repo_name,
 "description": description,
 "tech_stack": json.dumps(tech_stack),
 "api_domains": json.dumps(api_domains),
 "primary_symbols": json.dumps(primary_symbols),
 "built_at": datetime.now(UTC).isoformat,
 },
 }
 success = await sync_to_async(
 QdrantService.upsert_vectors_by_name, thread_sensitive=False,
 )("repo_summaries", [point])
 if success:
 logger.info(
 "repo_summary_built",
 repository_id=repository_id,
 symbols_count=len(primary_symbols),
 domains_count=len(api_domains),
 extensions_count=len(tech_stack),
 )
 else:
 logger.warning(
 "repo_summary_upsert_failed",
 repository_id=repository_id,
 )
 return bool(success)
 except Exception:
 logger.warning(
 "repo_summary_build_failed",
 repository_id=repository_id,
 exc_info=True,
 )
 return False
