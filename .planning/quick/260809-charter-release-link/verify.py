#!/usr/bin/env python3
"""验收：上线挂仓可见性 + 章程覆盖率 + 两条消费链是否真能取到数。

只读脚本，不写任何库。

Run from server/:
  uv run python ../.planning/quick/260809-charter-release-link/verify.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "server"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

from asgiref.sync import sync_to_async  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.db.models import Count  # noqa: E402

from initiatives.models import Artifact  # noqa: E402
from knowledge.artifact_associations import ArtifactAssociationService  # noqa: E402
from knowledge.models import EntityKind, KnowledgeEdge, KnowledgeEntity  # noqa: E402
from repositories.models import RepoCharter, Repository  # noqa: E402
from services.process_runtime.blueprint_route_history import (  # noqa: E402
    _resolve_repos_via_edges,
)


def _line(label: str, value) -> None:
    print(f"  {label:<38} {value}")


@sync_to_async
def _edge_stats() -> dict:
    total_release = Artifact.objects.filter(type__key="release_record").count()
    edges_artifact = KnowledgeEdge.objects.filter(metadata__source="artifact").count()
    edges_release = KnowledgeEdge.objects.filter(
        metadata__origin="release_bitable_import"
    ).count()
    legacy = KnowledgeEdge.objects.filter(metadata__source="release_bitable_import").count()
    linked_entities = (
        KnowledgeEdge.objects.filter(metadata__origin="release_bitable_import")
        .values("source_entity_id")
        .distinct()
        .count()
    )
    top = list(
        KnowledgeEdge.objects.filter(metadata__origin="release_bitable_import")
        .values("target_entity_id")
        .annotate(c=Count("id"))
        .order_by("-c")[:3]
    )
    return {
        "total_release": total_release,
        "edges_artifact": edges_artifact,
        "edges_release": edges_release,
        "legacy": legacy,
        "linked_entities": linked_entities,
        "top": top,
    }


@sync_to_async
def _charter_stats() -> dict:
    rows = list(RepoCharter.objects.values("source").annotate(c=Count("id")).order_by("-c"))
    return {
        "by_source": rows,
        "total": RepoCharter.objects.count(),
        "repos_with_summary": Repository.objects.filter(ai_summary_status="completed").count(),
    }


@sync_to_async
def _sample_release_entity_ids(limit: int = 200) -> list[str]:
    return [
        str(eid)
        for eid in KnowledgeEdge.objects.filter(metadata__origin="release_bitable_import")
        .values_list("source_entity_id", flat=True)
        .distinct()[:limit]
    ]


@sync_to_async
def _repo_source_id(node_id) -> str:
    ent = KnowledgeEntity.objects.filter(id=node_id, kind=EntityKind.REPOSITORY).first()
    return str(ent.source_id) if ent else ""


@sync_to_async
def _first_superuser():
    return get_user_model().objects.filter(is_superuser=True).first()


async def main() -> None:
    print("=== 1. 上线记录挂仓边 ===")
    stats = await _edge_stats()
    _line("上线记录工件总数", stats["total_release"])
    _line("已挂仓的上线实体数", stats["linked_entities"])
    _line("本次回填产出的边", stats["edges_release"])
    _line("source=artifact 边总数（含官方管线）", stats["edges_artifact"])
    _line("残留未归一的边（应为 0）", stats["legacy"])
    assert stats["legacy"] == 0, "仍有边用自造 source，关联卡片看不到"

    print("\n=== 2. 反查链（仓库详情/知识实体关联卡片读的就是它） ===")
    user = await _first_superuser()
    svc = ArtifactAssociationService()
    for row in stats["top"]:
        repo_id = await _repo_source_id(row["target_entity_id"])
        if not repo_id:
            continue
        rows = await svc.find_artifacts_by_repository(repo_id, user=user)
        name = await sync_to_async(
            lambda rid=repo_id: getattr(Repository.objects.filter(id=rid).first(), "name", "?")
        )()
        _line(f"{name} 反查工件数", f"{len(rows)}（其中上线边 {row['c']}）")
        assert rows, "归一化后反查仍为空——过滤条件或权限闸有问题"

    print("\n=== 3. 历史落点归因（blueprint_route_history 经图边归因） ===")
    entity_ids = await _sample_release_entity_ids()
    mapping = await _resolve_repos_via_edges(entity_ids)
    multi = sum(1 for v in mapping.values() if len(v) > 1)
    _line("抽样上线实体数", len(entity_ids))
    _line("成功归因到仓库的", len(mapping))
    _line("其中挂多仓的（FK 列表达不了的）", multi)
    assert mapping, "图边归因返回空——历史分量仍拿不到上线证据"

    print("\n=== 4. 仓库章程覆盖率 ===")
    charter = await _charter_stats()
    _line("有 AI 摘要的仓", charter["repos_with_summary"])
    _line("已有章程的仓", charter["total"])
    for row in charter["by_source"]:
        _line(f"  source={row['source']}", row["c"])

    print("\n全部验收项通过。")


if __name__ == "__main__":
    asyncio.run(main())
