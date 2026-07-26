"""feature list 技术方案 → 完整 Markdown 渲染。

与 ``process_runtime.render.render_merged_plan_markdown``（飞书 lark_md 卡片正文，刻意精简）
不同：本渲染面向 **IDE / CLI / 对话** 的完整阅读场景，输出「整体方案 + 分仓方案」两层，
并把 feature list 特有的落点信息铺开——每个仓改的是什么、动哪些文件、关键逻辑伪代码，
以及功能点的新增/改造分类。这是用户最终拿到手的那份技术方案。

纯函数，无 IO / ORM / LLM；半可信输入（LLM 产物）一律防御性处理，绝不抛异常。
"""

from __future__ import annotations

from typing import Any

__all__ = ["render_feature_solution_markdown"]

_CHANGE_TYPE_LABEL = {
    "new": "新增",
    "modify": "改造",
    "unclear": "待定",
}


def render_feature_solution_markdown(plan: Any, *, classification: Any = None) -> str:
    """§7 MergedPlan（+ 功能点分类）→ 完整技术方案 Markdown。

    Args:
        plan: 半可信 MergedPlan dict（``ArtifactVersion.content``）。
        classification: 可选的功能点分类结果（``{"items": [...], "summary": {...}}``）。

    Returns:
        Markdown 文本；``plan`` 非 dict 时返回 ``""``（防御性，绝不抛）。
    """
    if not isinstance(plan, dict):
        return ""

    parts: list[str] = []
    title = _clean(plan.get("title")) or "技术方案"
    parts.append(f"# {title}")

    summary = _clean(plan.get("summary"))
    if summary:
        parts.append(summary)

    section = _render_classification(classification)
    if section:
        parts.append(section)

    section = _render_overall(plan)
    if section:
        parts.append(section)

    section = _render_per_repo(plan)
    if section:
        parts.append(section)

    section = _render_cross_repo(plan)
    if section:
        parts.append(section)

    return "\n\n".join(p for p in parts if p)


def _render_classification(classification: Any) -> str:
    """功能点新增/改造一览（feature list 特有）。"""
    if not isinstance(classification, dict):
        return ""
    items = classification.get("items") or []
    if not isinstance(items, list) or not items:
        return ""

    summary = classification.get("summary") or {}
    head = "## 功能点分类"
    if isinstance(summary, dict) and summary:
        head += (
            f"（新增 {summary.get('new', 0)} · 改造 {summary.get('modify', 0)}"
            f" · 待定 {summary.get('unclear', 0)}）"
        )

    lines = [head, "", "| 模块 | 功能点 | 类型 | 落点 |", "| --- | --- | --- | --- |"]
    for item in items:
        if not isinstance(item, dict):
            continue
        change_type = str(item.get("change_type") or "unclear")
        label = _CHANGE_TYPE_LABEL.get(change_type, change_type)
        files = item.get("evidence_files") or []
        location = (
            "、".join(f"`{_clean(f)}`" for f in files[:3] if _clean(f))
            if files
            else (
                f"`{_clean(item.get('suggested_location'))}`"
                if _clean(item.get("suggested_location"))
                else "—"
            )
        )
        lines.append(
            f"| {_cell(item.get('module'))} | {_cell(item.get('name'))} | {label} | {_cell(location)} |"
        )
    return "\n".join(lines) if len(lines) > 4 else ""


def _render_overall(plan: Any) -> str:
    """整体方案：叙述 + 发布顺序 + 依赖关系 + 兼容风险。"""
    lines: list[str] = ["## 整体方案"]
    body = False

    overall = _clean(plan.get("overall_plan"))
    if overall:
        lines.extend(["", overall])
        body = True

    release_order = plan.get("release_order") or []
    if isinstance(release_order, list) and release_order:
        lines.extend(["", "**发布顺序**（被依赖的仓先发）", ""])
        for i, repo in enumerate(release_order, 1):
            if _clean(repo):
                lines.append(f"{i}. `{_clean(repo)}`")
        body = True

    dag = plan.get("dependency_dag")
    if isinstance(dag, dict) and dag:
        lines.extend(["", "**仓库依赖**", ""])
        for repo, deps in dag.items():
            dep_list = deps if isinstance(deps, list) else []
            rendered = "、".join(f"`{_clean(d)}`" for d in dep_list if _clean(d)) or "无"
            lines.append(f"- `{_clean(repo)}` 依赖 {rendered}")
        body = True

    contracts = plan.get("api_contracts") or []
    if isinstance(contracts, list) and contracts:
        lines.extend(["", "**跨仓接口契约**", ""])
        for contract in contracts:
            if isinstance(contract, dict):
                name = _clean(contract.get("name"))
                repo = _clean(contract.get("repo"))
                if name:
                    lines.append(f"- {name}" + (f"（`{repo}`）" if repo else ""))
            elif _clean(contract):
                lines.append(f"- {_clean(contract)}")
        body = True

    risks = plan.get("compat_risks") or []
    if isinstance(risks, list) and risks:
        lines.extend(["", "**兼容风险**", ""])
        for risk in risks:
            if _clean(risk):
                lines.append(f"- {_clean(risk)}")
        body = True

    migrations = plan.get("data_migrations") or []
    if isinstance(migrations, list) and migrations:
        rendered = [
            _clean(m.get("repository_id")) if isinstance(m, dict) else _clean(m) for m in migrations
        ]
        rendered = [r for r in rendered if r]
        if rendered:
            lines.extend(["", "**数据迁移**（按执行顺序）", ""])
            lines.extend(f"- `{r}`" for r in rendered)
            body = True

    return "\n".join(lines) if body else ""


