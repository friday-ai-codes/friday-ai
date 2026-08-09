"""``affected_processes`` 单一方言组装（Phase 126 / EXEC-03 / D-07）。

纯函数：命中 symbol_id 或 ``file_path:name`` ∩ ProcessTrace.steps → 条目列表。
无 ORM；调用方一次加载仓分支 Process 集后传入，禁止第三套方言。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
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
    raise NotImplementedError("126-03: assemble_affected_processes")


def collect_hits_from_impact_payload(
    *,
    seed: Mapping[str, Any] | None,
    groups: Any,
) -> tuple[set[str], set[str]]:
    """Extract hit_symbol_ids / hit_file_name_keys from an impact envelope fragment."""
    raise NotImplementedError("126-03: collect_hits_from_impact_payload")


__all__ = [
    "assemble_affected_processes",
    "collect_hits_from_impact_payload",
]
