"""仓库章程起草与确认服务（CHARTER-01 / DESIGN §5.7，RepoCharter 唯一写入入口 INV-6）。

三源蒸馏起草管道（镜像 ``services/process_runtime/decompose_segments.py`` 的 LLM
五步骨架）：``ai_summary``/``facets``（仓库摘要与语义分面）+ 近期 MR 历史（哪类需求
实际落在此仓）+ verified/rejected ``RepoAssociation``（verified 作 owned 证据、
rejected 作 boundaries 候选）→ 单轮 LLM 蒸馏 → :func:`normalize_charter_draft`
白名单归一 → 落库。LLM 不可用/解析失败一律 best-effort 返回 ``None``、零副作用；
**落库失败抛 :class:`CharterPersistError`**（DB 写错误不是「供应商未配置」，视图层
据此区分 500 与 503——MJ-02）。

Append-only 契约（D-02/D-04/D-05）：基线行存在后，自动化只写 ``appendices`` /
``change_proposals`` 并持久化 ``baseline_fingerprint``；正式字段与 ``draft_content``
仅经 :func:`aconfirm_charter`（edits / 批准提案）变更。首次无行时可创建基线。

LLM 调用赋 ``call_source=blueprint_charter_draft``（LOGGING-SPEC §4.1），观测事件
含 ``charter_draft_*`` / ``charter_baseline_created`` / ``charter_material_change_skipped``
等（category=caller，component=charter_service），异常文本经 ``redact_secrets_in_text``
脱敏后入日志。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from common.logging import redact_secrets_in_text

if TYPE_CHECKING:
    from repositories.models import RepoCharter

logger = structlog.get_logger(__name__)

__all__ = [
    "adraft_charter",
    "aconfirm_charter",
    "aapply_charter_from_runner",
    "normalize_charter_draft",
    "compute_charter_fingerprint",
    "classify_charter_delta",
    "resolve_fingerprint_for_repository",
    "CharterPersistError",
]

_FORMAL_FIELDS = (
    "positioning",
    "owned_domains",
    "boundaries",
    "placement_preferences",
    "audience",
    "form",
    "evolution",
)
_MERGE_KEYS = {
    "owned_domains": ("domain",),
    "boundaries": ("rule",),
    "placement_preferences": ("kind", "target"),
}
_SCALAR_FIELDS = ("positioning", "audience", "form", "evolution")
_LIST_FIELDS = ("owned_domains", "boundaries", "placement_preferences")


class CharterPersistError(RuntimeError):
    """章程草案落库失败（DB 写错误 / 唯一约束重试仍失败）。

    与「上游模型不可用」严格区分：后者 best-effort 返回 ``None``（视图 503），
    本异常是**业务写失败**，必须上抛让视图回 500——不得伪装成「供应商未配置」
    把运维引向错误的排查方向。
    """


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


def _extract_paths_for_fingerprint(tree_or_paths: Any) -> list[str]:
    """从 tree 节点列表 / 路径字符串列表提取稳定 path/node_id 集合。"""
    if tree_or_paths is None:
        return []
    paths: list[str] = []
    if isinstance(tree_or_paths, list):
        for item in tree_or_paths:
            if isinstance(item, str):
                if item.strip():
                    paths.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            raw_paths = item.get("paths")
            if isinstance(raw_paths, list):
                paths.extend(str(p).strip() for p in raw_paths if str(p).strip())
            elif isinstance(raw_paths, str) and raw_paths.strip():
                paths.append(raw_paths.strip())
            single = item.get("path")
            if isinstance(single, str) and single.strip():
                paths.append(single.strip())
            for key in ("node_id", "id"):
                nid = item.get(key)
                if nid is not None and str(nid).strip():
                    paths.append(f"id:{str(nid).strip()}")
        return sorted(set(paths))
    if isinstance(tree_or_paths, dict):
        # nested tree: walk children
        stack = [tree_or_paths]
        while stack:
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            raw_paths = node.get("paths")
            if isinstance(raw_paths, list):
                paths.extend(str(p).strip() for p in raw_paths if str(p).strip())
            for key in ("node_id", "id"):
                nid = node.get(key)
                if nid is not None and str(nid).strip():
                    paths.append(f"id:{str(nid).strip()}")
            children = node.get("children")
            if isinstance(children, list):
                stack.extend(children)
        return sorted(set(paths))
    return []


def compute_charter_fingerprint(
    overview: Any,
    tree_or_paths: Any,
    facets: Any,
) -> str:
    """对 overview + tree paths/node_ids + facets 做稳定 SHA-256 指纹（64 hex）。"""
    payload = {
        "overview": str(overview or "").strip(),
        "paths": _extract_paths_for_fingerprint(tree_or_paths),
        "facets": {
            str(k): str(v)
            for k, v in sorted((facets or {}).items())
            if isinstance(facets, dict)
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def resolve_fingerprint_for_repository(
    repo: Any,
    *,
    fingerprint: str | None = None,
    stored: str = "",
) -> str:
    """解析本次应持久化的指纹。

    显式传入优先；否则从 Repository overview/tree/facets 计算；证据不可读时保留
    已有非空 stored，绝不把非空指纹清空成 ``""``。
    """
    if fingerprint is not None and str(fingerprint).strip():
        return str(fingerprint).strip()[:64]
    try:
        overview = getattr(repo, "overview_text", None) or ""
        tree = getattr(repo, "ai_summary_tree", None)
        facets = getattr(repo, "facets", None) if isinstance(getattr(repo, "facets", None), dict) else {}
        computed = compute_charter_fingerprint(overview, tree, facets)
        if computed:
            return computed
    except Exception:  # noqa: BLE001 — 证据不可读时回退 stored
        pass
    return (stored or "")[:64]


def _merge_key(field: str, item: Any) -> tuple[str, ...]:
    keys = _MERGE_KEYS[field]
    src = item if isinstance(item, dict) else {}
    return tuple(str(src.get(key) or "") for key in keys)


def _item_core_without_citations(item: dict[str, Any]) -> dict[str, Any]:
    core = {k: v for k, v in item.items() if k != "citations"}
    return core


def _citation_only_evidence(base: dict[str, Any], incoming: dict[str, Any]) -> bool:
    """同 key 且非 citations 字段字节相等，且 incoming 的 citations 有新增。"""
    if _item_core_without_citations(base) != _item_core_without_citations(incoming):
        return False
    base_cits = {str(c) for c in (base.get("citations") or []) if str(c)}
    new_cits = {str(c) for c in (incoming.get("citations") or []) if str(c)}
    return bool(new_cits - base_cits)


def _formal_snapshot(charter: Any) -> dict[str, Any]:
    return {field: getattr(charter, field) for field in _FORMAL_FIELDS}


def classify_charter_delta(
    baseline_fields: dict[str, Any],
    incoming_normalized: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """对照基线与 incoming，产出 appendices additions / change_proposals。

    分类表见 plan D-04/D-05：新 list key 与 citation-only → additions；
    标量变更、删除、同 key 语义变更 → proposals。
    """
    additions: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    now_iso = timezone.now().isoformat()

    for field in _SCALAR_FIELDS:
        before = baseline_fields.get(field) or ""
        after = incoming_normalized.get(field) or ""
        if before != after:
            proposals.append(
                {
                    "id": str(uuid.uuid4()),
                    "status": "pending",
                    "field": field,
                    "before": before,
                    "after": after,
                    "reason": "scalar_change",
                    "recorded_at": now_iso,
                }
            )

    for field in _LIST_FIELDS:
        base_list = [i for i in (baseline_fields.get(field) or []) if isinstance(i, dict)]
        inc_list = [i for i in (incoming_normalized.get(field) or []) if isinstance(i, dict)]
        base_map = {_merge_key(field, i): i for i in base_list}
        inc_map = {_merge_key(field, i): i for i in inc_list}

        for key, item in inc_map.items():
            if key not in base_map:
                additions.append(
                    {
                        "id": str(uuid.uuid4()),
                        "kind": field,
                        "item": item,
                        "reason": "new_key",
                        "recorded_at": now_iso,
                    }
                )
                continue
            base_item = base_map[key]
            if base_item == item:
                continue
            if _citation_only_evidence(base_item, item):
                additions.append(
                    {
                        "id": str(uuid.uuid4()),
                        "kind": f"{field}_citation",
                        "item": item,
                        "key": list(key),
                        "reason": "citation_only",
                        "recorded_at": now_iso,
                    }
                )
            else:
                proposals.append(
                    {
                        "id": str(uuid.uuid4()),
                        "status": "pending",
                        "field": field,
                        "key": list(key),
                        "before": base_item,
                        "after": item,
                        "reason": "same_key_semantic",
                        "recorded_at": now_iso,
                    }
                )

        for key, item in base_map.items():
            if key not in inc_map:
                proposals.append(
                    {
                        "id": str(uuid.uuid4()),
                        "status": "pending",
                        "field": field,
                        "key": list(key),
                        "before": item,
                        "after": None,
                        "reason": "removal",
                        "recorded_at": now_iso,
                    }
                )

    return {"additions": additions, "proposals": proposals}


def _append_side_channels(
    charter: Any,
    *,
    additions: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
) -> tuple[int, int]:
    """把 additions/proposals 追加到侧信道；返回新增条数。"""
    appendices = list(charter.appendices or [])
    change_proposals = list(charter.change_proposals or [])
    appendices.extend(additions)
    change_proposals.extend(proposals)
    charter.appendices = appendices
    charter.change_proposals = change_proposals
    return len(additions), len(proposals)


def _persist_fingerprint_and_lock(
    charter: Any,
    fingerprint: str,
    *,
    update_fields: list[str],
) -> bool:
    """写入 fingerprint；若 locked_at 为空则补写。返回是否新设 locked_at。"""
    charter.baseline_fingerprint = (fingerprint or "")[:64]
    locked_now = False
    if charter.baseline_locked_at is None:
        charter.baseline_locked_at = timezone.now()
        locked_now = True
        if "baseline_locked_at" not in update_fields:
            update_fields.append("baseline_locked_at")
    if "baseline_fingerprint" not in update_fields:
        update_fields.append("baseline_fingerprint")
    if "updated_at" not in update_fields:
        update_fields.append("updated_at")
    return locked_now


def apply_automation_to_existing_charter(
    charter: Any,
    incoming_normalized: dict[str, Any],
    *,
    fingerprint: str,
    repository_id: str,
    initiated_by_user_id: str,
    started: float,
) -> Any:
    """对已有行执行门禁：相等指纹 skip 增长；否则 classify 侧信道；永不改正式/draft。"""
    stored_fp = (charter.baseline_fingerprint or "").strip()
    observed = (fingerprint or "").strip()[:64]

    if stored_fp and observed and stored_fp == observed:
        update_fields: list[str] = []
        _persist_fingerprint_and_lock(charter, observed, update_fields=update_fields)
        charter.save(update_fields=update_fields)
        try:
            logger.info(
                "charter_material_change_skipped",
                category="caller",
                component="charter_service",
                repository_id=str(repository_id),
                initiated_by_user_id=initiated_by_user_id,
                fingerprint=observed,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            logger.info(
                "charter_fingerprint_persisted",
                category="caller",
                component="charter_service",
                repository_id=str(repository_id),
                initiated_by_user_id=initiated_by_user_id,
                fingerprint=observed,
                reason="no_material_change",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬
            pass
        return charter

    delta = classify_charter_delta(_formal_snapshot(charter), incoming_normalized)
    n_add, n_prop = _append_side_channels(
        charter, additions=delta["additions"], proposals=delta["proposals"]
    )
    update_fields = ["appendices", "change_proposals"]
    _persist_fingerprint_and_lock(charter, observed, update_fields=update_fields)
    charter.save(update_fields=update_fields)
    try:
        if n_add:
            logger.info(
                "charter_appendix_appended",
                category="caller",
                component="charter_service",
                repository_id=str(repository_id),
                initiated_by_user_id=initiated_by_user_id,
                count=n_add,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        if n_prop:
            logger.info(
                "charter_proposal_recorded",
                category="caller",
                component="charter_service",
                repository_id=str(repository_id),
                initiated_by_user_id=initiated_by_user_id,
                count=n_prop,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        logger.info(
            "charter_fingerprint_persisted",
            category="caller",
            component="charter_service",
            repository_id=str(repository_id),
            initiated_by_user_id=initiated_by_user_id,
            fingerprint=observed,
            additions=n_add,
            proposals=n_prop,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
    except Exception:  # noqa: BLE001 — 观测绝不反噬
        pass
    return charter


def create_baseline_charter(
    repo: Any,
    draft: dict[str, Any],
    *,
    fingerprint: str,
) -> Any:
    """首次建行：写入正式字段 + fingerprint + locked_at。"""
    from repositories.models import RepoCharter

    now = timezone.now()
    return RepoCharter.objects.create(
        repository=repo,
        source=RepoCharter.Source.AI_DRAFT,
        version=1,
        baseline_fingerprint=(fingerprint or "")[:64],
        baseline_locked_at=now,
        appendices=[],
        change_proposals=[],
        draft_content={},
        **{k: draft[k] for k in _FORMAL_FIELDS if k in draft},
    )


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
    recent_releases: list[dict[str, str]] | None = None,
) -> str:
    parts: list[str] = []
    parts.append("## 仓库摘要\n" + (overview.strip() or "（暂无 AI 摘要）"))
    if facets:
        facet_lines = "\n".join(f"- {k}: {v}" for k, v in facets.items())
        parts.append("## 语义分面\n" + facet_lines)
    if recent_mrs:
        mr_lines = "\n".join(f"- [{m['status']}] {m['title']}" for m in recent_mrs)
        parts.append("## 近期 MR\n" + mr_lines)
    if recent_releases:
        rel_lines = "\n".join(
            f"- {r.get('date') or '未知日期'}: {r.get('title') or '（无标题）'}"
            for r in recent_releases
        )
        parts.append("## 近期上线记录（已关联到本仓）\n" + rel_lines)
    if associations:
        assoc_lines = "\n".join(
            f"- [{a['status']}] {a['routed_reason'] or '（无路由理由）'}" for a in associations
        )
        parts.append(
            "## 关联裁决（confirmed/verified→owned 证据、rejected→边界候选）\n" + assoc_lines
        )
    parts.append("请输出该仓库的章程草案 JSON。")
    return "\n\n".join(parts)


def _draft_failed(
    reason: str,
    *,
    repository_id: str,
    initiated_by_user_id: str,
    started: float,
    error: str | None = None,
) -> None:
    """起草失败观测事件（上游不可用类，warning 级——业务侧 best-effort 返回 None）。"""
    logger.warning(
        "charter_draft_failed",
        category="caller",
        component="charter_service",
        repository_id=str(repository_id),
        initiated_by_user_id=initiated_by_user_id,
        reason=reason,
        error=error,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )


async def _agenerate_draft(
    repo: Any,
    *,
    repository_id: str,
    initiated_by_user_id: str,
    started: float,
    provider_credential_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any] | None:
    """三源蒸馏 → LLM 单调用 → 解析归一；上游不可用/解析失败一律返回 ``None``。

    ``try`` 只包「LLM 调用」与「解析」两段（MJ-02）：ORM 读失败与编程错误照常上抛，
    不被压成「供应商未配置」。
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.call_source import CallSource, use_call_source
    from agents.llm_concurrency import acquire_llm_slot
    from agents.llm_factory import build_chat_model
    from services.provider_config import ProviderConfigService, ProviderMissingError

    # ── 三源蒸馏输入（ORM 一律 sync_to_async，P1）─────────────────────────────
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

        # confirmed 是人工确认常态；verified 是深验终态——起草都要吃到，否则
        # 生产里大量 confirmed 关联会被静默丢掉（实测 1058 confirmed / 0 verified）。
        return [
            {"status": assoc.status, "routed_reason": assoc.routed_reason}
            for assoc in RepoAssociation.objects.filter(
                repository_id=repository_id,
                status__in=["confirmed", "verifying", "verified", "rejected"],
            ).order_by("-updated_at")[:_RECENT_LIMIT]
        ]

    def _load_recent_releases() -> list[dict[str, str]]:
        """经 RELATES_TO（metadata.source="artifact"）边反查已挂到本仓的上线记录标题。

        ⭐ 按**工件类型**（`type__key="release_record"`）筛选而非按导入来源筛选：
        挂仓边统一是 `source="artifact"`（官方 `RepoRouterV2` 管线与 bitable 回填
        归一后同一形状，quick-260809 续作），来源只在 `origin` 留痕——按 origin 过滤
        会漏掉官方管线以后挂上来的上线记录。
        """
        from initiatives.models import Artifact
        from knowledge.models import (
            EdgeRelation,
            EntityKind,
            KnowledgeEdge,
            KnowledgeEntity,
            KnowledgeEntityVersion,
            generate_entity_id,
        )

        repo_node = generate_entity_id(EntityKind.REPOSITORY, "repository", str(repository_id))
        # 不能在边这一步就截 _RECENT_LIMIT：挂仓边里混着需求文档等其他工件，
        # 先截会把真正的上线记录挤掉（study-app 有上千条边）。
        candidate_ids = list(
            KnowledgeEdge.objects.filter(
                target_entity_id=repo_node,
                relation=EdgeRelation.RELATES_TO,
                invalid_at__isnull=True,
                expired_at__isnull=True,
                metadata__source="artifact",
            ).values_list("source_entity_id", flat=True)
        )
        if not candidate_ids:
            return []
        entities = list(
            KnowledgeEntity.objects.filter(id__in=candidate_ids, source_kind="artifact").only(
                "id", "title", "source_id"
            )
        )
        release_artifact_ids = {
            str(aid)
            for aid in Artifact.objects.filter(
                id__in=[e.source_id for e in entities if e.source_id],
                type__key="release_record",
            ).values_list("id", flat=True)
        }
        source_ids = [e.id for e in entities if str(e.source_id) in release_artifact_ids]
        if not source_ids:
            return []
        titles = {str(e.id): (e.title or "") for e in entities}
        out: list[dict[str, str]] = []
        for ver in (
            KnowledgeEntityVersion.objects.filter(entity_id__in=source_ids, is_latest=True)
            .only("entity_id", "payload")
            .order_by("-event_time")[:_RECENT_LIMIT]
        ):
            out.append(
                {
                    "title": titles.get(str(ver.entity_id), "")[:200],
                    "date": str((ver.payload or {}).get("release_date") or "")[:32],
                }
            )
        return out

    recent_mrs = await sync_to_async(_load_recent_mrs)()
    associations = await sync_to_async(_load_associations)()
    recent_releases = await sync_to_async(_load_recent_releases)()

    # ── LLM 五步骨架（镜像 decompose_segments）────────────────────────────────
    try:
        if provider_credential_id:
            resolved = await ProviderConfigService.aresolve_or_error(
                node_config={"provider_credential_id": provider_credential_id}
            )
            if isinstance(resolved, ProviderMissingError):
                _draft_failed(
                    "provider_missing",
                    repository_id=repository_id,
                    initiated_by_user_id=initiated_by_user_id,
                    started=started,
                    error=str(resolved),
                )
                return None
        else:
            resolved = await ProviderConfigService.aresolve()
        model_name = (model or "").strip() or (getattr(resolved, "extra", None) or {}).get(
            "default_model", ""
        )
        if not model_name:
            _draft_failed(
                "no_default_model",
                repository_id=repository_id,
                initiated_by_user_id=initiated_by_user_id,
                started=started,
            )
            return None

        model_obj = build_chat_model(resolved, model_name, streaming=False)
        messages = [
            SystemMessage(content=_system_prompt()),
            HumanMessage(
                content=_build_prompt(
                    overview=overview,
                    facets=facets,
                    recent_mrs=recent_mrs,
                    associations=associations,
                    recent_releases=recent_releases,
                )
            ),
        ]
        cred_id = str(getattr(resolved, "credential_id", "") or provider_credential_id or "")
        max_c = int(getattr(resolved, "max_concurrency", 0) or 0)
        with use_call_source(CallSource.BLUEPRINT_CHARTER_DRAFT):
            async with acquire_llm_slot(cred_id, max_c):
                response = await model_obj.ainvoke(messages)
    except Exception as exc:  # noqa: BLE001 — 上游不可用 → best-effort None
        _draft_failed(
            "llm_error",
            repository_id=repository_id,
            initiated_by_user_id=initiated_by_user_id,
            started=started,
            error=redact_secrets_in_text(str(exc)),
        )
        return None

    try:
        raw = _parse_charter_json(_content_to_text(response.content))
    except Exception as exc:  # noqa: BLE001 — 畸形响应体 → best-effort None
        _draft_failed(
            "parse_failed",
            repository_id=repository_id,
            initiated_by_user_id=initiated_by_user_id,
            started=started,
            error=redact_secrets_in_text(str(exc)),
        )
        return None
    if raw is None:
        _draft_failed(
            "parse_failed",
            repository_id=repository_id,
            initiated_by_user_id=initiated_by_user_id,
            started=started,
        )
        return None
    return normalize_charter_draft(raw)


