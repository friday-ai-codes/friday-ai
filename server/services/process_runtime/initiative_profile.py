"""专项画像抽取（Phase 128，PROF-01/02/03）。

从 feature list 产出可 JSON 序列化的 ``InitiativeProfile``。主路径语料优先模块
简述/总览与功能 name+description，**默认剔除** acceptance / 测试 case 正文；
语料不足返回 ``clarify(insufficient_profile_corpus)``；LLM 失败 fail-soft 为
``degraded``，不抛垮调用方。

观测：``initiative_profile_started/completed/failed``，``category=sampling``，
``component=process_runtime``；日志仅长度/reason，禁止需求原文；异常走
``redact_secrets_in_text``。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = [
    "InitiativeProfile",
    "ProfileCorpus",
    "build_profile",
    "select_profile_corpus",
    "profile_to_dict",
]

_COMPONENT = "process_runtime"
_VALID_CHANGE_KINDS = frozenset({"brownfield", "greenfield", "fix"})
_MAX_CORPUS_CHARS = 12000
_MAX_PROMPT_CHARS = 8000

# 视为「测试/验收正文」的键——主路径语料默认剔除。
_ACCEPTANCE_KEYS = frozenset(
    {
        "acceptance",
        "acceptance_criteria",
        "acceptances",
        "test_case",
        "test_cases",
        "test_steps",
        "steps",
        "操作步骤",
        "验收",
        "验收项",
    }
)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass
class InitiativeProfile:
    """机读专项画像（可 asdict / JSON 进 stage 观测）。"""

    product_form: str = ""
    domains: list[str] = field(default_factory=list)
    change_kind: str = "brownfield"
    capability_clusters: list[str] = field(default_factory=list)
    non_goals: list[str] = field(default_factory=list)
    reuse_summary: str = ""


@dataclass
class ProfileCorpus:
    """画像语料选择结果。"""

    texts: list[str] = field(default_factory=list)
    sufficient: bool = False
    char_len: int = 0


def profile_to_dict(profile: InitiativeProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return asdict(profile)


def select_profile_corpus(
    feature_list: Any = None,
    *,
    features_flat: list[dict[str, Any]] | None = None,
    modules: list[dict[str, Any]] | None = None,
) -> ProfileCorpus:
    """选择画像主路径语料：模块简述/总览 + 功能 name/description；剔除验收正文。"""
    texts: list[str] = []
    has_overview = False

    fl = feature_list if isinstance(feature_list, dict) else {}
    mod_list = modules if modules is not None else list(fl.get("modules") or [])
    flat = features_flat if features_flat is not None else list(fl.get("features_flat") or [])

    for key in ("flow_summary", "global_flow", "overview", "summary", "module_overview"):
        value = str(fl.get(key) or "").strip()
        if value:
            texts.append(value)
            has_overview = True

    for mod in mod_list:
        if not isinstance(mod, dict):
            continue
        for key in ("summary", "overview", "description", "brief", "模块简述", "总览"):
            value = str(mod.get(key) or "").strip()
            if value:
                texts.append(value)
                has_overview = True
        name = str(mod.get("name") or "").strip()
        if name:
            texts.append(f"模块：{name}")
        for feat in mod.get("features") or []:
            if not isinstance(feat, dict):
                continue
            _append_feature_text(texts, feat)

    for feat in flat:
        if not isinstance(feat, dict):
            continue
        _append_feature_text(texts, feat)

    # 去重保序
    seen: set[str] = set()
    unique: list[str] = []
    for t in texts:
        if t in seen:
            continue
        seen.add(t)
        unique.append(t)

    joined = "\n".join(unique)
    if len(joined) > _MAX_CORPUS_CHARS:
        joined = joined[:_MAX_CORPUS_CHARS]
        unique = [joined]
    char_len = len(joined)

    # 充足：有模块/全局简述，或至少有非空功能描述（非仅 name）
    has_feature_desc = any(
        isinstance(f, dict) and str(f.get("description") or "").strip() for f in flat
    )
    if not has_feature_desc:
        for mod in mod_list:
            if not isinstance(mod, dict):
                continue
            for feat in mod.get("features") or []:
                if isinstance(feat, dict) and str(feat.get("description") or "").strip():
                    has_feature_desc = True
                    break
            if has_feature_desc:
                break

    sufficient = bool(has_overview or has_feature_desc) and char_len > 0
    return ProfileCorpus(texts=unique, sufficient=sufficient, char_len=char_len)


def _append_feature_text(texts: list[str], feat: dict[str, Any]) -> None:
    name = str(feat.get("name") or feat.get("title") or "").strip()
    description = str(feat.get("description") or "").strip()
    module = str(feat.get("module") or "").strip()
    parts = [p for p in (module, name, description) if p]
    if parts:
        texts.append(" / ".join(parts))
    # 明确不收录 acceptance / test 正文
    for key in _ACCEPTANCE_KEYS:
        _ = feat.get(key)


def _normalize_change_kind(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return raw if raw in _VALID_CHANGE_KINDS else "brownfield"


def _normalize_str_list(value: Any, *, limit: int = 32) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:limit]:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _parse_profile_json(text: str) -> InitiativeProfile | None:
    candidates: list[str] = []
    for match in _JSON_FENCE.finditer(text or ""):
        candidates.append(match.group(1))
    candidates.append(text or "")
    for block in candidates:
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        return InitiativeProfile(
            product_form=str(data.get("product_form") or "").strip(),
            domains=_normalize_str_list(data.get("domains")),
            change_kind=_normalize_change_kind(data.get("change_kind")),
            capability_clusters=_normalize_str_list(data.get("capability_clusters")),
            non_goals=_normalize_str_list(data.get("non_goals")),
            reuse_summary=str(data.get("reuse_summary") or "").strip(),
        )
    return None


def _content_to_text(content: Any) -> str:
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


def _system_prompt() -> str:
    return (
        "你是资深产品架构师。根据专项需求语料抽取机读画像，只输出 JSON：\n"
        "{\n"
        '  "product_form": "产品形态简述",\n'
        '  "domains": ["业务域"],\n'
        '  "change_kind": "brownfield|greenfield|fix",\n'
        '  "capability_clusters": ["主能力簇"],\n'
        '  "non_goals": ["显式非目标"],\n'
        '  "reuse_summary": "复用声明摘要"\n'
        "}\n"
        "规则：不得编造语料未暗示的能力；判不出 change_kind 填 brownfield；"
        "不要输出 JSON 以外文字。"
    )


def _result(
    *,
    status: str,
    clarify_reason: str = "",
    degrade_reason: str = "",
    profile: InitiativeProfile | None = None,
    corpus_char_len: int = 0,
) -> dict[str, Any]:
    return {
        "status": status,
        "clarify_reason": clarify_reason,
        "degrade_reason": degrade_reason,
        "profile": profile_to_dict(profile),
        "corpus_char_len": corpus_char_len,
    }


async def build_profile(
    feature_list: Any = None,
    *,
    features_flat: list[dict[str, Any]] | None = None,
    modules: list[dict[str, Any]] | None = None,
    initiated_by_user_id: str = "",
    request_id: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """抽取专项画像；三态 ``ok|clarify|degraded``，永不向上抛。"""
    started = time.monotonic()
    user_label = str(initiated_by_user_id or "") or "system"
    corpus = select_profile_corpus(
        feature_list, features_flat=features_flat, modules=modules
    )

    try:
        logger.info(
            "initiative_profile_started",
            category="sampling",
            component=_COMPONENT,
            initiated_by_user_id=user_label,
            request_id=request_id or None,
            run_id=run_id or None,
            corpus_char_len=corpus.char_len,
            corpus_sufficient=corpus.sufficient,
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort
        pass

    if not corpus.sufficient:
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        try:
            logger.info(
                "initiative_profile_completed",
                category="sampling",
                component=_COMPONENT,
                initiated_by_user_id=user_label,
                request_id=request_id or None,
                run_id=run_id or None,
                status="clarify",
                clarify_reason="insufficient_profile_corpus",
                corpus_char_len=corpus.char_len,
                duration_ms=duration_ms,
            )
        except Exception:  # noqa: BLE001
            pass
        return _result(
            status="clarify",
            clarify_reason="insufficient_profile_corpus",
            corpus_char_len=corpus.char_len,
        )

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            duration_ms = round((time.monotonic() - started) * 1000, 2)
            try:
                logger.info(
                    "initiative_profile_completed",
                    category="sampling",
                    component=_COMPONENT,
                    initiated_by_user_id=user_label,
                    request_id=request_id or None,
                    run_id=run_id or None,
                    status="degraded",
                    degrade_reason="no_default_model",
                    corpus_char_len=corpus.char_len,
                    duration_ms=duration_ms,
                )
            except Exception:  # noqa: BLE001
                pass
            return _result(
                status="degraded",
                degrade_reason="no_default_model",
                corpus_char_len=corpus.char_len,
            )

        model = build_chat_model(resolved, model_name, streaming=False)
        body = "\n".join(corpus.texts)[:_MAX_PROMPT_CHARS]
        messages = [
            SystemMessage(content=_system_prompt()),
            HumanMessage(content=f"## 专项语料\n\n{body}\n\n请输出画像 JSON。"),
        ]
        with use_call_source(CallSource.INITIATIVE_PROFILE):
            response = await model.ainvoke(messages)
        profile = _parse_profile_json(_content_to_text(response.content))
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        if profile is None:
            try:
                logger.info(
                    "initiative_profile_completed",
                    category="sampling",
                    component=_COMPONENT,
                    initiated_by_user_id=user_label,
                    request_id=request_id or None,
                    run_id=run_id or None,
                    status="degraded",
                    degrade_reason="invalid_profile_json",
                    corpus_char_len=corpus.char_len,
                    duration_ms=duration_ms,
                )
            except Exception:  # noqa: BLE001
                pass
            return _result(
                status="degraded",
                degrade_reason="invalid_profile_json",
                corpus_char_len=corpus.char_len,
            )

        try:
            logger.info(
                "initiative_profile_completed",
                category="sampling",
                component=_COMPONENT,
                initiated_by_user_id=user_label,
                request_id=request_id or None,
                run_id=run_id or None,
                status="ok",
                change_kind=profile.change_kind,
                domain_count=len(profile.domains),
                cluster_count=len(profile.capability_clusters),
                corpus_char_len=corpus.char_len,
                duration_ms=duration_ms,
            )
        except Exception:  # noqa: BLE001
            pass
        return _result(status="ok", profile=profile, corpus_char_len=corpus.char_len)
    except Exception as exc:  # noqa: BLE001 — fail-soft，不抛垮调用方
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        reason = redact_secrets_in_text(str(exc))[:300]
        try:
            logger.warning(
                "initiative_profile_failed",
                category="sampling",
                component=_COMPONENT,
                initiated_by_user_id=user_label,
                request_id=request_id or None,
                run_id=run_id or None,
                degrade_reason=reason,
                corpus_char_len=corpus.char_len,
                duration_ms=duration_ms,
            )
        except Exception:  # noqa: BLE001
            pass
        return _result(
            status="degraded",
            degrade_reason=reason or "llm_error",
            corpus_char_len=corpus.char_len,
        )
