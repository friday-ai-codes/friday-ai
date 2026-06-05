"""容器 SubAgent 提问卡片模板（Phase, 增强于 Phase）。

与 question_card.py 的区别：
- action value 中包含 container_session_id（而非 agent session_id）
- 回调 action 为 "container_answer"（区分 Agent 提问的 "user_answer"）

Phase 增强：
- 支持 code_snippet 和 diff 视图
- 添加 question_id 用于匹配回复
- 已回复卡片显示上下文
"""

from typing import Any


def build_container_question_card(
    question: str,
    options: list[str] | None = None,
    session_id: str = "",
    context: str = "",
    code_snippet: str = "",
    question_id: str = "",
) -> dict[str, Any]:
    """构建容器 SubAgent 提问卡片（增强版）。

    Args:
        question: 问题内容
        options: 可选的快捷选项
        session_id: 容器会话 ID（SubAgentSession.session_id）
        context: 问题上下文说明（任务名、文件路径等）
        code_snippet: 代码片段或 diff（支持 ```diff 格式）
        question_id: 问题唯一标识

    Returns:
        Feishu 卡片 JSON
    """
    elements: list[dict[str, Any]] = []

    # 上下文说明（斜体）
    if context:
        elements.append({
            "tag": "markdown",
            "content": f"📋 _{context}_",
        })
        elements.append({"tag": "hr"})

    # 问题内容（加粗）
    elements.append({
        "tag": "markdown",
        "content": f"**{question}**",
    })

    # 代码块/diff 视图
    if code_snippet:
        # 检测是否为 diff 格式
        if code_snippet.strip().startswith("---") or code_snippet.strip().startswith("@@"):
            # Diff 格式，使用 diff 语法高亮
            elements.append({
                "tag": "markdown",
                "content": f"```diff\n{code_snippet}\n```",
            })
        else:
            # 普通代码块
            elements.append({
                "tag": "markdown",
                "content": f"```\n{code_snippet}\n```",
            })

    # 分隔线（总是添加）
    elements.append({"tag": "hr"})

    # 快捷选项按钮
    if options:
        actions: list[dict[str, Any]] = []
        for opt in options:
            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": opt},
                "type": "default",
                "value": {
                    "action": "container_answer",
                    "session_id": session_id,
                    "question_id": question_id,
                    "answer": opt,
                },
            })
        elements.append({"tag": "action", "actions": actions})

    # 文本输入表单
    elements.append({
        "tag": "form",
        "name": "container_answer_form",
        "elements": [
            {
                "tag": "input",
                "name": "custom_answer",
                "placeholder": {"tag": "plain_text", "content": "输入自定义回复..."},
            },
            {
                "tag": "button",
                "name": "submit_container_answer",
                "text": {"tag": "plain_text", "content": "提交"},
                "type": "primary",
                "action_type": "form_submit",
                "value": {
                    "action": "container_answer",
                    "session_id": session_id,
                    "question_id": question_id,
                },
            },
        ],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🤖 Friday 容器任务需要您的输入"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_container_answered_card(
    question: str,
    answer: str,
    context: str = "",
) -> dict[str, Any]:
    """构建已回复状态的卡片（灰色主题）。

    Args:
        question: 原始问题
        answer: 用户回复
        context: 问题上下文

    Returns:
        Feishu 卡片 JSON
    """
    elements: list[dict[str, Any]] = []

    if context:
        elements.append({
            "tag": "markdown",
            "content": f"📋 _{context}_",
        })
        elements.append({"tag": "hr"})

    elements.extend([
        {
            "tag": "markdown",
            "content": f"**Q:** {question}\n\n**A:** {answer}",
        },
        {"tag": "hr"},
        {
            "tag": "markdown",
            "content": "✅ _已收到回复，容器任务继续执行中..._",
        },
    ])

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "已收到回复"},
            "template": "grey",
        },
        "elements": elements,
    }
