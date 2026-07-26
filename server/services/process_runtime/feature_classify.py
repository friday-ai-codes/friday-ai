"""feature 变更类型分类生成器（feature list 方案编排的 classify 阶段 LLM helper）。

逐段镜像 ``decompose_segments.py``（本仓 LLM helper 权威样板）：入口无关纯 helper，
只接收原语、不接 IO。判定 feature list 里每个功能点是**新增功能**还是**改造已有功能**，
每项含：

- ``key``：功能点唯一键（``模块::功能点``，用于与输入功能点对齐）
- ``change_type``：``new``（新增）/ ``modify``（改造已有）/ ``unclear``（判不出）
- ``confidence``：``high`` / ``medium`` / ``low``
- ``target_repo_id``：判定归属仓库（取自证据；无法判定留空）
- ``reason``：判定理由（一句话）
- ``evidence_files``：支撑判定的已有代码文件路径（判 ``modify`` 必须非空）
- ``suggested_location``：建议落点目录/文件（判 ``new`` 时给）

**判不出就标 unclear，不许猜**——下游 classify 阶段会把 unclear 项组装成确认题交给用户
指认，猜错比不猜代价更大。

LLM 调用赋 ``call_source=feature_change_classify`` 并经 ``use_call_source`` 标注（可观测性
规范，category=sampling / component=process_runtime）。失败一律 best-effort 降级返回
``None``（绝不阻断编排主流程；上游 adapter 据此把全部功能点降级为 ``unclear``）。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = ["aclassify_feature_changes", "normalize_feature_classifications", "build_feature_key"]

_MAX_ITEMS = 60
_VALID_CHANGE_TYPES = ("new", "modify", "unclear")
_VALID_CONFIDENCE = ("high", "medium", "low")
# 单个功能点喂给 LLM 的证据条数上限（控 prompt 体积，证据按 score 降序取前 N）。
_MAX_EVIDENCE_PER_FEATURE = 5


def build_feature_key(module: str, name: str) -> str:
    """组装功能点唯一键（``模块::功能点``）——adapter 与 LLM 输出对齐用同一函数。"""
    return f"{str(module or '').strip()}::{str(name or '').strip()}"


def _content_to_text(content: Any) -> str:
    """LangChain message.content 归一为文本（兼容 str / 分块 list）。

    reasoning 模型（经兼容代理的 deepseek/glm 等）content 为 content_blocks 列表，
    直接 ``str()`` 会得到 Python repr（单引号）致下游 ``json.loads`` 失败——只拼接
    含 text 的 block。
    """
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
    """从 LLM 文本中健壮提取 items 数组（支持 ```json 代码块 / 裸 JSON）。

    接受 ``{"items": [...]}`` 或顶层 list；非 JSON / 非法 → 返回 ``[]``（不抛）。
    """
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


def normalize_feature_classifications(
    raw: list[dict[str, Any]],
    *,
    allowed_keys: set[str] | None = None,
    allowed_files: dict[str, set[str]] | None = None,
    max_items: int = _MAX_ITEMS,
) -> list[dict[str, Any]]:
    """把 LLM 产出的分类列表归一为稳定结构（防御 LLM 畸形输出与幻觉）。

    - 缺/空 ``key`` 的项跳过；``allowed_keys`` 非空时不在其中的 key 跳过（防 LLM 编造功能点）。
    - ``change_type`` 仅接受 ``new|modify|unclear``，非法/缺失回退 ``unclear``。
    - ``confidence`` 仅接受 ``high|medium|low``，非法/缺失回退 ``low``。
    - ``evidence_files`` 经 ``allowed_files``（key → 该功能点检索到的真实文件集合）过滤，
      **剔除不在证据集合里的路径**——LLM 幻觉出的文件名不得流入方案落点。
    - 判 ``modify`` 但过滤后无证据文件 → 降级为 ``unclear``（判定失去依据，交回用户确认）。
    - 截断到 ``max_items`` 防 LLM 失控。
    """
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw[:max_items]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        if not key or key in seen:
            continue
        if allowed_keys is not None and key not in allowed_keys:
            continue
        seen.add(key)

        change_type = str(item.get("change_type", "")).strip().lower()
        if change_type not in _VALID_CHANGE_TYPES:
            change_type = "unclear"
        confidence = str(item.get("confidence", "")).strip().lower()
        if confidence not in _VALID_CONFIDENCE:
            confidence = "low"

        raw_files = item.get("evidence_files") or []
        files = [str(f).strip() for f in raw_files if str(f).strip()]
        if allowed_files is not None:
            permitted = allowed_files.get(key, set())
            files = [f for f in files if f in permitted]

        # 判「改造已有」却给不出真实存在的证据文件 → 判定无依据，降级 unclear 交回用户。
        if change_type == "modify" and not files:
            change_type = "unclear"
            confidence = "low"

        result.append(
            {
                "key": key,
                "change_type": change_type,
                "confidence": confidence,
                "target_repo_id": str(item.get("target_repo_id", "")).strip(),
                "reason": str(item.get("reason", "")).strip(),
                "evidence_files": files,
                "suggested_location": str(item.get("suggested_location", "")).strip(),
            }
        )
    return result


def _system_prompt() -> str:
    return (
        "你是资深技术方案架构师的变更分析助手。给定一份 feature list 的功能点，以及每个功能点"
        "在现有代码库中检索到的相关代码证据，判定每个功能点属于**新增功能**还是**改造已有功能**。\n"
        "要求：\n"
        '- 只输出 JSON，形如 {"items": [{"key":..,"change_type":"new"|"modify"|"unclear",'
        '"confidence":"high"|"medium"|"low","target_repo_id":..,"reason":..,'
        '"evidence_files":[..],"suggested_location":..}]}。\n'
        "- key 必须逐字取自输入功能点的 key，不得改写、不得编造新的 key。\n"
        "- change_type=modify：现有代码里已有承载该能力的实现，本次是在其上改造/扩展。"
        "此时 evidence_files 必须非空，且**只能**从该功能点的证据清单里逐字挑选文件路径，"
        "严禁编造路径。\n"
        "- change_type=new：现有代码里没有承载该能力的实现，需要新写。此时给出 suggested_location"
        "（建议落点目录或文件，参考证据里同类功能的组织方式）。\n"
        "- change_type=unclear：证据不足以判断。**判不出就填 unclear，不要猜**——下游会把它交给"
        "用户确认，猜错的代价比不猜大。\n"
        "- target_repo_id 只能取自该功能点证据里出现过的仓库 id；无法判定留空。\n"
        "- reason 一句话说明判定依据，不要复述功能描述。\n"
        "- 不要写任何解释性/meta 文字，不要 Markdown 代码块以外的内容。\n"
        f"- 输入有多少个功能点就输出多少项，最多 {_MAX_ITEMS} 项。"
    )


def _build_prompt(features: list[dict[str, Any]], evidence_by_key: dict[str, list[dict]]) -> str:
    """拼装分类 prompt：逐功能点列出描述与检索证据（证据截断防 prompt 爆炸）。"""
    blocks: list[str] = []
    for feat in features:
        key = str(feat.get("key", "")).strip()
        if not key:
            continue
        lines = [f"### {key}"]
        title = str(feat.get("title", "")).strip()
        if title:
            lines.append(f"功能点：{title}")
        layer = str(feat.get("layer", "")).strip()
        if layer:
            lines.append(f"改动层：{layer}")

        hits = evidence_by_key.get(key) or []
        if hits:
            lines.append("检索到的现有代码证据：")
            for hit in hits[:_MAX_EVIDENCE_PER_FEATURE]:
                if not isinstance(hit, dict):
                    continue
                lines.append(
                    f"- 仓库 {hit.get('repository_id', '')} | 文件 {hit.get('file_path', '')}"
                    f" | 符号 {hit.get('symbol', '') or '-'}"
                    f" | 相似度 {hit.get('score', 0)}"
                )
        else:
            lines.append("检索到的现有代码证据：无")
        blocks.append("\n".join(lines))

    return (
        "## 待分类的功能点\n\n"
        + "\n\n".join(blocks)
        + "\n\n请输出分类结果 JSON（每个功能点一项，key 逐字对应）。"
    )


async def aclassify_feature_changes(
    *,
    features: list[dict[str, Any]],
    evidence_by_key: dict[str, list[dict]] | None = None,
    max_items: int = _MAX_ITEMS,
) -> list[dict[str, Any]] | None:
    """LLM 判定各功能点新增/改造；失败/无 model/空 → ``None``（best-effort，绝不抛）。

    返回 ``None`` 作为「LLM 分类不可用」信号，交由上游 adapter 把全部功能点降级为
    ``unclear``（不阻断编排，由用户在确认环节指认）。成功时返回经
    :func:`normalize_feature_classifications` 归一的 ``list[dict]``。
    """
    if not features:
        return None

    evidence = evidence_by_key or {}
    started = time.monotonic()
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        logger.info(
            "feature_classify_started",
            category="sampling",
            component="process_runtime",
            feature_count=len(features),
            with_evidence_count=sum(1 for v in evidence.values() if v),
        )

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            logger.warning(
                "feature_classify_no_default_model",
                category="sampling",
                component="process_runtime",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            return None

        model = build_chat_model(resolved, model_name, streaming=False)
        messages = [
            SystemMessage(content=_system_prompt()),
            HumanMessage(content=_build_prompt(features, evidence)),
        ]
        with use_call_source(CallSource.FEATURE_CHANGE_CLASSIFY):
            response = await model.ainvoke(messages)

        allowed_keys = {str(f.get("key", "")).strip() for f in features if f.get("key")}
        allowed_files = {
            key: {
                str(h.get("file_path", "")).strip()
                for h in hits
                if isinstance(h, dict) and str(h.get("file_path", "")).strip()
            }
            for key, hits in evidence.items()
        }
        raw = _parse_items_json(_content_to_text(response.content))
        items = normalize_feature_classifications(
            raw,
            allowed_keys=allowed_keys,
            allowed_files=allowed_files,
            max_items=max_items,
        )
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        if not items:
            logger.info(
                "feature_classify_completed",
                category="sampling",
                component="process_runtime",
                item_count=0,
                duration_ms=duration_ms,
            )
            return None
        logger.info(
            "feature_classify_completed",
            category="sampling",
            component="process_runtime",
            item_count=len(items),
            new_count=sum(1 for i in items if i["change_type"] == "new"),
            modify_count=sum(1 for i in items if i["change_type"] == "modify"),
            unclear_count=sum(1 for i in items if i["change_type"] == "unclear"),
            duration_ms=duration_ms,
        )
        return items
    except Exception as exc:  # noqa: BLE001 — best-effort，绝不阻断编排
        logger.warning(
            "feature_classify_failed",
            category="sampling",
            component="process_runtime",
            error=redact_secrets_in_text(str(exc)),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return None
