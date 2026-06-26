"""技术方案深化卡片模板（Phase 89，PLAN-01，89-01）。

``build_plan_deepen_card``：方案深化三态卡片（CardKit schema 2.0）——

- ``stage="clarify"``：澄清问询（展示澄清问题 + 输入框 + 发送按钮，多轮校验 HITL）。
- ``stage="done"``：终态方案概览（标题 + 概要 + 仓数）。
- ``stage="progress"``（默认）：深化进行中占位。

``action_value`` 仅携 ``execution_id`` / ``node_id`` / ``round`` / ``action``，**绝不**含
方案正文 / 澄清原文（脱敏 + 减小回调体积，T-89-01-INFO）。
"""

from __future__ import annotations

from typing import Any

__all__ = ["build_plan_deepen_card"]


def build_plan_deepen_card(
    *,
    stage: str = "progress",
    execution_id: str,
    node_id: str,
    round: int = 1,
    title: str = "",
    summary: str = "",
    repo_count: int = 0,
    clarify_question: str = "",
) -> dict[str, Any]:
    """构建技术方案深化卡片（progress / clarify / done 三态）。

    Args:
        stage: 卡片态（``progress`` / ``clarify`` / ``done``）。
        execution_id / node_id: 工作流执行/节点 ID（回调路由，不携正文）。
        round: 当前澄清轮次（≥1）。
        title / summary / repo_count: 终态方案概览（``done``）。
        clarify_question: 澄清问题（``clarify``，已脱敏）。
    """
    if stage == "clarify":
        return _clarify_card(execution_id, node_id, round, clarify_question)
    if stage == "done":
        return _done_card(title, summary, repo_count)
    return _progress_card()


def _progress_card() -> dict[str, Any]:
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "技术方案深化中…"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": "_正在消费确认仓并深化 per-repo + overall 方案…_"}
            ]
        },
    }


def _clarify_card(
    execution_id: str, node_id: str, round: int, question: str
) -> dict[str, Any]:
    body = question.strip() or "方案深化需要补充澄清，请提供更多信息后继续。"
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"方案深化需澄清（第 {round} 轮）"},
            "template": "orange",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": body},
                {"tag": "hr"},
                {
                    "tag": "form",
                    "name": "plan_deepen_clarify_form",
                    "elements": [
                        {
                            "tag": "input",
                            "name": "clarify_input",
                            "placeholder": {
                                "tag": "plain_text",
                                "content": "输入澄清答复，点发送继续深化方案…",
                            },
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "发送并继续"},
                            "type": "primary",
                            "action_type": "form_submit",
                            "behaviors": [
                                {
                                    "type": "callback",
                                    "value": {
                                        "action": "plan_deepen_clarify",
                                        "execution_id": execution_id,
                                        "node_id": node_id,
                                        "round": round,
                                    },
                                }
                            ],
                        },
                    ],
                },
            ]
        },
    }


def _done_card(title: str, summary: str, repo_count: int) -> dict[str, Any]:
    lines = [f"✅ 技术方案已深化完成（覆盖 **{repo_count}** 个仓）。"]
    if title.strip():
        lines.append(f"\n**{title.strip()}**")
    if summary.strip():
        lines.append(f"\n{summary.strip()}")
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "技术方案深化完成"},
            "template": "green",
        },
        "elements": [{"tag": "markdown", "content": "\n".join(lines)}],
    }
