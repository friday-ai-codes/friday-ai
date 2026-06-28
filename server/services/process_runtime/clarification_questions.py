"""结构化澄清问题生成器（P1：完善 process_runtime 的澄清能力）。

替换原 ``default_needs_clarification`` 只产一句粗问题的做法：当需要澄清时，让 LLM 基于
**需求 + 路由候选 + 召回上下文** 产出一组**结构化、可交互**的澄清问题，每题含：
- ``question``：问题文本（可用 Markdown 加重关键词，如 ``**实验组用户**``）
- ``type``：``single``（单选）/ ``multi``（多选）
- ``options``：候选项（2–4 个；基于代码库/常见实践给合理候选）
- ``recommended``：推荐项（single 为字符串、multi 为字符串数组；卡片默认选中）

工作流与对话复用同一生成器（入口无关，只接收原语，不接 IO）。信息充分时返回 ``[]``。
LLM 调用赋 ``call_source=plan_clarification`` 并经 ``use_call_source`` 标注（可观测性规范）。
失败一律 best-effort 降级返回 ``[]``（绝不阻断编排主流程）。
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["agenerate_clarification_questions", "normalize_clarification_questions"]

_MAX_QUESTIONS = 5
_VALID_TYPES = ("single", "multi")


def _content_to_text(content: Any) -> str:
    """LangChain message.content 归一为文本（兼容 str / 分块 list）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content or "")


def _parse_questions_json(text: str) -> list[dict[str, Any]]:
    """从 LLM 文本中健壮提取 questions 数组（支持 ```json 代码块 / 裸 JSON）。"""
    candidates: list[str] = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidates.append(text)
    for block in candidates:
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("questions"), list):
            return [q for q in data["questions"] if isinstance(q, dict)]
        if isinstance(data, list):
            return [q for q in data if isinstance(q, dict)]
    return []


def normalize_clarification_questions(
    raw: list[dict[str, Any]], *, max_questions: int = _MAX_QUESTIONS
) -> list[dict[str, Any]]:
    """把 LLM 产出的问题列表归一为卡片可直接渲染的结构（防御非法字段）。"""
    result: list[dict[str, Any]] = []
    for item in raw[:max_questions]:
        question = str(item.get("question", "")).strip()
        if not question:
            continue
        q_type = str(item.get("type", "single")).strip().lower()
        if q_type not in _VALID_TYPES:
            q_type = "single"
        options = [str(o).strip() for o in (item.get("options") or []) if str(o).strip()]

        rec_raw = item.get("recommended")
        if q_type == "multi":
            if isinstance(rec_raw, (list, tuple)):
                recommended: Any = [str(r).strip() for r in rec_raw if str(r).strip()]
            elif rec_raw:
                recommended = [str(rec_raw).strip()]
            else:
                recommended = []
            recommended = [r for r in recommended if r in options]
        else:
            recommended = str(rec_raw).strip() if rec_raw else ""
            if recommended and recommended not in options:
                recommended = ""

        result.append(
            {
                "question": question,
                "type": q_type,
                "options": options,
                "recommended": recommended,
            }
        )
    return result


def _system_prompt() -> str:
    return (
        "你是资深技术方案架构师的澄清助手。基于需求和已知的仓库路由/召回信息，"
        "找出**信息不足、会显著影响技术方案**的关键点，产出结构化澄清问题。\n"
        "要求：\n"
        "- 只输出 JSON，形如 {\"questions\": [{\"question\":..,\"type\":\"single\"|\"multi\",\"options\":[..],\"recommended\":..}]}。\n"
        "- 问题要自然、简洁、可直接给研发回答；关键词可用 Markdown **加重**。\n"
        "- 每题尽量给 2–4 个候选 options，并基于代码库惯例/常见实践给一个 recommended（单选为字符串，多选为数组）。\n"
        "- 确实可同时成立才用 type=multi，否则用 single。\n"
        "- 不要写任何解释性/meta 文字（如『（无选项请直接输入）』）。\n"
        "- 若现有信息已足够生成可靠方案，返回 {\"questions\": []}。最多 "
        f"{_MAX_QUESTIONS} 个问题。"
    )


def _build_prompt(requirement: str, routing: dict[str, Any] | None, recall_hits: list | None) -> str:
    parts = [f"## 需求\n{requirement.strip()}"]
    candidates = (routing or {}).get("candidates") if isinstance(routing, dict) else None
    if candidates:
        lines = []
        for c in candidates:
            if isinstance(c, dict):
                lines.append(f"- {c.get('repo_id', '')}（置信度 {c.get('confidence', '?')}）")
        if lines:
            parts.append("## 已路由的候选仓库\n" + "\n".join(lines))
    if recall_hits:
        parts.append(f"## 召回到的相关上下文条数\n{len(recall_hits)}")
    parts.append("请输出澄清问题 JSON。")
    return "\n\n".join(parts)


async def agenerate_clarification_questions(
    *,
    requirement: str,
    routing: dict[str, Any] | None = None,
    recall_hits: list | None = None,
    max_questions: int = _MAX_QUESTIONS,
) -> list[dict[str, Any]]:
    """LLM 产结构化澄清问题；信息充分或失败时返回 ``[]``（best-effort，绝不抛）。"""
    if not (requirement or "").strip():
        return []
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            logger.warning("clarification_questions_no_default_model", category="sampling")
            return []
        model = build_chat_model(resolved, model_name, streaming=False)
        messages = [
            SystemMessage(content=_system_prompt()),
            HumanMessage(content=_build_prompt(requirement, routing, recall_hits)),
        ]
        with use_call_source(CallSource.PLAN_CLARIFICATION):
            response = await model.ainvoke(messages)
        raw = _parse_questions_json(_content_to_text(response.content))
        questions = normalize_clarification_questions(raw, max_questions=max_questions)
        logger.info(
            "clarification_questions_generated",
            category="sampling",
            component="process_runtime",
            count=len(questions),
        )
        return questions
    except Exception as exc:  # noqa: BLE001 — best-effort，绝不阻断编排
        logger.warning(
            "clarification_questions_generation_failed",
            category="sampling",
            component="process_runtime",
            error=str(exc),
        )
        return []