async def adraft_charter(
    repository_id: str,
    *,
    initiated_by_user_id: str = "system",
    provider_credential_id: str | None = None,
    model: str | None = None,
    fingerprint: str | None = None,
) -> RepoCharter | None:
    """AI 起草仓库章程（三源蒸馏 → LLM 单调用 → 归一化落库）。

    - 仓库不存在：``Repository.DoesNotExist`` 上抛（视图层转 404）。
    - LLM 不可用（无 provider/default_model）/ 上游报错 / 解析失败：返回 ``None``，
      不落任何行（首次起草场景零副作用）——视图层回 503。
    - 落库失败（DB 写错误）：``CharterPersistError`` 上抛（视图层回 500）。
    - 落库语义（append-only）：无 charter → 建基线；已有行 → classify 侧信道 +
      指纹持久化，**永不**改正式字段或 ``draft_content``。
    - ``fingerprint`` 可选；省略时从 Repository 证据计算，证据不可用则保留已存非空指纹。
    """
    from repositories.models import RepoCharter, Repository

    repo = await Repository.objects.aget(id=repository_id)  # DoesNotExist 上抛 → 视图转 404

    started = time.monotonic()
    logger.info(
        "charter_draft_started",
        category="caller",
        component="charter_service",
        repository_id=str(repository_id),
        initiated_by_user_id=initiated_by_user_id,
        provider_credential_id=provider_credential_id or "",
        model=model or "",
    )

    draft = await _agenerate_draft(
        repo,
        repository_id=str(repository_id),
        initiated_by_user_id=initiated_by_user_id,
        started=started,
        provider_credential_id=provider_credential_id,
        model=model,
    )
    if draft is None:
        return None

    def _write() -> RepoCharter:
        from django.db import transaction

        with transaction.atomic():
            charter = RepoCharter.objects.select_for_update().filter(repository=repo).first()
            observed = resolve_fingerprint_for_repository(
                repo,
                fingerprint=fingerprint,
                stored=(charter.baseline_fingerprint if charter else "") or "",
            )
            if charter is None:
                created = create_baseline_charter(repo, draft, fingerprint=observed)
                try:
                    logger.info(
                        "charter_baseline_created",
                        category="caller",
                        component="charter_service",
                        repository_id=str(repository_id),
                        initiated_by_user_id=initiated_by_user_id,
                        fingerprint=observed,
                        duration_ms=round((time.monotonic() - started) * 1000, 2),
                    )
                except Exception:  # noqa: BLE001
                    pass
                return created
            return apply_automation_to_existing_charter(
                charter,
                draft,
                fingerprint=observed,
                repository_id=str(repository_id),
                initiated_by_user_id=initiated_by_user_id,
                started=started,
            )

    def _persist() -> RepoCharter:
        from django.db import IntegrityError

        try:
            return _write()
        except IntegrityError:
            # MN-05：并发首次起草撞 OneToOne → 重跑读-改（此时行已存在 → 侧信道）
            return _write()

    try:
        charter = await sync_to_async(_persist)()
    except Exception as exc:
        logger.error(
            "charter_draft_failed",
            category="caller",
            component="charter_service",
            repository_id=str(repository_id),
            initiated_by_user_id=initiated_by_user_id,
            reason="persist_error",
            error=redact_secrets_in_text(str(exc)),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        raise CharterPersistError("章程草案落库失败") from exc

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


async def aapply_charter_from_runner(
    repository_id: str,
    charter_payload: dict[str, Any],
    *,
    evidence: dict[str, Any] | None = None,
    fingerprint: str,
    initiated_by_user_id: str = "system",
) -> RepoCharter | None:
    """Runner ``submit_summary.charter`` 一等产出落库（D-01）。

    - 无行 → 建基线（正式字段 + fingerprint + locked_at）。
    - 有行 → classify 侧信道 + 指纹持久化；指纹相等则 skip 增长。
    - best-effort：异常脱敏日志后返回 ``None``（summary 回调不得失败）。
    """
    from repositories.models import RepoCharter, Repository

    started = time.monotonic()
    try:
        repo = await Repository.objects.aget(id=repository_id)
    except Exception:  # noqa: BLE001
        return None

    draft = normalize_charter_draft(charter_payload)
    evidence = evidence if isinstance(evidence, dict) else {}
    observed = (fingerprint or "").strip()[:64]
    if not observed:
        observed = resolve_fingerprint_for_repository(
            repo,
            fingerprint=None,
            stored="",
        )
        if evidence:
            observed = compute_charter_fingerprint(
                evidence.get("overview"),
                evidence.get("tree") or evidence.get("paths"),
                evidence.get("facets"),
            ) or observed

    def _write() -> RepoCharter:
        from django.db import IntegrityError, transaction

        def _inner() -> RepoCharter:
            with transaction.atomic():
                charter = RepoCharter.objects.select_for_update().filter(repository=repo).first()
                if charter is None:
                    created = create_baseline_charter(repo, draft, fingerprint=observed)
                    try:
                        logger.info(
                            "charter_baseline_created",
                            category="caller",
                            component="charter_service",
                            repository_id=str(repository_id),
                            initiated_by_user_id=initiated_by_user_id,
                            fingerprint=observed,
                            source="runner",
                            duration_ms=round((time.monotonic() - started) * 1000, 2),
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    return created
                return apply_automation_to_existing_charter(
                    charter,
                    draft,
                    fingerprint=observed,
                    repository_id=str(repository_id),
                    initiated_by_user_id=initiated_by_user_id,
                    started=started,
                )

        try:
            return _inner()
        except IntegrityError:
            return _inner()

    try:
        return await sync_to_async(_write)()
    except Exception as exc:  # noqa: BLE001 — best-effort
        try:
            logger.warning(
                "charter_apply_from_runner_failed",
                category="caller",
                component="charter_service",
                repository_id=str(repository_id),
                initiated_by_user_id=initiated_by_user_id,
                error=redact_secrets_in_text(str(exc)),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001
            pass
        return None


def _apply_proposal_to_formal(charter: Any, proposal: dict[str, Any]) -> None:
    """把单条已批准提案应用到正式字段。"""
    field = proposal.get("field")
    if field in _SCALAR_FIELDS:
        after = proposal.get("after")
        setattr(charter, field, after if after is not None else "")
        return
    if field not in _LIST_FIELDS:
        return
    after = proposal.get("after")
    reason = proposal.get("reason")
    items = [i for i in (getattr(charter, field) or []) if isinstance(i, dict)]
    key_tuple = tuple(proposal.get("key") or ())
    if reason == "removal" or after is None:
        items = [i for i in items if _merge_key(field, i) != key_tuple]
    else:
        replaced = False
        new_items: list[dict[str, Any]] = []
        for i in items:
            if _merge_key(field, i) == key_tuple:
                new_items.append(after if isinstance(after, dict) else i)
                replaced = True
            else:
                new_items.append(i)
        if not replaced and isinstance(after, dict):
            new_items.append(after)
        items = new_items
    setattr(charter, field, items)


async def aconfirm_charter(
    repository_id: str,
    user: Any,
    *,
    edits: dict[str, Any] | None = None,
    approve_proposal_ids: list[str] | None = None,
    reject_proposal_ids: list[str] | None = None,
) -> RepoCharter:
    """人工确认章程生效：草案提升 + edits + 提案批准/拒绝 + version+1。

    - charter 不存在且 ``edits`` 为非空 dict：按 edits 归一后直接创建
      ``source=human_confirmed`` / ``version=1``。
    - charter 不存在且无 edits → ``ValueError``（视图层转 404）。
    - ``draft_content`` 非空：先提升为正式字段（人工路径残留）。
    - ``approve_proposal_ids``：把 pending 提案 after 写入正式字段并标 approved。
    - ``reject_proposal_ids``：仅标 rejected，不改正式字段。
    - 非法 id 忽略并打日志。
    """
    from repositories.models import RepoCharter, Repository

    started = time.monotonic()
    created = False
    approve_ids = {str(x) for x in (approve_proposal_ids or []) if str(x).strip()}
    reject_ids = {str(x) for x in (reject_proposal_ids or []) if str(x).strip()}

    def _confirm() -> tuple[RepoCharter, bool]:
        from django.db import transaction

        with transaction.atomic():
            charter = (
                RepoCharter.objects.select_for_update().filter(repository_id=repository_id).first()
            )
            if charter is None:
                if not isinstance(edits, dict) or not edits:
                    raise ValueError("章程不存在，请先生成草案")
                if not Repository.objects.filter(pk=repository_id).exists():
                    raise ValueError("章程不存在，请先生成草案")
                normalized = normalize_charter_draft(edits)
                new_charter = RepoCharter.objects.create(
                    repository_id=repository_id,
                    source=RepoCharter.Source.HUMAN_CONFIRMED,
                    version=1,
                    confirmed_by=user,
                    draft_content={},
                    baseline_locked_at=timezone.now(),
                    **normalized,
                )
                return new_charter, True

            if charter.draft_content:
                promoted = normalize_charter_draft(charter.draft_content)
                for field, value in promoted.items():
                    setattr(charter, field, value)

            if edits:
                normalized_edits = normalize_charter_draft(edits)
                for field in normalized_edits:
                    if field in edits:
                        setattr(charter, field, normalized_edits[field])

            proposals = list(charter.change_proposals or [])
            known_ids = {str(p.get("id")) for p in proposals if isinstance(p, dict)}
            for bad in (approve_ids | reject_ids) - known_ids:
                try:
                    logger.info(
                        "charter_proposal_id_ignored",
                        category="caller",
                        component="charter_service",
                        repository_id=str(repository_id),
                        initiated_by_user_id=str(user.id),
                        proposal_id=bad,
                    )
                except Exception:  # noqa: BLE001
                    pass

            approved_n = 0
            rejected_n = 0
            for prop in proposals:
                if not isinstance(prop, dict):
                    continue
                pid = str(prop.get("id") or "")
                if pid in approve_ids and prop.get("status") == "pending":
                    _apply_proposal_to_formal(charter, prop)
                    prop["status"] = "approved"
                    approved_n += 1
                elif pid in reject_ids and prop.get("status") == "pending":
                    prop["status"] = "rejected"
                    rejected_n += 1
            charter.change_proposals = proposals

            charter.version += 1
            charter.source = RepoCharter.Source.HUMAN_CONFIRMED
            charter.confirmed_by = user
            charter.draft_content = {}
            if charter.baseline_locked_at is None:
                charter.baseline_locked_at = timezone.now()
            charter.save()
            try:
                if approved_n:
                    logger.info(
                        "charter_proposal_approved",
                        category="caller",
                        component="charter_service",
                        repository_id=str(repository_id),
                        initiated_by_user_id=str(user.id),
                        count=approved_n,
                        duration_ms=round((time.monotonic() - started) * 1000, 2),
                    )
                if rejected_n:
                    logger.info(
                        "charter_proposal_rejected",
                        category="caller",
                        component="charter_service",
                        repository_id=str(repository_id),
                        initiated_by_user_id=str(user.id),
                        count=rejected_n,
                        duration_ms=round((time.monotonic() - started) * 1000, 2),
                    )
            except Exception:  # noqa: BLE001
                pass
            return charter, False

    try:
        charter, created = await sync_to_async(_confirm)()
    except ValueError:
        raise
    except Exception as exc:
        try:
            logger.error(
                "charter_confirm_failed",
                category="caller",
                component="charter_service",
                repository_id=str(repository_id),
                initiated_by_user_id=str(user.id),
                error=redact_secrets_in_text(str(exc)),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬
            pass
        raise

    logger.info(
        "charter_confirmed",
        category="caller",
        component="charter_service",
        repository_id=str(repository_id),
        initiated_by_user_id=str(user.id),
        version=charter.version,
        created=created,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return charter
