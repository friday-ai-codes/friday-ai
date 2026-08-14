"""章程角色图（Phase 129，ROLE-01/02/03；D-02、D-11~D-14）。

对 shortlist 逐仓映射固定四角色枚举，产出 primary|supporting|forbidden；
触碰 boundaries 无 override → 不得 primary；无法映射的拥有域 → clarify(unmapped_role)。
导出 ``placement_defaults`` 供 Phase 130 放置单元消费（本模块不实现放置算法）。

观测：``role_map_started/completed/failed``，``category=sampling``，无需求原文。
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = [
    "RepoRole",
    "RoleMapResult",
    "PLACEMENT_DEFAULTS",
    "build_role_map",
    "map_domain_to_role",
]

_COMPONENT = "process_runtime"
_MAX_REASON_CHARS = 240


class RepoRole(str, Enum):
    """固定小枚举（D5 / D-02）——不可扩展。"""

    APP_SHELL = "app_shell"
    PRACTICE_REUSE_HOST = "practice_reuse_host"
    COURSE_CONFIG = "course_config"
    LEARNING_STATE = "learning_state"


PLACEMENT_DEFAULTS: dict[str, Any] = {
    # learning_state 写方不得默认落在 app_shell primary（D-13）
    "learning_state_writer_not_app_shell": True,
    "practice_reuse_prefers_host_not_shell": True,
    "course_config_not_learning_state_writer": True,
}

# 领域关键词 → 角色（不硬编码仓 UUID，D-14）
_DOMAIN_KEYWORDS: list[tuple[RepoRole, tuple[str, ...]]] = [
    (
        RepoRole.APP_SHELL,
        ("app壳", "app 壳", "壳导航", "壳容器", "导航容器", "宿主壳", "前端壳"),
    ),
    (
        RepoRole.PRACTICE_REUSE_HOST,
        ("做题复用", "复用宿主", "练习引擎", "练习宿主", "practice", "题库宿主"),
    ),
    (
        RepoRole.COURSE_CONFIG,
        ("课程配置", "课程大纲", "课程目录", "course config", "课程内容目录"),
    ),
    (
        RepoRole.LEARNING_STATE,
        ("学习状态", "学习进度", "进度记录", "learning state", "学情状态"),
    ),
]


@dataclass
class RoleMapResult:
    status: str = "ok"
    clarify_reason: str = ""
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)
    per_repo: list[dict[str, Any]] = field(default_factory=list)
    placement_defaults: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


def map_domain_to_role(domain_text: str) -> RepoRole | None:
    """启发式 domain/note → 四角色；无法映射返回 None。"""
    text = str(domain_text or "").strip().lower()
    if not text:
        return None
    for role, keywords in _DOMAIN_KEYWORDS:
        for kw in keywords:
            if kw.lower() in text:
                return role
    return None


def _empty_roles() -> dict[str, dict[str, Any]]:
    return {
        role.value: {"primary": None, "supporting": [], "forbidden": []}
        for role in RepoRole
    }


def build_role_map(
    *,
    shortlist_repos: Sequence[str] | None = None,
    charters_by_repo: Mapping[str, Mapping[str, Any] | None] | None = None,
    profile: Mapping[str, Any] | None = None,  # noqa: ARG001 — 预留画像对照
    override_reasons: Mapping[str, str] | None = None,
    violated_boundaries_by_repo: Mapping[str, Sequence[str]] | None = None,
    query_terms: Sequence[str] | None = None,  # noqa: ARG001 — 预留
) -> RoleMapResult:
    """对 shortlist 逐仓映射角色并导出 placement_defaults。"""
    started = time.perf_counter()
    repo_ids = [str(r) for r in (shortlist_repos or []) if str(r or "").strip()]
    charters = dict(charters_by_repo or {})
    overrides = {
        str(k): str(v).strip()[:_MAX_REASON_CHARS]
        for k, v in (override_reasons or {}).items()
        if str(v or "").strip()
    }
    violated_map = {
        str(k): [str(x) for x in (v or []) if str(x or "").strip()]
        for k, v in (violated_boundaries_by_repo or {}).items()
    }

    logger.info(
        "role_map_started",
        shortlist_count=len(repo_ids),
        category="sampling",
        component=_COMPONENT,
    )

    try:
        roles = _empty_roles()
        per_repo: list[dict[str, Any]] = []
        unmapped_owned = False

        # 第一遍：逐仓推断角色与 assignment
        scored: list[tuple[str, RepoRole | None, str, list[str], dict[str, Any]]] = []
        for rid in repo_ids:
            charter = charters.get(rid) if isinstance(charters.get(rid), dict) else {}
            domains = charter.get("owned_domains") if isinstance(charter, dict) else []
            domain_texts: list[str] = []
            if isinstance(domains, list):
                for item in domains:
                    if not isinstance(item, dict):
                        continue
                    domain = str(item.get("domain") or "").strip()
                    note = str(item.get("note") or "").strip()
                    if domain:
                        domain_texts.append(f"{domain} {note}".strip())

            mapped_role: RepoRole | None = None
            for text in domain_texts:
                mapped_role = map_domain_to_role(text)
                if mapped_role is not None:
                    break

            if domain_texts and mapped_role is None:
                # 章程声明拥有却无法映射 → clarify
                unmapped_owned = True

            violated = list(violated_map.get(rid) or [])
            if not violated and isinstance(charter, dict):
                # 若调用方未显式传入，尝试从 score 语义：本模块不做 query 打分，
                # 仅当 boundaries 非空且调用方传入 violated 才降级（测试显式传入）
                pass

            override = overrides.get(rid, "")
            if violated and not override:
                assignment = "forbidden"
            elif violated and override:
                assignment = "supporting"  # 可保留非 forbidden，仍不宜默认 primary
            elif mapped_role is None:
                assignment = "supporting"
            else:
                assignment = "primary"

            evidence = []
            if domain_texts:
                evidence.append({"matched_domains": domain_texts[:5]})
            if violated:
                evidence.append({"violated_boundaries": violated[:5]})
            if override:
                evidence.append({"boundary_override_reason": override})

            scored.append(
                (
                    rid,
                    mapped_role,
                    assignment,
                    violated,
                    {
                        "repository_id": rid,
                        "role": mapped_role.value if mapped_role else "",
                        "assignment": assignment,
                        "evidence": evidence,
                        "violated_boundaries": violated,
                        "boundary_override_reason": override,
                        "charter_source": str((charter or {}).get("source") or ""),
                        "charter_version": int((charter or {}).get("version") or 0)
                        if str((charter or {}).get("version") or "").isdigit()
                        or isinstance((charter or {}).get("version"), int)
                        else 0,
                    },
                )
            )

        # 按角色选 primary：每个角色取第一个 assignment=primary 且角色匹配的仓
        claimed: set[str] = set()
        for role in RepoRole:
            primary_id = None
            for rid, mapped_role, assignment, violated, entry in scored:
                if mapped_role != role:
                    continue
                if assignment == "forbidden":
                    roles[role.value]["forbidden"].append(rid)
                    continue
                if assignment == "primary" and primary_id is None and rid not in claimed:
                    primary_id = rid
                    claimed.add(rid)
                elif assignment in ("primary", "supporting"):
                    if rid != primary_id:
                        roles[role.value]["supporting"].append(rid)
            roles[role.value]["primary"] = primary_id
            # 若曾是 primary 候选但因 boundary 变 forbidden，已进 forbidden

        # 补：forbidden 未归入角色桶的（无映射）
        for rid, mapped_role, assignment, violated, entry in scored:
            if assignment == "forbidden" and mapped_role is None:
                # 挂到第一个角色的 forbidden 以便可观测；更干净是只留 per_repo
                pass
            # 若 mapped 为 primary 但该角色 primary 已被占 → demote supporting
            if (
                assignment == "primary"
                and mapped_role is not None
                and roles[mapped_role.value]["primary"] != rid
            ):
                entry["assignment"] = "supporting"
                if rid not in roles[mapped_role.value]["supporting"]:
                    roles[mapped_role.value]["supporting"].append(rid)
            if (
                assignment == "forbidden"
                and mapped_role is not None
                and rid not in roles[mapped_role.value]["forbidden"]
            ):
                roles[mapped_role.value]["forbidden"].append(rid)
            per_repo.append(entry)

        # 去重 supporting/forbidden
        for role in RepoRole:
            bucket = roles[role.value]
            bucket["supporting"] = list(dict.fromkeys(bucket["supporting"]))
            bucket["forbidden"] = list(dict.fromkeys(bucket["forbidden"]))
            # primary 不得出现在 forbidden
            if bucket["primary"] in bucket["forbidden"]:
                bucket["primary"] = None

        status = "clarify" if unmapped_owned else "ok"
        clarify_reason = "unmapped_role" if unmapped_owned else ""
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        result = RoleMapResult(
            status=status,
            clarify_reason=clarify_reason,
            roles=roles,
            per_repo=per_repo,
            placement_defaults=dict(PLACEMENT_DEFAULTS),
            duration_ms=duration_ms,
        )
        logger.info(
            "role_map_completed",
            shortlist_count=len(repo_ids),
            status=status,
            clarify_reason=clarify_reason or "",
            primary_count=sum(1 for r in roles.values() if r.get("primary")),
            duration_ms=duration_ms,
            category="sampling",
            component=_COMPONENT,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.warning(
            "role_map_failed",
            error=redact_secrets_in_text(str(exc)),
            duration_ms=duration_ms,
            category="sampling",
            component=_COMPONENT,
        )
        return RoleMapResult(
            status="ok",
            roles=_empty_roles(),
            per_repo=[],
            placement_defaults=dict(PLACEMENT_DEFAULTS),
            duration_ms=duration_ms,
        )
