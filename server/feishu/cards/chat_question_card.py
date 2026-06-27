"""群聊提问卡片模板。

构建群聊提问交互卡片和已回复状态卡片。
与 question_card.py（Agent 提问）不同，此模板用于群聊节点提问，
action value 包含 execution_id + node_id 用于工作流回调路由。
"""

from typing import Any


def build_chat_question_card(
    question: str,
    execution_id: str,
    node_id: str,
    options: list[str] | None = None,
    work_item_name: str = "",
    history: list[dict[str, str]] | None = None,
    mention_user_id: str | None = None,
) -> dict[str, Any]:
    """构建群聊提问交互卡片。

    Args:
        question: 当前问题文本
        execution_id: 工作流执行 ID，用于回调路由
        node_id: 节点 ID，用于回调路由
        options: 可选的快捷选项列表
        work_item_name: 工作项名称，显示在 header 中
        history: 历史 Q&A 列表，每项含 question 和 answer 键
        mention_user_id: 要 @mention 的飞书用户 ID

    Returns:
        飞书卡片 JSON 结构
    """
    elements: list[dict[str, Any]] = []

    # @mention 提示（放在最前面）
    if mention_user_id:
        elements.append(
            {
                "tag": "markdown",
                "content": f'<at id="{mention_user_id}">相关人员</at> 请查看以下问题',
            }
        )

    # 历史 Q&A 区块
    if history:
        history_content = ""
        for qa in history:
            history_content += f"**Q:** {qa.get('question', '')}\n"
            history_content += f"**A:** {qa.get('answer', '')}\n\n"

        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": history_content.strip(),
                },
            }
        )
        elements.append({"tag": "hr"})

    # 当前问题（加粗）
    elements.append(
        {
            "tag": "markdown",
            "content": f"**{question}**",
        }
    )

    # 快捷选项按钮
    if options:
        actions: list[dict[str, Any]] = []
        for opt in options:
            actions.append(
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": opt},
                    "type": "default",
                    "value": {
                        "action": "chat_question_answer",
                        "execution_id": execution_id,
                        "node_id": node_id,
                        "answer": opt,
                    },
                }
            )
        elements.append({"tag": "action", "actions": actions})

    # 自由输入表单
    elements.append(
        {
            "tag": "form",
            "name": "chat_answer_form",
            "elements": [
                {
                    "tag": "input",
                    "name": "custom_answer",
                    "placeholder": {"tag": "plain_text", "content": "输入自定义回复..."},
                },
                {
                    "tag": "button",
                    "name": "submit_chat_answer",
                    "text": {"tag": "plain_text", "content": "提交"},
                    "type": "primary",
                    "action_type": "form_submit",
                    "value": {
                        "action": "chat_question_answer",
                        "execution_id": execution_id,
                        "node_id": node_id,
                    },
                },
            ],
        }
    )

    # Header 标题
    title = "Friday 提问"
    if work_item_name:
        title = f"Friday 提问 — {work_item_name}"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        },
        "elements": elements,
    }


