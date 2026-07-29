"""feature_point 意图分类 helper（Phase 112-02，FLOW-01 后半）。

契约四段：

- **谁调用**：``blueprint_spec_gate`` stage adapter——规格锁定时给每个 feature_point
  补 ``intent``（``blueprint_schema`` 的必填枚举，驱动 112-03 双面路由加权）。
- **保守方向**：分类不可得或枚举非法一律回落 ``brownfield``（存量改造）。假设「要改
  存量」会让路由继续要能力树证据；反过来误判 ``greenfield`` 则会让净新增假设跳过证据
  校验——保守值选更难被绕过的那个。
- **绝不写非法枚举**：``normalize_intents`` 用 ``allowed_ids`` 过滤 LLM 编造的
  feature_point id，输出值恒 ∈ :data:`_VALID_INTENT`（schema 必填枚举永不违约）。
- **best-effort**：LLM 不可用/响应不可解析返回 ``None``，上游按保守值兜底，绝不阻断编排。

LLM 调用赋 ``call_source=blueprint_decompose``（需求拆解链路同源），观测三事件只记
计数标量——需求正文不进日志。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = ["aclassify_intents", "normalize_intents", "DEFAULT_INTENT"]

_VALID_INTENT = ("greenfield", "brownfield", "fix")
# 保守值：存量改造（见模块 docstring「保守方向」）。
DEFAULT_INTENT = "brownfield"

# 单次分类的功能点条数上界（控 prompt 体积）。
_MAX_ITEMS = 60
_MAX_PROMPT_CHARS = 4000


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


def _parse_items_json(text: str) -> list[dict[str, Any]]:
    """从 LLM 文本中提取 items 数组（``` 围栏 + 裸 JSON 双路）；失败返回 ``[]``。"""
    candidates: list[str] = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidates.append(text)
    for block in candidates:
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return [s for s in data["items"] if isinstance(s, dict)]
        if isinstance(data, list):
            return [s for s in data if isinstance(s, dict)]
    return []


def normalize_intents(data: Any, allowed_ids: set[str] | None = None) -> dict[str, str]:
    """归一 LLM 意图分类为 ``{feature_point_id: intent}``（反幻觉，T-112-05）。

    - ``allowed_ids`` 非空时，不在其中的 id 直接丢弃（LLM 编造的功能点不得混入蓝图）。
    - 枚举值非法/缺失 → 回落保守值 ``brownfield``。
    - 输入非 list（含 ``None``）→ 空 dict。
    """
    items = data if isinstance(data, list) else []
    result: dict[str, str] = {}
    for item in items[:_MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        point_id = str(item.get("id", "") or "").strip()
        if not point_id or point_id in result:
            continue
        if allowed_ids is not None and point_id not in allowed_ids:
            continue
        intent = str(item.get("intent", "") or "").strip().lower()
        result[point_id] = intent if intent in _VALID_INTENT else DEFAULT_INTENT
    return result


def _system_prompt() -> str:
    return (
        "你是资深技术方案架构师。给定一份需求的功能点清单，判定每个功能点的**实现意图**：\n"
        "- greenfield：净新增能力，现有系统里没有承载它的实现。\n"
        "- brownfield：在已有能力上改造/扩展。\n"
        "- fix：修复已有能力的缺陷，不改变既定行为契约。\n"
        "要求：\n"
        '- 只输出 JSON，形如 {"items": [{"id": "fp_01", "intent": "greenfield"}]}。\n'
        "- id 必须逐字取自输入功能点的 id，不得改写、不得编造。\n"
        "- 判不出就填 brownfield（默认假设要动存量，后续会用现状调研证据纠正）。\n"
        "- 不要输出 JSON 以外的解释性文字。"
    )


def _build_prompt(feature_points: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for point in feature_points:
        if not isinstance(point, dict):
            continue
        point_id = str(point.get("id", "") or "").strip()
        title = str(point.get("title", "") or "").strip()
        if not point_id or not title:
            continue
        lines.append(f"- [{point_id}] {title}")
    body = "\n".join(lines)[:_MAX_PROMPT_CHARS]
    return f"## 待分类的功能点\n\n{body}\n\n请输出每个功能点的意图分类 JSON。"


async def aclassify_intents(
    *,
    feature_points: list[dict[str, Any]],
    session_id: str = "",
) -> dict[str, str] | None:
    """LLM 判定各 feature_point 的 intent；不可用时返回 ``None``（上游落保守值）。

    成功时返回 ``{feature_point_id: greenfield|brownfield|fix}``，仅含输入里真实存在
    的 id。本函数 best-effort，不外抛。
    """
    points = [p for p in (feature_points or []) if isinstance(p, dict)]
    if not points:
        return None

    started = time.monotonic()
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        logger.info(
            "blueprint_intent_classify_started",
            category="sampling",
            component="process_runtime",
            session_id=session_id,
            feature_point_count=len(points),
        )

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            logger.warning(
                "blueprint_intent_classify_no_default_model",
                category="sampling",
                component="process_runtime",
                session_id=session_id,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            return None

        model = build_chat_model(resolved, model_name, streaming=False)
        messages = [
            SystemMessage(content=_system_prompt()),
            HumanMessage(content=_build_prompt(points)),
        ]
        with use_call_source(CallSource.BLUEPRINT_DECOMPOSE):
            response = await model.ainvoke(messages)

        allowed_ids = {
            str(p.get("id", "") or "").strip() for p in points if str(p.get("id", "") or "").strip()
        }
        intents = normalize_intents(
            _parse_items_json(_content_to_text(response.content)), allowed_ids
        )
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        if not intents:
            logger.info(
                "blueprint_intent_classify_completed",
                category="sampling",
                component="process_runtime",
                session_id=session_id,
                classified_count=0,
                duration_ms=duration_ms,
            )
            return None
        logger.info(
            "blueprint_intent_classify_completed",
            category="sampling",
            component="process_runtime",
            session_id=session_id,
            classified_count=len(intents),
            greenfield_count=sum(1 for v in intents.values() if v == "greenfield"),
            brownfield_count=sum(1 for v in intents.values() if v == "brownfield"),
            fix_count=sum(1 for v in intents.values() if v == "fix"),
            duration_ms=duration_ms,
        )
        return intents
    except Exception as exc:  # noqa: BLE001 — best-effort：上游落保守值兜底
        logger.warning(
            "blueprint_intent_classify_failed",
            category="sampling",
            component="process_runtime",
            session_id=session_id,
            error=redact_secrets_in_text(str(exc)),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return None
