"""DeliveryKnowledgeRecallAdapter —— recalling stage 真实实现（RECALL-01）。

把编排 `recalling` 阶段的骨架 `SkeletonRecall` 替换为复用既有
`DeliveryKnowledgeSearchService.search_similar`（向量召回 + 图扩散 + 时间衰减 +
fail-closed 权限过滤）的 adapter：召回相似需求/缺陷/复盘/技术方案，映射为精简命中
列表供 engine 经 `transition(recall_context=)` 落 `ConvergenceSession.recall_context`。

本 adapter **不重写检索逻辑**——只做编排接线（取数 + entity_kinds 映射 + 权限 actor
透传 + 结果映射）。权限 fail-closed：`session.created_by` 为 None 时直接透传（绝不
伪造/提权 actor），search_similar 经 `resolve_allowed_project_ids(None)` 返回 [] →
空召回，不泄漏越权数据。检索任何异常 → best-effort 空召回（不阻断编排）。
"""

from __future__ import annotations

import structlog
from asgiref.sync import sync_to_async

from delivery.models import ConvergenceSession
from knowledge.models import EntityKind

logger = structlog.get_logger(__name__)

__all__ = ["DeliveryKnowledgeRecallAdapter", "RECALL_ENTITY_KINDS"]

# entity_kinds 映射：相似需求/缺陷/复盘 → work_item（缺陷/复盘归 work_item 类）；
# 技术方案 → tech_plan；代码变更 → code_change。对齐 knowledge.EntityKind 实际枚举
# （work_item/tech_plan/code_change/document），document 本阶段不召回。
RECALL_ENTITY_KINDS = [
    EntityKind.WORK_ITEM,
    EntityKind.TECH_PLAN,
    EntityKind.CODE_CHANGE,
]


class DeliveryKnowledgeRecallAdapter:
    """历史/相似召回 stage 依赖的真实实现（满足 RecallProtocol，RECALL-01）。"""

    def __init__(self, *, top_k: int = 10) -> None:
        # top_k 召回命中上限（对齐 38-CONTEXT 默认 10）
        self.top_k = top_k

    async def recall(self, session: ConvergenceSession) -> dict:
        """召回相似需求/缺陷/复盘/技术方案，返回 `{hits, query, kinds}`。

        空 query → 直接返回空 hits，不调检索。`repository_ids` 用路由候选仓收窄召回。
        actor 经 ``_resolve_actor``（``created_by_id`` 短路/同步 ORM 经 sync_to_async）解析
        —— **绝不在 async 上下文懒加载 FK**（否则触发 SynchronousOnlyOperation）。actor 解析
        与检索同处一个 try/except：任何异常（含 actor 解析失败）→ log warning + 空 hits
        （best-effort 不阻断编排，守 RECALL-01：召回失败返回空、不冒泡破坏编排）。
        """
        kinds = [str(k) for k in RECALL_ENTITY_KINDS]
        query = (session.decomposition or {}).get("requirement_text", "")
        if not query:
            return {"hits": [], "query": "", "kinds": kinds}

        candidates = (session.routing or {}).get("candidates")
        repository_ids = (
            [c["repo_id"] for c in candidates if c.get("repo_id")] if candidates else None
        )

        try:
            from knowledge.retrieval import DeliveryKnowledgeSearchService

            user = await self._resolve_actor(session)
            results = await DeliveryKnowledgeSearchService().search_similar(
                query,
                user=user,
                top_k=self.top_k,
                entity_kinds=kinds,
                repository_ids=repository_ids,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort：召回失败不阻断编排
            logger.warning(
                "plan_recall_search_failed", session_id=str(session.id), error=str(exc)
            )
            return {"hits": [], "query": query, "kinds": kinds}

        hits = [self._map_hit(r) for r in results]
        return {"hits": hits, "query": query, "kinds": kinds}

    @sync_to_async
    def _resolve_actor(self, session: ConvergenceSession):
        """同步解析发起人 actor（召回权限 user）经 sync_to_async 桥接。

        ``created_by_id`` 为空时 Django 短路返回 None（不查库，fail-closed 不伪造 actor）；
        非空则同步 ORM 取关联 User —— 镜像 ``RepoRouterV2Adapter._project_repository_ids``
        的 async ORM 范式，避免在 async 事件循环内懒加载 FK 触发 SynchronousOnlyOperation。
        """
        return session.created_by

    @staticmethod
    def _map_hit(result) -> dict:
        """SearchResultDTO 精简映射为 {entity_id, kind, title, score}（getattr 防御）。"""
        entity = getattr(result, "entity", None)
        return {
            "entity_id": str(getattr(entity, "entity_id", "") or ""),
            "kind": getattr(entity, "entity_kind", "") or "",
            "title": getattr(entity, "title", "") or "",
            "score": getattr(result, "score", 0.0) or 0.0,
        }
