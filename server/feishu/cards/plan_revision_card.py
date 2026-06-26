"""方案修订回路「调研问题发现」卡片模板（Phase 89，PLAN-02，89-02）。

逐字镜像 ``repo_association_card`` / ``plan_deepen_card`` 的 action_value 仅携路由 ID 范式，
覆盖修订回路两态：

- ``build_plan_revision_card``：**「调研问题发现」问询卡**——列出执行中检测到的需改 / 增 / 删
  仓库 + 方案修订摘要，提供「确认补充修订」（``plan_revision_confirm``）/「调整修订」
  （输入框 + ``plan_revision_adjust`` 多轮重检测）/「取消修订，保持原方案」
  （``plan_revision_cancel``）三动作。
- ``build_plan_revision_done_card``：**修订收尾卡**——展示补充修订是否落地 / 是否取消。

``action_value`` **绝不**携方案正文 / 仓库变更全文，仅携 ``execution_id`` / ``node_id`` /
``round`` / ``action``（脱敏 + 减小回调体积，T-89-02-INFO；调整要求经 form_value 合并，
仅作筛选要求不构造执行指令，V5）。``render_revision_markdown`` 供卡片正文渲染。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "build_plan_revision_card",
    "build_plan_revision_done_card",
    "render_revision_markdown",
]


def render_revision_markdown(revision: dict[str, Any]) -> str:
    """把检测到的修订（改/增/删仓 + 摘要）渲染成问询卡正文 markdown。"""
    revision = revision or {}
    add_repos = [str(r) for r in (revision.get("add_repos") or []) if r]
    remove_repos = [str(r) for r in (revision.get("remove_repos") or []) if r]
    change_repos = [str(r) for r in (revision.get("change_repos") or []) if r]
    delta = str(revision.get("plan_delta_summary") or "").strip()

    lines: list[str] = ["执行过程中发现可能需要调整技术方案涉及的仓库："]
    if add_repos:
        lines.append(f"➕ 建议**新增**仓库（{len(add_repos)}）：" + "、".join(add_repos))
    if remove_repos:
        lines.append(f"➖ 建议**移除**仓库（{len(remove_repos)}）：" + "、".join(remove_repos))
    if change_repos:
        lines.append(f"🔁 建议**重新校验**仓库（{len(change_repos)}）：" + "、".join(change_repos))
    if not (add_repos or remove_repos or change_repos):
        lines.append("（暂无仓库增删改建议，仅方案文本补充。）")
    if delta:
        lines.append(f"\n**方案修订要点**：{delta}")
    return "\n\n".join(lines)


def build_plan_revision_card(
    revision: dict[str, Any],
    *,
    execution_id: str,
    node_id: str,
    round: int = 1,
) -> dict[str, Any]:
    """构建「调研问题发现」问询卡（确认补充修订 / 调整修订 / 取消修订三动作）。

    Args:
        revision: ``detect_revision`` 产物（``{add_repos, remove_repos, change_repos,
            plan_delta_summary}``；正文经 ``render_revision_markdown`` 渲染，不入 action_value）。
        execution_id / node_id: 工作流执行/节点 ID（回调路由，不携正文）。
        round: 当前修订轮次（≥1，多轮调整递增）。
    """
    body = render_revision_markdown(revision)

    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": body},
        {"tag": "hr"},
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "✅ 确认补充修订"},
            "type": "primary",
            "behaviors": [
                {
                    "type": "callback",
                    "value": {
                        "action": "plan_revision_confirm",
                        "execution_id": execution_id,
                        "node_id": node_id,
                        "round": round,
                    },
                }
            ],
        },
        # 输入框 + 「调整修订」：多轮重检测（adjust_input 经 form_value 合并进 action_value）。
        {
            "tag": "form",
            "name": "plan_revision_adjust_form",
            "elements": [
                {
                    "tag": "input",
                    "name": "adjust_input",
                    "placeholder": {
                        "tag": "plain_text",
                        "content": "输入调整要求（如还要改某仓 / 不必删某仓），点发送重新研判…",
                    },
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "发送并重新研判"},
                    "type": "default",
                    "action_type": "form_submit",
                    "behaviors": [
                        {
                            "type": "callback",
                            "value": {
                                "action": "plan_revision_adjust",
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
            "text": {"tag": "plain_text", "content": "取消修订，保持原方案"},
            "type": "default",
            "behaviors": [
                {
                    "type": "callback",
                    "value": {
                        "action": "plan_revision_cancel",
                        "execution_id": execution_id,
                        "node_id": node_id,
                        "round": round,
                    },
                }
            ],
        },
    ]

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"调研问题发现 · 方案修订（第 {round} 轮）",
            },
            "template": "orange",
        },
        "body": {"elements": elements},
    }


def build_plan_revision_done_card(result: dict[str, Any]) -> dict[str, Any]:
    """构建修订收尾卡（补充修订已落地 / 已取消保持原方案）。

    经普通 ``send_card`` 下发（非流式），收尾整个修订回路；``result`` 仅含路由态摘要，不携正文。
    """
    result = result or {}
    cancelled = bool(result.get("cancelled"))
    if cancelled:
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "方案修订已取消"},
                "template": "grey",
            },
            "elements": [
                {"tag": "markdown", "content": "已取消本次修订，保持原技术方案继续执行。"}
            ],
        }

    version = result.get("version")
    add_count = int(result.get("add_count", 0) or 0)
    remove_count = int(result.get("remove_count", 0) or 0)
    change_count = int(result.get("change_count", 0) or 0)
    lines = ["✅ 已创建补充修订版本，并同步仓库关联。"]
    if version is not None:
        lines.append(f"补充修订版本号：v{version}")
    sync_bits = []
    if add_count:
        sync_bits.append(f"新增 {add_count}")
    if remove_count:
        sync_bits.append(f"移除 {remove_count}")
    if change_count:
        sync_bits.append(f"重校验 {change_count}")
    if sync_bits:
        lines.append("仓库关联同步：" + "、".join(sync_bits))

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "方案补充修订完成"},
            "template": "green",
        },
        "elements": [{"tag": "markdown", "content": "\n\n".join(lines)}],
    }
