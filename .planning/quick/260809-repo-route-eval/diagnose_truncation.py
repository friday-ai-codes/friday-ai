"""诊断 3：4000 字符预算截掉的后半段语料，是否正是 study-course 的相关语料（只读）。

生产 query 只保留前 ~2 个模块。这里把语料按模块切片分别做 Stage 0 检索，
看各目标仓在「前半段」和「后半段」语料下的排名差异。
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


async def rank_report(query: str, repo_ids: list[str], label: str) -> None:
    from agents.call_source import CallSource, use_call_source
    from codegraph.services.repo_router_v2 import RepoRouterV2

    with use_call_source(CallSource.AUX_REPO_ROUTER):
        result = await RepoRouterV2.route(
            query, top_k=30, repository_ids=repo_ids, use_llm=False
        )
    ranks = {}
    for i, c in enumerate(result.candidates, 1):
        if str(c.repo_id) in GROUND_TRUTH:
            ranks[GROUND_TRUTH[str(c.repo_id)]] = (i, round(float(c.score), 4))
    print(f"\n### {label} (query_len={len(query)}, 候选仓 {len(result.candidates)})")
    for name in sorted(GROUND_TRUTH.values()):
        r = ranks.get(name)
        print(f"    {name:<34} {'#%d  score=%s' % r if r else '未进候选'}")


async def main() -> None:
    from asgiref.sync import sync_to_async

    from initiatives.services.repo_association_service import RepoAssociationService
    from projects.models import Space

    def _load():
        sp = Space.objects.get(id=SPACE_ID)
        return [str(r) for r in sp.repositories.values_list("id", flat=True)]

    repo_ids = await sync_to_async(_load)()
    flat = await sync_to_async(build_features_flat)(include_test_case=False)

    # 生产 query 实际覆盖到第几条语料
    full = RepoAssociationService._build_query(flat)
    prod = full[:4000]
    covered = 0
    acc = 0
    for f in flat:
        seg = " / ".join(p for p in (f["module"], f["name"], f["description"]) if p)
        acc += len(seg) + 1
        if acc <= 4000:
            covered += 1
    modules_covered = sorted({f["module"] for f in flat[:covered]})
    print(json.dumps({
        "features_total": len(flat),
        "features_inside_4000_budget": covered,
        "modules_inside_budget": modules_covered,
    }, ensure_ascii=False, indent=2))

    head = RepoAssociationService._build_query(flat[:covered])[:4000]
    tail = RepoAssociationService._build_query(flat[covered:])[:4000]

    await rank_report(prod, repo_ids, "A. 生产 query（前 4000 字符）")
    await rank_report(head, repo_ids, "B. 仅预算内语料")
    await rank_report(tail, repo_ids, "C. 仅被截掉的后半段语料（同样截到 4000）")


if __name__ == "__main__":
    asyncio.run(main())
