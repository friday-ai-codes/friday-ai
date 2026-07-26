"""FeatureChangeClassifyAdapter —— classify stage 真实实现（feature list 方案编排）。

把 feature list 的每个功能点判定为**新增功能**还是**改造已有功能**：先在路由候选仓范围内
用既有 ``HybridSearchService`` 混合检索取「现有代码证据」，再把证据喂给
``aclassify_feature_changes`` 让 LLM 判定，产出带证据文件路径的分类结果供

1. 强制确认环节组装确认题（用户复核误判 / 指认 unclear 项）；
2. 融合环节给出每个功能点的落点与伪代码。

本 adapter **不重写检索逻辑**——只做编排接线（取数 + 有界并发检索 + 证据映射 + 结果映射）。

**fail-soft（对齐 RECALL-01 / CLARIFY-02 范式）**：单个功能点检索失败 → 该功能点证据为空
（不影响其余）；LLM 分类不可用（返回 ``None``）→ 全部功能点降级为 ``unclear``，交由用户在
确认环节指认。任何异常都不冒泡，绝不让 ``engine.advance`` 通用 except 落 failed。

**async 防裸 lazy-FK**：只读 ``session`` 的 JSON 字段（decomposition / routing），绝不裸访问
``session.work_item`` 等同步 lazy-FK。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from delivery.models import ConvergenceSession
from services.process_runtime.feature_classify import (
    aclassify_feature_changes,
    build_feature_key,
)

logger = structlog.get_logger(__name__)

__all__ = ["FeatureChangeClassifyAdapter"]

# 逐功能点检索的并发上限（对齐 rag_search 的有界并发范式，防几十个功能点打爆 provider）。
_SEARCH_CONCURRENCY = 4
# 单功能点检索取回的 chunk 上限（够判定即可，控 prompt 体积）。
_SEARCH_TOP_K = 5
# 单次分类处理的功能点上限（超出部分不判定，留给后续轮次/人工，防超大 feature list 失控）。
_MAX_FEATURES = 60


class FeatureChangeClassifyAdapter:
    """feature 变更类型分类 stage 依赖的真实实现（满足 ClassifyProtocol）。"""

    def __init__(
        self,
        *,
        top_k: int = _SEARCH_TOP_K,
        concurrency: int = _SEARCH_CONCURRENCY,
        max_features: int = _MAX_FEATURES,
    ) -> None:
        self.top_k = top_k
        self.concurrency = concurrency
        self.max_features = max_features

    async def classify(self, session: ConvergenceSession) -> dict:
        """判定各功能点新增/改造，返回 ``{items, summary, evidence_hits}``。

        无功能点 → 直接返回空结果（不检索、不调 LLM）。
        """
        started = time.monotonic()
        features = self._collect_features(session)
        if not features:
            return {"items": [], "summary": {"new": 0, "modify": 0, "unclear": 0}}

        repository_ids = self._candidate_repository_ids(session)
        evidence_by_key = await self._collect_evidence(features, repository_ids)

        items = await aclassify_feature_changes(features=features, evidence_by_key=evidence_by_key)
        if items is None:
            # LLM 不可用 → 全量降级 unclear（不阻断编排，交回用户在确认环节指认）。
            items = [
                {
                    "key": feat["key"],
                    "change_type": "unclear",
                    "confidence": "low",
                    "target_repo_id": "",
                    "reason": "分类模型不可用，待人工确认",
                    "evidence_files": [],
                    "suggested_location": "",
                }
                for feat in features
            ]

        items = self._merge_feature_meta(items, features)
        summary = {
            "new": sum(1 for i in items if i["change_type"] == "new"),
            "modify": sum(1 for i in items if i["change_type"] == "modify"),
            "unclear": sum(1 for i in items if i["change_type"] == "unclear"),
        }
        evidence_hits = sum(len(v) for v in evidence_by_key.values())

        logger.info(
            "feature_classify_stage_completed",
            category="sampling",
            component="process_runtime",
            session_id=str(session.id),
            feature_count=len(features),
            evidence_hits=evidence_hits,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            **summary,
        )
        return {"items": items, "summary": summary, "evidence_hits": evidence_hits}

    # ------------------------------------------------------------------ 取数

    def _collect_features(self, session: ConvergenceSession) -> list[dict[str, Any]]:
        """从 decomposition.segments 提取待分类功能点（截断到 max_features）。

        segments 形如 ``{"title","module","layer","repo_hint"}``（feature list 模式下由
        feature 树展平而来，非 feature list 模式本 adapter 不会被调用）。
        """
        decomposition = session.decomposition if isinstance(session.decomposition, dict) else {}
        segments = decomposition.get("segments") or []
        features: list[dict[str, Any]] = []
        seen: set[str] = set()
        for seg in segments[: self.max_features]:
            if not isinstance(seg, dict):
                continue
            title = str(seg.get("title", "")).strip()
            if not title:
                continue
            module = str(seg.get("module", "")).strip()
            key = build_feature_key(module, title)
            if key in seen:
                continue
            seen.add(key)
            features.append(
                {
                    "key": key,
                    "title": title,
                    "module": module,
                    "layer": str(seg.get("layer", "")).strip(),
                }
            )
        return features

    @staticmethod
    def _candidate_repository_ids(session: ConvergenceSession) -> list[str] | None:
        """取路由候选仓 id 收窄检索范围；无候选返回 None（由检索侧决定全库/空）。"""
        routing = session.routing if isinstance(session.routing, dict) else {}
        candidates = routing.get("candidates") or []
        repo_ids = [
            str(c.get("repo_id")) for c in candidates if isinstance(c, dict) and c.get("repo_id")
        ]
        return repo_ids or None

    # ------------------------------------------------------------------ 检索

    async def _collect_evidence(
        self, features: list[dict[str, Any]], repository_ids: list[str] | None
    ) -> dict[str, list[dict[str, Any]]]:
        """逐功能点有界并发检索现有代码证据；单项失败 → 该项证据为空（不影响其余）。"""
        try:
            from services.code_intel import get_provider
            from services.retrieval import HybridSearchService

            service = HybridSearchService(get_provider())
        except Exception as exc:  # noqa: BLE001 — provider 不可用 → 全量无证据（不阻断）
            logger.warning(
                "feature_classify_provider_unavailable",
                category="sampling",
                component="process_runtime",
                error=str(exc),
            )
            return {feat["key"]: [] for feat in features}

        sem = asyncio.Semaphore(self.concurrency)

        async def _search_one(feat: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
            async with sem:
                query = " ".join(p for p in (feat.get("module"), feat.get("title")) if p)
                try:
                    result = await service.search(
                        query,
                        repository_ids=repository_ids,
                        top_k=self.top_k,
                        enable_graph_enrichment=False,
                    )
                except Exception as exc:  # noqa: BLE001 — 单项检索失败 → 空证据
                    logger.warning(
                        "feature_classify_evidence_search_failed",
                        category="sampling",
                        component="process_runtime",
                        error=str(exc),
                    )
                    return feat["key"], []
                return feat["key"], self._extract_hits(result)

        pairs = await asyncio.gather(
            *(_search_one(feat) for feat in features), return_exceptions=True
        )
        evidence: dict[str, list[dict[str, Any]]] = {feat["key"]: [] for feat in features}
        for pair in pairs:
            if isinstance(pair, BaseException) or not isinstance(pair, tuple):
                continue
            key, hits = pair
            evidence[key] = hits
        return evidence

    def _extract_hits(self, result: Any) -> list[dict[str, Any]]:
        """从检索结果的 L3 层抽取精简证据（对齐 MCP search_rag_chunks 的提取方式）。"""
        hits: list[dict[str, Any]] = []
        for layer in getattr(result, "layers", []) or []:
            if getattr(layer, "layer", None) != "L3":
                continue
            for item in getattr(layer, "items", []) or []:
                if not isinstance(item, dict):
                    continue
                payload = item.get("payload", {}) or {}
                file_path = str(payload.get("file_path", "") or "").strip()
                if not file_path:
                    continue
                hits.append(
                    {
                        "repository_id": str(item.get("repository_id", "") or ""),
                        "file_path": file_path,
                        "symbol": str(payload.get("symbol_name", "") or ""),
                        "score": item.get("score", 0.0),
                    }
                )
        return hits[: self.top_k]

    # ------------------------------------------------------------------ 映射

    @staticmethod
    def _merge_feature_meta(
        items: list[dict[str, Any]], features: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """回填 module / name 元信息，并补齐 LLM 漏判的功能点（漏判按 unclear 计）。

        LLM 可能少输出若干项；漏掉的功能点补 ``unclear`` 而非静默丢弃——否则这些功能点
        会在方案里凭空消失。
        """
        by_key = {item["key"]: item for item in items}
        merged: list[dict[str, Any]] = []
        for feat in features:
            item = by_key.get(feat["key"]) or {
                "key": feat["key"],
                "change_type": "unclear",
                "confidence": "low",
                "target_repo_id": "",
                "reason": "分类结果缺失，待人工确认",
                "evidence_files": [],
                "suggested_location": "",
            }
            merged.append({**item, "module": feat["module"], "name": feat["title"]})
        return merged
