"""``ask_clarification`` agent tool —— implementation。

让 LLM 主动「停下来等用户回答」的工具。返回 ``ToolResult.output`` 里携带
``pending=True`` + ``marker="ask_clarification"``；``orchestration.graph``
看到此 marker 后会把 ``pending_clarification`` 写入 state 并转入
``wait_clarification_node`` interrupt 等待用户答复。

**关键设计**：

- 工具调用本身是**轻量、纯函数**：参数校验 + 生成 ``clarification_id`` 后立即
  返回，不写 DB、不调外部 API。``ConversationIntentTrace`` 落库由
  ``ClarificationAnswerView`` 在用户答复时一次性写入（避免 interrupt 前置 DB
  副作用，让 resume 路径完全幂等 —— 这是 LangGraph 重放语义的硬规则，
  ``coding_graph`` 的 ``wait_coding_complete_node`` 历史踩过坑）。
- ``options[i].implies`` 是**自由 JSON**：schema 不强约束 keys，让上层
  ``IntentRouter`` / ``analyze_repository_relevance`` 后处理决定语义。可识别
  的常用 key 见 docstring（``selected_repository_ids`` / ``task_category``）。
- ``COMMUNICATION`` category 让 chat_runner / chat_graph 能用 ``category``
  快速过滤出「会触发 interrupt 的协商类工具」分支。
"""

from __future__ import annotations

import uuid
from typing import Any, Final

import structlog

from agents.tools.base import ToolResult, tool

logger = structlog.get_logger(__name__)


# graph.py 用此 marker 识别「ask_clarification 触发的暂停」与其它 blocking
# task 区分。改名时同步搜全仓 ``CLARIFICATION_PENDING_MARKER`` 引用。
CLARIFICATION_PENDING_MARKER: Final[str] = "ask_clarification"


_MAX_OPTIONS = 6
_MIN_OPTIONS = 2
_OPTION_LABEL_MAX = 80
_OPTION_HINT_MAX = 200
_QUESTION_MIN = 5
_QUESTION_MAX = 500


_TOOL_DESCRIPTION = (
    "向用户主动发起「ABCD 选项 + 兜底自由输入」式的澄清请求，暂停对话流等待"
    "用户答复后再继续。\n"
    "\n"
    "使用时机：当你不确定用户想动哪个仓库 / 哪种实现方案 / 哪种意图时（典型场景："
    "analyze_repository_relevance 返回多个 plausible 候选），与其猜测，不如调用"
    "本工具把 2-6 个候选选项交给用户挑选。\n"
    "\n"
    "调用后系统会暂停 graph，前端渲染 ClarificationCard；用户提交后 graph 自动"
    "恢复，用户答复 + option.implies 会作为下一轮 user_message + result_metadata"
    ".inferred_intent 注入对话上下文。\n"
    "\n"
    "options[i].implies 推荐 key：selected_repository_ids: list[str] —— 用户"
    "选这个意味着接下来操作的仓库集合；task_category: str —— 任务大类，"
    "如 backend_api_change / frontend_ui_change。\n"
    "\n"
    "若你对某个选项有明显倾向（如证据最充分的候选），给该选项设 recommended: true"
    "（**至多一个**）——UI 会展示「推荐」徽标并默认选中，降低用户决策成本。"
)


_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": (
                "向用户提的澄清问题，自然语言，中文优先，5-500 字。"
            ),
        },
        "options": {
            "type": "array",
            "description": (
                "2-6 个候选选项，每个含 id / label / hint? / implies?。"
                "用户选其中一个或自由输入。"
            ),
            "minItems": _MIN_OPTIONS,
            "maxItems": _MAX_OPTIONS,
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "选项 id，建议 opt-A/opt-B/...；同一调用内 unique。",
                    },
                    "label": {
                        "type": "string",
                        "description": "选项标签（1-80 字符），用户在 UI 上看到的主文案。",
                    },
                    "hint": {
                        "type": "string",
                        "description": "选项详细解释（0-200 字符）；用于辅助理解，可选。",
                    },
                    "implies": {
                        "type": "object",
                        "description": (
                            "用户选此选项后系统能 inferred 出的结构化状态，"
                            "如 {selected_repository_ids: [...], task_category: ...}。"
                        ),
                    },
                    "recommended": {
                        "type": "boolean",
                        "description": (
                            "是否为推荐选项（至多一个）；UI 展示「推荐」徽标并默认选中。"
                        ),
                    },
                },
                "required": ["id", "label"],
            },
        },
        "allow_freeform": {
            "type": "boolean",
            "description": "是否允许用户跳过选项自由输入答复，默认 True。",
            "default": True,
        },
    },
    "required": ["question", "options"],
}


