"""团队硬门禁（Phase 128，TEAM-01/02/03；锁定 D1/D3）。

解析 ``team_core``、标注 ``team_core|team_adjacent|out_of_team``，空/缺团队
返回 clarify，禁止静默全库 primary。``team_adjacent`` 仅预留枚举，本相位无证据
时不得升 primary。

**不**调用 / 改写 ``RepoRouterV2``。
"""

from __future__ import annotations

import time
from collections.abc import Collection, Mapping, Sequence
from enum import Enum
from typing import Any

import structlog
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)

__all__ = [
    "TeamMembership",
    "resolve_team_core",
    "annotate_team_membership",
    "apply_team_gate",
    "filter_indexed_repository_ids",
    "alist_team_options",
    "aresolve_accessible_space_id",
    "match_team_answer",
]

_COMPONENT = "process_runtime"

#: 团队澄清一次最多回几个候选取值（防把整份 facet 字典糊给人看）。
_MAX_TEAM_OPTIONS = 20


class TeamMembership(str, Enum):
    """候选相对 team_core 的隶属标注。"""

    TEAM_CORE = "team_core"
    TEAM_ADJACENT = "team_adjacent"
    OUT_OF_TEAM = "out_of_team"


def _as_id_set(values: Collection[str] | None) -> set[str]:
    if not values:
        return set()
    return {str(v) for v in values if str(v or "").strip()}


@sync_to_async
def _load_space_repo_ids(space_id: str) -> list[str] | None:
    from projects.models import Space

    space = Space.objects.filter(pk=space_id).first()
    if space is None:
        return None
    return [str(r) for r in space.repositories.values_list("id", flat=True)]


@sync_to_async
def filter_indexed_repository_ids(repository_ids: Collection[str]) -> list[str]:
    """返回已索引（``index_status=indexed``）的仓库 id 子集。"""
    from repositories.models import IndexStatus, Repository

    ids = [str(r) for r in repository_ids if str(r or "").strip()]
    if not ids:
        return []
    return [
        str(r)
        for r in Repository.objects.filter(
            id__in=ids, index_status=IndexStatus.INDEXED, is_deleted=False
        ).values_list("id", flat=True)
    ]


@sync_to_async
def _load_project_repo_ids(
    project_id: str,
) -> tuple[str | None, list[str] | None, list[str] | None]:
    """读取 Project 责任仓，并独立返回所属 Space 的可访问仓库宇宙。"""
    from initiatives.models import Project, RepoAssociationStatus

    project = Project.objects.select_related("space").filter(pk=project_id).first()
    if project is None or project.space is None:
        return None, None, None
    space_id = str(project.space_id)
    team_repo_ids = [
        str(r)
        for r in project.repo_associations.filter(
            status__in=[RepoAssociationStatus.CONFIRMED, RepoAssociationStatus.VERIFIED]
        ).values_list("repository_id", flat=True)
    ]
    accessible_repo_ids = [str(r) for r in project.space.repositories.values_list("id", flat=True)]
    return space_id, team_repo_ids, accessible_repo_ids


@sync_to_async
def _load_team_repo_ids(team_name: str) -> list[str]:
    """按 Repository.facets 的真实“团队归属”字段解析责任团队。"""
    from repositories.models import Repository

    expected = str(team_name or "").strip().casefold()
    if not expected:
        return []
    matched: list[str] = []
    for repository in Repository.objects.filter(is_deleted=False).only("id", "facets"):
        facets = repository.facets if isinstance(repository.facets, dict) else {}
        raw = facets.get("团队归属")
        values = raw if isinstance(raw, list) else [raw]
        if any(str(value or "").strip().casefold() == expected for value in values):
            matched.append(str(repository.id))
    return matched


