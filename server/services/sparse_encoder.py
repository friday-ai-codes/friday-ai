"""BM25 稀疏向量编码服务，基于 Qdrant FastEmbed。"""

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# 懒加载 fastembed 模型实例
_sparse_model: Any = None
# 模型初始化失败标志：触发后所有 encode() 返回空 sparse，
# 由调用方退化为 dense-only，避免每次请求都重复尝试初始化。
_sparse_model_unavailable: bool = False


def _get_sparse_model() -> Any:
    """获取或创建 BM25 稀疏编码模型（懒加载）。

    初始化失败（含 py-rust-stemmers 在某些平台 SIGSEGV 之外的可恢复异常）
    时返回 None，让上层降级为 dense-only。"""
    global _sparse_model, _sparse_model_unavailable
    if _sparse_model_unavailable:
        return None
    if _sparse_model is None:
        try:
            from fastembed import SparseTextEmbedding

            # disable_stemmer=True 绕过 py-rust-stemmers 0.1.5 在
            # Python 3.14 + macOS arm64 上加载 SnowballStemmer 时
            # 必现的 SIGSEGV（PyInit_py_rust_stemmers 段错误，
            # 发生在 sync_to_async 工作线程时会让整个 ASGI 进程卡死）。
            # Snowball 不支持中文，对中文 query 完全无影响；对英文
            # query 仅损失词形归并（running ↔ run），可接受。
            # 等 py-rust-stemmers > 0.1.5 修复 3.14 兼容性后可移除。
            _sparse_model = SparseTextEmbedding(
                model_name="Qdrant/bm25",
                disable_stemmer=True,
            )
            logger.info(
                "sparse_encoder_initialized",
                model="Qdrant/bm25",
                disable_stemmer=True,
            )
        except ImportError:
            logger.error("fastembed_not_installed", hint="pip install fastembed")
            raise
        except Exception as exc:
            # 任何其他初始化错误（模型下载失败、onnxruntime 加载失败等）
            # 都不能让 chat / 检索整体崩溃；记下标志位让后续 encode 直接
            # 返回空 sparse，调用方走 dense-only 路径。
            _sparse_model_unavailable = True
            logger.error(
                "sparse_encoder_init_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return None
    return _sparse_model


class SparseEncoderService:
    """基于 FastEmbed BM25 的稀疏向量编码服务。"""

    @classmethod
    def encode(cls, text: str) -> dict[str, Any]:
        """编码单条文本为 Qdrant SparseVector 格式。

        Returns:
            {"indices": list[int], "values": list[float]}
            模型不可用或编码失败时返回空 sparse，让上层退化为 dense-only。
        """
        model = _get_sparse_model()
        if model is None:
            return {"indices": [], "values": []}
        try:
            results = list(model.embed([text]))
        except Exception as exc:
            logger.warning("sparse_encode_failed", error=str(exc))
            return {"indices": [], "values": []}
        if not results:
            return {"indices": [], "values": []}

        sparse = results[0]
        return {
            "indices": sparse.indices.tolist(),
            "values": sparse.values.tolist(),
        }

    @classmethod
    def encode_batch(cls, texts: list[str]) -> list[dict[str, Any]]:
        """批量编码文本为稀疏向量。

        Returns:
            [{"indices": [...], "values": [...]}, ...]
            模型不可用或编码失败时返回与 texts 等长的空 sparse 列表。
        """
        if not texts:
            return []

        model = _get_sparse_model()
        empty: list[dict[str, Any]] = [
            {"indices": [], "values": []} for _ in texts
        ]
        if model is None:
            return empty
        try:
            results = list(model.embed(texts))
        except Exception as exc:
            logger.warning(
                "sparse_encode_batch_failed",
                error=str(exc),
                batch_size=len(texts),
            )
            return empty

        sparse_vectors: list[dict[str, Any]] = []
        for sparse in results:
            sparse_vectors.append({
                "indices": sparse.indices.tolist(),
                "values": sparse.values.tolist(),
            })

        return sparse_vectors
