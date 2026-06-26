"""分支确认卡片模板（Phase 89 PLAN-04，建分支绑项目 HITL）。

镜像 ``repo_association_card.py`` 范式（action_value 仅携路由 ID，不携正文/分支名全文——分支名
经 server 权威态 ``output_data`` 持有，回调按 ``execution_id/node_id`` 反查）：

- ``build_branch_confirm_card``：**确认卡**——逐仓建议分支名列表 + 「确认建分支」（branch_confirm_apply）
  + 改 type 输入框「调整类型重生成」（branch_confirm_edit）+ 「取消」（branch_confirm_cancel）。
- ``build_branch_done_card``：**终态卡**——建推绑结果（succeeded/failed 逐仓）+ 回接 IDE 闭环提示。

action_value 仅 ``execution_id`` / ``node_id`` / ``round`` / ``action``（改 type 经 form_value 合并
``type_input``）——脱敏 + 减小回调体积（T-89-04-INFO）。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "build_branch_confirm_card",
    "build_branch_done_card",
    "render_branch_plan_markdown",
]


def render_branch_plan_markdown(branch_plan: list[dict[str, Any]]) -> str:
    """把逐仓建议分支名渲染为 markdown 列表（卡片正文）。"""
    if not branch_plan:
        return "_未生成任何建议分支名，请取消后重试。_"
    lines: list[str] = [f"将为 **{len(branch_plan)}** 个仓库按方案建分支并绑定项目：\n"]
    for idx, item in enumerate(branch_plan, 1):
        item = item or {}
        repo_name = str(item.get("repository_name") or item.get("repository_id") or "未知仓库")
        branch_name = str(item.get("branch_name") or "")
        lines.append(f"**{idx}. 📦 {repo_name}**")
        if branch_name:
            lines.append(f"- 分支：`{branch_name}`")
    return "\n".join(lines).strip()


def build_branch_confirm_card(
    branch_plan: list[dict[str, Any]],
    *,
    execution_id: str,
    node_id: str,
    round: int,
) -> dict[str, Any]:
    """构建分支确认卡（逐仓建议分支名 + 确认/改 type/取消）。"""
    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": render_branch_plan_markdown(branch_plan)},
        {"tag": "hr"},
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "✅ 确认建分支并绑项目"},
            "type": "primary",
            "behaviors": [
                {
                    "type": "callback",
                    "value": {
                        "action": "branch_confirm_apply",
                        "execution_id": execution_id,
                        "node_id": node_id,
                        "round": round,
                    },
                }
            ],
        },
        {
            "tag": "form",
            "name": "branch_confirm_edit_form",
            "elements": [
                {
                    "tag": "input",
                    "name": "type_input",
                    "placeholder": {
                        "tag": "plain_text",
                        "content": "调整分支类型（feat/fix/chore/refactor/...），点发送重生成…",
                    },
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "调整类型并重生成"},
                    "type": "default",
                    "action_type": "form_submit",
                    "behaviors": [
                        {
                            "type": "callback",
                            "value": {
                                "action": "branch_confirm_edit",
                                "execution_id": execution_id,
                                "node_id": node_id,
                                "round": round,
                            },
                        }
                    ],
                },
            ],
        },
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "取消（不建分支）"},
            "type": "default",
            "behaviors": [
                {
                    "type": "callback",
                    "value": {
                        "action": "branch_confirm_cancel",
                        "execution_id": execution_id,
                        "node_id": node_id,
                        "round": round,
                    },
                }
            ],
        },
    ]
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"确认按方案建分支（第 {round} 轮）",
            },
            "template": "blue",
        },
        "elements": elements,
    }


def build_branch_done_card(result: dict[str, Any]) -> dict[str, Any]:
    """构建建推绑结果终态卡（succeeded/failed 逐仓 + 回接 IDE 闭环提示）。"""
    succeeded = result.get("succeeded") or []
    failed = result.get("failed") or []
    cancelled = bool(result.get("cancelled"))

    if cancelled:
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "已取消建分支"},
                "template": "grey",
            },
            "elements": [{"tag": "markdown", "content": "_已按你的选择取消，本次未建任何分支。_"}],
        }

    lines: list[str] = []
    if succeeded:
        lines.append(f"✅ 成功 **{len(succeeded)}** 个仓库：")
        for item in succeeded:
            item = item or {}
            name = str(item.get("repository_name") or item.get("repository_id") or "")
            branch = str(item.get("branch_name") or "")
            tag = "（已存在）" if item.get("skipped_existing") else ""
            lines.append(f"- {name}：`{branch}`{tag}")
    if failed:
        lines.append(f"\n❌ 失败 **{len(failed)}** 个仓库：")
        for item in failed:
            item = item or {}
            name = str(item.get("repository_name") or item.get("repository_id") or "")
            err = str(item.get("error") or "")
            lines.append(f"- {name}：{err}")
    if not lines:
        lines.append("_未处理任何仓库。_")

    lines.append("\n_分支已绑定到项目，IDE 可经 rule/MCP 按分支反查所属项目（回接闭环）。_")

    template = "green" if succeeded and not failed else ("orange" if succeeded else "red")
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "建分支绑项目结果"},
            "template": template,
        },
        "elements": [{"tag": "markdown", "content": "\n".join(lines)}],
    }
