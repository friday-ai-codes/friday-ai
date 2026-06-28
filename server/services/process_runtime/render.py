"""MergedPlan §7 → 干净结构化 markdown 渲染（Phase 94 UNIFY-06）。

把 canonical ``MergedPlan`` content（``PlanVersion.content``，§7）渲染为飞书 lark_md
卡片正文。**MCP delegate（UNIFY-03）与 ``ai_plan_research`` done 出口共享本 helper**
（落「不造两套」），范式移植自 ``workflows.nodes.ai.plan_generation._render_plan_markdown``
但适配 §7 MergedPlan schema（``execution_plan[]`` / ``compat_risks`` 等跨仓字段）。

**脱敏纵深（T-94-01-INFO）**：只读 MergedPlan **结构化字段**（title/summary/execution_plan/
compat_risks），绝不内联任何 LLM 原始文本 / ``raw_*`` 字段（UNIFY-06「不 dump 原文」）；
content 本身已是 schema 化产物。

lark_md 限制：不支持 Markdown `- ` 列表语法（markdown 组件也仅 ≥7.6 渲染）→ 用 `•`
字面项目符号，跨客户端/跨版本稳定。

纯函数无 IO/ORM/LLM，故无观测埋点需求（观测纯函数豁免）。
"""

from __future__ import annotations

from typing import Any

__all__ = ["render_merged_plan_markdown"]

# coding_instruction 截断阈值（飞书卡片正文不宜过长）
_INSTRUCTION_MAX = 300


def render_merged_plan_markdown(plan: Any) -> str:
    """把 §7 MergedPlan content 渲染为干净的飞书 lark_md 卡片正文。

    Args:
        plan: 半可信 MergedPlan dict（canonical ``PlanVersion.content``）。

    Returns:
        渲染后的 lark_md 文本；顶层非 dict / 空 dict 等半可信输入恒返回 ``""``
        （防御性，对齐 ``merged_plan.validate_merged_plan`` fail-safe 范式），绝不抛异常。
    """
    if not isinstance(plan, dict):
        return ""

    parts: list[str] = []

    title = str(plan.get("title", "")).strip()
    if title:
        parts.append(f"**{title}**")

    summary = str(plan.get("summary", "")).strip()
    if summary:
        parts.append(summary)

    tasks = plan.get("execution_plan") or []
    if isinstance(tasks, list) and tasks:
        parts.append(f"**📋 执行计划（共 {len(tasks)} 项）**")
        for i, task in enumerate(tasks, 1):
            if not isinstance(task, dict):
                continue
            name = str(task.get("name", f"任务 {i}")).strip()
            repo = str(task.get("repository_name", "")).strip()
            head = f"**{i}. {name}**"
            if repo:
                head += f"  `{repo}`"
            parts.append(head)
            desc = str(task.get("description", "")).strip()
            if desc:
                parts.append(desc)
            instruction = str(task.get("coding_instruction", "")).strip()
            if instruction:
                snippet = (
                    instruction
                    if len(instruction) <= _INSTRUCTION_MAX
                    else instruction[:_INSTRUCTION_MAX] + "…"
                )
                parts.append(f"> {snippet}")

    risks = plan.get("compat_risks") or []
    if isinstance(risks, list) and risks:
        # lark_md 不支持列表语法 → 用 • 字面项目符号（跨客户端稳定）。
        bullets = "\n".join(f"• {str(r).strip()}" for r in risks if str(r).strip())
        if bullets:
            parts.append(f"**⚠️ 兼容风险**\n{bullets}")

    return "\n\n".join(p for p in parts if p)
