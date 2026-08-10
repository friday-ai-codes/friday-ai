"""诊断 2：study-course 是否有能力树节点入库，以及它在节点级检索里的深度排名（只读）。"""

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


async def main() -> None:
    from asgiref.sync import sync_to_async

    from codegraph.services.repo_router_v2 import COLLECTION_NAME
    from initiatives.services.repo_association_service import RepoAssociationService
    from projects.models import Space
    from services.embedding import EmbeddingService
    from services.qdrant_service import QdrantService
    from services.sparse_encoder import SparseEncoderService

    def _load():
        sp = Space.objects.get(id=SPACE_ID)
        return [str(r) for r in sp.repositories.values_list("id", flat=True)]

    repo_ids = await sync_to_async(_load)()
    print("collection:", COLLECTION_NAME)

    # 1) 每个目标仓在能力树 collection 里的节点数（raw client count）
    from qdrant_client import models as qmodels

    client = await sync_to_async(QdrantService.get_client, thread_sensitive=False)()

    def _count(rid: str) -> int:
        return client.count(
            collection_name=COLLECTION_NAME,
            count_filter=qmodels.Filter(
                must=[qmodels.FieldCondition(
                    key="repository_id", match=qmodels.MatchValue(value=rid)
                )]
            ),
            exact=True,
        ).count

    print("\n=== 目标仓能力树节点数 ===")
    for rid, name in GROUND_TRUTH.items():
        try:
            n = await sync_to_async(_count, thread_sensitive=False)(rid)
        except Exception as exc:  # noqa: BLE001
            n = f"ERR {type(exc).__name__}: {exc}"
        print(f"  {name:<34} nodes={n}")

    # 2) 用生产 query 做节点级检索，看命中节点在各仓的分布（top-50 全局）
    flat = await sync_to_async(build_features_flat)(include_test_case=True)
    query = RepoAssociationService._build_query(flat)
    qs = await sync_to_async(SparseEncoderService.encode, thread_sensitive=False)(query)
    qd = await EmbeddingService.generate_embedding(query)

    for k in (50, 300, 1000):
        hits = await sync_to_async(QdrantService.hybrid_search_by_name, thread_sensitive=False)(
            COLLECTION_NAME, qd, qs, top_k=k, filters={"repository_id": repo_ids}
        )
        by_repo: dict[str, int] = {}
        first_rank: dict[str, int] = {}
        for i, h in enumerate(hits or [], 1):
            r = str((h.get("payload") or {}).get("repository_id", ""))
            by_repo[r] = by_repo.get(r, 0) + 1
            first_rank.setdefault(r, i)
        print(f"\n=== 节点级检索 top_k={k}：命中 {len(hits or [])} 节点，覆盖 {len(by_repo)} 个仓 ===")
        for rid, name in GROUND_TRUTH.items():
            if rid in by_repo:
                print(f"  ✅ {name:<34} 命中 {by_repo[rid]} 节点，最高排名 #{first_rank[rid]}")
            else:
                print(f"  ⛔ {name:<34} 0 节点")


if __name__ == "__main__":
    asyncio.run(main())
