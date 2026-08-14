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
]

_COMPONENT = "process_runtime"


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
def _load_project_space_repo_ids(project_id: str) -> tuple[str | None, list[str] | None]:
    from initiatives.models import Project

    project = Project.objects.select_related("space").filter(pk=project_id).first()
    if project is None or project.space is None:
        return None, None
    space_id = str(project.space_id)
    repo_ids = [str(r) for r in project.space.repositories.values_list("id", flat=True)]
    return space_id, repo_ids


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
    """解析 team_core：Project→Space → 显式 space/team → 上下文 Space。

    ``indexed_repository_ids`` 非 None 时做 ``mounted ∩ indexed``；交集空 →
    ``empty_team_core``。仅显式传 ``None`` 表示调用方未做索引探测（漏斗层不得
    长期绕过）。
    """
    resolution = "missing"
    resolved_space_id: str | None = None
    mounted: list[str] = []
    clarify_reason = ""

    # ① Project 挂载 Space
    pid = str(project_id or "") or (
        str(getattr(project, "id", "") or "") if project is not None else ""
    )
    if project is not None and getattr(project, "space", None) is not None:
        resolved_space_id = str(getattr(project, "space_id", "") or getattr(project.space, "id", ""))
        try:
            if hasattr(project.space, "repositories"):
                mounted = [
                    str(r)
                    for r in await sync_to_async(
                        lambda: list(project.space.repositories.values_list("id", flat=True))
                    )()
                ]
            resolution = "project_space"
        except Exception:  # noqa: BLE001 — ORM 失败继续下级解析
            mounted = []
    elif pid:
        try:
            sid, repos = await _load_project_space_repo_ids(pid)
        except Exception:  # noqa: BLE001
            sid, repos = None, None
        if sid is not None:
            resolved_space_id = sid
            mounted = list(repos or [])
            resolution = "project_space"

    # ② 显式 space_id / team_id（primary_team 别名）
    explicit = (
        str(space_id or "").strip()
        or str(team_id or "").strip()
        or str(primary_team or "").strip()
    )
    if not resolved_space_id and space is not None:
        resolved_space_id = str(getattr(space, "id", "") or "")
        try:
            mounted = [
                str(r)
                for r in await sync_to_async(
                    lambda: list(space.repositories.values_list("id", flat=True))
                )()
            ]
            resolution = "explicit_space"
        except Exception:  # noqa: BLE001
            mounted = []
            resolution = "explicit_space"
    elif not resolved_space_id and explicit:
        resolved_space_id = explicit
        try:
            repos = await _load_space_repo_ids(explicit)
        except Exception:  # noqa: BLE001
            repos = None
        if repos is None:
            clarify_reason = "missing_team"
            resolution = "explicit_missing"
            mounted = []
        else:
            mounted = list(repos)
            resolution = "explicit_space"

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
            mounted = []
        else:
            mounted = list(repos)
            resolution = "context_space"

    if not resolved_space_id:
        return {
            "team_core": [],
            "space_id": None,
            "resolution": "missing",
            "clarify_reason": "missing_team",
            "should_clarify": True,
        }

    if clarify_reason == "missing_team":
        return {
            "team_core": [],
            "space_id": resolved_space_id,
            "resolution": resolution,
            "clarify_reason": "missing_team",
            "should_clarify": True,
        }

    if not mounted:
        return {
            "team_core": [],
            "space_id": resolved_space_id,
            "resolution": resolution,
            "clarify_reason": "empty_team_core",
            "should_clarify": True,
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
            }

    return {
        "team_core": team_core,
        "space_id": resolved_space_id,
        "resolution": resolution,
        "clarify_reason": "",
        "should_clarify": False,
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
        rid = str(
            item.get("repository_id")
            or item.get("repo_id")
            or item.get("id")
            or ""
        ).strip()
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
        reason = clarify_reason or ("empty_team_core" if resolved.get("space_id") else "missing_team")
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
    primary_pool = [c for c in annotated if c.get("team_membership") == TeamMembership.TEAM_CORE.value]
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
