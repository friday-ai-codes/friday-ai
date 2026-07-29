"""仓库章程起草与确认服务（CHARTER-01 / DESIGN §5.7，RepoCharter 唯一写入入口 INV-6）。

三源蒸馏起草管道（镜像 ``services/process_runtime/decompose_segments.py`` 的 LLM
五步骨架）：``ai_summary``/``facets``（仓库摘要与语义分面）+ 近期 MR 历史（哪类需求
实际落在此仓）+ verified/rejected ``RepoAssociation``（verified 作 owned 证据、
rejected 作 boundaries 候选）→ 单轮 LLM 蒸馏 → :func:`normalize_charter_draft`
白名单归一 → 落草案。LLM 不可用/解析失败一律 best-effort 返回 ``None``、零副作用。

「AI 不覆盖人工」不变量（P11，CHARTER-01 核心）：``source=human_confirmed`` 之后，
AI 起草路径只写 ``draft_content``（pending 修订草案），正式字段逐字节不变；草案经
:func:`aconfirm_charter` 人工确认（version+1、confirmed_by 署名）才提升为正式内容。

LLM 调用赋 ``call_source=blueprint_charter_draft``（LOGGING-SPEC §4.1），观测事件
``charter_draft_started/completed/failed`` + ``charter_confirmed``（category=caller，
component=charter_service），异常文本经 ``redact_secrets_in_text`` 脱敏后入日志。
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async

from common.logging import redact_secrets_in_text

if TYPE_CHECKING:
    from repositories.models import RepoCharter

logger = structlog.get_logger(__name__)

__all__ = ["adraft_charter", "aconfirm_charter", "normalize_charter_draft"]

_POSITIONING_MAX = 500
_FACET_FIELD_MAX = 64
_VALID_DOMAIN_STATUS = ("implemented", "planned")
_VALID_EVOLUTION = ("active", "maintenance_only", "deprecated")
_RECENT_LIMIT = 20


def _clean_str(value: Any, max_len: int) -> str:
    """任意输入强转 str/strip 并截断；None/非法 → 空字符串。"""
    if value is None:
        return ""
    return str(value).strip()[:max_len]


def _clean_citations(value: Any) -> list[str]:
    """citations 白名单：仅接受 list，项强转 str/strip，空项剔除。"""
    if not isinstance(value, list):
        return []
    return [str(c).strip() for c in value if str(c).strip()]


def normalize_charter_draft(data: Any) -> dict[str, Any]:
    """把 LLM/edits 产出的章程 dict 归一为稳定白名单结构（防御畸形输出，绝不抛）。

    - ``positioning``：str，截断 500。
    - ``owned_domains``：list[dict]，item 白名单 domain/status/note/citations；
      status 只认 ``implemented|planned``，非法回退 ``implemented``；缺 domain 的项跳过。
    - ``boundaries``：list[dict]，白名单 rule/decided_by/citations；缺 rule 的项跳过。
    - ``placement_preferences``：list[dict]，白名单 kind/target/note；kind/target 全空跳过。
    - ``audience`` / ``form``：str，截断 64。
    - ``evolution``：只认 ``active|maintenance_only|deprecated``，非法回退 ``active``。
    - 非法类型逐字段回退空值（非 dict 输入 → 全空默认结构）。
    """
    src = data if isinstance(data, dict) else {}

    owned_domains: list[dict[str, Any]] = []
    raw_domains = src.get("owned_domains")
    if isinstance(raw_domains, list):
        for item in raw_domains:
            if not isinstance(item, dict):
                continue
            domain = _clean_str(item.get("domain"), 200)
            if not domain:
                continue
            status = _clean_str(item.get("status"), 32).lower()
            if status not in _VALID_DOMAIN_STATUS:
                status = "implemented"
            owned_domains.append(
                {
                    "domain": domain,
                    "status": status,
                    "note": _clean_str(item.get("note"), 500),
                    "citations": _clean_citations(item.get("citations")),
                }
            )

    boundaries: list[dict[str, Any]] = []
    raw_boundaries = src.get("boundaries")
    if isinstance(raw_boundaries, list):
        for item in raw_boundaries:
            if not isinstance(item, dict):
                continue
            rule = _clean_str(item.get("rule"), 500)
            if not rule:
                continue
            boundaries.append(
                {
                    "rule": rule,
                    "decided_by": _clean_str(item.get("decided_by"), 100),
                    "citations": _clean_citations(item.get("citations")),
                }
            )

    placement_preferences: list[dict[str, Any]] = []
    raw_prefs = src.get("placement_preferences")
    if isinstance(raw_prefs, list):
        for item in raw_prefs:
            if not isinstance(item, dict):
                continue
            kind = _clean_str(item.get("kind"), 200)
            target = _clean_str(item.get("target"), 200)
            if not kind and not target:
                continue
            placement_preferences.append(
                {
                    "kind": kind,
                    "target": target,
                    "note": _clean_str(item.get("note"), 500),
                }
            )

    evolution = _clean_str(src.get("evolution"), 32).lower()
    if evolution not in _VALID_EVOLUTION:
        evolution = "active"

    return {
        "positioning": _clean_str(src.get("positioning"), _POSITIONING_MAX),
        "owned_domains": owned_domains,
        "boundaries": boundaries,
        "placement_preferences": placement_preferences,
        "audience": _clean_str(src.get("audience"), _FACET_FIELD_MAX),
        "form": _clean_str(src.get("form"), _FACET_FIELD_MAX),
        "evolution": evolution,
    }


def _content_to_text(content: Any) -> str:
    """LangChain message.content 归一为文本（兼容 reasoning content_blocks）。"""
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


def _parse_charter_json(text: str) -> dict[str, Any] | None:
    """从 LLM 文本健壮提取章程 dict（```json 代码块 + 裸 JSON 双路）；失败 → None。"""
    candidates: list[str] = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidates.append(text)
    for block in candidates:
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _system_prompt() -> str:
    return (
        "你是仓库章程（RepoCharter）起草助手。基于给定的仓库摘要、语义分面、近期 MR "
        "历史与关联裁决，蒸馏出该仓库的**意图面**章程：职责定位、owned 业务域、边界"
        "禁区、新功能落点偏好。\n"
        "要求：\n"
        '- 只输出 JSON，形如 {"positioning": "一句话定位", '
        '"owned_domains": [{"domain":..,"status":"implemented"|"planned",'
        '"note":..,"citations":[]}], '
        '"boundaries": [{"rule":..,"decided_by":..,"citations":[]}], '
        '"placement_preferences": [{"kind":..,"target":..,"note":..}], '
        '"audience":.., "form":.., '
        '"evolution":"active"|"maintenance_only"|"deprecated"}。\n'
        "- positioning 一句话说明该仓是什么、服务谁、承载什么类型改动。\n"
        "- owned_domains 从近期 MR 实际落点与 verified 关联裁决归纳；无证据不臆造。\n"
        "- boundaries 从 rejected 关联裁决提炼「该类需求不落此仓」的候选禁区。\n"
        "- audience/form 与语义分面对齐（服务对象/技术形态）。\n"
        "- 不要写任何解释性/meta 文字，不要 Markdown 代码块以外的内容。"
    )


def _build_prompt(
    *,
    overview: str,
    facets: dict[str, Any],
    recent_mrs: list[dict[str, str]],
    associations: list[dict[str, str]],
) -> str:
    parts: list[str] = []
    parts.append("## 仓库摘要\n" + (overview.strip() or "（暂无 AI 摘要）"))
    if facets:
        facet_lines = "\n".join(f"- {k}: {v}" for k, v in facets.items())
        parts.append("## 语义分面\n" + facet_lines)
    if recent_mrs:
        mr_lines = "\n".join(f"- [{m['status']}] {m['title']}" for m in recent_mrs)
        parts.append("## 近期 MR\n" + mr_lines)
    if associations:
        assoc_lines = "\n".join(
            f"- [{a['status']}] {a['routed_reason'] or '（无路由理由）'}" for a in associations
        )
        parts.append("## 关联裁决（verified→owned 证据、rejected→边界候选）\n" + assoc_lines)
    parts.append("请输出该仓库的章程草案 JSON。")
    return "\n\n".join(parts)


async def adraft_charter(
    repository_id: str, *, initiated_by_user_id: str = "system"
) -> RepoCharter | None:
    """AI 起草仓库章程草案（三源蒸馏 → LLM 单调用 → 归一化落库，best-effort）。

    - 仓库不存在：``Repository.DoesNotExist`` 上抛（视图层转 404）。
    - LLM 不可用（无 provider/default_model）/ 解析失败 / 任何异常：返回 ``None``，
      不落任何行（首次起草场景零副作用）。
    - 落库语义（INV-6 单点，P11 不变量）：无 charter → 建行 ``source=ai_draft``；
      已有且仍是草案 → 正式字段就地更新（version 不变）；已有且
      ``source=human_confirmed`` → **只写 ``draft_content``**，正式字段一个不碰。
    """
    from repositories.models import RepoCharter, Repository

    repo = await Repository.objects.aget(id=repository_id)  # DoesNotExist 上抛 → 视图转 404

    started = time.monotonic()
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        logger.info(
            "charter_draft_started",
            category="caller",
            component="charter_service",
            repository_id=str(repository_id),
            initiated_by_user_id=initiated_by_user_id,
        )

        # ── 三源蒸馏输入（ORM 一律 sync_to_async，P1）─────────────────────────
        overview = repo.overview_text
        facets = repo.facets if isinstance(repo.facets, dict) else {}

        def _load_recent_mrs() -> list[dict[str, str]]:
            from initiatives.models import MergeRequest

            return [
                {"title": mr.title, "status": mr.status}
                for mr in MergeRequest.objects.filter(repository_id=repository_id).order_by(
                    "-created_at"
                )[:_RECENT_LIMIT]
            ]

        def _load_associations() -> list[dict[str, str]]:
            from initiatives.models import RepoAssociation

            return [
                {"status": assoc.status, "routed_reason": assoc.routed_reason}
                for assoc in RepoAssociation.objects.filter(
                    repository_id=repository_id, status__in=["verified", "rejected"]
                )[:_RECENT_LIMIT]
            ]

        recent_mrs = await sync_to_async(_load_recent_mrs)()
        associations = await sync_to_async(_load_associations)()

        # ── LLM 五步骨架（镜像 decompose_segments）────────────────────────────
        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            logger.warning(
                "charter_draft_failed",
                category="caller",
                component="charter_service",
                repository_id=str(repository_id),
                initiated_by_user_id=initiated_by_user_id,
                reason="no_default_model",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            return None

        model = build_chat_model(resolved, model_name, streaming=False)
        messages = [
            SystemMessage(content=_system_prompt()),
            HumanMessage(
                content=_build_prompt(
                    overview=overview,
                    facets=facets,
                    recent_mrs=recent_mrs,
                    associations=associations,
                )
            ),
        ]
        with use_call_source(CallSource.BLUEPRINT_CHARTER_DRAFT):
            response = await model.ainvoke(messages)

        raw = _parse_charter_json(_content_to_text(response.content))
        if raw is None:
            logger.warning(
                "charter_draft_failed",
                category="caller",
                component="charter_service",
                repository_id=str(repository_id),
                initiated_by_user_id=initiated_by_user_id,
                reason="parse_failed",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            return None
        draft = normalize_charter_draft(raw)

        # ── 落库（INV-6 单点 + P11 不变量）────────────────────────────────────
        def _persist() -> RepoCharter:
            from django.db import transaction

            with transaction.atomic():
                charter = RepoCharter.objects.select_for_update().filter(repository=repo).first()
                if charter is None:
                    return RepoCharter.objects.create(
                        repository=repo,
                        source=RepoCharter.Source.AI_DRAFT,
                        version=1,
                        **draft,
                    )
                if charter.source == RepoCharter.Source.AI_DRAFT:
                    # 仍是草案：正式字段就地更新（version 不变）
                    for field, value in draft.items():
                        setattr(charter, field, value)
                    charter.save()
                    return charter
                # human_confirmed：只写 draft_content，正式字段一个不碰（P11）
                charter.draft_content = draft
                charter.save(update_fields=["draft_content", "updated_at"])
                return charter

        charter = await sync_to_async(_persist)()
        logger.info(
            "charter_draft_completed",
            category="caller",
            component="charter_service",
            repository_id=str(repository_id),
            initiated_by_user_id=initiated_by_user_id,
            charter_source=str(charter.source),
            charter_version=charter.version,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return charter
    except Exception as exc:  # noqa: BLE001 — best-effort，绝不上抛（DB 写失败同样吞）
        logger.warning(
            "charter_draft_failed",
            category="caller",
            component="charter_service",
            repository_id=str(repository_id),
            initiated_by_user_id=initiated_by_user_id,
            error=redact_secrets_in_text(str(exc)),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return None


async def aconfirm_charter(
    repository_id: str, user: Any, *, edits: dict[str, Any] | None = None
) -> RepoCharter:
    """人工确认章程生效：草案提升 + edits 套用 + version+1 + confirmed_by 署名。

    - charter 不存在 → ``ValueError``（视图层转 404）。
    - ``draft_content`` 非空：先过 :func:`normalize_charter_draft` 提升为正式字段。
    - ``edits``：仅套用调用方显式给出的白名单字段（同 normalize 归一，非法值回退）。
    - 收口后 ``source=human_confirmed``、``version += 1``、``draft_content = {}``。
    """
    from repositories.models import RepoCharter

    def _confirm() -> RepoCharter:
        from django.db import transaction

        with transaction.atomic():
            charter = (
                RepoCharter.objects.select_for_update().filter(repository_id=repository_id).first()
            )
            if charter is None:
                raise ValueError("章程不存在，请先生成草案")

            if charter.draft_content:
                promoted = normalize_charter_draft(charter.draft_content)
                for field, value in promoted.items():
                    setattr(charter, field, value)

            if edits:
                normalized_edits = normalize_charter_draft(edits)
                for field in normalized_edits:
                    if field in edits:
                        setattr(charter, field, normalized_edits[field])

            charter.version += 1
            charter.source = RepoCharter.Source.HUMAN_CONFIRMED
            charter.confirmed_by = user
            charter.draft_content = {}
            charter.save()
            return charter

    charter = await sync_to_async(_confirm)()
    logger.info(
        "charter_confirmed",
        category="caller",
        component="charter_service",
        repository_id=str(repository_id),
        initiated_by_user_id=str(user.id),
        version=charter.version,
    )
    return charter
