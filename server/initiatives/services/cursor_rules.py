"""项目专属 Cursor rules 模板生成（CURSOR-02）。

生成一段 Cursor ``.mdc`` rules 文本，强制 Cursor 在编码前**先用当前分支名经 MCP
``lookup_project_by_branch`` 关联本分支所属 Friday 项目、召回需求/工件/记忆上下文，再编码**；
完成后经 ``report_project_knowledge`` 上报沉淀（人工确认入库）。

下发方式（双轨，见 81-CONTEXT specifics）：
1. 项目详情页「概览」Tab 提供「复制 / 下载」（前端消费 ``GET /api/projects/<id>/cursor-rules/``）；
2. 仓库内文档化（团队把模板提交进 ``.cursor/rules/``）。

纯文本生成、无 IO（项目对象由调用方传入），可单测。
"""

from __future__ import annotations

from typing import Any

__all__ = ["build_project_cursor_rules", "cursor_rules_filename"]


def cursor_rules_filename(project: Any) -> str:
    """建议的 rules 文件名（``friday-project-<id>.mdc``）。"""
    return f"friday-project-{project.id}.mdc"


def build_project_cursor_rules(project: Any) -> str:
    """生成项目专属 Cursor rules（.mdc 文本，CURSOR-02）。

    Args:
        project: ``initiatives.Project`` 实例（建议已 ``select_related("space")``）。

    Returns:
        可直接放入 ``.cursor/rules/<name>.mdc`` 的 Markdown frontmatter + 正文文本。
    """
    name = getattr(project, "name", "") or "（未命名项目）"
    project_id = str(getattr(project, "id", ""))
    feishu_key = getattr(project, "feishu_project_key", "") or ""
    space_name = ""
    try:
        space_name = getattr(getattr(project, "space", None), "name", "") or ""
    except Exception:  # noqa: BLE001 — space 未预取时不致命
        space_name = ""

    feishu_line = (
        f"- 飞书项目标识：`{feishu_key}`" if feishu_key else "- 飞书项目标识：（未关联）"
    )
    space_line = f"- 所属空间：{space_name}" if space_name else "- 所属空间：（未知）"

    return f"""---
description: Friday 项目「{name}」编码前置规则——先关联本分支项目、召回上下文，再编码
alwaysApply: true
---

# Friday 项目上下文规则：{name}

本规则由 Friday 为项目「{name}」生成，确保在该项目相关分支上编码时，先加载项目的完整交付上下文（需求 / 工件 / 记忆），再动手写代码。

## 项目信息

- 项目名称：{name}
- 项目 ID：`{project_id}`
{space_line}
{feishu_line}

## 强制流程（每次开始编码任务前）

1. **先关联本分支项目**：用当前 git 分支名调用 Friday MCP 工具 `lookup_project_by_branch(branch_name=<当前分支名>)`。
   - 分支命名约定 `feat/xxxx-m{{work_item_id}}-slug`，工具据此反查所属 Friday 项目并召回需求/工件/记忆上下文。
   - 若 `matched=true`，**必须先阅读返回的 `context`**（项目记忆、关联需求、工件摘要），把它作为本次编码的事实依据。
   - 若 `matched=false`（多/无命中），结合返回的 `candidates` 人工确认项目，必要时向维护者求证，不要在缺乏上下文的情况下臆测实现。
2. **再编码**：在已加载的项目上下文约束下进行设计与实现，遵守项目记忆中已记录的方案决策、约束与历史教训；不要与既有记忆/需求矛盾。
3. **完成后上报沉淀**：把本次产生的、对团队有价值的方案决策 / 经验教训，经 MCP 工具 `report_project_knowledge(project_id="{project_id}", content=<提炼后的沉淀>)` 上报。
   - 上报内容会经脱敏 + 质量门槛过滤后，写入项目记忆**草稿**，由项目成员人工确认后才正式入库（不会自动污染共享记忆）。
   - 绝不上报任何凭证 / 密钥 / token / 个人敏感信息。

## 约束

- 上述 MCP 工具需以你的 Friday 个人访问令牌（PAT）鉴权；上下文召回与记忆写回均按项目成员权限校验，非成员不会得到上下文、也无法写回。
- 本规则只约束「先召回、再编码、后沉淀」的流程，不替代仓库内其他工程规范。
"""
