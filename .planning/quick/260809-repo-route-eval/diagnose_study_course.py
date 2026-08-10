"""定位 study-course 到底死在哪一层（只读）。

四层逐层验尸：
  L1 单探针：8 个探针各自看 study-course 的最佳节点排第几
  L2 融合后：8 路 RRF 融合的 top-N 里还有没有它
  L3 仓级聚合：进没进 stage0_candidates（STAGE0_REPO_K=12）
  L4 LLM：进了候选还是被 opus 排掉
"""

from __future__ import annotations

import asyncio
import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from route_eval import GROUND_TRUTH, SPACE_ID, build_features_flat  # noqa: E402

SC = "47991a7f-c8e4-4da6-b42c-2ce81d8b137f"  # backend/study-course


def _rank_of(hits: list[dict], repo_id: str) -> tuple[int | None, int]:
    """返回 (最佳排名, 命中节点数)。"""
    best = None
    count = 0
    for i, h in enumerate(hits or [], 1):
        if str((h.get("payload") or {}).get("repository_id", "")) == repo_id:
            count += 1
            if best is None:
                best = i
    return best, count


async def main() -> None:
    from asgiref.sync import sync_to_async

    from codegraph.services.repo_router_v2 import (
        COLLECTION_NAME,
        RepoRouterV2,
        _stage0_node_k,
    )
    from initiatives.services.repo_association_service import RepoAssociationService
    from projects.models import Space
    from services.qdrant_service import QdrantService
    from services.query_embedding import embed_query
    from services.sparse_encoder import SparseEncoderService

    def _load():
        sp = Space.objects.get(id=SPACE_ID)
        return [str(r) for r in sp.repositories.values_list("id", flat=True)]

    repo_ids = await sync_to_async(_load)()
    flat = await sync_to_async(build_features_flat)(include_test_case=True)
    query = RepoAssociationService._build_query(flat)
    node_k = _stage0_node_k()
    filters = {"repository_id": repo_ids}

    embedded = await embed_query(query, drop_noise=False)
    sparse = await sync_to_async(SparseEncoderService.encode)(query)
    print(json.dumps({
        "query_len": len(query), "probes": len(embedded.vectors), "node_k": node_k
    }, ensure_ascii=False))

    # ---------- L1 单探针 ----------
    print("\n=== L1 每个探针单独看（top_k=node_k）：study-course 的最佳节点排名 ===")
    for i, vec in enumerate(embedded.vectors, 1):
        hits = await sync_to_async(QdrantService.hybrid_search_by_name)(
            COLLECTION_NAME, vec, sparse, top_k=node_k, filters=filters
        )
        rank, cnt = _rank_of(hits, SC)
        head = (embedded.segments[i - 1][:40].replace("\n", " ")) if i <= len(embedded.segments) else ""
        print(f"  探针{i}: study-course {'#%d (%d 节点)' % (rank, cnt) if rank else '未命中'}"
              f"   | 块首: {head}…")

    # ---------- L2 融合后 ----------
    print("\n=== L2 8 路 RRF 融合后（生产路径）===")
    fused = await sync_to_async(QdrantService.hybrid_search_multi_by_name)(
        COLLECTION_NAME, embedded.vectors, sparse, top_k=node_k,
        prefetch_limit=node_k, filters=filters,
    )
    rank, cnt = _rank_of(fused, SC)
    print(f"  融合 top-{node_k} 共 {len(fused)} 个节点，覆盖 "
          f"{len({str((h.get('payload') or {}).get('repository_id')) for h in fused})} 个仓")
    print(f"  study-course: {'#%d（%d 节点）' % (rank, cnt) if rank else '⛔ 不在融合结果里'}")
    for rid, name in GROUND_TRUTH.items():
        r, c = _rank_of(fused, rid)
        print(f"    {name:<34} {'#%-5d %d 节点' % (r, c) if r else '未命中'}")

    # 融合结果里各仓占了多少节点（看广度偏置）
    by_repo: dict[str, int] = {}
    for h in fused:
        p = h.get("payload") or {}
        by_repo[str(p.get("repo_name") or p.get("repository_id"))] = (
            by_repo.get(str(p.get("repo_name") or p.get("repository_id")), 0) + 1
        )
    print("\n  融合结果里节点数最多的 8 个仓（广度偏置观察）:")
    for name, n in sorted(by_repo.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {name:<38} {n} 节点")

    # ---------- L3 仓级聚合 ----------
    print("\n=== L3 仓级聚合后（route use_llm=False，top_k=30）===")
    r0 = await RepoRouterV2.route(
        query, top_k=30, repository_ids=repo_ids, use_llm=False, corpus_kind="requirement"
    )
    for i, c in enumerate(r0.candidates, 1):
        mark = "✅" if str(c.repo_id) in GROUND_TRUTH else "  "
        print(f"  {mark}{i:<3}{c.repo_name:<38}{round(float(c.score), 4)}")
    in_stage0 = any(str(c.repo_id) == SC for c in r0.candidates)
    print(f"  study-course 进入仓级候选: {in_stage0}")

    # ---------- L4 LLM ----------
    print("\n=== L4 Stage 1 LLM 之后（top_k=5）===")
    r1 = await RepoRouterV2.route(
        query, top_k=5, repository_ids=repo_ids, use_llm=True, corpus_kind="requirement"
    )
    for c in r1.candidates:
        mark = "✅" if str(c.repo_id) in GROUND_TRUTH else "  "
        print(f"  {mark}{c.repo_name:<38}{round(float(c.score), 4)}  {c.confidence}")
    print(f"  结论：study-course 在 L3 {'进了' if in_stage0 else '没进'}，"
          f"在 L4 {'进了' if any(str(c.repo_id) == SC for c in r1.candidates) else '没进'}")


if __name__ == "__main__":
    asyncio.run(main())
