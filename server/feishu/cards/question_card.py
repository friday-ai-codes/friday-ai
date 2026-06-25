"""Question card template for Agent user interaction.

Builds interactive cards for asking users questions and displaying answered state.
Supports option buttons, text input, and multi-turn conversation history.
"""

from typing import Any


def build_question_card(
    question: str,
    options: list[str] | None = None,
    session_id: str = "",
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build an interactive question card for user input.

    Creates a Feishu card with:
    - Header with Friday branding (blue theme)
    - History section showing previous Q&A (if any)
    - Current question in markdown format
    - Option buttons (if provided)
    - Text input form with submit button

    Args:
        question: The current question to ask the user
        options: Optional list of option strings for quick selection buttons
        session_id: Agent session ID for callback matching
        history: List of previous Q&A dicts with 'question' and 'answer' keys

    Returns:
        Feishu card JSON structure ready for sending

    Example:
        >>> card = build_question_card(
        ...     question="Which language do you prefer?",
        ...     options=["Python", "Go", "TypeScript"],
        ...     session_id="sess-123",
        ...     history=[{"question": "Space name?", "answer": "Friday"}],
        ... )
    """
    elements: list[dict[str, Any]] = []

    # History section (if any previous Q&A)
    if history:
        history_content = ""
        for qa in history:
            history_content += f"**Q:** {qa.get('question', '')}\n"
            history_content += f"**A:** {qa.get('answer', '')}\n\n"

        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": history_content.strip(),
            },
        })
        elements.append({"tag": "hr"})

    # Current question
    elements.append({
        "tag": "markdown",
        "content": f"**{question}**",
    })

    # Option buttons (if provided)
    if options:
        actions: list[dict[str, Any]] = []
        for opt in options:
            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": opt},
                "type": "default",
                "value": {
                    "action": "user_answer",
                    "session_id": session_id,
                    "answer": opt,
                },
            })
        elements.append({"tag": "action", "actions": actions})

    # Text input form with submit button
    elements.append({
        "tag": "form",
        "name": "answer_form",
        "elements": [
            {
                "tag": "input",
                "name": "custom_answer",
                "placeholder": {"tag": "plain_text", "content": "输入自定义回复..."},
            },
            {
                "tag": "button",
                "name": "submit_answer",
                "text": {"tag": "plain_text", "content": "提交"},
                "type": "primary",
                "action_type": "form_submit",
                "value": {
                    "action": "user_answer",
                    "session_id": session_id,
                },
            },
        ],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Friday 需要您的输入"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_answered_card(
    question: str,
    answer: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a card showing the answered state (greyed out).

    Creates a Feishu card with:
    - Header with grey theme indicating completion
    - Full Q&A history including the latest answer
    - Processing indicator

    Args:
        question: The question that was answered
        answer: The user's answer
        history: Previous Q&A history (not including current)

    Returns:
        Feishu card JSON structure for the answered state

    Example:
        >>> card = build_answered_card(
        ...     question="Which language?",
        ...     answer="Python",
        ...     history=[{"question": "Name?", "answer": "Friday"}],
        ... )
    """
    elements: list[dict[str, Any]] = []

    # Build full history content including the new answer
    history_content = ""

    # Previous history
    if history:
        for qa in history:
            history_content += f"**Q:** {qa.get('question', '')}\n"
            history_content += f"**A:** {qa.get('answer', '')}\n\n"

    # Current Q&A
    history_content += f"**Q:** {question}\n"
    history_content += f"**A:** {answer}\n"

    elements.append({
        "tag": "markdown",
        "content": history_content.strip(),
    })

    elements.append({"tag": "hr"})

    # Processing indicator
    elements.append({
        "tag": "markdown",
        "content": "_正在处理中..._",
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "已收到回复"},
            "template": "grey",
        },
        "elements": elements,
    }
