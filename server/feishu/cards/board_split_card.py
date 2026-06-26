"""看板拆分流式结果卡片模板（BOARD-02，87-04）。

``build_board_split_card``：CardKit schema 2.0 流式卡片（``config.streaming_mode=True``）——
含一个可流式 markdown 元素（``element_id``，初值空，由节点经 ``stream_card_content`` 灌入按
模块分组的 feature 列表）+ 交互区「开始创建」按钮 + 输入框 + 「发送」按钮（多轮重拆）。

``build_board_split_done_card``：建看板结果终态卡片（created 数 + 父子降级提示 + 失败摘要），
经普通 ``send_card`` 下发。

action_value 仅携 ``execution_id`` / ``node_id`` / ``round`` / ``action``，**绝不**含 feature
原文（脱敏 + 减小回调体积，T-87-04-INFO）。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "build_board_split_card",
    "build_board_split_done_card",
    "render_proposal_markdown",
]

# 父子关系缺失降级提示（与 BoardSplitService._DEGRADED_HINT 语义一致，引导去配置中心）。
_DEGRADED_HINT = (
    "⚠️ 父子关系类型未配置：建看板时将不挂父子（仍关联项目跟踪），"
    "请去飞书项目配置中心预配关系类型。"
)


def render_proposal_markdown(proposal: dict[str, Any]) -> str:
    """把拆分提案渲染成按模块分组的 markdown（供流式灌入可流式元素）。

    优先用 ``modules`` 分组；缺失时回退 ``features_flat`` 平铺。空提案返回占位提示。
    """
    modules = proposal.get("modules") or []
    lines: list[str] = []

    if modules:
        for mod in modules:
            mod_name = str(mod.get("name") or "未命名模块")
            features = mod.get("features") or []
            lines.append(f"**📦 {mod_name}**（{len(features)} 项）")
            for feat in features:
                lines.append(f"- {feat.get('name', '')}")
            lines.append("")
    else:
        flat = proposal.get("features_flat") or []
        if not flat:
            return "_未解析出任何 feature，请检查输入或补充拆分要求后重试。_"
        for feat in flat:
            module = feat.get("module", "")
            prefix = f"[{module}] " if module else ""
            lines.append(f"- {prefix}{feat.get('name', '')}")

    feature_count = len(proposal.get("features_flat") or [])
    module_count = len(modules)
    header = f"共 **{feature_count}** 个 feature、**{module_count}** 个模块：\n"
    return header + "\n".join(lines).strip()


def build_board_split_card(
    proposal: dict[str, Any],
    *,
    execution_id: str,
    node_id: str,
    round: int,
    streamable_element_id: str = "split_md",
) -> dict[str, Any]:
    """构建 CardKit schema 2.0 流式拆分结果卡片。

    Args:
        proposal: 拆分提案（读 ``degraded`` 决定是否附降级提示；正文经流式灌入，不放 value）。
        execution_id: 工作流执行 ID（回调路由）。
        node_id: 节点 ID（回调路由）。
        round: 当前拆分轮次（≥1）。
        streamable_element_id: 可流式 markdown 元素 ID（1~20 字符），节点据此 stream_card_content。

    Returns:
        schema 2.0 卡片 dict（``config.streaming_mode=True``）。
    """
    degraded = bool(proposal.get("degraded"))

    elements: list[dict[str, Any]] = [
        # 可流式结果元素：初值空，节点经 stream_card_content 灌入按模块分组的 feature 列表。
        {
            "tag": "markdown",
            "element_id": streamable_element_id,
            "content": "_拆分结果生成中…_",
        }
    ]

    if degraded:
        elements.append({"tag": "markdown", "content": _DEGRADED_HINT})

    elements.append({"tag": "hr"})

    # 「开始创建」：直接建看板（回调 action=board_split_start）。
    elements.append(
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🚀 开始创建"},
            "type": "primary",
            "behaviors": [
                {
                    "type": "callback",
                    "value": {
                        "action": "board_split_start",
                        "execution_id": execution_id,
                        "node_id": node_id,
                        "round": round,
                    },
                }
            ],
        }
    )

    # 输入框 + 「发送」：多轮重拆（回调 action=board_split_refine，refine_input 经 form_value 合并）。
    elements.append(
        {
            "tag": "form",
            "name": "board_split_refine_form",
            "elements": [
                {
                    "tag": "input",
                    "name": "refine_input",
                    "placeholder": {
                        "tag": "plain_text",
                        "content": "输入补充拆分要求（如按端拆分 / 合并某模块），点发送重新拆分…",
                    },
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "发送并重拆"},
                    "type": "default",
                    "action_type": "form_submit",
                    "behaviors": [
                        {
                            "type": "callback",
                            "value": {
                                "action": "board_split_refine",
                                "execution_id": execution_id,
                                "node_id": node_id,
                                "round": round,
                            },
                        }
                    ],
                },
            ],
        }
    )

    return {
        "schema": "2.0",
        "config": {"streaming_mode": True, "update_multi": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"看板拆分结果（第 {round} 轮）",
            },
            "template": "blue",
        },
        "body": {"elements": elements},
    }


def build_board_split_done_card(result: dict[str, Any]) -> dict[str, Any]:
    """构建建看板结果终态卡片（created 数 + 父子降级提示 + 失败摘要）。

    经普通 ``send_card`` 下发（非流式），收尾整个拆分协同回路。
    """
    created = result.get("created") or []
    failures = result.get("failures") or []
    degraded = bool(result.get("degraded_parent_child"))
    hint = result.get("hint") or ""

    lines = [f"✅ 已创建 **{len(created)}** 个子看板。"]
    if created:
        preview = "、".join(str(c.get("feature", "")) for c in created[:10])
        lines.append(f"包含：{preview}{'…' if len(created) > 10 else ''}")
    if failures:
        lines.append(f"⚠️ 有 **{len(failures)}** 个 feature 建项失败（详见系统日志）。")
    if degraded and hint:
        lines.append(f"\n{hint}")

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "看板拆分完成"},
            "template": "green",
        },
        "elements": [{"tag": "markdown", "content": "\n\n".join(lines)}],
    }