@sync_to_async
def alist_team_options(space_id: str) -> list[dict[str, Any]]:
    """枚举某 Space 内已索引仓库真实出现过的 ``团队归属`` 取值及其仓数。

    团队澄清必须**带候选**：``options=[]`` 逼人自由作答，答复无从校验，采纳不了就只能
    反复问同一题（AGE-66 的死循环成因）。这里只回 facet 里**真实存在**的取值 —— 问一个
    答了也解析不出仓的团队名毫无意义。

    ``space_id`` 空 → 返回空列表（fail-closed：解析不出可访问范围时不得枚举全库团队）。
    """
    from projects.models import Space
    from repositories.models import IndexStatus

    sid = str(space_id or "").strip()
    if not sid:
        return []
    space = Space.objects.filter(pk=sid).first()
    if space is None:
        return []
    counts: dict[str, int] = {}
    queryset = space.repositories.filter(
        index_status=IndexStatus.INDEXED, is_deleted=False
    ).only("id", "facets")
    for repository in queryset:
        facets = repository.facets if isinstance(repository.facets, dict) else {}
        raw = facets.get("团队归属")
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            label = str(value or "").strip()
            if label:
                counts[label] = counts.get(label, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"team": team, "repo_count": n} for team, n in ranked[:_MAX_TEAM_OPTIONS]]


@sync_to_async
def _load_work_item_space_id(work_item_id: Any) -> str:
    from delivery.models import WorkItem

    if work_item_id is None:
        return ""
    work_item = WorkItem.objects.filter(id=work_item_id).only("space_id").first()
    return str(work_item.space_id) if work_item and work_item.space_id else ""


async def aresolve_accessible_space_id(session: Any) -> str:
    """解析会话的可访问 Space id（``stage_state`` 优先，回落到宿主工作项）。

    ⭐ Space 只界定**可访问仓库宇宙**，不代表责任团队 —— 本函数的结果只能用于枚举候选
    团队取值与求交，⛔ 不得当成 ``team_core``。
    """
    # 函数内 lazy import 规避 import 环（blueprint_route 在模块加载期 import 本模块）。
    from services.process_runtime.blueprint_route import _extract_team_context

    try:
        _, space_id, _ = _extract_team_context(session)
    except Exception:  # noqa: BLE001 — 解析失败回落工作项，绝不阻断
        space_id = ""
    if space_id:
        return space_id
    try:
        return await _load_work_item_space_id(getattr(session, "work_item_id", None))
    except Exception:  # noqa: BLE001
        return ""


def match_team_answer(answer: str, options: Sequence[Mapping[str, Any]]) -> str:
    """把人类的团队澄清答复解析成**唯一**的权威团队名（解析不出回空串）。

    两档匹配，都要求唯一命中：

    1. 整段答复 casefold 后与某取值全串相等（人只回了团队名）。
    2. 某取值作为子串出现在答复里（人回了带解释的整句）。

    ⛔ 命中多个取值时一律回空串 —— 猜一个等于替人做范围决策，宁可带着候选再问一次。
    """
    text = str(answer or "").strip()
    if not text:
        return ""
    labels = [str((o or {}).get("team") or "").strip() for o in options]
    labels = [label for label in labels if label]
    if not labels:
        return ""
    folded = text.casefold()
    exact = [label for label in labels if label.casefold() == folded]
    if len(exact) == 1:
        return exact[0]
    contained = [label for label in labels if label.casefold() in folded]
    return contained[0] if len(contained) == 1 else ""


