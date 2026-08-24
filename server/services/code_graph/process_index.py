"""ProcessTrace → 独立 Qdrant dense+sparse 可重建投影（Phase 136）。"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from collections.abc import Mapping
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.log_context import bind_task_context
from common.logging import redact_secrets_in_text
from services.embedding import EmbeddingService

logger = structlog.get_logger(__name__)

PROCESS_INDEX_SCHEMA_VERSION = "process-index/v1"
_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def process_collection_name(repository_id: str) -> str:
    """每仓独立 collection；名称只含 Qdrant 安全字符。"""
    return f"friday_processes_{repository_id.replace('-', '_')}"


def process_generation(
    repository_id: str,
    branch_name: str,
    built_at_sha: str,
) -> str:
    """同输入同 generation，支持幂等重建与严格查询过滤。"""
    raw = (
        f"{PROCESS_INDEX_SCHEMA_VERSION}\0{repository_id}\0"
        f"{branch_name}\0{built_at_sha}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _normalize_step(step: Mapping[str, Any]) -> dict[str, Any]:
    start = int(step.get("start_line") or step.get("line") or 0)
    end = int(step.get("end_line") or start or 0)
    return {
        **dict(step),
        "symbol_id": str(step.get("symbol_id") or ""),
        "file_path": str(step.get("file_path") or ""),
        "start_line": start if start >= 1 else None,
        "end_line": end if end >= 1 else None,
    }


def build_process_document(trace: Mapping[str, Any]) -> dict[str, Any]:
    """由 canonical ProcessTrace 投影确定性文档；不读取 Qdrant。"""
    steps = [_normalize_step(step) for step in (trace.get("steps") or [])]
    entry = dict(trace.get("entry_endpoint") or {})
    terminal = dict(steps[-1]) if steps else {}
    modules = sorted(
        {
            str(step.get("file_path") or "").rsplit("/", 1)[0]
            for step in steps
            if step.get("file_path")
        }
    )
    keyword_source = " ".join(
        [
            str(trace.get("name") or ""),
            str(entry.get("url_path") or ""),
            *(str(step.get("name") or "") for step in steps),
            *modules,
        ]
    )
    keywords = sorted(
        {
            token.lower()
            for token in _TOKEN_RE.findall(keyword_source)
            if len(token) >= 2
        }
    )
    ordered_summary = " -> ".join(
        str(step.get("name") or step.get("symbol_id") or "") for step in steps
    )
    content = "\n".join(
        [
            f"# Process: {trace.get('name') or trace.get('process_key') or ''}",
            f"Entry: {entry.get('http_method', '')} {entry.get('url_path', '')}",
            f"Terminal: {terminal.get('name') or terminal.get('symbol_id') or ''}",
            f"Modules: {', '.join(modules)}",
            f"Keywords: {', '.join(keywords)}",
            f"Steps: {ordered_summary}",
        ]
    )
    return {
        "process_key": str(trace.get("process_key") or ""),
        "name": str(trace.get("name") or ""),
        "entry": entry,
        "terminal": terminal,
        "steps": steps,
        "modules": modules,
        "business_keywords": keywords,
        "built_at_sha": str(trace.get("built_at_sha") or ""),
        "content": content,
    }


def _load_traces(repository_id: str, branch_name: str) -> list[dict[str, Any]]:
    from codegraph.models import ProcessTrace

    return list(
        ProcessTrace.objects.filter(
            repository_id=repository_id,
            branch_name=branch_name,
        ).values(
            "process_key",
            "name",
            "entry_endpoint",
            "steps",
            "built_at_sha",
        )
    )


def _point_id(repository_id: str, branch_name: str, generation: str, key: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"process:{repository_id}:{branch_name}:{generation}:{key}",
        )
    )


async def rebuild_process_index(
    repository_id: str,
    branch_name: str = "",
    *,
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """从 Django 事实源幂等重建 Process Qdrant 投影，并重新 bind 触发用户。"""
    from qdrant_client.http.models import SparseVector

    from services.qdrant_service import QdrantService
    from services.sparse_encoder import SparseEncoderService

    started = time.monotonic()
    branch = branch_name or ""
    user_id = initiated_by_user_id or "system"
    with bind_task_context(user_id=user_id, source="process_index"):
        try:
            logger.info(
                "code_graph_process_index_rebuild_started",
                repository_id=repository_id,
                branch_name=branch,
                initiated_by_user_id=user_id,
                category="caller",
                component="codegraph",
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            traces = await sync_to_async(_load_traces)(repository_id, branch)
            shas = {str(row.get("built_at_sha") or "") for row in traces}
            if not traces:
                return {"status": "ok", "generation": "", "indexed": 0}
            if "" in shas or len(shas) != 1:
                raise ValueError("process_trace_mixed_or_empty_built_at_sha")
            built_at_sha = next(iter(shas))
            generation = process_generation(repository_id, branch, built_at_sha)
            documents = [build_process_document(row) for row in traces]
            texts = [doc["content"] for doc in documents]
            dense = await EmbeddingService.generate_embeddings_batch(texts)
            sparse = await sync_to_async(SparseEncoderService.encode_batch)(texts)
            if len(dense) != len(documents) or len(sparse) != len(documents):
                raise ValueError("process_index_embedding_count_mismatch")

            points: list[dict[str, Any]] = []
            for doc, dense_vector, sparse_vector in zip(
                documents, dense, sparse, strict=True
            ):
                if not dense_vector:
                    raise ValueError("process_index_empty_dense_vector")
                payload = {
                    **doc,
                    "repository_id": repository_id,
                    "branch_name": branch,
                    "generation": generation,
                    "commit_sha": built_at_sha,
                    "schema_version": PROCESS_INDEX_SCHEMA_VERSION,
                    "content_type": "process",
                }
                points.append(
                    {
                        "id": _point_id(
                            repository_id,
                            branch,
                            generation,
                            doc["process_key"],
                        ),
                        "vector": {
                            "dense": dense_vector,
                            "sparse": SparseVector(
                                indices=sparse_vector["indices"],
                                values=sparse_vector["values"],
                            ),
                        },
                        "payload": payload,
                    }
                )

            collection = process_collection_name(repository_id)
            created = await sync_to_async(QdrantService.create_collection_by_name)(
                collection,
                vector_size=len(points[0]["vector"]["dense"]),
                hybrid=True,
                recreate_on_mismatch=True,
            )
            if not created:
                raise RuntimeError("process_index_collection_unavailable")
            ok = await sync_to_async(QdrantService.upsert_vectors_by_name)(
                collection, points
            )
            if not ok:
                raise RuntimeError("process_index_upsert_failed")
            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                logger.info(
                    "code_graph_process_index_rebuild_completed",
                    repository_id=repository_id,
                    branch_name=branch,
                    generation=generation,
                    indexed=len(points),
                    duration_ms=duration_ms,
                    initiated_by_user_id=user_id,
                    category="caller",
                    component="codegraph",
                )
            except Exception:  # noqa: BLE001
                pass
            return {
                "status": "ok",
                "generation": generation,
                "commit_sha": built_at_sha,
                "indexed": len(points),
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            try:
                logger.warning(
                    "code_graph_process_index_rebuild_failed",
                    repository_id=repository_id,
                    branch_name=branch,
                    error=redact_secrets_in_text(str(exc)),
                    duration_ms=int((time.monotonic() - started) * 1000),
                    initiated_by_user_id=user_id,
                    category="caller",
                    component="codegraph",
                )
            except Exception:  # noqa: BLE001
                pass
            raise


async def search_process_index(
    query: str,
    *,
    repository_id: str,
    branch_name: str,
    commit_sha: str,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """严格同 generation/commit 的 Process hybrid 召回。"""
    if not query.strip():
        raise ValueError("query 不能为空")

    from services.qdrant_service import QdrantService
    from services.query_embedding import embed_query
    from services.sparse_encoder import SparseEncoderService

    embedded = await embed_query(query)
    if not embedded.primary:
        return []
    sparse = await sync_to_async(SparseEncoderService.encode)(query)
    if not sparse or not sparse.get("indices"):
        return []
    generation = process_generation(repository_id, branch_name or "", commit_sha)
    rows = await sync_to_async(QdrantService.hybrid_search_by_name)(
        process_collection_name(repository_id),
        embedded.primary,
        sparse,
        top_k=top_k,
        filters={
            "repository_id": repository_id,
            "branch_name": branch_name or "",
            "generation": generation,
            "commit_sha": commit_sha,
        },
    )
    return [
        {
            **dict(row.get("payload") or {}),
            "score": row.get("score"),
            "lane": "hybrid",
        }
        for row in rows
    ]


__all__ = [
    "PROCESS_INDEX_SCHEMA_VERSION",
    "build_process_document",
    "process_collection_name",
    "process_generation",
    "rebuild_process_index",
    "search_process_index",
]