def _validate_options(options: list[dict[str, Any]]) -> str | None:
    """对 options 列表做静态校验，返回错误字符串或 None。"""
    if not isinstance(options, list):
        return "options 必须是数组"
    if not (_MIN_OPTIONS <= len(options) <= _MAX_OPTIONS):
        return f"options 数量必须在 {_MIN_OPTIONS}-{_MAX_OPTIONS} 之间"

    seen_ids: set[str] = set()
    recommended_count = 0
    for idx, opt in enumerate(options):
        if not isinstance(opt, dict):
            return f"options[{idx}] 必须是对象"
        opt_id = opt.get("id")
        if not isinstance(opt_id, str) or not opt_id.strip():
            return f"options[{idx}].id 必须是非空字符串"
        if opt_id in seen_ids:
            return f"options 中 id 重复: {opt_id!r}"
        seen_ids.add(opt_id)

        label = opt.get("label")
        if not isinstance(label, str) or not label.strip():
            return f"options[{idx}].label 必须是非空字符串"
        if len(label) > _OPTION_LABEL_MAX:
            return (
                f"options[{idx}].label 过长（>{_OPTION_LABEL_MAX} 字符）"
            )

        hint = opt.get("hint", "")
        if hint and not isinstance(hint, str):
            return f"options[{idx}].hint 必须是字符串"
        if isinstance(hint, str) and len(hint) > _OPTION_HINT_MAX:
            return f"options[{idx}].hint 过长（>{_OPTION_HINT_MAX} 字符）"

        implies = opt.get("implies", {})
        if implies and not isinstance(implies, dict):
            return f"options[{idx}].implies 必须是对象"

        recommended = opt.get("recommended", False)
        if recommended is not None and not isinstance(recommended, bool):
            return f"options[{idx}].recommended 必须是布尔值"
        if recommended:
            recommended_count += 1

    if recommended_count > 1:
        return "recommended 选项至多一个"

    return None


@tool(
    name="ask_clarification",
    description=_TOOL_DESCRIPTION,
    category="COMMUNICATION",
    parameters=_TOOL_PARAMETERS,
)
async def ask_clarification(
    question: str,
    options: list[dict[str, Any]],
    allow_freeform: bool = True,
) -> ToolResult:
    """暂停对话流，让用户在结构化选项里选或自由输入。

    Returns:
        ``ToolResult(success=True, output={...})``，output 字典含：

        - ``clarification_id`` (str): 新生成的 uuid hex，前后端透传 id。
        - ``pending`` (bool): True —— ``orchestration.graph`` 的 marker。
        - ``marker`` (str): ``CLARIFICATION_PENDING_MARKER``；graph 用此识别。
        - ``question`` / ``options`` / ``allow_freeform``: 原样回传给前端。

    工具实现里仅做参数校验 + uuid 生成，不写 DB / 不调外部服务 —— 落
    ``ConversationIntentTrace`` 是 ``ClarificationAnswerView`` 的责任。
    """
    if not isinstance(question, str) or not question.strip():
        return ToolResult(success=False, error="question 必须是非空字符串")
    if not (_QUESTION_MIN <= len(question) <= _QUESTION_MAX):
        return ToolResult(
            success=False,
            error=f"question 长度必须在 {_QUESTION_MIN}-{_QUESTION_MAX} 之间",
        )

    err = _validate_options(options)
    if err is not None:
        return ToolResult(success=False, error=err)

    clarification_id = uuid.uuid4().hex

    logger.info(
        "ask_clarification_emitted",
        clarification_id=clarification_id,
        option_count=len(options),
        allow_freeform=allow_freeform,
        question_preview=question[:80],
    )

    return ToolResult(
        success=True,
        output={
            "clarification_id": clarification_id,
            "pending": True,
            "marker": CLARIFICATION_PENDING_MARKER,
            "question": question,
            "options": list(options),
            "allow_freeform": bool(allow_freeform),
        },
    )


__all__ = ["ask_clarification", "CLARIFICATION_PENDING_MARKER"]
