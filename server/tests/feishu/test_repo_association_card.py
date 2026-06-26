"""业务↔仓库关联四态卡片测试（Phase 88，REPO-01/02，88-04）。

覆盖：
- 四态卡（候选 / 进行中 / 回退 / 终态）返回合法 CardKit dict（header + body/elements）。
- 候选卡按钮 action_value 仅携路由 ID（action/execution_id/node_id/round + confirm 携 repo_ids），
  **不含** feature 正文 / 命中理由长串（脱敏 + 防超大，T-88-04-INFO）。
- mismatch 卡含 repo_assoc_accept_mismatch / repo_assoc_reconfirm 两动作。
- 流式正文 render_candidates_markdown / render_verdicts_markdown 含关键信息。
"""

from __future__ import annotations

import json

from feishu.cards.repo_association_card import (
    build_repo_assoc_card,
    build_repo_assoc_done_card,
    build_repo_assoc_mismatch_card,
    build_repo_assoc_verifying_card,
    render_candidates_markdown,
    render_verdicts_markdown,
)

# 含一段「正文长串」命中理由——用于断言绝不进入 action_value。
_REASON = "本仓承接鉴权与会话管理，命中能力树 auth/login，深度覆盖飞书扫码登录全链路实现细节"
_PROPOSAL = {
    "candidates": [
        {
            "repo_id": "repo-1",
            "repo_name": "backend-auth",
            "score": 0.91,
            "confidence": "high",
            "reason": _REASON,
            "matched_node_paths": ["backend-auth/auth"],
        },
        {
            "repo_id": "repo-2",
            "repo_name": "frontend-web",
            "score": 0.62,
            "confidence": "medium",
            "reason": "前端登录页",
            "matched_node_paths": [],
        },
    ],
    "router_version": "v2",
    "auto_selected": True,
}


def _iter_action_values(card: dict) -> list[dict]:
    """递归收集卡片内所有 callback behavior 的 value（action_value）。"""
    values: list[dict] = []

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "callback" and isinstance(node.get("value"), dict):
                values.append(node["value"])
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(card)
    return values


# ---------------------------------------------------------------------------
# 候选卡
# ---------------------------------------------------------------------------


def test_candidate_card_is_streaming_schema() -> None:
    card = build_repo_assoc_card(
        _PROPOSAL, execution_id="e1", node_id="n1", round=1
    )
    assert card["schema"] == "2.0"
    assert card["config"]["streaming_mode"] is True
    assert "header" in card and "body" in card
    # 含可流式元素（element_id）
    elements = card["body"]["elements"]
    assert any(el.get("element_id") == "repo_md" for el in elements)


def test_candidate_card_action_value_only_routing_ids() -> None:
    card = build_repo_assoc_card(
        _PROPOSAL, execution_id="e1", node_id="n1", round=3
    )
    values = _iter_action_values(card)
    actions = {v["action"] for v in values}
    assert actions == {"repo_assoc_confirm", "repo_assoc_refine"}

    confirm = next(v for v in values if v["action"] == "repo_assoc_confirm")
    assert confirm["execution_id"] == "e1"
    assert confirm["node_id"] == "n1"
    assert confirm["round"] == 3
    # confirm 携选中 repo_ids（仅路由 ID）
    assert confirm["repo_ids"] == ["repo-1", "repo-2"]

    # action_value 绝不携带 feature 正文 / 命中理由长串
    serialized = json.dumps(values, ensure_ascii=False)
    assert _REASON not in serialized
    assert "命中理由" not in serialized


def test_candidate_card_renders_reason_only_in_streaming_body() -> None:
    body = render_candidates_markdown(_PROPOSAL)
    assert "backend-auth" in body
    assert _REASON in body  # 正文经流式灌入，不进 action_value
    assert "high" in body


def test_candidate_card_empty_candidates_placeholder() -> None:
    body = render_candidates_markdown({"candidates": []})
    assert "未命中" in body


# ---------------------------------------------------------------------------
# 验证进行中卡
# ---------------------------------------------------------------------------


def test_verifying_card_grey() -> None:
    card = build_repo_assoc_verifying_card(["backend-auth", "frontend-web"])
    assert card["header"]["template"] == "grey"
    assert "elements" in card
    content = card["elements"][0]["content"]
    assert "backend-auth" in content


# ---------------------------------------------------------------------------
# 回退卡
# ---------------------------------------------------------------------------


def test_mismatch_card_has_accept_and_reconfirm_actions() -> None:
    verdicts = {"fit": ["backend-auth"], "mismatch": ["frontend-web"], "unknown": []}
    card = build_repo_assoc_mismatch_card(
        verdicts, execution_id="e1", node_id="n1", round=1
    )
    values = _iter_action_values(card)
    actions = {v["action"] for v in values}
    assert "repo_assoc_accept_mismatch" in actions
    assert "repo_assoc_reconfirm" in actions
    # 路由 ID 完整
    for v in values:
        assert v["execution_id"] == "e1"
        assert v["node_id"] == "n1"


# ---------------------------------------------------------------------------
# 终态卡 + verdict 渲染
# ---------------------------------------------------------------------------


def test_done_card_lists_verified_repos() -> None:
    card = build_repo_assoc_done_card(
        {
            "verified_repos": ["backend-auth"],
            "verdicts": {"fit": ["backend-auth"], "mismatch": [], "unknown": []},
        }
    )
    assert card["header"]["template"] == "green"
    content = card["elements"][0]["content"]
    assert "backend-auth" in content


def test_render_verdicts_markdown_groups() -> None:
    body = render_verdicts_markdown(
        {"fit": ["a"], "mismatch": ["b"], "unknown": ["c"]}
    )
    assert "适配" in body
    assert "不适配" in body
    assert "无法判定" in body
