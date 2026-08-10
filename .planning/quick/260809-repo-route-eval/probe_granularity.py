"""探针：多探针的粒度选型 —— 逐 feature（45 次）vs 逐模块（9 次）vs 摘要（1 次）。

逐 feature 已验证四个目标仓全进候选，但 45 次 Stage 0 成本不低。
这里对比逐模块（9 次）能否达到同样召回，作为成本/质量的选型依据。
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from route_eval import GROUND_TRUTH, SPACE_ID, build_features_flat  # noqa: E402


async def probe_union(repo_ids: list[str], queries: list[str], per_k: int, label: str) -> None:
    from agents.call_source import CallSource, use_call_source
    from codegraph.services.repo_router_v2 import RepoRouterV2

    best: dict[str, float] = {}
    name_of: dict[str, str] = {}
    breadth: dict[str, int] = {}
    sem = asyncio.Semaphore(6)
    started = time.monotonic()

    async def one(q: str) -> None:
        async with sem:
            with use_call_source(CallSource.AUX_REPO_ROUTER):
                r = await RepoRouterV2.route(
                    q, top_k=per_k, repository_ids=repo_ids, use_llm=False
                )
        for c in r.candidates:
            rid = str(c.repo_id)
            best[rid] = max(best.get(rid, -1.0), float(c.score))
            name_of[rid] = c.repo_name
            breadth[rid] = breadth.get(rid, 0) + 1

    await asyncio.gather(*(one(q) for q in queries))
    elapsed = int((time.monotonic() - started) * 1000)

    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    pos = {GROUND_TRUTH[rid]: i for i, (rid, _) in enumerate(ranked, 1) if rid in GROUND_TRUTH}
    print(f"\n=== {label} ===")
    print(f"    探针数={len(queries)}  耗时={elapsed}ms  候选池={len(ranked)} 仓")
    print(f"    四仓名次: {json.dumps(pos, ensure_ascii=False)}")
    print(f"    全部进池: {len(pos) == 4}")
    print(f"    {'rank':<6}{'repo':<38}{'max_score':<11}探针命中")
    for i, (rid, s) in enumerate(ranked[:10], 1):
        mark = "✅" if rid in GROUND_TRUTH else "  "
        print(f"    {mark}{i:<4}{name_of[rid]:<38}{round(s,4):<11}{breadth[rid]}/{len(queries)}")


async def main() -> None:
    from asgiref.sync import sync_to_async

    from projects.models import Space

    def _load():
        sp = Space.objects.get(id=SPACE_ID)
        return [str(r) for r in sp.repositories.values_list("id", flat=True)]

    repo_ids = await sync_to_async(_load)()
    flat = await sync_to_async(build_features_flat)(include_test_case=False)

    # 逐 feature：45 个探针
    q_feature = [
        " / ".join(p for p in (f["module"], f["name"], f["description"]) if p) for f in flat
    ]

    # 逐模块：把同模块功能点名拼一条，9 个探针（每条控制在 embedding 安全长度内）
    by_mod: dict[str, list[str]] = {}
    for f in flat:
        by_mod.setdefault(f["module"], []).append(f["name"])
    q_module = [f"{mod} / " + "、".join(names) for mod, names in by_mod.items()]

    await probe_union(repo_ids, q_feature, 5, "A. 逐 feature（45 探针，每个 top5）")
    await probe_union(repo_ids, q_module, 5, "B. 逐模块（9 探针，每个 top5）")
    await probe_union(repo_ids, q_module, 8, "C. 逐模块（9 探针，每个 top8）")


if __name__ == "__main__":
    asyncio.run(main())
