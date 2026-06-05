"""Coding result card and branch confirmation card for AI coding workflow.

Provides card builders for:
- build_coding_result_card: 编码完成后的结果通知卡片
- build_branch_confirmation_card: 分支名确认交互卡片
"""

from typing import Any

# 卡片内容最大长度（与 approval_card.py 一致，确保 < 30KB）
_MAX_SUMMARY_LENGTH = 2000
_MAX_ERROR_LENGTH = 200


def _truncate(text: str, max_length: int) -> str:
    """截断文本并添加省略标记。"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "\n\n_...内容过长已截断_"


def build_coding_result_card(
    plan_title: str,
    succeeded_repos: list[dict[str, Any]],
    failed_repos: list[dict[str, Any]],
    branch_name: str,
    changes_summary: dict[str, Any],
) -> dict[str, Any]:
    """构建编码结果通知卡片。

    每个成功仓库展示：MR 链接、完成的任务列表、变更统计。
    失败仓库展示：仓库名 + 错误原因摘要。

    Args:
        plan_title: 技术方案标题
        succeeded_repos: 成功仓库列表，每个 dict 包含:
            - repository_name: str
            - mr_url: str
            - tasks_completed: list[str]
            - files_changed: int
            - insertions: int
            - deletions: int
        failed_repos: 失败仓库列表，每个 dict 包含:
            - repository_name: str
            - error: str
        branch_name: 分支名
        changes_summary: 总变更统计 dict:
            - total_files: int
            - total_insertions: int
            - total_deletions: int

    Returns:
        飞书卡片 JSON 结构
    """
    total = len(succeeded_repos) + len(failed_repos)
    elements: list[dict[str, Any]] = []

    # 概览信息
    overview_parts = [
        f"**{plan_title}**",
        f"分支: `{branch_name}`",
    ]
    elements.append({
        "tag": "markdown",
        "content": "\n\n".join(overview_parts),
    })

    elements.append({"tag": "hr"})

    # 成功仓库区
    content_length = 0
    if succeeded_repos:
        for repo in succeeded_repos:
            repo_name: str = repo.get("repository_name", "")
            mr_url: str = repo.get("mr_url", "")
            tasks_completed: list[str] = repo.get("tasks_completed", [])
            files_changed: int = repo.get("files_changed", 0)
            insertions: int = repo.get("insertions", 0)
            deletions: int = repo.get("deletions", 0)

            # 仓库名 + MR 链接
            if mr_url:
                repo_header = f"**{repo_name}** - [查看 MR]({mr_url})"
            else:
                repo_header = f"**{repo_name}**"

            # 完成的任务列表
            task_lines: list[str] = []
            for task_name in tasks_completed:
                if task_name:
                    task_lines.append(f"  - {task_name}")

            # 变更统计
            stats = f"{files_changed} 文件 | +{insertions} -{deletions}"

            # 组合
            parts = [repo_header]
            if task_lines:
                parts.append("\n".join(task_lines))
            parts.append(stats)

            block_content = "\n".join(parts)

            # 检查内容长度限制
            content_length += len(block_content)
            if content_length > _MAX_SUMMARY_LENGTH:
                elements.append({
                    "tag": "markdown",
                    "content": f"_...还有 {len(succeeded_repos) - succeeded_repos.index(repo)} 个仓库，内容已截断_",
                })
                break

            elements.append({
                "tag": "markdown",
                "content": block_content,
            })

    # 失败仓库区
    if failed_repos:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "markdown",
            "content": "**失败仓库**",
        })

        for repo in failed_repos:
            repo_name = repo.get("repository_name", "")
            error: str = repo.get("error", "未知错误")
            error_display = error[:_MAX_ERROR_LENGTH]
            if len(error) > _MAX_ERROR_LENGTH:
                error_display += "..."

            elements.append({
                "tag": "markdown",
                "content": f"**{repo_name}** - 失败\n原因: {error_display}",
            })

    # 底部汇总
    elements.append({"tag": "hr"})

    total_files: int = changes_summary.get("total_files", 0)
    total_insertions: int = changes_summary.get("total_insertions", 0)
    total_deletions: int = changes_summary.get("total_deletions", 0)

    summary_text = (
        f"总计: {total} 个仓库 | "
        f"成功: {len(succeeded_repos)} | "
        f"失败: {len(failed_repos)} | "
        f"变更: {total_files} 文件, +{total_insertions} -{total_deletions}"
    )
    elements.append({
        "tag": "markdown",
        "content": summary_text,
    })

    # 决定 header 颜色和标题
    if not failed_repos:
        template = "green"
        header_title = f"编码完成 - {plan_title}"
    elif not succeeded_repos:
        template = "red"
        header_title = "编码失败"
    else:
        template = "orange"
        header_title = "编码部分完成"

    # 截断 header 标题（飞书限制）
    if len(header_title) > 60:
        header_title = header_title[:57] + "..."

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": header_title},
            "template": template,
        },
        "elements": elements,
    }


def build_branch_confirmation_card(
    candidate_branch_name: str,
    plan_title: str,
    execution_id: str,
    node_id: str,
) -> dict[str, Any]:
    """构建分支名确认交互卡片。

    包含：
    - 候选分支名显示
    - 确认按钮（直接使用候选名）
    - 修改表单（用户输入自定义分支名）

    Args:
        candidate_branch_name: 候选分支名
        plan_title: 技术方案标题
        execution_id: 工作流执行 ID
        node_id: 节点 ID

    Returns:
        飞书卡片 JSON 结构
    """
    elements: list[dict[str, Any]] = []

    # 方案标题和候选分支名
    elements.append({
        "tag": "markdown",
        "content": (
            f"**{plan_title}**\n\n"
            f"候选分支名: `{candidate_branch_name}`"
        ),
    })

    elements.append({"tag": "hr"})

    # 确认按钮
    elements.append({
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "确认使用此分支名"},
                "type": "primary",
                "value": {
                    "action": "branch_confirm",
                    "branch_name": candidate_branch_name,
                    "execution_id": execution_id,
                    "node_id": node_id,
                },
            },
        ],
    })

    elements.append({"tag": "hr"})

    # 修改表单
    elements.append({
        "tag": "form",
        "name": "branch_modify_form",
        "elements": [
            {
                "tag": "input",
                "name": "branch_name",
                "placeholder": {
                    "tag": "plain_text",
                    "content": "输入自定义分支名...",
                },
                "required": True,
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "使用自定义分支名"},
                "type": "default",
                "action_type": "form_submit",
                "value": {
                    "action": "branch_modify",
                    "execution_id": execution_id,
                    "node_id": node_id,
                },
            },
        ],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "分支确认"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_branch_confirmed_card(
    branch_name: str,
    plan_title: str,
) -> dict[str, Any]:
    """构建分支已确认状态卡片（替换交互卡片）。

    Args:
        branch_name: 已确认的分支名
        plan_title: 技术方案标题

    Returns:
        飞书卡片 JSON 结构
    """
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "分支已确认"},
            "template": "green",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": f"**{plan_title}**\n\n分支名: `{branch_name}`",
            },
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": "分支名已确认，编码任务即将开始执行。",
            },
        ],
    }
