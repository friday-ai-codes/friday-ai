"""业务↔仓库关联四态结果卡片模板（REPO-01/02，88-04）。

逐字镜像 ``board_split_card.py``（schema 2.0 流式卡 + 交互区 + action_value 仅携路由 ID
范式），覆盖人机协同回路的四个状态：

- ``build_repo_assoc_card``：**候选卡**——CardKit schema 2.0 流式卡片（``config.streaming_mode=True``）
  含一个可流式 markdown 元素（节点经 ``stream_card_content`` 灌入候选仓列表：名/置信度/活跃度/
  命中理由）+ 「确认这些仓库」按钮（action=repo_assoc_confirm，携选中 repo_ids 列表）+ 输入框 +
  「补充澄清」按钮（action=repo_assoc_refine，多轮重选）。
- ``build_repo_assoc_verifying_card``：**验证进行中卡**（grey，逐仓深验中…）。
- ``build_repo_assoc_mismatch_card``：**不符回退卡**——列 mismatch 仓 + 理由摘要 + 「接受并继续」
  （repo_assoc_accept_mismatch）/「重新确认仓库」（repo_assoc_reconfirm）。
- ``build_repo_assoc_done_card``：**最终确认终态卡**（verified 仓 + 各仓 verdict 摘要）。

``render_candidates_markdown`` / ``render_verdicts_markdown``：流式正文渲染（供节点灌入）。

action_value **绝不**携 feature 正文 / verdict 全文，仅携 ``execution_id`` / ``node_id`` /
``round`` / ``action``（+ confirm 时携 ``repo_ids`` 路由 ID 列表）——脱敏 + 减小回调体积
（T-88-04-INFO，mirror board_split Anti-Pattern「整篇 diff 进 action_value」）。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "build_repo_assoc_card",
    "build_repo_assoc_verifying_card",
    "build_repo_assoc_mismatch_card",
    "build_repo_assoc_done_card",
    "render_candidates_markdown",
    "render_verdicts_markdown",
]

# 候选卡可流式 markdown 元素 ID（1~20 字符，节点据此 stream_card_content）。
_STREAM_ELEMENT_ID = "repo_md"


def _candidate_repo_ids(proposal: dict[str, Any]) -> list[str]:
    """从提案抽取候选仓 repo_id 列表（仅路由 ID，供 confirm action_value 携带）。"""
    candidates = proposal.get("candidates") or []
    ids: list[str] = []
    for cand in candidates:
        repo_id = str((cand or {}).get("repo_id") or "").strip()
        if repo_id:
            ids.append(repo_id)
    return ids


def render_candidates_markdown(proposal: dict[str, Any]) -> str:
    """把选仓提案渲染成候选列表 markdown（供流式灌入可流式元素）。

    每个候选渲染：名 + 置信度 + 综合打分 + 命中理由。空候选返回占位提示。
    """
    candidates = proposal.get("candidates") or []
    if not candidates:
        return "_未命中任何候选仓库，请补充澄清要求后重试，或确认本项目尚未关联仓库。_"

    lines: list[str] = [f"共命中 **{len(candidates)}** 个候选仓库（按相关度排序）：\n"]
    for idx, cand in enumerate(candidates, 1):
        cand = cand or {}
        name = str(cand.get("repo_name") or cand.get("repo_id") or "未知仓库")
        confidence = str(cand.get("confidence") or "")
        score = cand.get("score")
        reason = str(cand.get("reason") or "").strip()
        head = f"**{idx}. 📦 {name}**"
        meta_parts = []
        if confidence:
            meta_parts.append(f"置信度 {confidence}")
        if isinstance(score, (int, float)):
            meta_parts.append(f"相关度 {score:.2f}")
        if meta_parts:
            head += f"（{' · '.join(meta_parts)}）"
        lines.append(head)
        if reason:
            lines.append(f"- 命中理由：{reason}")
    return "\n".join(lines).strip()


def render_verdicts_markdown(verdicts: dict[str, Any]) -> str:
    """把逐仓深验聚合结果渲染成 markdown（供流式灌入或终态卡正文）。

    ``verdicts`` 形如 ``{fit:[...], mismatch:[...], unknown:[...]}``，元素为仓名或 repo_id。
    """
    fit = verdicts.get("fit") or []
    mismatch = verdicts.get("mismatch") or []
    unknown = verdicts.get("unknown") or []
    lines: list[str] = []
    if fit:
        lines.append(f"✅ 适配（{len(fit)}）：" + "、".join(str(r) for r in fit))
    if mismatch:
        lines.append(f"❌ 不适配（{len(mismatch)}）：" + "、".join(str(r) for r in mismatch))
    if unknown:
        lines.append(f"❓ 无法判定（{len(unknown)}）：" + "、".join(str(r) for r in unknown))
    if not lines:
        return "_暂无深验结论。_"
    return "\n\n".join(lines)


def build_repo_assoc_card(
    proposal: dict[str, Any],
    *,
    execution_id: str,
    node_id: str,
    round: int,
    streamable_element_id: str = _STREAM_ELEMENT_ID,
) -> dict[str, Any]:
    """构建候选卡（CardKit schema 2.0 流式卡片）。

    Args:
        proposal: 选仓提案（``{candidates, router_version, ...}``；正文经流式灌入，不放 value）。
        execution_id: 工作流执行 ID（回调路由）。
        node_id: 节点 ID（回调路由）。
        round: 当前澄清轮次（≥1）。
        streamable_element_id: 可流式 markdown 元素 ID（1~20 字符）。

    Returns:
        schema 2.0 卡片 dict（``config.streaming_mode=True``）。
    """
    repo_ids = _candidate_repo_ids(proposal)

    elements: list[dict[str, Any]] = [
        # 可流式结果元素：初值占位，节点经 stream_card_content 灌入候选仓列表。
        {
            "tag": "markdown",
            "element_id": streamable_element_id,
            "content": "_候选仓库匹配中…_",
        },
        {"tag": "hr"},
    ]

    # 「确认这些仓库」：携选中 repo_ids（仅路由 ID，无正文）触发逐仓深验。
    elements.append(
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "✅ 确认这些仓库"},
            "type": "primary",
            "behaviors": [
                {
                    "type": "callback",
                    "value": {
                        "action": "repo_assoc_confirm",
                        "execution_id": execution_id,
                        "node_id": node_id,
                        "round": round,
                        "repo_ids": repo_ids,
                    },
                }
            ],
        }
    )

    # 输入框 + 「补充澄清」：多轮重选（refine_input 经 form_value 合并进 action_value）。
    elements.append(
        {
            "tag": "form",
            "name": "repo_assoc_refine_form",
            "elements": [
                {
                    "tag": "input",
                    "name": "refine_input",
                    "placeholder": {
                        "tag": "plain_text",
                        "content": "输入补充澄清（如只看后端仓 / 排除某仓），点发送重新匹配…",
                    },
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "发送并重新匹配"},
                    "type": "default",
                    "action_type": "form_submit",
                    "behaviors": [
                        {
                            "type": "callback",
                            "value": {
                                "action": "repo_assoc_refine",
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
                "content": f"业务关联仓库候选（第 {round} 轮）",
            },
            "template": "blue",
        },
        "body": {"elements": elements},
    }


def build_repo_assoc_verifying_card(repos: list[Any]) -> dict[str, Any]:
    """构建验证进行中卡（grey，逐仓深验中…）。

    经普通 ``send_card`` 下发，告知用户已确认并起逐仓容器深验。
    """
    names = [str((r.get("repo_name") if isinstance(r, dict) else r) or "") for r in (repos or [])]
    names = [n for n in names if n]
    body = "、".join(names) if names else "选定仓库"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "仓库适配性深度校验"},
            "template": "grey",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"⏳ 已确认 **{len(names)}** 个仓库，正在逐仓启动容器深度校验：\n\n"
                    f"{body}\n\n_校验完成后将自动回报结论…_"
                ),
            }
        ],
    }


def build_repo_assoc_mismatch_card(
    verdicts: dict[str, Any],
    *,
    execution_id: str,
    node_id: str,
    round: int,
) -> dict[str, Any]:
    """构建不符回退卡（列 mismatch 仓 + 理由摘要 + 接受/重确认按钮）。

    action_value 仅携路由 ID，绝不携 verdict 全文。
    """
    mismatch = verdicts.get("mismatch") or []
    body = render_verdicts_markdown(verdicts)

    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": (
                f"⚠️ 深验发现 **{len(mismatch)}** 个仓库可能不适配，请确认如何处理：\n\n{body}"
            ),
        },
        {"tag": "hr"},
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "接受并继续"},
            "type": "primary",
            "behaviors": [
                {
                    "type": "callback",
                    "value": {
                        "action": "repo_assoc_accept_mismatch",
                        "execution_id": execution_id,
                        "node_id": node_id,
                        "round": round,
                    },
                }
            ],
        },
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "重新确认仓库"},
            "type": "default",
            "behaviors": [
                {
                    "type": "callback",
                    "value": {
                        "action": "repo_assoc_reconfirm",
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
            "title": {"tag": "plain_text", "content": "仓库深验发现不符"},
            "template": "orange",
        },
        "elements": elements,
    }


def build_repo_assoc_done_card(result: dict[str, Any]) -> dict[str, Any]:
    """构建最终确认终态卡（verified 仓 + 各仓 verdict 摘要）。

    经普通 ``send_card`` 下发（非流式），收尾整个仓库关联协同回路。
    """
    verified = result.get("verified_repos") or []
    verdicts = result.get("verdicts") or {}

    names = [str((r.get("repo_name") if isinstance(r, dict) else r) or "") for r in verified]
    names = [n for n in names if n]
    preview = "、".join(names) if names else "（无）"

    lines = [f"✅ 已确认关联 **{len(names)}** 个仓库：{preview}"]
    summary = render_verdicts_markdown(verdicts) if verdicts else ""
    if summary and summary != "_暂无深验结论。_":
        lines.append(summary)

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "业务关联仓库已确认"},
            "template": "green",
        },
        "elements": [{"tag": "markdown", "content": "\n\n".join(lines)}],
    }