def build_clarification_card(
    questions: list[dict[str, Any]],
    execution_id: str,
    node_id: str,
    *,
    clarification_id: str = "",
    title: str = "",
    reason: str = "",
    round_no: int = 1,
    history: list[dict[str, str]] | None = None,
    mention_user_id: str | None = None,
) -> dict[str, Any]:
    """构建多问题交互澄清卡片（卡片 JSON 2.0 表单）。

    每个问题各自一块：问题文本（支持 Markdown 加重，如 **实验组用户**）+ 可选下拉
    （含「（推荐）」标记并默认选中推荐项）+ 自定义输入框；底部一个提交按钮统一提交。
    提交后由回调用 build_clarification_answered_card 置灰，禁止重复提交。

    Args:
        questions: 结构化问题列表，每项 {question, options?(list[str]), recommended?(str)}
        execution_id / node_id: 工作流回调路由
        clarification_id: 澄清轮次（delivery.Clarification）id；写进 form_submit value，
            供 plan_clarify 回调据此定位轮 + 按 order 映射 q{i} 子题（CLARIFY-05 / Pitfall 1）。
        title: 卡片标题（通常为工作项名）
        reason: 需要澄清的原因，展示在顶部
        round_no: 当前澄清轮次（多轮时展示）
        history: 历史轮次问答 [{question, answer}]
        mention_user_id: @ 的用户 open_id

    Returns:
        飞书卡片 JSON（2.0 结构，form 表单）
    """
    elements: list[dict[str, Any]] = []

    if mention_user_id:
        elements.append(
            {
                "tag": "markdown",
                "content": f'<at id="{mention_user_id}"></at> 需要你补充以下信息以继续生成技术方案',
            }
        )

    if reason:
        elements.append({"tag": "markdown", "content": f"💡 {reason}"})

    # 历史轮次（多轮澄清）
    if history:
        hist = "\n".join(
            f"**第{idx + 1}轮** Q: {qa.get('question', '')}\nA: {qa.get('answer', '')}"
            for idx, qa in enumerate(history)
        )
        elements.append({"tag": "markdown", "content": hist})
        elements.append({"tag": "hr"})

    # 表单：每个问题一组 (label + 单选/多选 + 「其他」输入框)
    form_elements: list[dict[str, Any]] = []
    for i, q in enumerate(questions):
        q_text = str(q.get("question", "")).strip()
        q_type = str(q.get("type", "single")).strip().lower()
        is_multi = q_type in ("multi", "multiple", "multi_select")
        options = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()]

        # recommended 可为 str（单选）或 list（多选）
        rec_raw = q.get("recommended")
        if isinstance(rec_raw, (list, tuple)):
            recommended = {str(r).strip() for r in rec_raw if str(r).strip()}
        elif rec_raw:
            recommended = {str(rec_raw).strip()}
        else:
            recommended = set()

        label = f"**{i + 1}. {q_text}**"
        if is_multi and options:
            label += "（可多选）"
        form_elements.append({"tag": "markdown", "content": label})

        if options:
            select_options: list[dict[str, Any]] = []
            rec_values: list[str] = []
            for opt in options:
                is_rec = opt in recommended
                text = f"⭐ {opt}" if is_rec else opt
                if is_rec:
                    rec_values.append(opt)
                select_options.append(
                    {
                        "text": {"tag": "plain_text", "content": text},
                        "value": opt,
                    }
                )

            if is_multi:
                multi_el: dict[str, Any] = {
                    "tag": "multi_select_static",
                    "name": f"q{i}",
                    "placeholder": {"tag": "plain_text", "content": "选择（可多选）"},
                    "options": select_options,
                }
                if rec_values:
                    multi_el["selected_values"] = rec_values
                form_elements.append(multi_el)
            else:
                single_el: dict[str, Any] = {
                    "tag": "select_static",
                    "name": f"q{i}",
                    "placeholder": {"tag": "plain_text", "content": "选择"},
                    "options": select_options,
                }
                if rec_values:
                    single_el["initial_option"] = rec_values[0]
                form_elements.append(single_el)

            # 每题常驻「其他」输入框（飞书无法做"选其他才出现"的条件显隐）
            form_elements.append(
                {
                    "tag": "input",
                    "name": f"qt{i}",
                    "placeholder": {"tag": "plain_text", "content": "其他（自定义填写）"},
                }
            )
        else:
            form_elements.append(
                {
                    "tag": "input",
                    "name": f"qt{i}",
                    "placeholder": {"tag": "plain_text", "content": "请输入"},
                }
            )

    # 提交按钮（form_submit 统一收集所有命名字段）
    form_elements.append(
        {
            "tag": "button",
            "name": "submit_clarification",
            "text": {"tag": "plain_text", "content": "提交"},
            "type": "primary",
            "action_type": "form_submit",
            "value": {
                # Pitfall 1：新前缀 `plan_clarify_` 隔离工作流 GroupChatQuestion 的
                # `chat_question_answer` 路由（CardCallbackView 前缀 startswith 匹配不交叉）；
                # 携服务端权威 clarification_id 供回调按 round 取轮 + order 映射子题。
                "action": "plan_clarify_answer",
                "execution_id": execution_id,
                "node_id": node_id,
                "clarification_id": clarification_id,
                "question_count": len(questions),
            },
        }
    )

    elements.append(
        {
            "tag": "form",
            "name": "clarification_form",
            "elements": form_elements,
        }
    )

    header_title = "需要补充需求信息"
    if title:
        header_title = f"需要补充需求信息 — {title}"
    if round_no > 1:
        header_title += f"（第 {round_no} 轮）"

    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": header_title},
            "template": "orange",
        },
        "elements": elements,
    }


