"""能力树节点向量化服务（PageIndex 化）。

把 Repository.ai_summary_tree 的每个节点（title + summary + keywords + 祖先
路径拼接）生成 dense + sparse 向量，写入独立 Qdrant collection
`repo_index_nodes`。节点是检索单元，树结构是推理上下文：

- payload.node_path：祖先链 "admin-portal > 权限管理 > 角色批量授权"，
  供路由结果解释与前端定位展开
- payload.sub_project：monorepo 子应用归属，路由结果可落到子应用粒度
- payload.facets：仓库分面标签冗余进节点，供路由过滤/降权（如废弃仓库）

事实校准：按节点 paths 前缀把 codegraph Endpoint（API 域）挂到节点 payload，
LLM 树 + 静态分析事实互补。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from services.embedding import EmbeddingService
from services.qdrant_service import QdrantService
from services.sparse_encoder import SparseEncoderService

logger = structlog.get_logger(__name__)

COLLECTION_NAME = "repo_index_nodes"


def flatten_tree(
    tree: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """嵌套树 → 扁平节点列表，附 node_path（祖先标题链）/ depth / sub_project。"""
    out: list[dict[str, Any]] = []

    def _walk(
        nodes: list[dict[str, Any]],
        ancestors: list[str],
        sub_project: str,
        depth: int,
    ) -> None:
        for node in nodes:
            title = str(node.get("title", ""))
            current_sub = sub_project
            if node.get("node_type") == "sub_app" and not sub_project:
                current_sub = title
            path_titles = [*ancestors, title]
            out.append(
                {
                    "node_id": str(node.get("node_id", "")),
                    "node_type": str(node.get("node_type", "module")),
                    "title": title,
                    "summary": str(node.get("summary", "")),
                    "keywords": list(node.get("keywords", [])),
                    "paths": list(node.get("paths", [])),
                    "node_path": " > ".join(t for t in path_titles if t),
                    "sub_project": current_sub,
                    "depth": depth,
                }
            )
            children = node.get("children", [])
            if children:
                _walk(children, path_titles, current_sub, depth + 1)

    _walk(tree, [], "", 1)
    return out


class RepoIndexTreeBuilder:
    """能力树节点向量化构建器——纯 @classmethod async 服务类。"""

    @classmethod
    async def build(cls, repository_id: str) -> bool:
        """重建某仓库的全部树节点向量（先删后写，幂等）。

        Returns:
            True 表示节点向量全部写入成功。
        """
        from repositories.models import Repository

        try:
            repo = await Repository.objects.filter(id=repository_id).afirst()
            if repo is None or not repo.ai_summary_tree:
                logger.info(
                    "repo_index_tree_skipped_no_tree", repository_id=repository_id
                )
                return False

            flat_nodes = flatten_tree(repo.ai_summary_tree)
            if not flat_nodes:
                return False

            await sync_to_async(
                QdrantService.ensure_repo_index_nodes_collection,
                thread_sensitive=False,
            )()

            # 事实校准：endpoint URL 前缀按 paths 归属到节点
            endpoint_map = await cls._build_endpoint_map(repository_id, flat_nodes)

            facets = dict(repo.facets or {})
            repo_name = repo.name
            built_at = datetime.now(UTC).isoformat()

            points: list[dict[str, Any]] = []
            for node in flat_nodes:
                text = cls._node_embedding_text(repo_name, node)
                dense = await EmbeddingService.generate_embedding(text)
                if not dense:
                    logger.warning(
                        "repo_index_node_dense_failed",
                        repository_id=repository_id,
                        node_id=node["node_id"],
                    )
                    continue
                sparse = await sync_to_async(
                    SparseEncoderService.encode, thread_sensitive=False
                )(text)
                if not sparse or not sparse.get("indices"):
                    continue

                point_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_DNS,
                        f"repo_index_node:{repository_id}:{node['node_id']}",
                    )
                )
                points.append(
                    {
                        "id": point_id,
                        "vector": {"dense": dense, "sparse": sparse},
                        "payload": {
                            "repository_id": repository_id,
                            "repo_name": repo_name,
                            "node_id": node["node_id"],
                            "node_type": node["node_type"],
                            "title": node["title"],
                            "summary": node["summary"],
                            "keywords": json.dumps(
                                node["keywords"], ensure_ascii=False
                            ),
                            "paths": json.dumps(node["paths"], ensure_ascii=False),
                            "node_path": node["node_path"],
                            "sub_project": node["sub_project"],
                            "depth": node["depth"],
                            "api_domains": json.dumps(
                                endpoint_map.get(node["node_id"], []),
                                ensure_ascii=False,
                            ),
                            "facets": json.dumps(facets, ensure_ascii=False),
                            "built_at": built_at,
                        },
                    }
                )

            if not points:
                logger.warning(
                    "repo_index_tree_no_points", repository_id=repository_id
                )
                return False

            # 先删旧节点再写新节点（树结构可能收缩，残留节点会污染检索）
            await sync_to_async(
                QdrantService.delete_by_payload_field, thread_sensitive=False
            )(COLLECTION_NAME, "repository_id", repository_id)

            success = await sync_to_async(
                QdrantService.upsert_vectors_by_name, thread_sensitive=False
            )(COLLECTION_NAME, points)

            logger.info(
                "repo_index_tree_built",
                repository_id=repository_id,
                node_count=len(points),
                success=bool(success),
            )
            return bool(success)
        except Exception:
            logger.warning(
                "repo_index_tree_build_failed",
                repository_id=repository_id,
                exc_info=True,
            )
            return False

    @classmethod
    async def refresh_facts(cls, repository_id: str) -> bool:
        """事实层刷新（零 LLM）：仅更新节点 payload 的 facets / api_domains。

        webhook 索引完成后调用；树结构与向量不动，避免无谓的 embedding 成本。
        Qdrant 不支持部分 payload 字段的批量条件更新到任意点集，这里直接走
        全量重建（节点数 ≤100，成本可控）——与 build 的区别是调用方语义：
        refresh_facts 不要求树有变化。
        """
        return await cls.build(repository_id)

    @classmethod
    def _node_embedding_text(cls, repo_name: str, node: dict[str, Any]) -> str:
        """节点 embedding 文本：祖先路径 + 标题 + 摘要 + 关键词 + 目录。"""
        parts = [
            f"Repository: {repo_name}",
            f"Path: {node['node_path']}",
            f"Title: {node['title']}",
        ]
        if node["summary"]:
            parts.append(f"Summary: {node['summary']}")
        if node["keywords"]:
            parts.append(f"Keywords: {', '.join(node['keywords'])}")
        if node["paths"]:
            parts.append(f"Dirs: {', '.join(node['paths'])}")
        return "\n".join(parts)

    @classmethod
    async def _build_endpoint_map(
        cls, repository_id: str, flat_nodes: list[dict[str, Any]]
    ) -> dict[str, list[str]]:
        """按节点 paths 前缀把 Endpoint URL 一级前缀聚到节点（事实校准）。"""
        from codegraph.models import Endpoint

        def _load() -> list[tuple[str, str]]:
            return list(
                Endpoint.objects.filter(repository_id=repository_id).values_list(
                    "file_path", "url_path"
                )
            )

        try:
            endpoints = await sync_to_async(_load, thread_sensitive=False)()
        except Exception:  # noqa: BLE001 — codegraph 未启用时静默跳过
            return {}

        if not endpoints:
            return {}

        result: dict[str, set[str]] = {}
        for node in flat_nodes:
            node_paths = [p for p in node.get("paths", []) if p]
            if not node_paths:
                continue
            for file_path, url_path in endpoints:
                fp = str(file_path or "").strip("/")
                if not any(
                    fp == np or fp.startswith(np + "/") for np in node_paths
                ):
                    continue
                parts = str(url_path or "").strip("/").split("/")
                if parts and parts[0]:
                    result.setdefault(node["node_id"], set()).add(parts[0])

        return {k: sorted(v)[:10] for k, v in result.items()}


__all__ = ["RepoIndexTreeBuilder", "flatten_tree", "COLLECTION_NAME"]
