"""结构化需求拆分生成器（DECOMP-01：plan_orchestration 的 LLM 拆分 helper）。

逐段镜像 ``clarification_questions.py``（CLARIFY-02 权威样板）：入口无关纯 helper，
单轮 LLM 把需求**跨仓业务线/模块/前后端**拆为结构化 ``segments``，每项含：
- ``title``：拆分项标题（必填，人类可读）
- ``module``：业务线/模块名（可空）
- ``layer``：``frontend`` / ``backend`` / ``fullstack`` / ``infra`` 之一（非法/缺失回退空）
- ``repo_hint``：候选仓库提示（取自 ``include_repos``，可空）

工作流与对话复用同一生成器（入口无关，只接收原语，不接 IO）。LLM 调用赋
``call_source=plan_decompose`` 并经 ``use_call_source`` 标注（可观测性规范，
category=sampling / component=plan_orchestration）。失败一律 best-effort 降级返回
``None``（绝不阻断编排主流程；上游 ``_decompose`` 据此触发 splitlines 回退）。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["agenerate_decomposition_segments", "normalize_decomposition_segments"]

_MAX_SEGMENTS = 20
_VALID_LAYERS = ("frontend", "backend", "fullstack", "infra")


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


def _parse_segments_json(text: str) -> list[dict[str, Any]]:
    """从 LLM 文本中健壮提取 segments 数组（支持 ```json 代码块 / 裸 JSON）。

    接受 ``{"segments": [...]}`` 或顶层 list；非 JSON / 非法 → 返回 ``[]``（不抛）。
    """
    candidates: list[str] = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidates.append(text)
    for block in candidates:
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("segments"), list):
            return [s for s in data["segments"] if isinstance(s, dict)]
        if isinstance(data, list):
            return [s for s in data if isinstance(s, dict)]
    return []


def normalize_decomposition_segments(
    raw: list[dict[str, Any]], *, max_segments: int = _MAX_SEGMENTS
) -> list[dict[str, Any]]:
    """把 LLM 产出的 segments 列表归一为稳定结构（防御 LLM 畸形输出）。

    - 缺/空 ``title`` 的项跳过（title 必填，字段强转 str/strip）。
    - ``layer`` 仅接受 ``frontend|backend|fullstack|infra``，非法/缺失回退空字符串。
    - ``module`` / ``repo_hint`` 强转 str/strip，缺失为空字符串。
    - 截断到 ``max_segments`` 防 LLM 失控。
    - 返回每项形如 ``{"title","module","layer","repo_hint"}`` 的 list[dict]。
    """
    result: list[dict[str, Any]] = []
    for item in raw[:max_segments]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        layer = str(item.get("layer", "")).strip().lower()
        if layer not in _VALID_LAYERS:
            layer = ""
        module = str(item.get("module", "")).strip()
        repo_hint = str(item.get("repo_hint", "")).strip()
        result.append(
            {
                "title": title,
                "module": module,
                "layer": layer,
                "repo_hint": repo_hint,
            }
        )
    return result


def _system_prompt() -> str:
    return (
        "你是资深技术方案架构师的需求拆分助手。把需求**跨业务线/模块/前后端**拆成"
        "若干**最小可独立交付**的拆分项，供后续仓库路由与调研使用。\n"
        "要求：\n"
        '- 只输出 JSON，形如 {"segments": [{"title":..,"module":..,"layer":'
        '"frontend"|"backend"|"fullstack"|"infra","repo_hint":..}]}。\n'
        "- title 必填、简洁、人类可读；module 为业务线/模块名（可空）。\n"
        "- layer 表征改动所在层（前端/后端/全栈/基础设施），无法判断留空。\n"
        "- repo_hint 仅从给定的候选仓库列表中取；无匹配留空。\n"
        "- 不要写任何解释性/meta 文字，不要 Markdown 代码块以外的内容。\n"
        f'- 最多 {_MAX_SEGMENTS} 个拆分项；信息不足以拆分时返回 {{"segments": []}}。'
    )


def _build_prompt(requirement: str, include_repos: list | None) -> str:
    parts = [f"## 需求\n{requirement.strip()}"]
    repos = [str(r).strip() for r in (include_repos or []) if str(r).strip()]
    if repos:
        parts.append(
            "## 候选仓库（repo_hint 只能取自此列表）\n" + "\n".join(f"- {r}" for r in repos)
        )
    parts.append("请输出拆分 segments JSON。")
    return "\n\n".join(parts)


async def agenerate_decomposition_segments(
    *,
    requirement_text: str,
    include_repos: list | None = None,
    max_segments: int = _MAX_SEGMENTS,
) -> list[dict[str, Any]] | None:
    """LLM 把需求跨仓拆为结构化 segments；失败/无 model/空 → ``None``（best-effort，绝不抛）。

    返回 ``None`` 作为「LLM 拆分不可用」信号，交由上游 ``_decompose`` 触发 splitlines 回退。
    成功时返回 ``list[dict]``（经 :func:`normalize_decomposition_segments` 归一）。
    """
    if not (requirement_text or "").strip():
        return None

    started = time.monotonic()
    repos_count = len(include_repos or [])
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        logger.info(
            "plan_decompose_started",
            category="sampling",
            component="plan_orchestration",
            requirement_len=len(requirement_text),
            include_repos_count=repos_count,
        )

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            logger.warning(
                "plan_decompose_no_default_model",
                category="sampling",
                component="plan_orchestration",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            return None

        model = build_chat_model(resolved, model_name, streaming=False)
        messages = [
            SystemMessage(content=_system_prompt()),
            HumanMessage(content=_build_prompt(requirement_text, include_repos)),
        ]
        with use_call_source(CallSource.PLAN_DECOMPOSE):
            response = await model.ainvoke(messages)

        raw = _parse_segments_json(_content_to_text(response.content))
        segments = normalize_decomposition_segments(raw, max_segments=max_segments)
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        if not segments:
            logger.info(
                "plan_decompose_completed",
                category="sampling",
                component="plan_orchestration",
                segment_count=0,
                duration_ms=duration_ms,
            )
            return None
        logger.info(
            "plan_decompose_completed",
            category="sampling",
            component="plan_orchestration",
            segment_count=len(segments),
            duration_ms=duration_ms,
        )
        return segments
    except Exception as exc:  # noqa: BLE001 — best-effort，绝不阻断编排
        logger.warning(
            "plan_decompose_failed",
            category="sampling",
            component="plan_orchestration",
            error=str(exc),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return None