def build_clarification_answered_card(
    qa_pairs: list[dict[str, str]],
    *,
    title: str = "",
    responder_name: str = "",
) -> dict[str, Any]:
    """构建澄清「已提交」状态卡片（灰色、只读，等于置灰原交互卡片）。"""
    lines: list[str] = []
    for i, qa in enumerate(qa_pairs):
        lines.append(f"**{i + 1}. {qa.get('question', '')}**")
        lines.append(f"↳ {qa.get('answer', '') or '（未填写）'}")
    content = "\n".join(lines)
    if responder_name:
        content += f"\n\n**回复者：** {responder_name}"

    header_title = "已收到补充信息"
    if title:
        header_title = f"已收到补充信息 — {title}"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": header_title},
            "template": "grey",
        },
        "elements": [
            {"tag": "markdown", "content": content},
            {"tag": "hr"},
            {"tag": "markdown", "content": "_正在据此继续生成技术方案..._"},
        ],
    }


def build_chat_answered_card(
    question: str,
    answer: str,
    responder_name: str = "",
    work_item_name: str = "",
) -> dict[str, Any]:
    """构建已回复状态卡片（灰色主题，替换原交互卡片）。

    Args:
        question: 原始问题
        answer: 用户回复内容
        responder_name: 回复者名称
        work_item_name: 工作项名称

    Returns:
        飞书卡片 JSON 结构
    """
    elements: list[dict[str, Any]] = []

    # Q&A 内容
    content = f"**Q:** {question}\n\n**A:** {answer}"
    if responder_name:
        content += f"\n\n**回复者:** {responder_name}"
    elements.append({"tag": "markdown", "content": content})

    elements.append({"tag": "hr"})

    # 处理中提示
    elements.append(
        {
            "tag": "markdown",
            "content": "_正在处理中..._",
        }
    )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "已收到回复"},
            "template": "grey",
        },
        "elements": elements,
    }


def build_chat_reminder_card(
    question: str,
    work_item_name: str = "",
    remaining_minutes: int = 15,
) -> dict[str, Any]:
    """构建超时提醒卡片（orange 主题，只读）。

    Args:
        question: 原始问题文本（超过 200 字会截断）
        work_item_name: 工作项名称
        remaining_minutes: 剩余时间（分钟）

    Returns:
        飞书卡片 JSON 结构
    """
    elements: list[dict[str, Any]] = []

    # 问题摘要（截断到 200 字）
    summary = question[:200] + "..." if len(question) > 200 else question
    elements.append(
        {
            "tag": "markdown",
            "content": f"**原问题摘要：**\n{summary}",
        }
    )

    elements.append({"tag": "hr"})

    # 剩余时间提示
    elements.append(
        {
            "tag": "markdown",
            "content": f"距离超时还剩 **{remaining_minutes}** 分钟，请尽快回复原提问卡片。",
        }
    )

    # Header 标题
    title = "提醒：待回复提问"
    if work_item_name:
        title = f"提醒：待回复提问 — {work_item_name}"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "orange",
        },
        "elements": elements,
    }
