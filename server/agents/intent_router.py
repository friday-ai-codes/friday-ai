"""意图分类 + 相关性置信度判定 + 协商 payload 构造。

本模块提供 3 个**纯函数**，供 ``orchestration.graph`` 在 executing_node 入口
做 pre-routing 决策。所有函数：

- 不调 LLM / 不调 DB / 不调外部服务（保持 ≤ 1ms 量级）；
- 全部类型注解；
- 错误路径降级为安全默认值（不抛异常 → 不阻塞 chat 主流）。

接口契约与 :mod:`agents.tools.repository_relevance` 的 ``analyze_repository_
relevance`` 工具输出对齐 —— ``evaluate_relev_confidence`` 直接消费工具
``ToolResult.output["data"]`` 形态的 dict。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Literal

# implementation / 硬编码动词词典 —— **不进 Prompt Center**。
# 词典是代码硬约束，跟测试强耦合；运营层 polish 走 prompt 即可。
# 添加 / 删除词条必须同步更新 test_intent_router.py 的对应 case。
CODING_VERBS_ZH: Final[frozenset[str]] = frozenset({
    "实现", "修复", "修改", "改", "添加", "新增", "重构",
    "优化", "接入", "适配", "对接", "支持", "去掉", "删除",
    "替换", "升级", "迁移", "搭建", "集成",
})


CODING_VERBS_EN: Final[frozenset[str]] = frozenset({
    "implement", "fix", "add", "refactor", "optimize",
    "integrate", "support", "remove", "replace", "upgrade",
    "migrate",
})


# 低置信阈值常量 —— implementation 用固定值起步；evaluation phase（v27 候选）会
# 基于 trace 表（work item）+ RoutingTrace 表（work item）的真实数据 A/B 调优。
#
# coding-plan workflow hotfix #1（2026-05-21）：CONFIDENCE_GAP_MAX 从 0.7 → 0.92。
# 原值 0.7 在跨仓 HybridSearch 输出的多仓中度相关场景（典型 0.75-0.78 区间，
# top2/top1 ≈ 0.85-0.99）几乎必触发 low_confidence，把 graph 强制路由进
# WAITING_CLARIFICATION，吃掉 chat_runner 已流出的正文（详见
# project docs）。
#
# coding-plan workflow hotfix #2（2026-05-21，UAT 复测发现）：单 ratio 仍不够，需引入
# 绝对差 CONFIDENCE_ABS_GAP_MIN。
# 真实生产数据：top1=0.82, top2=0.78, ratio=0.95 → 旧逻辑判 low_confidence，
# 但绝对差 0.04（4 个百分点）已是清晰决策，不该强制澄清。
# 新逻辑：判 low_confidence 需要 **ratio > 0.92** AND **(top1 - top2) < 0.03** 同时成立 —
# 即"分数比例接近 且 绝对差距极小"才视作真正歧义。
# 兼容旧 case：top1=0.7765 / top2=0.7704（284 DEBUG 实测）ratio=0.992，
# 绝对差 0.0061 < 0.03 → 仍判 low_confidence ✓
CONFIDENCE_TOP1_MIN: Final[float] = 0.7
CONFIDENCE_GAP_MAX: Final[float] = 0.92      # top2 / top1 > 此值即"比例接近"
CONFIDENCE_ABS_GAP_MIN: Final[float] = 0.03  # top1 - top2 < 此值即"绝对差极小"


# 英文动词词边界匹配（避免误命中 "addendum" 之类）。
_EN_VERB_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(" + "|".join(re.escape(v) for v in CODING_VERBS_EN) + r")\b",
    re.IGNORECASE,
)


IntentConfidence = Literal["high", "low_signal", "ambiguous"]
TaskCategory = Literal[
    "coding_change",
    "needs_clarification",
    "feature_solution",
    "full_tech_plan",
]
KNOWN_TASK_CATEGORIES: Final[frozenset[str]] = frozenset({
    "coding_change",
    "needs_clarification",
    "feature_solution",
    "full_tech_plan",
})
_SOLUTION_INTENT_RE: Final[re.Pattern[str]] = re.compile(
    r"(技术方案|整体方案|(?:生成|创建|产出|制定).{0,8}方案|feature\s*list|全部.{0,12}模块)",
    re.IGNORECASE,
)


def normalize_task_category(raw: Any) -> TaskCategory | None:
    """把模型产生的 task_category 收口到服务端白名单。"""
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().lower()
    if normalized not in KNOWN_TASK_CATEGORIES:
        return None
    return normalized  # type: ignore[return-value]


def classify_solution_intent(
    message: str | None,
    *,
    bound_project_id: Any,
) -> TaskCategory | None:
    """识别项目级强方案意图；纯函数且不对弱编码请求作猜测。"""
    if not bound_project_id or not isinstance(message, str):
        return None
    if _SOLUTION_INTENT_RE.search(message.strip()):
        return "feature_solution"
    return None


@dataclass(frozen=True)
class IntentClassification:
    """``classify_intent`` 的返回类型。

    Attributes:
        is_coding_request: 命中任意编码动词即 True。
        matched_verbs: 命中的动词列表（保留原文，方便测试 / log 审计）。
        confidence: ``high``（明确命中 1-2 个）/ ``ambiguous``（命中 ≥ 3 个，
            堆砌词，建议澄清）/ ``low_signal``（0 命中，多半是问答）。
    """

    is_coding_request: bool
    matched_verbs: tuple[str, ...]
    confidence: IntentConfidence


def classify_intent(message: str | None) -> IntentClassification:
    """对用户消息做轻量「编码请求 vs 问答」分类。

    逻辑：
    - 中文动词：直接子串命中（``in``）—— 中文无空格分词，子串足够准。
    - 英文动词：词边界正则匹配。
    - 命中数 ≥ 3 → ``ambiguous``；命中数 1-2 → ``high``；命中数 0 → ``low_signal``。

    Args:
        message: 用户原始 user_message 文本；None / 非字符串 → 安全降级。

    Returns:
        ``IntentClassification`` 实例；空 message → ``low_signal``。
    """
    if not message or not isinstance(message, str):
        return IntentClassification(
            is_coding_request=False, matched_verbs=(), confidence="low_signal",
        )

    matched: list[str] = []
    # 中文：子串命中（保持原大小写敏感）
    for verb in CODING_VERBS_ZH:
        if verb in message:
            matched.append(verb)

    # 英文：词边界匹配（不区分大小写，但 normalize 后存原词）
    for m in _EN_VERB_RE.finditer(message):
        matched.append(m.group(1).lower())

    # 去重保序（matched 顺序对测试稳定性重要）
    seen: set[str] = set()
    unique: list[str] = []
    for v in matched:
        if v not in seen:
            seen.add(v)
            unique.append(v)

    count = len(unique)
    if count == 0:
        confidence: IntentConfidence = "low_signal"
    elif count >= 3:
        confidence = "ambiguous"
    else:
        confidence = "high"

    return IntentClassification(
        is_coding_request=count > 0,
        matched_verbs=tuple(unique),
        confidence=confidence,
    )


RelevLevel = Literal["high_confidence", "low_confidence", "missing"]


@dataclass(frozen=True)
class RelevConfidence:
    """``evaluate_relev_confidence`` 的返回类型。

    Attributes:
        level: ``high_confidence`` / ``low_confidence`` / ``missing``。
        top1_score: top candidate 的 score，工具未调或无 candidates 时 None。
        selected_repository_ids: candidates 中 ``selected_by_user_final=True``
            的 repository_id；high 置信场景下用作 ``create_coding_plan`` 的
            ``recommended_repository_ids`` 预填。
        plausible_alternatives: 前 5 个 candidates 精简 dict
            (id/name/score/evidence)，用于构造 ask_clarification 选项。
    """

    level: RelevLevel
    top1_score: float | None
    selected_repository_ids: tuple[str, ...]
    plausible_alternatives: tuple[dict[str, Any], ...]


def _unwrap_candidates(relev_output: dict[str, Any]) -> list[dict[str, Any]]:
    """支持两种输入形态：

    1. ``{"candidates": [...]}`` —— ``_analyze_relevance_core`` helper 直返。
    2. ``{"data": {"candidates": [...]}}`` —— ``ToolResult.output`` 完整形态
       （工具调用层封装）。

    返回 candidates list；任何异常 / 缺字段 → 空 list（让上层降级处理）。
    """
    if not isinstance(relev_output, dict):
        return []
    # 第一层：直接 candidates
    candidates = relev_output.get("candidates")
    if isinstance(candidates, list):
        return [c for c in candidates if isinstance(c, dict)]
    # 第二层：data.candidates
    data = relev_output.get("data")
    if isinstance(data, dict):
        nested = data.get("candidates")
        if isinstance(nested, list):
            return [c for c in nested if isinstance(c, dict)]
    return []


def evaluate_relev_confidence(
    relev_output: dict[str, Any] | None,
) -> RelevConfidence:
    """判定 ``analyze_repository_relevance`` 输出的置信度。

    输入支持两种形态：

    - ``{"candidates": [...]}``（``_analyze_relevance_core`` helper 直返）；
    - ``{"data": {"candidates": [...]}}``（``ToolResult.output`` 完整形态）。

    判定逻辑：
    - ``relev_output is None`` → ``missing``（工具尚未调用 / implementation 未实施）。
    - candidates 为空 → ``low_confidence``（没找到任何相关仓库 —— 应澄清）。
    - top1.score < ``CONFIDENCE_TOP1_MIN`` → ``low_confidence``。
    - top1 ≥ threshold 且 top2 / top1 > ``CONFIDENCE_GAP_MAX`` →
      ``low_confidence``（多个 plausible 分支，应澄清）。
    - 否则 → ``high_confidence``。
    """
    if relev_output is None:
        return RelevConfidence(
            level="missing",
            top1_score=None,
            selected_repository_ids=(),
            plausible_alternatives=(),
        )

    candidates_raw = _unwrap_candidates(relev_output)
    if not candidates_raw:
        return RelevConfidence(
            level="low_confidence",
            top1_score=None,
            selected_repository_ids=(),
            plausible_alternatives=(),
        )

    # 按 score 倒序（防工具未排序的边界情况）
    candidates = sorted(
        candidates_raw,
        key=lambda c: float(c.get("score", 0.0) or 0.0),
        reverse=True,
    )

    if not candidates:
        return RelevConfidence(
            level="low_confidence",
            top1_score=None,
            selected_repository_ids=(),
            plausible_alternatives=(),
        )

    top1 = float(candidates[0].get("score", 0.0) or 0.0)
    top2 = float(candidates[1].get("score", 0.0) or 0.0) if len(candidates) >= 2 else 0.0

    # selected_by_user_final 优先；fallback 到 selected_by_ai（工具未走人工
    # override 路径时只有 ai 字段）—— 两者其一为 True 即视作"已确定仓库"。
    selected_ids = tuple(
        str(c.get("repository_id", ""))
        for c in candidates
        if (
            c.get("selected_by_user_final") is True
            or c.get("selected_by_ai") is True
        ) and c.get("repository_id")
    )

    plausible = tuple(
        {
            "repository_id": str(c.get("repository_id", "")),
            "repository_name": str(c.get("repository_name", "")),
            "score": float(c.get("score", 0.0) or 0.0),
            "evidence": str(c.get("evidence", "")),
        }
        for c in candidates[:5]
    )

    if top1 < CONFIDENCE_TOP1_MIN:
        level: RelevLevel = "low_confidence"
    elif (
        top1 > 0
        and (top2 / top1) > CONFIDENCE_GAP_MAX
        and (top1 - top2) < CONFIDENCE_ABS_GAP_MIN
    ):
        # 仅当比例接近 AND 绝对差极小才算真歧义（coding-plan workflow hotfix #2）
        level = "low_confidence"
    else:
        level = "high_confidence"

    return RelevConfidence(
        level=level,
        top1_score=top1,
        selected_repository_ids=selected_ids,
        plausible_alternatives=plausible,
    )


def build_clarification_from_relev(
    relev_output: dict[str, Any],
    triggering_query: str,
) -> dict[str, Any]:
    """从 RELEV 输出构造 ``ask_clarification`` 工具调用所需的 payload。

    返回字典直接喂给 ``agents.tools.clarification.ask_clarification`` 即可。
    最多 5 个 option：前 4 个候选仓库 + 1 个「都不是 / 我自己选其它」兜底。

    Args:
        relev_output: ``ToolResult.output["data"]`` 形态。
        triggering_query: 用户原始 query，用于问题模板。

    Returns:
        ``{"question": str, "options": list[ClarificationOption], "allow_freeform": True}``。
    """
    query_excerpt = triggering_query[:60]
    suffix = "..." if len(triggering_query) > 60 else ""
    question = (
        f"针对你的需求「{query_excerpt}{suffix}」，AI 找到几个可能相关的仓库，"
        f"请确认要改哪一个 / 几个："
    )

    candidates = _unwrap_candidates(relev_output)
    # 按 score 倒序取前 4 个
    candidates.sort(
        key=lambda c: float(c.get("score", 0.0) or 0.0), reverse=True,
    )
    candidates = candidates[:4]

    options: list[dict[str, Any]] = []
    for idx, cand in enumerate(candidates):
        repo_id = str(cand.get("repository_id", ""))
        repo_name = str(cand.get("repository_name", "未命名仓库"))
        score = float(cand.get("score", 0.0) or 0.0)
        evidence = str(cand.get("evidence", ""))
        options.append({
            "id": f"opt-{idx}",
            "label": f"{repo_name}（相关度 {score:.2f}）",
            "hint": evidence,
            "implies": {
                "selected_repository_ids": [repo_id] if repo_id else [],
                "task_category": "coding_change",
                "ai_suggested_score": score,
            },
        })

    # 兜底选项「都不是 / 自己选其它」—— implies 留空让 LLM 走 freeform 走向
    options.append({
        "id": "opt-other",
        "label": "都不是 / 我自己选其它",
        "hint": "如果以上候选都不准确，可在自由输入里描述",
        "implies": {
            "selected_repository_ids": [],
            "task_category": "needs_clarification",
        },
    })

    return {
        "question": question,
        "options": options,
        "allow_freeform": True,
    }


__all__ = [
    "CODING_VERBS_ZH",
    "CODING_VERBS_EN",
    "CONFIDENCE_TOP1_MIN",
    "CONFIDENCE_GAP_MAX",
    "CONFIDENCE_ABS_GAP_MIN",
    "IntentClassification",
    "IntentConfidence",
    "TaskCategory",
    "KNOWN_TASK_CATEGORIES",
    "RelevConfidence",
    "RelevLevel",
    "classify_intent",
    "classify_solution_intent",
    "normalize_task_category",
    "evaluate_relev_confidence",
    "build_clarification_from_relev",
]
