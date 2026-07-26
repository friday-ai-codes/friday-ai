"""feature list 强制确认题组装单测。

核心守的是「哪怕路由十分确定也必须问一次」这条产品约束——它是确定性组装而非 LLM 判断，
所以必须有测试钉住，否则很容易在后续重构里被"信息充分就跳过"的优化悄悄破坏。
"""

from __future__ import annotations

from types import SimpleNamespace

from services.process_runtime.feature_confirm_questions import (
    build_feature_confirm_questions,
    feature_list_needs_clarification,
)


def _session(*, items: list[dict] | None = None, candidates: list[dict] | None = None):
    """构造轻量 session 替身（只读 routing / stage_state 两个 JSON 视图）。"""
    stage_state = {}
    if items is not None:
        stage_state["classification"] = {"items": items}
    if candidates is not None:
        stage_state["routing"] = {"candidates": candidates}
    return SimpleNamespace(
        stage_state=stage_state,
        routing=stage_state.get("routing", {}),
        decomposition={},
    )


_HIGH_CANDIDATES = [
    {"repo_id": "r1", "repository_name": "friday-server", "confidence": "high"},
    {"repo_id": "r2", "repository_name": "friday-web", "confidence": "high"},
]


def test_asks_repo_confirmation_even_when_all_candidates_are_high_confidence() -> None:
    """INV-B：全部 high 置信仍然要问——这是 feature list 入口的硬约束。"""
    session = _session(
        items=[{"key": "m::a", "module": "m", "name": "a", "change_type": "new"}],
        candidates=_HIGH_CANDIDATES,
    )
    questions = build_feature_confirm_questions(session)

    assert questions, "全 high 置信时仍必须产出确认题"
    assert "仓库" in questions[0]["question"]
    assert questions[0]["options"] == ["friday-server", "friday-web"]
    assert questions[0]["recommended"] == ["friday-server", "friday-web"]


def test_policy_forces_clarification_when_classification_exists() -> None:
    session = _session(
        items=[{"key": "m::a", "module": "m", "name": "a", "change_type": "new"}],
        candidates=_HIGH_CANDIDATES,
    )
    needs, question, affected = feature_list_needs_clarification(session)
    assert needs is True
    assert question
    assert affected == []


def test_policy_falls_back_to_default_without_classification() -> None:
    """无分类结果（非 feature list 会话）→ 回落默认策略，不改变既有行为。

    默认策略在有 high 置信候选且无 ambiguous 标记时判「不需澄清」。
    """
    session = _session(candidates=_HIGH_CANDIDATES)
    needs, _question, _affected = feature_list_needs_clarification(session)
    assert needs is False


def test_returns_empty_after_first_round() -> None:
    """非首轮返回空 → 回落 LLM 重判，避免同一批确认题被反复追问（死循环）。"""
    session = _session(
        items=[{"key": "m::a", "module": "m", "name": "a", "change_type": "modify"}],
        candidates=_HIGH_CANDIDATES,
    )
    assert build_feature_confirm_questions(session, round_count=1) == []


def test_returns_empty_without_classification() -> None:
    """没有分类结果就不接管澄清，让既有 LLM 路径照常工作。"""
    assert build_feature_confirm_questions(_session(candidates=_HIGH_CANDIDATES)) == []


def test_includes_modify_review_and_unclear_questions() -> None:
    session = _session(
        items=[
            {"key": "m::a", "module": "入口", "name": "鉴权", "change_type": "modify"},
            {"key": "m::b", "module": "入口", "name": "排序", "change_type": "unclear"},
            {"key": "m::c", "module": "入口", "name": "新页", "change_type": "new"},
        ],
        candidates=_HIGH_CANDIDATES,
    )
    questions = build_feature_confirm_questions(session)

    assert len(questions) == 3
    modify_q, unclear_q = questions[1], questions[2]
    assert modify_q["options"] == ["入口 / 鉴权"]
    # 改造项默认勾选（系统判定即推荐），无法判定项默认不勾选（不替用户拿主意）。
    assert modify_q["recommended"] == ["入口 / 鉴权"]
    assert unclear_q["options"] == ["入口 / 排序"]
    assert unclear_q["recommended"] == []


def test_skips_repo_question_when_no_candidates() -> None:
    """没路由到候选仓时无选项可给，跳过该题交回 LLM 出开放式问题。"""
    session = _session(
        items=[{"key": "m::a", "module": "m", "name": "a", "change_type": "modify"}],
        candidates=[],
    )
    questions = build_feature_confirm_questions(session)
    assert all("仓库" not in q["question"] for q in questions)


def test_dedupes_and_truncates_long_option_lists() -> None:
    """功能点过多时截断，且截断后重名的选项去重（否则作答语义歧义）。"""
    items = [
        {"key": f"m::{i}", "module": "模块", "name": f"功能{i}", "change_type": "modify"}
        for i in range(30)
    ]
    items.append({"key": "dup", "module": "模块", "name": "功能0", "change_type": "modify"})
    session = _session(items=items, candidates=_HIGH_CANDIDATES)
    questions = build_feature_confirm_questions(session)

    modify_q = questions[1]
    assert len(modify_q["options"]) == 12
    assert len(set(modify_q["options"])) == len(modify_q["options"])
    assert "其余按分类结果执行" in modify_q["question"]
