"""量出 study-course 与压过它的仓在**每个信号**上的差距（只读）。

上一轮把「breadth 被多探针放大」当成根因，但 breadth 是对数饱和的软计数
（n_eff = Σ(s_hat_i/s_hat_top)^p，再 log1p 饱和到 n_cap=6），未必是真正的分手信号。
六信号加性可拆（INV-R3：Σbreakdown == score），直接看拆解即可定位。
"""

from __future__ import annotations

import asyncio
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from route_eval import GROUND_TRUTH, SPACE_ID, build_features_flat  # noqa: E402

SC = "47991a7f-c8e4-4da6-b42c-2ce81d8b137f"


async def main() -> None:
    from asgiref.sync import sync_to_async

    from codegraph.services.repo_router_v2 import (
        COLLECTION_NAME,
        STAGE0_REPO_K_WIDE,
        RepoRouterV2,
        _stage0_node_k,
    )
    from codegraph.services.repo_router_scoring import aggregate_and_score
    from codegraph.services.repo_router_config import aload_weight_config
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

    embedded = await embed_query(query, drop_noise=False)
    sparse = await sync_to_async(SparseEncoderService.encode)(query)
    node_k = _stage0_node_k()
    hits = await sync_to_async(QdrantService.hybrid_search_multi_by_name)(
        COLLECTION_NAME, embedded.vectors, sparse, top_k=node_k,
        prefetch_limit=node_k, filters={"repository_id": repo_ids},
    )

    config = await aload_weight_config()
    repo_meta, meta_stats = await RepoRouterV2._load_repo_meta(
        hits, query, embedded.primary, config, probe_vectors=embedded.vectors
    )
    consts = {**config["constants"], "n_bar": meta_stats.get("n_bar")}
    scored = aggregate_and_score(
        hits,
        weights=config["weights"],
        repo_meta=repo_meta,
        constants=consts,
        criticality_anchors=config.get("criticality_anchors"),
        now="2026-08-09T00:00:00+00:00",
    )[:STAGE0_REPO_K_WIDE]

    print(f"n_bar={meta_stats.get('n_bar')}  候选 {len(scored)} 仓\n")
    keys = ["text", "breadth", "activity", "domain", "stack", "team"]
    header = f"{'#':<4}{'仓':<38}{'score':<9}" + "".join(f"{k:<10}" for k in keys) + "n_r"
    print(header)
    print("-" * len(header))
    for i, c in enumerate(scored, 1):
        mark = "✅" if str(c.repo_id) in GROUND_TRUTH else "  "
        bd = c.breakdown or {}
        row = f"{mark}{i:<2}{c.repo_name:<38}{round(c.score, 4):<9}"
        row += "".join(f"{round(bd.get(k, 0.0), 4):<10}" for k in keys)
        n_r = (repo_meta.get(str(c.repo_id)) or {}).get("n_r")
        row += str(n_r)
        print(row)

    print("\n=== study-course vs 压过它的仓：逐信号差额 ===")
    sc = next((c for c in scored if str(c.repo_id) == SC), None)
    if sc is None:
        print("study-course 不在候选里")
        return
    sc_i = scored.index(sc)
    print(f"study-course 排 #{sc_i + 1}，score={round(sc.score, 4)}")
    for c in scored[:sc_i]:
        if str(c.repo_id) in GROUND_TRUTH:
            continue
        diffs = {
            k: round((c.breakdown or {}).get(k, 0.0) - (sc.breakdown or {}).get(k, 0.0), 4)
            for k in keys
        }
        biggest = max(diffs.items(), key=lambda kv: kv[1])
        print(f"  {c.repo_name:<38} 总差 {round(c.score - sc.score, 4):<9}"
              f" 最大来源: {biggest[0]}(+{biggest[1]})  全部: {diffs}")


if __name__ == "__main__":
    asyncio.run(main())
