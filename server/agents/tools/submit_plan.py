"""submit_technical_plan / request_clarification 工具。

方案生成节点的「终止动作」工具：不再依赖 LLM 在自由文本里输出 ```json``` 代码块
（脆弱、需正则解析），而是强制通过 function-calling 的结构化入参提交方案 / 发起澄清。
节点侧从工具调用入参里直接拿到结构化 JSON（见 base_agent 的 tool 调用捕获）。
"""

from typing import Any

from agents.tools.base import ToolResult, tool
from workflows.schemas.technical_plan import (
    TECHNICAL_PLAN_JSON_SCHEMA,
    validate_technical_plan,
)

# 嵌入 function-calling 参数时去掉 JSON Schema 顶层元信息（$schema/title），
# 仅保留 type/required/properties，避免个别 provider 对嵌套 $schema 处理异常。
_PLAN_ARG_SCHEMA: dict[str, Any] = {
    k: v
    for k, v in TECHNICAL_PLAN_JSON_SCHEMA.items()
    if k not in ("$schema", "title")
}


@tool(
    name="submit_technical_plan",
    description=(
        "提交最终技术方案（方案生成的终止动作）。必须以结构化 JSON 传入完整方案，"
        "字段需符合技术方案 Schema（title / summary / execution_plan 等）。"
        "调用本工具即视为方案产出完成，不要再把方案 JSON 写进文本回复。"
    ),
    category="GENERAL",
    parameters={
        "type": "object",
        "properties": {"plan": _PLAN_ARG_SCHEMA},
        "required": ["plan"],
    },
)
async def submit_technical_plan(plan: dict[str, Any]) -> ToolResult:
    """接收并校验最终技术方案。

    工具自身恒 success=True（与 verify_plan 同构）；校验结论在 output。
    节点侧（plan_generation.map_output）从本次工具调用入参 ``plan`` 直接取结构化方案，
    无需解析 LLM 自由文本。
    """
    is_valid, error_msg = validate_technical_plan(plan if isinstance(plan, dict) else {})
    return ToolResult(
        success=True,
        output={
            "accepted": True,
            "valid": is_valid,
            "error": None if is_valid else error_msg,
            "summary": "方案已接收" + ("（校验通过）" if is_valid else f"（校验警告：{error_msg}）"),
        },
    )


@tool(
    name="request_clarification",
    description=(
        "当需求信息不足、无法生成可靠技术方案时调用：以结构化入参提交需要用户补充的问题列表"
        "与原因。调用本工具即视为需要澄清，工作流会分流到下游人工处理节点；"
        "不要再把澄清内容写进文本回复，也不要在信息充分时调用本工具。"
    ),
    category="GENERAL",
    parameters={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "信息为何不足、无法生成方案的简要说明",
            },
            "questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "需要用户补充的问题列表（至少 1 条）",
            },
        },
        "required": ["reason", "questions"],
    },
)
async def request_clarification(reason: str, questions: list[str]) -> ToolResult:
    """接收澄清请求（终止动作）。节点侧从工具调用入参取 reason/questions 分流到 need_clarification 出口。"""
    normalized = [str(q).strip() for q in (questions or []) if str(q).strip()]
    return ToolResult(
        success=True,
        output={
            "accepted": True,
            "reason": str(reason or ""),
            "questions": normalized,
            "summary": f"已记录 {len(normalized)} 条澄清问题",
        },
    )
