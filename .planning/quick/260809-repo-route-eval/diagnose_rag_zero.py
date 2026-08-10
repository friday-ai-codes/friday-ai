"""定位 rag_search 返回 0 条：是我的改动，还是既有问题？（只读）

对照三层：
  A. 直接打 BranchAwareSearchService.search（rag_search 的下游）
  B. search_rag 全链路
  C. 排除过滤器 build_matcher_for_repo 的行为（fail-closed 会静默吃掉全部结果）
"""

from __future__ import annotations

import asyncio
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

CODING = "真题检测页复用端内做题组件，提交后展示答案解析，中途返回要弹阻断弹窗，这段逻辑在哪"


async def main() -> None:
    from asgiref.sync import sync_to_async

    from repositories.models import Repository
    from services.branch_search import BranchAwareSearchService
    from services.embedding import EmbeddingService
    from services.sparse_encoder import SparseEncoderService

    def _repos():
        names = ["frontend/onion-practice", "backend/study-course"]
        return [(r.name, str(r.id)) for r in Repository.objects.filter(name__in=names)]

    repos = await sync_to_async(_repos)()
    dense = await EmbeddingService.generate_embedding(CODING)
    sparse = await sync_to_async(SparseEncoderService.encode)(CODING)
    print(f"dense dim={len(dense) if dense else None}  sparse terms={len(sparse.get('indices') or [])}")

    print("\n=== A. 直接打 BranchAwareSearchService.search ===")
    for name, rid in repos:
        hits = await BranchAwareSearchService.search(
            rid, dense, query_sparse=sparse, branch_name=None, top_k=10
        )
        print(f"  {name:<32} {len(hits or [])} 条")
        if hits:
            p = (hits[0].get("payload") or {})
            print(f"      样例: {str(p.get('file_path') or p.get('rel_path') or '')[:70]}")

    print("\n=== B. search_rag 全链路 ===")
    from services.retrieval.rag_search import search_rag

    snap = await search_rag(CODING, repo_ids=[r[1] for r in repos], top_k=10)
    print(f"  status={snap.status}  results={len(getattr(snap, 'results', []) or [])}"
          f"  error={getattr(snap, 'error', '')}")

    print("\n=== C. 排除过滤器（fail-closed 会静默吃掉全部命中）===")
    from services.code_graph.access import build_matcher_for_repo

    for name, rid in repos:
        try:
            matcher = await build_matcher_for_repo(rid)
            print(f"  {name:<32} matcher={type(matcher).__name__}")
            hits = await BranchAwareSearchService.search(
                rid, dense, query_sparse=sparse, branch_name=None, top_k=10
            )
            kept = 0
            for h in hits or []:
                p = h.get("payload") or {}
                rel = str(p.get("file_path") or p.get("rel_path") or "")
                if not matcher.is_excluded(rel):
                    kept += 1
            print(f"      过滤前 {len(hits or [])} 条 → 过滤后 {kept} 条")
        except Exception as exc:  # noqa: BLE001
            print(f"  {name:<32} matcher 构造失败: {type(exc).__name__}: {str(exc)[:120]}")


if __name__ == "__main__":
    asyncio.run(main())
