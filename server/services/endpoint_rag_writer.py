"""api_endpoint RAG 文档写入服务 —— ..03。
在 indexer._extract_and_write_graph 图谱轨末尾，把每个 EndpointData
转为 api_endpoint.md 文档，embedding 后写入 Qdrant。
payload 中加 content_type="api_endpoint"，与普通 code chunk 区分。
"""
from __future__ import annotations
import uuid
from typing import TYPE_CHECKING, Any
import structlog
from asgiref.sync import sync_to_async
# 顶层 import 保证 patch path services.endpoint_rag_writer.EmbeddingService 生效
from services.embedding import EmbeddingService
if TYPE_CHECKING:
 from codegraph.extractors.base import EndpointData
logger = structlog.get_logger(__name__)
_EXT_TO_LANG: dict[str, str] = {
 "go": "go",
 "py": "python",
 "ts": "typescript",
 "tsx": "typescript",
 "js": "javascript",
}
def _infer_language(file_path: str) -> str:
 """从文件路径推断语言（用于 Qdrant payload language 字段）。"""
 ext = file_path.rsplit(".", 1)[-1].lower if "." in file_path else ""
 return _EXT_TO_LANG.get(ext, "unknown")
_MD_TEMPLATE = """\
# API Endpoint: {method} {path}
**Repository**: {repo_name}
**Handler**: `{handler_name}`
**File**: `{file_path}`
**Line**: {line_number}
## Function Signature
```
{signature}
```
""".strip
def build_api_endpoint_md(
 *,
 http_method: str,
 url_path: str,
 handler_name: str,
 file_path: str,
 line_number: int,
 repo_name: str,
 signature: str = "",
) -> str:
 """：生成 api_endpoint.md 文档文本。
 Args:
 http_method: HTTP 方法（GET/POST/PUT/DELETE 等）
 url_path: URL 路径（如 "/api/users"）
 handler_name: 处理函数名（如 "userHandler.CreateUser"）
 file_path: 文件路径（相对 repo root）
 line_number: 路由注册所在行号
 repo_name: 仓库名称
 signature: 函数签名（best-effort，空时 fallback 为 handler_name）
 Returns:
 格式化 Markdown 字符串
 """
 sig = signature if signature else handler_name
 path_display = url_path if url_path else "(unknown)"
 return _MD_TEMPLATE.format(
 method=http_method.upper,
 path=path_display,
 repo_name=repo_name,
 handler_name=handler_name,
 file_path=file_path,
 line_number=line_number,
 signature=sig,
 )
def _make_endpoint_point_id(repository_id: str, ep: "EndpointData") -> str:
 """生成 endpoint 点的确定性 UUID（同一 endpoint 重索引幂等）。"""
 stable_key = (
 f"api_endpoint:{repository_id}:{ep.file_path}"
 f":{ep.http_method}:{ep.url_path or ''}:{ep.handler_name}"
 )
 return str(uuid.uuid5(uuid.NAMESPACE_URL, stable_key))
@sync_to_async
def _qdrant_upsert_endpoint_vectors(repository_id: str, points: list[dict[str, Any]]) -> bool:
 """将 endpoint 点写入 Qdrant（sync_to_async 包装）。"""
 from services.qdrant_service import QdrantService
 return QdrantService.upsert_vectors(repository_id, points)
async def write_endpoint_rag_docs(
 *,
 endpoints_with_sigs: list[tuple["EndpointData", str]],
 repository_id: str,
 repo_name: str,
 hybrid_enabled: bool = False,
) -> int:
 """为 endpoint 列表生成 api_endpoint.md 并写入 Qdrant。: indexer hook 调用本函数: build_api_endpoint_md 生成模板文本: payload 加 content_type="api_endpoint" 字段
 Args:
 endpoints_with_sigs: [(EndpointData, signature_str), ...] 列表
 signature_str 为 best-effort 函数签名，空字符串表示无匹配
 repository_id: 仓库 UUID 字符串
 repo_name: 仓库名称（用于模板 **Repository** 字段）
 hybrid_enabled: 是否使用 hybrid 向量（dense + sparse）
 Returns:
 成功写入 Qdrant 的点数量（0 表示跳过或失败）
 """
 if not endpoints_with_sigs:
 return 0
 # 过滤掉没有 url_path 的 endpoint（Python Layer 1 中间态，path 为 None）
 valid_items = [
 (ep, sig) for ep, sig in endpoints_with_sigs if ep.url_path
 ]
 if not valid_items:
 return 0
 texts = [
 build_api_endpoint_md(
 http_method=ep.http_method,
 url_path=ep.url_path or "",
 handler_name=ep.handler_name,
 file_path=ep.file_path,
 line_number=ep.line_number,
 repo_name=repo_name,
 signature=sig,
 )
 for ep, sig in valid_items
 ]
 embeddings = await EmbeddingService.generate_embeddings_batch(texts)
 if not embeddings:
 logger.warning(
 "endpoint_rag_embedding_failed",
 repository_id=repository_id,
 count=len(valid_items),
 )
 return 0
 sparse_vectors: list[dict[str, Any]] | None = None
 if hybrid_enabled:
 from asgiref.sync import sync_to_async as _sta
 from services.sparse_encoder import SparseEncoderService
 sparse_vectors = await _sta(SparseEncoderService.encode_batch)(texts)
 points: list[dict[str, Any]] =
 for idx, ((ep, _sig), text, emb) in enumerate(
 zip(valid_items, texts, embeddings)
 ):
 if emb is None:
 continue
 if hybrid_enabled and sparse_vectors and idx < len(sparse_vectors):
 sv = sparse_vectors[idx]
 from qdrant_client.http.models import SparseVector
 vector: Any = {
 "dense": emb,
 "sparse": SparseVector(
 indices=sv["indices"],
 values=sv["values"],
 ),
 }
 else:
 vector = emb
 payload: dict[str, Any] = {
 "content_type": "api_endpoint",
 "file_path": ep.file_path,
 "file_hash": "",
 "language": _infer_language(ep.file_path),
 "node_type": "api_endpoint",
 "content": text,
 "context_header": f"API Endpoint: {ep.http_method} {ep.url_path}",
 "http_method": ep.http_method,
 "url_path": ep.url_path or "",
 "handler_name": ep.handler_name,
 }
 points.append({
 "id": _make_endpoint_point_id(repository_id, ep),
 "vector": vector,
 "payload": payload,
 })
 if not points:
 return 0
 ok = await _qdrant_upsert_endpoint_vectors(repository_id, points)
 if ok:
 logger.info(
 "endpoint_rag_write_success",
 repository_id=repository_id,
 count=len(points),
 )
 else:
 logger.warning(
 "endpoint_rag_write_failed",
 repository_id=repository_id,
 count=len(points),
 )
 return len(points) if ok else 0
