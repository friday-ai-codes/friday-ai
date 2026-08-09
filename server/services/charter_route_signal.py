"""仓库路由的章程分量 —— AI 对话 / MCP 两条链复用的意图面接线（CHARTER-01）。

**为什么需要**：blueprint 链在 `services/process_runtime/blueprint_route.py` 的 adapter
层做「能力树 + 章程 + 历史」三分量加权融合，而对话工具（`analyze_repository_relevance`）
与 MCP（`route_repositories`）此前**完全不读章程**——用户在对话里问「这个功能该放哪个
仓」，拿到的只有能力树的事实面（这个仓现在有什么），拿不到意图面（这个仓该放什么、
不放什么）。本模块把同一套**纯函数**打分（`score_charter_match`）与候选补入
（`acollect_charter_candidates`）包成一个**与会话解耦**的入口给这两条链复用。

**§13.2 冻结面**：`codegraph/services/repo_router_v2.py` 零改动、只调不改；章程证据
也绝不进它的 Stage1 prompt。融合一律在调用方拿到 router 结果之后做。

**候选补入**才是这里最实在的收益：能力树没索引到、但章程 `owned_domains` 明确写了
「这块归我」的仓，路由器永远召不回——补入让它至少能以低置信度进候选。

**best-effort**：章程读失败 / 打分异常一律退化为「无章程分量」（原样返回 router 排序），
绝不阻断路由。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)

__all__ = [
    "CharterSignalItem",
    "aapply_charter_signal",
    "resolve_charter_weight",
    "DEFAULT_CHARTER_WEIGHT",
]

_COMPONENT = "services"

# 章程分量默认权重（可经 settings.REPO_ROUTE_CHARTER_WEIGHT 覆盖）。
# 取值参考 blueprint 的 brownfield 档（0.20）略上浮：对话链的 query 通常比蓝图的
# 需求规格短，能力树信号更噪，意图面值得多一点话语权；但仍让 router_base 主导。
DEFAULT_CHARTER_WEIGHT = 0.25
# 补入候选上限：章程命中但能力树未召回的仓，多了会淹没真正的代码证据。
DEFAULT_SUPPLEMENT_LIMIT = 3


@dataclass(frozen=True)
class CharterSignalItem:
    """单仓的章程分量结果（`blended_score` 已是最终排序依据）。"""

    repository_id: str
    repository_name: str
    router_score: float
    charter_score: float
    blended_score: float
    matched_domains: list[str] = field(default_factory=list)
    violated_boundaries: list[str] = field(default_factory=list)
    charter_source: str = ""
    charter_version: int = 0
    is_supplement: bool = False

    @property
    def evidence(self) -> str:
        """人类可读的一行章程证据（无章程信号时为空串，调用方据此决定是否拼接）。"""
        parts: list[str] = []
        if self.matched_domains:
            parts.append(f"章程声明拥有：{' / '.join(self.matched_domains[:3])}")
        if self.violated_boundaries:
            parts.append(f"⚠ 触及章程边界禁区：{' / '.join(self.violated_boundaries[:2])}")
        if self.is_supplement and not parts:
            parts.append("章程领域命中（能力树未召回）")
        if parts and self.charter_source == "ai_draft":
            parts.append("（章程为 AI 草案，未经人工确认）")
        return "；".join(parts)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _labels(values) -> list[str]:
    """章程列表项 → 展示用字符串。

    `owned_domains` / `boundaries` 的元素是 dict（`{"domain":...,"status":...}` /
    `{"rule":...}`），`acollect_charter_candidates` 的 `matched_domains` 则可能已是
    纯字符串——两种形状都要能拼进 evidence，否则 `join` 会直接抛 TypeError。
    """
    out: list[str] = []
    for value in values or []:
        if isinstance(value, dict):
            text = str(value.get("domain") or value.get("rule") or "").strip()
        else:
            text = str(value).strip()
        if text:
            out.append(text)
    return out


def resolve_charter_weight() -> float:
    """章程分量权重（调用时读 settings，保证 `override_settings` 可测、改 env 即生效）。

    章程分以此权重**加到** router 分上（见 `aapply_charter_signal`），调用方若另有
    排序键（如 `score_ranked`）需用同一权重做同样的加性调整才不会与 score 打架。
    """
    try:
        raw = getattr(settings, "REPO_ROUTE_CHARTER_WEIGHT", DEFAULT_CHARTER_WEIGHT)
        return _clamp01(float(raw))
    except (TypeError, ValueError):
        return DEFAULT_CHARTER_WEIGHT


async def aapply_charter_signal(
    *,
    query: str,
    candidates: list[tuple[str, str, float]],
    repository_ids: list[str] | None = None,
    supplement_limit: int = DEFAULT_SUPPLEMENT_LIMIT,
) -> list[CharterSignalItem]:
    """给 router 候选叠加章程分量，并补入「章程命中但能力树未召回」的仓。

    Args:
        query: 用户原始 query（直接当单个 query term 用——`score_charter_match` 的
            `_matches` 对无分隔符长句走 CJK 3-gram 交集，不需要外部分词）。
        candidates: `[(repository_id, repository_name, router_score), ...]`，router 原样输出。
        repository_ids: 限定扫描范围（None = 全库，对话链的 global 分区需要）。
        supplement_limit: 补入候选上限，`<= 0` 关闭补入。

    Returns:
        按 `blended_score` 降序的 `CharterSignalItem` 列表；入参候选恒在结果中出现
        （章程读失败时 `charter_score=0` 且 `blended_score=router_score`）。
    """
    items: list[CharterSignalItem] = []
    base = [
        (str(rid), str(name or ""), float(score or 0.0))
        for rid, name, score in (candidates or [])
        if str(rid or "").strip()
    ]
    if not str(query or "").strip():
        return [
            CharterSignalItem(
                repository_id=rid,
                repository_name=name,
                router_score=score,
                charter_score=0.0,
                blended_score=score,
            )
            for rid, name, score in base
        ]

    started = time.perf_counter()
    weight = resolve_charter_weight()
    query_terms = [query]
    supplement_count = 0

    try:
        from services.process_runtime.blueprint_charter_match import (
            acollect_charter_candidates,
            aload_charters,
            score_charter_match,
        )

        charters = await aload_charters([rid for rid, _, _ in base])
        for rid, name, router_score in base:
            result = score_charter_match(charters.get(rid), query_terms=query_terms)
            items.append(
                CharterSignalItem(
                    repository_id=rid,
                    repository_name=name,
                    router_score=router_score,
                    charter_score=result.score,
                    # ⭐ 加性调整而非凸组合：凸组合会把**没有章程**的仓整体 ×(1-weight)，
                    # 等于把「没写章程」当成负分——而无章程只是无证据（`score_charter_match`
                    # 对此显式返回 0 + `no_charter`）。加性下无章程恒等于原分；
                    # owned_domains 命中加分，禁区命中（章程分为负）扣分。
                    blended_score=_clamp01(router_score + result.score * weight),
                    matched_domains=_labels(result.matched_domains),
                    violated_boundaries=_labels(result.violated_boundaries),
                    charter_source=result.charter_source,
                    charter_version=result.charter_version,
                )
            )

        if supplement_limit > 0:
            collected = await acollect_charter_candidates(
                query_terms=query_terms,
                exclude_repository_ids={rid for rid, _, _ in base},
                repository_ids=repository_ids,
                limit=supplement_limit,
            )
            for row in collected or []:
                rid = str(row.get("repository_id") or "")
                if not rid:
                    continue
                charter_score = float(row.get("charter_match_raw") or 0.0)
                items.append(
                    CharterSignalItem(
                        repository_id=rid,
                        repository_name=str(row.get("repository_name") or ""),
                        # 能力树未召回 → router_base 恒 0，排序差异完全归因章程分量
                        router_score=0.0,
                        charter_score=charter_score,
                        blended_score=_clamp01(charter_score * weight),
                        matched_domains=_labels(row.get("matched_domains")),
                        is_supplement=True,
                    )
                )
                supplement_count += 1
    except Exception as exc:  # noqa: BLE001 — best-effort：章程失效退化为纯 router 排序
        from common.logging import redact_secrets_in_text

        logger.warning(
            "charter_route_signal_failed",
            candidate_count=len(base),
            error=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            category="sampling",
            component=_COMPONENT,
        )
        return [
            CharterSignalItem(
                repository_id=rid,
                repository_name=name,
                router_score=score,
                charter_score=0.0,
                blended_score=score,
            )
            for rid, name, score in base
        ]

    items.sort(key=lambda i: (-i.blended_score, i.repository_id))
    logger.info(
        "charter_route_signal_completed",
        candidate_count=len(base),
        supplement_count=supplement_count,
        matched_count=sum(1 for i in items if i.matched_domains),
        boundary_hit_count=sum(1 for i in items if i.violated_boundaries),
        weight=weight,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        category="sampling",
        component=_COMPONENT,
    )
    return items
