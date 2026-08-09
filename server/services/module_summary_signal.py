"""仓库路由的模块摘要 evidence —— AI 对话 / MCP 两条链复用（MOD-04 / D-15）。

**为什么需要**：社区检测产出的「关键文件 / 入口 / 职责」摘要回答「这个仓有哪些
模块职责」。对话工具与 MCP ``route_repositories`` 此前完全不读这些摘要——本模块
把仓级 ``SymbolCommunity.summary`` 以 **evidence / reason 文本追加**的方式喂给
调用方，**默认不改 router_base 分数、不加新权重键**。

**§13.2 冻结面**：``codegraph/services/repo_router_v2.py`` 零改动、只调不改；
摘要证据也绝不进它的 Stage1 prompt。融合一律在调用方拿到 router 结果之后做。

**best-effort**：摘要读失败 / 打分异常一律退化为「无模块摘要分量」（原样返回
router 排序），绝不阻断路由。v1 **不做候选补入**。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import structlog
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)

__all__ = [
    "ModuleSummarySignalItem",
    "aapply_module_summary_signal",
    "aload_module_summaries_for_repos",
    "score_summary_relevance",
    "DEFAULT_TOP_N",
]

_COMPONENT = "services"

# 单仓注入社区数上限（展示 / evidence）；超限按相关度截断。
DEFAULT_TOP_N = 5
# evidence 行单条责任文本上限（防刷屏）。
_MAX_RESPONSIBILITY_CHARS = 160


@dataclass(frozen=True)
class ModuleSummarySignalItem:
    """单仓模块摘要信号（``blended_score`` 恒等于 ``router_score`` —— D-15 不改分）。"""

    repository_id: str
    repository_name: str
    router_score: float
    evidence: str = ""

    @property
    def blended_score(self) -> float:
        return self.router_score


def score_summary_relevance(query: str, text: str) -> float:
    """query↔摘要文本轻量相关度（0..1）：CJK bigram + 空白分词重叠。"""
    q = (query or "").strip().lower()
    t = (text or "").strip().lower()
    if not q or not t:
        return 0.0
    q_tokens = _tokens(q)
    t_tokens = _tokens(t)
    if not q_tokens or not t_tokens:
        return 0.0
    overlap = len(q_tokens & t_tokens)
    return min(1.0, overlap / max(1, len(q_tokens)))


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for part in re.split(r"\s+", text):
        part = part.strip()
        if not part:
            continue
        if re.search(r"[\u4e00-\u9fff]", part):
            if len(part) >= 2:
                out.update(part[i : i + 2] for i in range(len(part) - 1))
            else:
                out.add(part)
        else:
            # 拉丁词：长度 ≥2 才计入，避免单字母噪声
            if len(part) >= 2:
                out.add(part)
    return out


def _responsibility_from_summary(summary: str) -> str:
    text = (summary or "").strip()
    if not text:
        return ""
    if text.startswith("{"):
        try:
            import json

            data = json.loads(text)
            if isinstance(data, dict):
                return str(data.get("responsibility") or "").strip()
        except Exception:  # noqa: BLE001 — 解析失败走整段截断
            pass
    return text[:_MAX_RESPONSIBILITY_CHARS]


def _row_to_item(row, *, query: str) -> dict | None:
    """ORM 行 → 消费端 dict；无有效 summary 返回 None。"""
    summary = (getattr(row, "summary", None) or "").strip()
    if not summary:
        return None
    responsibility = _responsibility_from_summary(summary)
    from services.code_graph.module_summary import render_module_summary

    rendered = render_module_summary(summary)
    text_for_score = f"{responsibility} {rendered}"
    return {
        "community_key": str(getattr(row, "community_key", "") or ""),
        "text": rendered,
        "responsibility": responsibility,
        "relevance": score_summary_relevance(query, text_for_score),
        "member_count": int(getattr(row, "member_count", 0) or 0),
    }


async def aload_module_summaries_for_repos(
    repository_ids: list[str],
    *,
    branch_name: str = "",
    query: str = "",
    limit_per_repo: int = DEFAULT_TOP_N,
) -> dict[str, list[dict]]:
    """批量加载仓模块摘要（branch 对齐；空/异常 → 该仓 []）。

    返回 ``{repository_id: [item, ...]}``，每项含 ``community_key`` / ``text`` /
    ``responsibility`` / ``relevance``，已按相关度降序截断。
    """
    ids = [str(rid).strip() for rid in (repository_ids or []) if str(rid or "").strip()]
    if not ids:
        return {}

    def _load() -> dict[str, list[dict]]:
        from codegraph.models import SymbolCommunity

        qs = SymbolCommunity.objects.filter(
            repository_id__in=ids,
            branch_name=branch_name or "",
        ).exclude(summary__isnull=True).exclude(summary="")
        by_repo: dict[str, list[dict]] = {rid: [] for rid in ids}
        for row in qs.iterator():
            rid = str(row.repository_id)
            item = _row_to_item(row, query=query)
            if item is None:
                continue
            by_repo.setdefault(rid, []).append(item)
        limit = max(0, int(limit_per_repo or 0))
        for rid, items in by_repo.items():
            items.sort(
                key=lambda i: (-float(i.get("relevance") or 0.0), -int(i.get("member_count") or 0))
            )
            by_repo[rid] = items[:limit] if limit else items
        return by_repo

    try:
        return await sync_to_async(_load, thread_sensitive=True)()
    except Exception as exc:  # noqa: BLE001 — fail-soft
        from common.logging import redact_secrets_in_text

        logger.warning(
            "module_summary_load_failed",
            repository_count=len(ids),
            error=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            category="sampling",
            component=_COMPONENT,
        )
        return {rid: [] for rid in ids}


def _format_evidence(items: list[dict]) -> str:
    parts: list[str] = []
    for item in items:
        key = str(item.get("community_key") or "").strip()
        resp = str(item.get("responsibility") or "").strip()
        if not resp:
            continue
        label = f"模块摘要[{key}]" if key else "模块摘要"
        parts.append(f"{label}：{resp[:_MAX_RESPONSIBILITY_CHARS]}")
    return "；".join(parts)


async def aapply_module_summary_signal(
    *,
    query: str,
    candidates: list[tuple[str, str, float]],
    branch_name: str = "",
    top_n: int = DEFAULT_TOP_N,
) -> list[ModuleSummarySignalItem]:
    """给 router 候选追加模块摘要 evidence；**不改分数**（D-15）。

    Args:
        query: 用户原始 query（用于相关度排序）。
        candidates: ``[(repository_id, repository_name, router_score), ...]``。
        branch_name: 社区行分支隔离（``""`` = 基线）。
        top_n: 单仓注入社区数上限。

    Returns:
        与入参候选一一对应的 ``ModuleSummarySignalItem``（顺序保持入参顺序）；
        失败时 evidence 为空、分数原样。
    """
    base = [
        (str(rid), str(name or ""), float(score or 0.0))
        for rid, name, score in (candidates or [])
        if str(rid or "").strip()
    ]
    if not base:
        return []

    started = time.perf_counter()
    try:
        by_repo = await aload_module_summaries_for_repos(
            [rid for rid, _, _ in base],
            branch_name=branch_name,
            query=query,
            limit_per_repo=top_n,
        )
        items: list[ModuleSummarySignalItem] = []
        matched = 0
        for rid, name, score in base:
            summaries = by_repo.get(rid) or []
            evidence = _format_evidence(summaries)
            if evidence:
                matched += 1
            items.append(
                ModuleSummarySignalItem(
                    repository_id=rid,
                    repository_name=name,
                    router_score=score,
                    evidence=evidence,
                )
            )
        logger.info(
            "module_summary_signal_completed",
            candidate_count=len(base),
            matched_count=matched,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            category="sampling",
            component=_COMPONENT,
        )
        return items
    except Exception as exc:  # noqa: BLE001 — best-effort
        from common.logging import redact_secrets_in_text

        logger.warning(
            "module_summary_signal_failed",
            candidate_count=len(base),
            error=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            category="sampling",
            component=_COMPONENT,
        )
        return [
            ModuleSummarySignalItem(
                repository_id=rid,
                repository_name=name,
                router_score=score,
            )
            for rid, name, score in base
        ]
