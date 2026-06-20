"""检索结果重排（reorder）编排 —— 接在 RAG 召回卡点之后的精排阶段。

设计目标：
- **单一卡点**：仅由 ``search_rag`` 在召回去重排序后调用一次，对话 / Agent /
  工作流全链路统一生效。
- **业务降级**：无 rerank 模型时走 model-free 的启发式重排（``_heuristic_reorder``），
  比纯向量分数排序更准；有 rerank 模型时调外部 API 精排，**失败即回退启发式**。
- **fail-open**：任何配置读取 / 模型调用异常都不得让检索崩溃；最坏情况返回
  按原始 score 截断的结果（与未接入前行为一致）。

注意：本模块不读 codegraph 启用开关（per Pitfall 5），纯粹对已召回的候选做
重排序，不参与召回/图谱启停决策。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import structlog

logger = structlog.get_logger(__name__)


# 启发式默认开启（业务降级常驻）；模型重排默认关闭，配了 API 才启用。
DEFAULT_FETCH_K: int = 50
_MIN_FETCH_K: int = 10
_MAX_FETCH_K: int = 200

# 查询分词：保留标识符风格 token（字母/数字/下划线），过滤过短与停用词。
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "of", "to", "in", "on", "for", "and", "or",
    "how", "what", "where", "when", "which", "code", "function", "method",
    "class", "def", "use", "used", "using", "implement", "implementation",
    "的", "了", "在", "是", "和", "与", "怎么", "如何", "哪里", "代码", "实现", "函数",
})


@dataclass(frozen=True)
class RerankPlan:
    """一次检索的重排计划（由 ``get_rerank_plan`` 从系统设置解析得到）。"""

    mode: Literal["model", "heuristic", "off"]
    fetch_k: int
    model: str | None = None


async def get_rerank_plan() -> RerankPlan:
    """从系统设置解析重排计划；任何异常一律降级为安全默认（不抛）。

    决策优先级：
    1. ``RERANKER_ENABLED`` + 已配 ``RERANKER_API_URL`` → ``mode="model"``。
    2. 否则 ``HEURISTIC_RERANK_ENABLED``（缺省 True）→ ``mode="heuristic"``。
    3. 二者皆否 → ``mode="off"``（保持原始 score 截断，byte-equivalent）。
    """
    try:
        from services.reranker import RerankerService
        from system.models import SettingKeys, SystemSetting

        config = await RerankerService.get_config()
        if config.get("enabled") and config.get("api_url"):
            fetch_k = await _read_fetch_k()
            return RerankPlan(mode="model", fetch_k=fetch_k, model=config.get("model"))

        heuristic = await SystemSetting.objects.filter(
            key=SettingKeys.HEURISTIC_RERANK_ENABLED
        ).afirst()
        # 缺省 True：未配置 setting 时即视为开启（业务降级常驻）。
        heuristic_on = heuristic.value == "true" if heuristic and heuristic.value else (
            heuristic is None
        )
        if heuristic_on:
            return RerankPlan(mode="heuristic", fetch_k=DEFAULT_FETCH_K)
        return RerankPlan(mode="off", fetch_k=DEFAULT_FETCH_K)
    except Exception as exc:  # noqa: BLE001 — 配置读取失败一律 fail-open，不影响检索
        logger.warning("rerank_plan_read_failed", error=str(exc))
        return RerankPlan(mode="off", fetch_k=DEFAULT_FETCH_K)


async def _read_fetch_k() -> int:
    from system.models import SettingKeys, SystemSetting

    setting = await SystemSetting.objects.filter(key=SettingKeys.RERANK_FETCH_K).afirst()
    if not setting or not setting.value:
        return DEFAULT_FETCH_K
    try:
        return max(_MIN_FETCH_K, min(_MAX_FETCH_K, int(setting.value)))
    except (TypeError, ValueError):
        return DEFAULT_FETCH_K


async def reorder(
    query: str,
    items: list[dict[str, Any]],
    *,
    top_k: int,
    plan: RerankPlan | None = None,
    out_meta: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """对召回候选重排并截断到 ``top_k``。

    Args:
        query: 查询文本（非可信输入）。
        items: 召回候选（已按原始 score 降序），每项含 ``payload`` / ``score``。
        top_k: 最终返回条数。
        plan: 预解析的重排计划；None 时内部读取。
        out_meta: 可选输出字典；填入本次**实际生效**的重排信息（mode / model /
            candidates / returned / fallback_from），供上层展示与可观测。

    Returns:
        重排并截断后的候选列表。任何异常都回退为 ``items[:top_k]``。
    """
    if not items:
        return items
    if plan is None:
        plan = await get_rerank_plan()

    def _report(**kwargs: Any) -> None:
        if out_meta is not None:
            out_meta.update(kwargs)

    try:
        if plan.mode == "model":
            reranked = await _model_reorder(query, items, top_k=top_k)
            if reranked is not None:
                logger.info(
                    "rerank_applied", mode="model", candidates=len(items), returned=len(reranked)
                )
                _report(
                    mode="model",
                    model=plan.model,
                    candidates=len(items),
                    returned=len(reranked),
                )
                return reranked
            # 模型重排失败 → 回退启发式（fail-open）
            logger.warning("rerank_model_failed_fallback_heuristic", candidates=len(items))
            result = _heuristic_reorder(query, items)[:top_k]
            _report(
                mode="heuristic",
                fallback_from="model",
                candidates=len(items),
                returned=len(result),
            )
            return result
        if plan.mode == "heuristic":
            result = _heuristic_reorder(query, items)[:top_k]
            logger.info(
                "rerank_applied", mode="heuristic", candidates=len(items), returned=len(result)
            )
            _report(mode="heuristic", candidates=len(items), returned=len(result))
            return result
        logger.debug("rerank_skipped", mode="off", candidates=len(items))
        _report(mode="off", candidates=len(items), returned=min(top_k, len(items)))
        return items[:top_k]
    except Exception as exc:  # noqa: BLE001 — 重排异常绝不影响检索主线
        logger.warning("rerank_reorder_failed", error=str(exc), mode=plan.mode)
        return items[:top_k]


async def _model_reorder(
    query: str,
    items: list[dict[str, Any]],
    *,
    top_k: int,
) -> list[dict[str, Any]] | None:
    """调外部 Reranker API 精排；失败/空结果返回 None 让调用方降级。"""
    from services.reranker import RerankerService

    documents = [str(it.get("payload", {}).get("content", "")) for it in items]
    results = await RerankerService.rerank(query, documents, top_n=top_k)
    if not results:
        return None

    reordered: list[dict[str, Any]] = []
    seen: set[int] = set()
    for r in results:
        idx = r.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(items) or idx in seen:
            continue
        seen.add(idx)
        entry = dict(items[idx])
        entry["score"] = r.get("relevance_score", entry.get("score", 0.0))
        entry["rerank_score"] = r.get("relevance_score")
        reordered.append(entry)

    if not reordered:
        return None
    return reordered[:top_k]


def _tokenize(text: str) -> list[str]:
    return [
        t.lower()
        for t in _TOKEN_RE.findall(text)
        if len(t) >= 2 and t.lower() not in _STOPWORDS
    ]


def _heuristic_reorder(
    query: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """model-free 启发式重排：在原始向量分数基础上叠加词法信号。

    信号（均为 0..1 量级，权重保守，使原始相关性仍占主导）：
    - 精确标识符匹配：query token 作为完整词出现在 chunk 内容里（代码检索最有效）。
    - 查询词覆盖率：命中 query token 的比例。
    - 路径相关性：query token 出现在文件路径里。
    - 定义优先：chunk 含 def/class/function/func 等定义关键字。
    - 短内容惩罚：过短 chunk（多为样板）轻微降权。

    base 用 min-max 归一化后的原始 score（跨仓可比），稳定排序保证同分有序。
    """
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        # 无有效 query token → 不引入噪声，保持原序
        return list(items)

    scores = [float(it.get("score", 0.0)) for it in items]
    lo, hi = min(scores), max(scores)
    span = (hi - lo) or 1.0

    def signal_score(item: dict[str, Any]) -> float:
        payload = item.get("payload", {})
        content = str(payload.get("content", ""))
        file_path = str(payload.get("file_path", ""))
        content_tokens = set(_tokenize(content))
        path_tokens = set(_tokenize(file_path))

        if not content_tokens:
            coverage = 0.0
            exact = 0.0
        else:
            hit = query_tokens & content_tokens
            coverage = len(hit) / len(query_tokens)
            # 精确标识符匹配：命中即给较高权重（代码符号场景关键）
            exact = 1.0 if hit else 0.0

        path_hit = 1.0 if (query_tokens & path_tokens) else 0.0

        lowered = content[:2000].lower()
        definition = 1.0 if any(
            kw in lowered for kw in ("def ", "class ", "function ", "func ")
        ) else 0.0

        short_penalty = 1.0 if len(content) < 60 else 0.0

        return (
            0.18 * exact
            + 0.12 * coverage
            + 0.06 * path_hit
            + 0.04 * definition
            - 0.05 * short_penalty
        )

    def blended(idx: int, item: dict[str, Any]) -> float:
        base = (float(item.get("score", 0.0)) - lo) / span
        return base + signal_score(item)

    # 稳定排序：负的混合分作为主键，原始下标作为次键保稳定性
    indexed = list(enumerate(items))
    indexed.sort(key=lambda pair: (-blended(pair[0], pair[1]), pair[0]))
    return [item for _, item in indexed]


__all__ = ["RerankPlan", "get_rerank_plan", "reorder"]