def _render_per_repo(plan: Any) -> str:
    """分仓方案：每个仓的改动类型、落点文件、伪代码、编码说明。"""
    tasks = plan.get("execution_plan") or []
    if not isinstance(tasks, list) or not tasks:
        return ""

    lines: list[str] = ["## 分仓方案"]
    for i, task in enumerate(tasks, 1):
        if not isinstance(task, dict):
            continue
        name = _clean(task.get("name")) or f"任务 {i}"
        repo = _clean(task.get("repository_name")) or _clean(task.get("repository_id"))
        heading = f"### {i}. {name}"
        if repo:
            heading += f" — `{repo}`"
        lines.extend(["", heading])

        change_type = _clean(task.get("change_type"))
        if change_type:
            lines.append(f"\n**改动类型**：{_CHANGE_TYPE_LABEL.get(change_type, change_type)}")

        branch = _clean(task.get("branch_strategy"))
        if branch:
            lines.append(f"\n**分支策略**：{branch}")

        touch_points = task.get("touch_points") or []
        if isinstance(touch_points, list) and touch_points:
            lines.extend(["", "**改动落点**", ""])
            for point in touch_points:
                if isinstance(point, dict):
                    path = _clean(point.get("path") or point.get("file_path"))
                    note = _clean(point.get("note") or point.get("description"))
                    if path:
                        lines.append(f"- `{path}`" + (f" — {note}" if note else ""))
                elif _clean(point):
                    lines.append(f"- `{_clean(point)}`")

        instruction = _clean(task.get("coding_instruction"))
        if instruction:
            lines.extend(["", "**实现说明**", "", instruction])

        pseudocode = task.get("pseudocode")
        rendered_code = _render_pseudocode(pseudocode)
        if rendered_code:
            lines.extend(["", "**关键逻辑（伪代码）**", "", rendered_code])

        deps = task.get("dependencies_on_other_repos") or task.get("dependencies") or []
        if isinstance(deps, list) and deps:
            rendered = "、".join(f"`{_clean(d)}`" for d in deps if _clean(d))
            if rendered:
                lines.append(f"\n**依赖**：{rendered}")

        exposed = task.get("api_contracts_exposed") or []
        if isinstance(exposed, list) and exposed:
            rendered = "、".join(
                _clean(c.get("name")) if isinstance(c, dict) else _clean(c) for c in exposed
            )
            rendered = rendered.strip("、")
            if rendered:
                lines.append(f"\n**对外接口**：{rendered}")

    return "\n".join(lines)


def _render_pseudocode(pseudocode: Any) -> str:
    """伪代码渲染为围栏代码块（支持 str / list[str] / list[dict]）。"""
    if isinstance(pseudocode, str):
        body = pseudocode.strip()
        return f"```\n{body}\n```" if body else ""
    if isinstance(pseudocode, list):
        blocks: list[str] = []
        for entry in pseudocode:
            if isinstance(entry, dict):
                path = _clean(entry.get("path") or entry.get("file_path"))
                code = str(entry.get("code") or entry.get("pseudocode") or "").strip()
                if not code:
                    continue
                blocks.append((f"`{path}`\n\n" if path else "") + f"```\n{code}\n```")
            elif str(entry).strip():
                blocks.append(f"```\n{str(entry).strip()}\n```")
        return "\n\n".join(blocks)
    return ""


def _render_cross_repo(plan: Any) -> str:
    """跨仓上下文 + 回滚方案。"""
    lines: list[str] = []

    context = _clean(plan.get("cross_repo_context"))
    if context:
        lines.extend(["## 跨仓上下文", "", context])

    rollback = plan.get("rollback_plan")
    if isinstance(rollback, dict) and rollback:
        if lines:
            lines.append("")
        lines.extend(["## 回滚方案", ""])
        for repo, steps in rollback.items():
            lines.append(f"- `{_clean(repo)}`：{_clean(steps)}")
    elif _clean(rollback):
        if lines:
            lines.append("")
        lines.extend(["## 回滚方案", "", _clean(rollback)])

    return "\n".join(lines)


def _clean(value: Any) -> str:
    """半可信值 → 去空白字符串（None/非字符串安全转换）。"""
    if value is None:
        return ""
    return str(value).strip()


def _cell(value: Any) -> str:
    """表格单元格：去掉换行与竖线，避免撑破 Markdown 表格。"""
    return _clean(value).replace("|", "\\|").replace("\n", " ") or "—"
