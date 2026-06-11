"""Galaxy 图谱文件缓存 —— 全量聚合结果落盘 + 数据签名失效。

问题背景
========
``GalaxyAggregator.aggregate`` 每次请求都对 5 类节点表做带 Subquery 的全量扫描
（ChunkRegistry 的 degree 是 per-row 双子查询）并加载全部 ChunkEdge，单仓库
数千节点时需要数秒。

方案（文件缓存 + 签名对比）
==========================
1. 首次请求时做一次 **全量无采样** 聚合，连同数据签名一起写入
   ``GALAXY_CACHE_DIR/{key}.json``（key = repo_ids 集合 hash）。
2. 后续请求只需计算签名（每张源表一条 COUNT+MAX 聚合查询，毫秒级），
   签名一致 → 直接读文件；node_types / edge_types 过滤与 degree 采样
   全部在内存完成（在数千节点量级 < 10ms）。
3. 签名取自各源表的 ``(行数, 最新时间戳)``：索引/图谱构建、边构建任何写入
   都会改变行数或最新时间戳 → 签名变化 → 自动失效重建。
4. 主动刷新：图谱构建 / 边构建完成后调用 ``refresh_repo``（见
   ``services/graph_builder.py`` 与 ``code_relations/tasks.py``）；
   服务启动后由 ``codegraph.apps`` 异步对比签名预热（``warm_stale``）。

文件格式
========
{"signature": "...", "repo_ids": [...] | null, "generated_at": "...",
 "nodes": [...], "edges": [...], "by_node_type": {...}}
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import structlog
from django.conf import settings
from django.db.models import Max
from django.utils import timezone

from code_relations.models import ChunkEdge, ChunkRegistry
from codegraph.models import ApiCallSite, ApiWrapper, CrossRepoApiCall, Endpoint, Symbol

from .aggregator import GalaxyAggregator, _apply_sampling
from .serializers import GalaxyEdge, GalaxyMeta, GalaxyNode

logger = structlog.get_logger(__name__)

# 全量聚合时传给 aggregate 的"无采样"上限
_UNSAMPLED = 10**9

# 签名源表：(label, model, repo 过滤字段, 时间戳字段)
_SIGNATURE_SOURCES: list[tuple[str, Any, str, str]] = [
    ("chunk_registry", ChunkRegistry, "repository_id", "updated_at"),
    ("chunk_edge", ChunkEdge, "repository_id", "created_at"),
    ("symbol", Symbol, "repository_id", "updated_at"),
    ("endpoint", Endpoint, "repository_id", "created_at"),
    ("api_wrapper", ApiWrapper, "repository_id", "created_at"),
    ("api_call_site", ApiCallSite, "repository_id", "created_at"),
    ("cross_repo_api_call", CrossRepoApiCall, "call_site__repository_id", "matched_at"),
]


def _cache_dir() -> Path:
    path = Path(getattr(settings, "GALAXY_CACHE_DIR", settings.DATA_DIR / "galaxy_cache"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(repo_ids: list[uuid.UUID] | None) -> str:
    """repo_ids 集合 → 稳定文件 key。None（全部仓库）= "all"。"""
    if repo_ids is None:
        return "all"
    joined = ",".join(sorted(str(r) for r in repo_ids))
    return hashlib.sha256(joined.encode()).hexdigest()[:24]


class GalaxyGraphCache:
    """Galaxy 全量图谱文件缓存（签名失效 + 内存过滤/采样）。"""

    # ------------------------------------------------------------------
    # 签名
    # ------------------------------------------------------------------

    @staticmethod
    def compute_signature(repo_ids: list[uuid.UUID] | None) -> str:
        """计算 repo 集合的数据签名（每张源表 COUNT + MAX(时间戳)）。

        任何写入（新增/删除改变行数；rebuild 重写改变最新时间戳）都会使
        签名变化。代价：7 条带索引的聚合查询，与全量聚合相比可忽略。
        """
        parts: list[str] = []
        for label, model, repo_field, ts_field in _SIGNATURE_SOURCES:
            qs = model.objects.all()
            if repo_ids is not None:
                qs = qs.filter(**{f"{repo_field}__in": repo_ids})
            agg = qs.aggregate(_max_ts=Max(ts_field))
            count = qs.count()
            max_ts = agg["_max_ts"]
            parts.append(f"{label}:{count}:{max_ts.isoformat() if max_ts else '-'}")
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()

    # ------------------------------------------------------------------
    # 文件读写
    # ------------------------------------------------------------------

    @staticmethod
    def _file_path(repo_ids: list[uuid.UUID] | None) -> Path:
        return _cache_dir() / f"{_cache_key(repo_ids)}.json"

    @staticmethod
    def _load(repo_ids: list[uuid.UUID] | None) -> dict[str, Any] | None:
        path = GalaxyGraphCache._file_path(repo_ids)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("galaxy_cache_load_failed", path=str(path), error=str(exc))
            return None

    @staticmethod
    def _store(
        repo_ids: list[uuid.UUID] | None,
        signature: str,
        nodes: list[GalaxyNode],
        edges: list[GalaxyEdge],
        by_node_type: dict[str, int],
    ) -> None:
        """原子写入（tmp + os.replace），避免并发读到半个文件。"""
        path = GalaxyGraphCache._file_path(repo_ids)
        payload = {
            "signature": signature,
            "repo_ids": [str(r) for r in repo_ids] if repo_ids is not None else None,
            "generated_at": timezone.now().isoformat(),
            "nodes": nodes,
            "edges": edges,
            "by_node_type": by_node_type,
        }
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(path.parent), prefix=f".{path.stem}.", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp_path, path)
            logger.info(
                "galaxy_cache_stored",
                path=str(path),
                nodes=len(nodes),
                edges=len(edges),
            )
        except OSError as exc:
            logger.warning("galaxy_cache_store_failed", path=str(path), error=str(exc))

    # ------------------------------------------------------------------
    # 内存过滤 + 采样
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_and_sample(
        nodes: list[GalaxyNode],
        edges: list[GalaxyEdge],
        node_types: list[str] | None,
        edge_types: list[str] | None,
        max_nodes: int,
    ) -> dict[str, Any]:
        """对全量缓存数据做类型过滤 + degree 采样，构造响应 payload。"""
        if node_types is not None:
            allowed_types = set(node_types)
            nodes = [n for n in nodes if n["type"] in allowed_types]
        if edge_types is not None:
            allowed_edges = set(edge_types)
            edges = [e for e in edges if e["edge_type"] in allowed_edges]

        # 边的两端必须都在过滤后的节点集合内（与 DB 路径"按需聚合"语义对齐）
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in edges if e["source"] in node_ids and e["target"] in node_ids]

        type_counts: dict[str, int] = {}
        for n in nodes:
            type_counts[n["type"]] = type_counts.get(n["type"], 0) + 1

        total_nodes_before = len(nodes)
        total_edges_before = len(edges)
        sampled_nodes, sampled_edges, was_sampled = _apply_sampling(nodes, edges, max_nodes)

        meta = GalaxyMeta(
            total_nodes=total_nodes_before,
            total_edges=total_edges_before,
            sampled=was_sampled,
            by_node_type=type_counts,
            per_repo_hint=was_sampled,
        )
        return {"nodes": sampled_nodes, "edges": sampled_edges, "meta": meta}

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    @staticmethod
    def aggregate_cached(
        repo_ids: list[uuid.UUID] | None = None,
        node_types: list[str] | None = None,
        edge_types: list[str] | None = None,
        max_nodes: int = 500,
    ) -> dict[str, Any]:
        """带缓存的聚合入口（与 ``GalaxyAggregator.aggregate`` 同签名同语义）。

        - 命中：签名一致 → 读文件 + 内存过滤/采样（毫秒级）。
        - 未命中：全量无采样聚合 → 落盘 → 内存过滤/采样。
        - ``GALAXY_CACHE_ENABLED=False`` 时直接透传 aggregate（逃生舱）。
        """
        if not getattr(settings, "GALAXY_CACHE_ENABLED", True):
            result = GalaxyAggregator.aggregate(
                repo_ids=repo_ids,
                node_types=node_types,
                edge_types=edge_types,
                max_nodes=max_nodes,
            )
            result["meta"]["cache_hit"] = False
            return result

        signature = GalaxyGraphCache.compute_signature(repo_ids)
        cached = GalaxyGraphCache._load(repo_ids)
        cache_hit = cached is not None and cached.get("signature") == signature

        if cache_hit:
            nodes = cached["nodes"]  # type: ignore[index]
            edges = cached["edges"]  # type: ignore[index]
        else:
            full = GalaxyAggregator.aggregate(
                repo_ids=repo_ids,
                node_types=None,
                edge_types=None,
                max_nodes=_UNSAMPLED,
            )
            nodes = full["nodes"]
            edges = full["edges"]
            GalaxyGraphCache._store(repo_ids, signature, nodes, edges, full["meta"]["by_node_type"])

        result = GalaxyGraphCache._filter_and_sample(
            nodes, edges, node_types, edge_types, max_nodes
        )
        result["meta"]["cache_hit"] = cache_hit
        logger.info(
            "galaxy_cache_aggregate",
            repo_ids=len(repo_ids) if repo_ids else "all",
            cache_hit=cache_hit,
            nodes=len(result["nodes"]),
            edges=len(result["edges"]),
        )
        return result

    # ------------------------------------------------------------------
    # 主动刷新 / 预热
    # ------------------------------------------------------------------

    @staticmethod
    def refresh_repo(repository_id: str | uuid.UUID) -> None:
        """仓库数据更新后主动刷新：清理含该仓库的过期缓存 + 重建单仓缓存。

        由图谱构建 / 边构建完成钩子调用。所有异常内部吞掉（缓存刷新失败
        不影响主流程，下次请求签名对比仍会自动重建）。
        """
        try:
            repo_uuid = uuid.UUID(str(repository_id))
            GalaxyGraphCache._evict_containing(repo_uuid)

            signature = GalaxyGraphCache.compute_signature([repo_uuid])
            full = GalaxyAggregator.aggregate(
                repo_ids=[repo_uuid],
                node_types=None,
                edge_types=None,
                max_nodes=_UNSAMPLED,
            )
            GalaxyGraphCache._store(
                [repo_uuid],
                signature,
                full["nodes"],
                full["edges"],
                full["meta"]["by_node_type"],
            )
            logger.info("galaxy_cache_refreshed", repository_id=str(repo_uuid))
        except Exception as exc:
            logger.warning(
                "galaxy_cache_refresh_failed",
                repository_id=str(repository_id),
                error=str(exc),
            )

    @staticmethod
    def _evict_containing(repo_uuid: uuid.UUID) -> None:
        """删除所有包含该仓库的缓存文件（多仓组合 + "all"）。"""
        repo_str = str(repo_uuid)
        for path in _cache_dir().glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
                member_ids = payload.get("repo_ids")
                # repo_ids=None 表示"全部仓库"缓存，任何仓库更新都失效
                if member_ids is None or repo_str in member_ids:
                    path.unlink(missing_ok=True)
            except (OSError, json.JSONDecodeError):
                # 读不动的文件直接删（损坏缓存无保留价值）
                path.unlink(missing_ok=True)

    @staticmethod
    def warm_stale() -> None:
        """启动预热：对比每个仓库的签名，缓存缺失或过期时重建。

        由 ``codegraph.apps`` 在启动后于后台线程调用；逐仓串行执行，
        任何单仓失败不影响其余。
        """
        from repositories.models import Repository

        repo_ids = list(Repository.objects.filter(is_deleted=False).values_list("id", flat=True))
        warmed = 0
        for repo_id in repo_ids:
            try:
                signature = GalaxyGraphCache.compute_signature([repo_id])
                cached = GalaxyGraphCache._load([repo_id])
                if cached is not None and cached.get("signature") == signature:
                    continue
                full = GalaxyAggregator.aggregate(
                    repo_ids=[repo_id],
                    node_types=None,
                    edge_types=None,
                    max_nodes=_UNSAMPLED,
                )
                # 没有任何图谱数据的仓库不值得占一个缓存文件
                if not full["nodes"]:
                    continue
                GalaxyGraphCache._store(
                    [repo_id],
                    signature,
                    full["nodes"],
                    full["edges"],
                    full["meta"]["by_node_type"],
                )
                warmed += 1
            except Exception as exc:
                logger.warning(
                    "galaxy_cache_warm_repo_failed",
                    repository_id=str(repo_id),
                    error=str(exc),
                )
        logger.info("galaxy_cache_warm_done", total_repos=len(repo_ids), warmed=warmed)


__all__ = ["GalaxyGraphCache"]
