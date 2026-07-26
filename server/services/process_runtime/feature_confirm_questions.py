"""feature list 强制确认题组装器（classify 结果 → 结构化澄清题）。

与 ``clarification_questions.py``（LLM 自由生成）互补：**确认关联仓库**这类问题不能交给
LLM 决定问不问——feature list 入口的产品约束是「哪怕路由十分确定也必须让用户确认一次」，
交给 LLM 判断必然出现「信息充分，无需澄清」而静默跳过。故本模块**确定性组装**：只要有
分类结果就一定产出确认题，题目内容由 routing 候选 + classification 数据直接推导，不经 LLM。

产出复用既有澄清卡片契约（``question`` / ``type`` / ``options`` / ``recommended``），最终经
``normalize_clarification_questions`` 归一，前端与作答回流零改动。

**只在首轮生效**：``round_count > 0`` 时返回 ``[]``，让 ``ClarifyAdapter`` 回落既有 LLM 重判
路径。否则用户答完确认题后会被反复追问同一批问题（同题死循环，见 CLARIFY-07 Pitfall 2）。
"""

from __future__ import annotations

from typing import Any

from services.process_runtime.clarification_questions import (
    normalize_clarification_questions,
)
from services.process_runtime.clarify_adapter import default_needs_clarification

__all__ = ["build_feature_confirm_questions", "feature_list_needs_clarification"]

# 单题选项上限——功能点可能有几十个，全列会把卡片撑爆且用户无法有效阅读。
# 超出部分不进选项，题干注明「其余按分类结果执行」。
_MAX_OPTIONS = 12
# 选项文本截断长度（功能点名可能很长）。
_MAX_OPTION_LEN = 60
_CONFIDENT = {"high", "medium"}


def feature_list_needs_clarification(session: Any) -> tuple[bool, str, list]:
    """feature list 入口的 needs-clarification policy：**有分类结果就一定问一次**。

    取代 ``default_needs_clarification`` 的「路由到高置信候选就不问」——feature list 入口的
    产品约束是选仓必须经用户确认，路由再确定也要问。无分类结果时回落默认策略（该会话不是
    feature list 链路，或分类阶段没产出）。

    多轮安全：本 policy 恒判需澄清，但 ``ClarifyAdapter`` 的 pending 短路 +
    ``_MAX_CLARIFY_ROUNDS`` 上界仍然生效，且 ``build_feature_confirm_questions`` 只在首轮
    产出——第二轮起走 LLM 重判，信息足够时返回空即放行，不会无限挂起。
    """
    stage_state = getattr(session, "stage_state", None) or {}
    items = (stage_state.get("classification") or {}).get("items") or []
    if items:
        return True, "请确认关联仓库与功能点的新增/改造判定", []
    return default_needs_clarification(session)


def _option_label(item: dict[str, Any]) -> str:
    """功能点 → 选项文本（``模块 / 功能点``，超长截断）。"""
    module = str(item.get("module", "") or "").strip()
    name = str(item.get("name", "") or "").strip()
    label = f"{module} / {name}" if module else name
    if len(label) > _MAX_OPTION_LEN:
        label = label[: _MAX_OPTION_LEN - 1] + "…"
    return label


def _dedupe_keep_order(labels: list[str]) -> list[str]:
    """去重保序——两个模块下同名功能点截断后可能撞车，撞车会让作答语义歧义。"""
    seen: set[str] = set()
    result: list[str] = []
    for label in labels:
        if label and label not in seen:
            seen.add(label)
            result.append(label)
    return result


def _repo_confirm_question(routing: dict[str, Any]) -> dict[str, Any] | None:
    """第 1 题（恒有）：确认本次需求关联的仓库。"""
    candidates = routing.get("candidates") or []
    options: list[str] = []
    recommended: list[str] = []
    for cand in candidates[:_MAX_OPTIONS]:
        if not isinstance(cand, dict):
            continue
        label = str(cand.get("repository_name") or cand.get("repo_id") or "").strip()
        if not label or label in options:
            continue
        options.append(label)
        if str(cand.get("confidence", "")).lower() in _CONFIDENT:
            recommended.append(label)
    if not options:
        # 没路由到任何候选仓：此时问「选哪个」没有选项可给，交回 LLM 生成开放式问题
        # （default policy 本就会因无高置信候选而判需澄清）。
        return None
    return {
        "question": "请确认本次需求**实际涉及的仓库**（已勾选的是系统推荐结果，可增删）",
        "type": "multi",
        "options": options,
        "recommended": recommended or options[:1],
    }


def _modify_review_question(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """第 2 题（有 modify 项时）：复核被判为「改造已有功能」的功能点。"""
    modify_items = [i for i in items if i.get("change_type") == "modify"]
    if not modify_items:
        return None
    labels = _dedupe_keep_order([_option_label(i) for i in modify_items])
    truncated = len(labels) > _MAX_OPTIONS
    labels = labels[:_MAX_OPTIONS]
    suffix = "（仅列前若干项，其余按分类结果执行）" if truncated else ""
    return {
        "question": (
            f"以下功能点系统判定为**改造已有功能**，请确认判定正确的项{suffix}；"
            "取消勾选的项将按**新增功能**处理"
        ),
        "type": "multi",
        "options": labels,
        "recommended": labels,
    }


def _unclear_question(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """第 3 题（有 unclear 项时）：请用户指认无法判定的功能点。"""
    unclear_items = [i for i in items if i.get("change_type") == "unclear"]
    if not unclear_items:
        return None
    labels = _dedupe_keep_order([_option_label(i) for i in unclear_items])
    truncated = len(labels) > _MAX_OPTIONS
    labels = labels[:_MAX_OPTIONS]
    suffix = "（仅列前若干项）" if truncated else ""
    return {
        "question": (
            f"以下功能点系统**无法判定**是新增还是改造{suffix}，"
            "请勾选其中属于**改造已有功能**的项；未勾选的按新增处理"
        ),
        "type": "multi",
        "options": labels,
        "recommended": [],
    }


def build_feature_confirm_questions(session: Any, *, round_count: int = 0) -> list[dict[str, Any]]:
    """据 routing + classification 确定性组装确认题；非首轮或无分类结果返回 ``[]``。

    Args:
        session: ``ConvergenceSession``（只读 ``routing`` / ``stage_state`` JSON 字段，
            不触碰 lazy-FK）。
        round_count: 已答澄清轮数。``> 0`` 时返回 ``[]`` 回落 LLM 重判（防同题死循环）。

    Returns:
        经 ``normalize_clarification_questions`` 归一的问题列表；无分类结果时为空。
    """
    if round_count > 0:
        return []

    stage_state = getattr(session, "stage_state", None) or {}
    classification = stage_state.get("classification") or {}
    items = classification.get("items") or []
    if not items:
        # 分类没跑（非 feature list 会话）或分类为空 → 不接管，走既有 LLM 澄清路径。
        return []

    routing = getattr(session, "routing", None)
    routing = routing if isinstance(routing, dict) else {}

    questions = [
        q
        for q in (
            _repo_confirm_question(routing),
            _modify_review_question(items),
            _unclear_question(items),
        )
        if q is not None
    ]
    return normalize_clarification_questions(questions)
