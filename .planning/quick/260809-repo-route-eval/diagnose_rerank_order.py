"""对照：聚合序 vs cross-encoder 精排序，看精排能否压住假阳性（只读）。

稳占高位的 study-app / study-practice / study-flow / study-stream /
new-course-builder-client 是聚合分高的假阳性。精排若能把它们排低，就该更信任精排；
若精排也把它们排高，问题在 rerank 文档的构造（喂给 cross-encoder 的材料不对）。
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

SUMMARY = (
    "高中数学培优课「极速提分营」：功能页入口与课程包权益鉴权、题型图谱、"
    "单题型学习页 4 节点解锁、真题检测、知识卡片、视频讲解、同型题检验、"
    "完成页反馈、学习进度与掌握程度"
)


async def main() -> None:
    from asgiref.sync import sync_to_async

    from codegraph.services.repo_router_v2 import (
        STAGE0_REPO_K_WIDE,
        RepoRouterV2,
        _stage0_node_k,
    )
    from initiatives.services.repo_association_service import RepoAssociationService
    from projects.models import Space
    from services.query_embedding import embed_query
    from services.reranker import RerankerService
    from services.sparse_encoder import SparseEncoderService

    def _load():
        sp = Space.objects.get(id=SPACE_ID)
        return [str(r) for r in sp.repositories.values_list("id", flat=True)]

    repo_ids = await sync_to_async(_load)()
    flat = await sync_to_async(build_features_flat)(include_test_case=True)
    query = RepoAssociationService._build_query(flat)

    # 复刻 route() 的 Stage 0：多探针 → 融合 → 仓级聚合（宽池）
    from codegraph.services.repo_router_v2 import COLLECTION_NAME
    from services.qdrant_service import QdrantService

    embedded = await embed_query(query, drop_noise=False)
    sparse = await sync_to_async(SparseEncoderService.encode)(query)
    node_k = _stage0_node_k()
    hits = await sync_to_async(QdrantService.hybrid_search_multi_by_name)(
        COLLECTION_NAME, embedded.vectors, sparse, top_k=node_k,
        prefetch_limit=node_k, filters={"repository_id": repo_ids},
    )
    cands = RepoRouterV2._stage0_candidates(hits, top_k=STAGE0_REPO_K_WIDE)
    docs = [RepoRouterV2._rerank_document(c) for c in cands]

    async def rank_with(q: str, label: str) -> None:
        res = await RerankerService.rerank(q, docs, top_n=len(docs))
        pos = {r["index"]: i for i, r in enumerate(res)}
        score = {r["index"]: r.get("relevance_score", 0.0) for r in res}
        print(f"\n=== {label}（query {len(q)} 字符）===")
        print(f"{'聚合序':<8}{'精排序':<8}{'仓':<38}{'rerank分'}")
        rows = sorted(range(len(cands)), key=lambda i: pos.get(i, 999))
        for i in rows[:14]:
            mark = "✅" if str(cands[i]["repo_id"]) in GROUND_TRUTH else "  "
            print(f"{mark}#{i + 1:<6}#{pos.get(i, -1) + 1:<7}"
                  f"{cands[i]['repo_name']:<38}{round(score.get(i, 0.0), 4)}")
        got = [str(cands[i]['repo_id']) for i in rows[:8]]
        n = sum(1 for g in GROUND_TRUTH if g in got)
        print(f"  精排前 8 名里的目标仓数：{n}/4")

    print(json.dumps({"pool": len(cands), "query_len": len(query)}, ensure_ascii=False))
    print("\n聚合序前 12：")
    for i, c in enumerate(cands[:12], 1):
        mark = "✅" if str(c["repo_id"]) in GROUND_TRUTH else "  "
        print(f"  {mark}#{i:<3}{c['repo_name']:<38}{round(float(c['score']), 4)}")

    await rank_with(query[:2000], "A. 当前实现：需求语料前 2000 字符")
    await rank_with(SUMMARY, "B. 一句话摘要作为 rerank query")


if __name__ == "__main__":
    asyncio.run(main())