async def resolve_team_core(
    *,
    project_id: str | None = None,
    project: Any = None,
    space: Any = None,
    space_id: str | None = None,
    team_id: str | None = None,
    primary_team: str | None = None,
    context_space_id: str | None = None,
    indexed_repository_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """独立解析责任 Team；Space 只提供可访问仓库宇宙。

    ``indexed_repository_ids`` 非 None 时做 ``mounted ∩ indexed``；交集空 →
    ``empty_team_core``。仅显式传 ``None`` 表示调用方未做索引探测（漏斗层不得
    长期绕过）。
    """
    resolution = "missing"
    resolved_space_id: str | None = None
    accessible: list[str] = []
    mounted: list[str] = []
    clarify_reason = ""

    # ① Project 挂载 Space
    pid = str(project_id or "") or (
        str(getattr(project, "id", "") or "") if project is not None else ""
    )
    if project is not None and getattr(project, "space", None) is not None:
        resolved_space_id = str(
            getattr(project, "space_id", "") or getattr(project.space, "id", "")
        )
        try:
            if hasattr(project.space, "repositories"):
                accessible = [
                    str(r)
                    for r in await sync_to_async(
                        lambda: list(project.space.repositories.values_list("id", flat=True))
                    )()
                ]
            mounted = [
                str(r)
                for r in await sync_to_async(
                    lambda: list(
                        project.repo_associations.filter(
                            status__in=["confirmed", "verified"]
                        ).values_list("repository_id", flat=True)
                    )
                )()
            ]
            resolution = "project_associations"
        except Exception:  # noqa: BLE001 — ORM 失败继续下级解析
            mounted = []
    elif pid:
        try:
            sid, repos, space_repos = await _load_project_repo_ids(pid)
        except Exception:  # noqa: BLE001
            sid, repos, space_repos = None, None, None
        if sid is not None:
            resolved_space_id = sid
            mounted = list(repos or [])
            accessible = list(space_repos or [])
            resolution = "project_associations"

    # ② Space 只解析可访问范围；team_id/primary_team 才表示责任 Team。
    explicit_space_id = str(space_id or "").strip()
    explicit_team = str(team_id or primary_team or "").strip()
    if not resolved_space_id and space is not None:
        resolved_space_id = str(getattr(space, "id", "") or "")
        try:
            accessible = [
                str(r)
                for r in await sync_to_async(
                    lambda: list(space.repositories.values_list("id", flat=True))
                )()
            ]
            resolution = "space_only"
        except Exception:  # noqa: BLE001
            accessible = []
            resolution = "space_only"
    elif not resolved_space_id and explicit_space_id:
        resolved_space_id = explicit_space_id
        try:
            repos = await _load_space_repo_ids(explicit_space_id)
        except Exception:  # noqa: BLE001
            repos = None
        if repos is None:
            clarify_reason = "missing_team"
            resolution = "explicit_missing"
            accessible = []
        else:
            accessible = list(repos)
            resolution = "space_only"

    # ③ 上下文 Space
    ctx = str(context_space_id or "").strip()
    if not resolved_space_id and ctx:
        resolved_space_id = ctx
        try:
            repos = await _load_space_repo_ids(ctx)
        except Exception:  # noqa: BLE001
            repos = None
        if repos is None:
            clarify_reason = "missing_team"
            resolution = "context_missing"
            accessible = []
        else:
            accessible = list(repos)
            resolution = "space_only"

    if explicit_team:
        team_ids = list(await _load_team_repo_ids(explicit_team))
        accessible_set = _as_id_set(accessible)
        mounted = [rid for rid in team_ids if not accessible_set or rid in accessible_set]
        resolution = "team_facet"

    if not resolved_space_id and not mounted:
        return {
            "team_core": [],
            "space_id": None,
            "resolution": "missing",
            "clarify_reason": "missing_team",
            "should_clarify": True,
            "accessible_repository_ids": [],
        }

    if clarify_reason == "missing_team":
        return {
            "team_core": [],
            "space_id": resolved_space_id,
            "resolution": resolution,
            "clarify_reason": "missing_team",
            "should_clarify": True,
            "accessible_repository_ids": accessible,
        }

    if not mounted:
        reason = (
            "empty_team_core"
            if not accessible or indexed_repository_ids is not None
            else "missing_team"
        )
        return {
            "team_core": [],
            "space_id": resolved_space_id,
            "resolution": resolution,
            "clarify_reason": reason,
            "should_clarify": True,
            "accessible_repository_ids": accessible,
        }

    team_core = list(mounted)
    if indexed_repository_ids is not None:
        indexed = _as_id_set(indexed_repository_ids)
        team_core = [rid for rid in team_core if rid in indexed]
        if not team_core:
            return {
                "team_core": [],
                "space_id": resolved_space_id,
                "resolution": resolution,
                "clarify_reason": "empty_team_core",
                "should_clarify": True,
                "accessible_repository_ids": accessible,
            }

    return {
        "team_core": team_core,
        "space_id": resolved_space_id,
        "resolution": resolution,
        "clarify_reason": "",
        "should_clarify": False,
        "accessible_repository_ids": accessible,
    }


def annotate_team_membership(
    candidates: Sequence[Mapping[str, Any]] | None,
    team_core: Collection[str] | None,
    *,
    adjacent_ids: Collection[str] | None = None,
) -> list[dict[str, Any]]:
    """为候选标注 team_membership；adjacent 仅在显式 adjacent_ids 时标记。"""
    core = _as_id_set(team_core)
    adjacent = _as_id_set(adjacent_ids)
    out: list[dict[str, Any]] = []
    for raw in candidates or []:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        rid = str(item.get("repository_id") or item.get("repo_id") or item.get("id") or "").strip()
        if rid and rid in core:
            membership = TeamMembership.TEAM_CORE.value
        elif rid and rid in adjacent:
            membership = TeamMembership.TEAM_ADJACENT.value
        else:
            membership = TeamMembership.OUT_OF_TEAM.value
        item["team_membership"] = membership
        item["repository_id"] = rid or str(item.get("repository_id") or item.get("repo_id") or "")
        out.append(item)
    return out


def apply_team_gate(
    *,
    resolve_result: Mapping[str, Any] | None = None,
    candidates: Sequence[Mapping[str, Any]] | None = None,
    team_core: Collection[str] | None = None,
    adjacent_ids: Collection[str] | None = None,
    offer: Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Hard gate：primary 仅 team_core；空/缺团队 clarify（D1/D3）。"""
    started = time.monotonic()
    resolved = dict(resolve_result or {})
    core = list(team_core) if team_core is not None else list(resolved.get("team_core") or [])
    clarify_reason = str(resolved.get("clarify_reason") or "")
    should_clarify = bool(resolved.get("should_clarify")) or clarify_reason in {
        "missing_team",
        "empty_team_core",
    }

    if should_clarify or not core:
        reason = clarify_reason or (
            "empty_team_core" if resolved.get("space_id") else "missing_team"
        )
        payload = {
            "status": "clarify",
            "clarify_reason": reason,
            "candidates": [],
            "team_core": [],
            "team_core_count": 0,
            "space_id": resolved.get("space_id"),
            "offer": dict(offer) if offer else {"bind_space": True},
            "profile": dict(profile) if profile else None,
            "primary": None,
        }
        try:
            logger.info(
                "team_gate_completed",
                category="sampling",
                component=_COMPONENT,
                team_core_count=0,
                gate_outcome="clarify",
                clarify_reason=reason,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001
            pass
        return payload

    annotated = annotate_team_membership(candidates, core, adjacent_ids=adjacent_ids)
    primary_pool = [
        c for c in annotated if c.get("team_membership") == TeamMembership.TEAM_CORE.value
    ]
    # out_of_team / adjacent 保留旁路，不可作 primary
    bypass = [c for c in annotated if c.get("team_membership") != TeamMembership.TEAM_CORE.value]
    primary = primary_pool[0] if primary_pool else None

    payload = {
        "status": "ok",
        "clarify_reason": "",
        "candidates": primary_pool,
        "bypass_candidates": bypass,
        "team_core": list(core),
        "team_core_count": len(core),
        "space_id": resolved.get("space_id"),
        "offer": dict(offer) if offer else None,
        "profile": dict(profile) if profile else None,
        "primary": primary,
    }
    try:
        logger.info(
            "team_gate_completed",
            category="sampling",
            component=_COMPONENT,
            team_core_count=len(core),
            gate_outcome="ok",
            clarify_reason="",
            primary_count=len(primary_pool),
            out_of_team_count=sum(
                1 for c in annotated if c.get("team_membership") == TeamMembership.OUT_OF_TEAM.value
            ),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
    except Exception:  # noqa: BLE001
        pass
    return payload
