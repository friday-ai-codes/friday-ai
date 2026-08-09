"""``affected_processes`` 单一方言组装（Phase 126 / EXEC-03 / D-07）。

纯函数：命中 symbol_id 或 ``file_path:name`` ∩ ProcessTrace.steps → 条目列表。
无 ORM；调用方一次加载仓分支 Process 集后传入，禁止第三套方言。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def assemble_affected_processes(
    *,
    hit_symbol_ids: set[str],
    hit_file_name_keys: set[str],
    processes: Sequence[Any],
) -> list[dict[str, Any]]:
    """Intersect impact/change hits with ProcessTrace steps (single dialect).

    Each returned dict: ``name`` / ``process_key`` / ``affected_steps`` /
    ``total_steps`` / ``community_class`` / optional ``step`` (first hit index).
    No rows or no intersection → ``[]`` (fail-soft).
    """
    out: list[dict[str, Any]] = []
    for proc in processes:
        steps = getattr(proc, "steps", None) or []
        if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
            continue
        affected: list[int] = []
        for i, step in enumerate(steps):
            if not isinstance(step, Mapping):
                continue
            sid = str(step.get("symbol_id") or "")
            key = f"{step.get('file_path')}:{step.get('name')}"
            if (sid and sid in hit_symbol_ids) or key in hit_file_name_keys:
                affected.append(i)
        if not affected:
            continue
        total = getattr(proc, "step_count", None)
        if not isinstance(total, int) or total <= 0:
            total = len(steps)
        out.append(
            {
                "name": str(getattr(proc, "name", "") or ""),
                "process_key": str(getattr(proc, "process_key", "") or ""),
                "affected_steps": affected,
                "total_steps": total,
                "community_class": str(getattr(proc, "community_class", "") or ""),
                "step": affected[0],
            }
        )
    return out


def collect_hits_from_impact_payload(
    *,
    seed: Mapping[str, Any] | None,
    groups: Any,
) -> tuple[set[str], set[str]]:
    """Extract hit_symbol_ids / hit_file_name_keys from an impact envelope fragment."""
    hit_ids: set[str] = set()
    hit_keys: set[str] = set()

    def _add(item: Mapping[str, Any]) -> None:
        sid = str(item.get("symbol_id") or item.get("uid") or "")
        name = str(item.get("name") or "")
        fp = str(item.get("file_path") or "")
        if sid:
            hit_ids.add(sid)
        if fp and name:
            hit_keys.add(f"{fp}:{name}")

    if isinstance(seed, Mapping):
        _add(seed)

    if isinstance(groups, Mapping):
        for rows in groups.values():
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                continue
            for item in rows:
                if isinstance(item, Mapping):
                    _add(item)
    elif isinstance(groups, Sequence) and not isinstance(groups, (str, bytes)):
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            items = group.get("items")
            if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
                continue
            for item in items:
                if isinstance(item, Mapping):
                    _add(item)

    return hit_ids, hit_keys


def collect_hits_from_detect_changes(
    *,
    files: Sequence[Any],
    impacts: Sequence[Any],
) -> tuple[set[str], set[str]]:
    """Union hits from detect_changes file symbols + per-seed impact envelopes."""
    hit_ids: set[str] = set()
    hit_keys: set[str] = set()

    for group in files:
        if not isinstance(group, Mapping):
            continue
        path = str(group.get("path") or "")
        for sym in group.get("symbols") or []:
            if not isinstance(sym, Mapping):
                continue
            uid = str(sym.get("uid") or "")
            name = str(sym.get("name") or "")
            if uid:
                hit_ids.add(uid)
            fp = str(sym.get("file_path") or path)
            if fp and name:
                hit_keys.add(f"{fp}:{name}")

    for entry in impacts:
        if not isinstance(entry, Mapping):
            continue
        sid = str(entry.get("symbol_id") or entry.get("uid") or "")
        if sid:
            hit_ids.add(sid)
        impact = entry.get("impact")
        if not isinstance(impact, Mapping):
            continue
        seed = impact.get("seed")
        if not isinstance(seed, Mapping) and sid:
            seed = {"symbol_id": sid}
        ids, keys = collect_hits_from_impact_payload(
            seed=seed if isinstance(seed, Mapping) else None,
            groups=impact.get("groups"),
        )
        hit_ids |= ids
        hit_keys |= keys

    return hit_ids, hit_keys


__all__ = [
    "assemble_affected_processes",
    "collect_hits_from_detect_changes",
    "collect_hits_from_impact_payload",
]
