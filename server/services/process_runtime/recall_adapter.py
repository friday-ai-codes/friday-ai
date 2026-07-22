"""DeliveryKnowledgeRecallAdapter —— recalling stage 真实实现（RECALL-01 / KNOW-04）。

把编排 `recalling` 阶段的骨架 `SkeletonRecall` 替换为复用既有
`DeliveryKnowledgeSearchService.search_similar`（向量召回 + 图扩散 + 时间衰减 +
fail-closed 权限过滤）的 adapter：召回相似需求/缺陷/复盘/技术方案/项目沉淀/历史经验，
映射为精简命中列表供 engine 经 `transition(recall_context=)` 落
`ConvergenceSession.recall_context`。

本 adapter **不重写检索逻辑**——只做编排接线（取数 + entity_kinds 映射 + 权限 actor
透传 + 结果映射）。权限 fail-closed：`session.created_by` 为 None 时直接透传（绝不
伪造/提权 actor），search_similar 经 `resolve_allowed_project_ids(None)` 返回 [] →
空召回，不泄漏越权数据。检索任何异常 → best-effort 空召回（不阻断编排）。

KNOW-04：召回 kinds 与每 kind 限额运行时经 Django settings 读取
（`PROCESS_RECALL_ENTITY_KINDS` / `PROCESS_RECALL_KIND_LIMITS`，env 可覆盖），
默认扩为 5 kinds（+ document/learning_case，默认开）。
"""

from __future__ import annotations

import structlog
from asgiref.sync import sync_to_async

from delivery.models import ConvergenceSession
from knowledge.models import EntityKind

logger = structlog.get_logger(__name__)

__all__ = ["DeliveryKnowledgeRecallAdapter", "RECALL_ENTITY_KINDS"]

# 召回实体 kinds 的**默认值常量**（KNOW-04）——运行时以 settings 为准
# （`PROCESS_RECALL_ENTITY_KINDS`，recall() 调用时读取，保证 override_settings 可测、
# 部署改 env 即生效）。相似需求/缺陷/复盘 → work_item；技术方案 → tech_plan；
# 代码变更 → code_change；项目沉淀 → document（召回需 include_document_kind=True）；
# 历史经验 → learning_case（Phase 100 新增 kind）。
RECALL_ENTITY_KINDS = [
    EntityKind.WORK_ITEM,
    EntityKind.TECH_PLAN,
    EntityKind.CODE_CHANGE,
    EntityKind.DOCUMENT,
    EntityKind.LEARNING_CASE,
]

# 每 kind 召回上限默认值（KNOW-04 locked）——运行时以 settings
# `PROCESS_RECALL_KIND_LIMITS` 为准；未配置的 kind 上限用 _DEFAULT_KIND_LIMIT 兜底。
_DEFAULT_KIND_LIMITS = {
    "work_item": 4,
    "tech_plan": 4,
    "code_change": 4,
    "document": 3,
    "learning_case": 3,
}
_DEFAULT_KIND_LIMIT = 3


class DeliveryKnowledgeRecallAdapter:
    """历史/相似召回 stage 依赖的真实实现（满足 RecallProtocol，RECALL-01）。"""

    def __init__(self, *, top_k: int = 10) -> None:
        # top_k 语义（KNOW-04 调整）：最终 hits 总数的「上限兜底」——
        # 总数不超过 max(top_k, sum(每 kind 限额))，不破坏既有无参构造方。
        self.top_k = top_k

    async def recall(self, session: ConvergenceSession) -> dict:
        """召回相似需求/缺陷/复盘/技术方案/项目沉淀/历史经验，返回 `{hits, query, kinds}`。

        空 query → 直接返回空 hits，不调检索。`repository_ids` 用路由候选仓收窄召回。
        actor 经 ``_resolve_actor``（``created_by_id`` 短路/同步 ORM 经 sync_to_async）解析
        —— **绝不在 async 上下文懒加载 FK**（否则触发 SynchronousOnlyOperation）。actor 解析
        与检索同处一个 try/except：任何异常（含 actor 解析失败）→ log warning + 空 hits
        （best-effort 不阻断编排，守 RECALL-01：召回失败返回空、不冒泡破坏编排）。

        KNOW-04 取舍已定：**单查后按 kind 截断**，不分 kind 多次查询——每次
        ``search_similar`` 是 embedding + sparse encode + Qdrant 查询的完整成本，
        5 kinds 分查 5 倍成本且跨查 score 出自不同排序不可比；单查所有 score 出自
        同一 RRF 融合排序，排序一致性好。top_k 按 sum(每 kind 限额)*2 超采样，
        给按 kind 截断留余量；总量守 token 预算（防召回候选集膨胀）。
        """
        from django.conf import settings

        kinds = [
            str(k) for k in getattr(settings, "PROCESS_RECALL_ENTITY_KINDS", RECALL_ENTITY_KINDS)
        ]
        limits_cfg = getattr(settings, "PROCESS_RECALL_KIND_LIMITS", _DEFAULT_KIND_LIMITS)
        limits = {kind: int(limits_cfg.get(kind, _DEFAULT_KIND_LIMIT)) for kind in kinds}

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
                # 超采样 2 倍给按 kind 截断留余量（KNOW-04）
                top_k=sum(limits.values()) * 2,
                entity_kinds=kinds,
                repository_ids=repository_ids,
                # vector_recall 严格「传入 ∩ 白名单」过滤：不传该 flag 则 document
                # kind 永远召不回，必须按 kinds 动态传（KNOW-04）
                include_document_kind=("document" in kinds),
            )
        except Exception as exc:  # noqa: BLE001 — best-effort：召回失败不阻断编排
            logger.warning("plan_recall_search_failed", session_id=str(session.id), error=str(exc))
            return {"hits": [], "query": query, "kinds": kinds}

        hits = self._truncate_per_kind([self._map_hit(r) for r in results], limits=limits)
        return {"hits": hits, "query": query, "kinds": kinds}

    def _truncate_per_kind(self, hits: list[dict], *, limits: dict[str, int]) -> list[dict]:
        """按 kind 分桶截断（KNOW-04 token 预算守卫）。

        输入 hits 已按融合分降序（search_similar 保证）；顺序遍历、每 kind 保留至多
        limits[kind] 条（未知 kind 上限用 _DEFAULT_KIND_LIMIT 兜底），天然保持原
        score 降序输出。最终总数不超过 max(self.top_k, sum(limits))（上限兜底）。
        """
        total_cap = max(self.top_k, sum(limits.values()))
        kept: list[dict] = []
        per_kind_counts: dict[str, int] = {}
        for hit in hits:
            kind = hit["kind"]
            if per_kind_counts.get(kind, 0) >= limits.get(kind, _DEFAULT_KIND_LIMIT):
                continue
            per_kind_counts[kind] = per_kind_counts.get(kind, 0) + 1
            kept.append(hit)
            if len(kept) >= total_cap:
                break
        return kept

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
