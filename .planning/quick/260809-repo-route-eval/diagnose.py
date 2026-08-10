"""诊断：四个目标仓在 Stage 0 检索里的排名，以及 query 截断的影响（只读）。

回答两个问题：
1. study-course / onion-learning 是压根没进 Stage 0 候选（检索/索引问题），
   还是进了但被 Stage 1 LLM 排掉（推理问题）？
2. _build_query 的 4000 字符预算把 238 条语料截到只剩前几个模块，是否是主因？
"""

from __future__ import annotations

import asyncio
import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from route_eval import GROUND_TRUTH, SPACE_ID, build_features_flat  # noqa: E402


async def stage0_ranks(query: str, repo_ids: list[str], label: str) -> None:
    from agents.call_source import CallSource, use_call_source
    from codegraph.services.repo_router_v2 import RepoRouterV2

    with use_call_source(CallSource.AUX_REPO_ROUTER):
        # use_llm=False → 纯 Stage 0 检索打分，top_k 放大到全部候选仓
        result = await RepoRouterV2.route(
            query, top_k=30, repository_ids=repo_ids, use_llm=False
        )
    print(f"\n### {label}  (query_len={len(query)}, router={result.router_version})")
    print(f"{'rank':<6}{'repo':<38}{'score':<10}conf")
    for i, c in enumerate(result.candidates, 1):
        mark = "✅" if str(c.repo_id) in GROUND_TRUTH else "  "
        print(f"{mark}{i:<4}{c.repo_name:<38}{round(float(c.score), 4):<10}{c.confidence}")
    got = {str(c.repo_id) for c in result.candidates}
    for rid, name in GROUND_TRUTH.items():
        if rid not in got:
            print(f"    ⛔ {name} 完全不在 Stage 0 候选中")


async def main() -> None:
    from asgiref.sync import sync_to_async

    import initiatives.services.repo_association_service as ras
    from initiatives.services.repo_association_service import RepoAssociationService
    from projects.models import Space

    def _load():
        sp = Space.objects.get(id=SPACE_ID)
        return [str(r) for r in sp.repositories.values_list("id", flat=True)]

    repo_ids = await sync_to_async(_load)()

    flat_fl = await sync_to_async(build_features_flat)(include_test_case=False)
    flat_all = await sync_to_async(build_features_flat)(include_test_case=True)

    q_prod = RepoAssociationService._build_query(flat_all)  # 4000 截断
    ras._QUERY_CHAR_BUDGET = 10**9
    q_full_fl = RepoAssociationService._build_query(flat_fl)
    q_full_all = RepoAssociationService._build_query(flat_all)

    print(json.dumps({
        "features_feature_list_only": len(flat_fl),
        "features_with_test_cases": len(flat_all),
        "query_len_prod_truncated": len(q_prod),
        "query_len_full_feature_list": len(q_full_fl),
        "query_len_full_all": len(q_full_all),
    }, ensure_ascii=False, indent=2))

    await stage0_ranks(q_prod, repo_ids, "A. 生产口径：feature_list+test_case，4000 字符截断")
    await stage0_ranks(q_full_fl, repo_ids, "B. 完整 feature_list（不截断）")
    await stage0_ranks(q_full_all, repo_ids, "C. 完整 feature_list + 测试用例标题（不截断）")


if __name__ == "__main__":
    asyncio.run(main())
