"""BM25 稀疏向量编码服务，基于 Qdrant FastEmbed。"""
from typing import Any
import structlog
logger = structlog.get_logger(__name__)
# 懒加载 fastembed 模型实例
_sparse_model: Any = None
def _get_sparse_model -> Any:
 """获取或创建 BM25 稀疏编码模型（懒加载）。"""
 global _sparse_model
 if _sparse_model is None:
 try:
 from fastembed import SparseTextEmbedding
 _sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
 logger.info("sparse_encoder_initialized", model="Qdrant/bm25")
 except ImportError:
 logger.error("fastembed_not_installed", hint="pip install fastembed")
 raise
 return _sparse_model
class SparseEncoderService:
 """基于 FastEmbed BM25 的稀疏向量编码服务。"""
 @classmethod
 def encode(cls, text: str) -> dict[str, Any]:
 """编码单条文本为 Qdrant SparseVector 格式。
 Returns:
 {"indices": list[int], "values": list[float]}
 """
 model = _get_sparse_model
 # fastembed 返回生成器，取第一个结果
 results = list(model.embed([text]))
 if not results:
 return {"indices":, "values": }
 sparse = results[0]
 return {
 "indices": sparse.indices.tolist,
 "values": sparse.values.tolist,
 }
 @classmethod
 def encode_batch(cls, texts: list[str]) -> list[dict[str, Any]]:
 """批量编码文本为稀疏向量。
 Returns:
 [{"indices": [...], "values": [...]}, ...]
 """
 if not texts:
 return
 model = _get_sparse_model
 results = list(model.embed(texts))
 sparse_vectors: list[dict[str, Any]] =
 for sparse in results:
 sparse_vectors.append({
 "indices": sparse.indices.tolist,
 "values": sparse.values.tolist,
 })
 return sparse_vectors
