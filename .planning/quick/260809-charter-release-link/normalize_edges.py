#!/usr/bin/env python3
"""把回填产出的上线挂仓边 metadata 归一到官方形状（source="artifact"）。

背景：`knowledge/artifact_associations.py` 正反两个方向都硬过滤
``metadata.source == "artifact"``，而 `backfill.py` 早期写的是自造的
``"release_bitable_import"``，导致 3154 条边在关联卡片里全部不可见。

归一而非放宽过滤条件：``source`` 语义是「关联种类」，官方 `RepoRouterV2` 管线
产出的 1512 条也是 ``"artifact"``；改数据零代码回归风险，且未来任何消费
``source=="artifact"`` 的地方自动生效。原来源改存 ``origin`` 保留留痕。

幂等：按 ``metadata__origin`` 判定已归一，重复跑只会补漏。

Run from server/:
  uv run python ../.planning/quick/260809-charter-release-link/normalize_edges.py --dry-run
  uv run python ../.planning/quick/260809-charter-release-link/normalize_edges.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "server"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

from knowledge.models import KnowledgeEdge  # noqa: E402

LEGACY_SOURCE = "release_bitable_import"
TARGET_SOURCE = "artifact"
BATCH = 500


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    stale = KnowledgeEdge.objects.filter(metadata__source=LEGACY_SOURCE)
    total = stale.count()
    already = KnowledgeEdge.objects.filter(
        metadata__source=TARGET_SOURCE, metadata__origin=LEGACY_SOURCE
    ).count()
    print(f"待归一: {total} | 已归一: {already}")
    if args.dry_run or total == 0:
        return

    updated = 0
    while True:
        rows = list(stale[:BATCH])
        if not rows:
            break
        for edge in rows:
            meta = dict(edge.metadata or {})
            meta["source"] = TARGET_SOURCE
            meta["origin"] = LEGACY_SOURCE
            edge.metadata = meta
        KnowledgeEdge.objects.bulk_update(rows, ["metadata"])
        updated += len(rows)
        print(f"  已归一 {updated}/{total}")

    print(f"完成: {updated} 条")
    print(
        "校验 source=artifact 总数:",
        KnowledgeEdge.objects.filter(metadata__source=TARGET_SOURCE).count(),
    )


if __name__ == "__main__":
    main()
