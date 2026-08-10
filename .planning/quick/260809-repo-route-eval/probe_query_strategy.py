"""探针：4000 能不能调大？逐个 feature 走一遍是不是更好？（只读）

三问三答：
1. embedding 端点的硬上限到底多少字符 —— 决定 4000 能调到多大。
2. 一句话摘要 query 的效果 —— 验证 DESIGN.md §5.7「换一句话摘要 query 立刻升至第 1」。
3. 逐 feature_point 分别检索再取并集 —— 验证「逐个 feature 校验」这条路。
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

# 一句话摘要（对齐 DESIGN.md §5.7 的 spec 摘要化设想）
SUMMARY_QUERY = (
    "高中数学培优课「极速提分营」：功能页入口与课程包权益鉴权、题型图谱、"
    "单题型学习页 4 节点解锁、真题检测、知识卡片、视频讲解、同型题检验、"
    "完成页反馈与掌握程度进度"
)


async def probe_embedding_limit(corpus: str) -> None:
    from services.embedding import EmbeddingService

    print("\n=== 1. embedding 硬上限探测 ===")
    for n in (2000, 4000, 6000, 8000, 10000, 12000, 16000, 21000, 28000):
        text = corpus[:n]
        try:
            v = await EmbeddingService.generate_embedding(text)
            ok = "OK dim=%d" % len(v) if v else "❌ 返回 None"
        except Exception as exc:  # noqa: BLE001
            ok = f"❌ {type(exc).__name__}: {str(exc)[:100]}"
        print(f"  {n:>6} 字符 -> {ok}")


async def stage0_ranks(query: str, repo_ids: list[str], label: str) -> dict[str, int]:
    from agents.call_source import CallSource, use_call_source
    from codegraph.services.repo_router_v2 import RepoRouterV2

    with use_call_source(CallSource.AUX_REPO_ROUTER):
        result = await RepoRouterV2.route(
            query, top_k=30, repository_ids=repo_ids, use_llm=False
        )
    ranks: dict[str, int] = {}
    for i, c in enumerate(result.candidates, 1):
        if str(c.repo_id) in GROUND_TRUTH:
            ranks[GROUND_TRUTH[str(c.repo_id)]] = i
    print(f"\n--- {label} (len={len(query)}, 候选 {len(result.candidates)}) ---")
    top = ", ".join(f"{c.repo_name}({round(float(c.score),3)})" for c in result.candidates[:6])
    print(f"    Top6: {top}")
    for name in sorted(GROUND_TRUTH.values()):
        print(f"    {name:<34} {('#%d' % ranks[name]) if name in ranks else '未进候选'}")
    return ranks


async def per_feature_union(repo_ids: list[str], flat: list[dict], per_k: int) -> None:
    """逐 feature_point 各跑一次 Stage 0，按仓取最高分后取并集排序。"""
    from agents.call_source import CallSource, use_call_source
    from codegraph.services.repo_router_v2 import RepoRouterV2

    best: dict[str, float] = {}
    name_of: dict[str, str] = {}
    hit_features: dict[str, int] = {}

    async def one(feat: dict) -> None:
        q = " / ".join(p for p in (feat["module"], feat["name"], feat["description"]) if p)
        with use_call_source(CallSource.AUX_REPO_ROUTER):
            r = await RepoRouterV2.route(q, top_k=per_k, repository_ids=repo_ids, use_llm=False)
        for c in r.candidates:
            rid = str(c.repo_id)
            s = float(c.score)
            if s > best.get(rid, -1):
                best[rid] = s
            name_of[rid] = c.repo_name
            hit_features[rid] = hit_features.get(rid, 0) + 1

    sem = asyncio.Semaphore(6)

    async def guarded(f: dict) -> None:
        async with sem:
            await one(f)

    await asyncio.gather(*(guarded(f) for f in flat))

    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    print(f"\n=== 3. 逐 feature 检索并集（{len(flat)} 个功能点，每个取 top{per_k}）===")
    print(f"{'rank':<6}{'repo':<38}{'max_score':<12}{'被几个功能点命中'}")
    for i, (rid, s) in enumerate(ranked[:12], 1):
        mark = "✅" if rid in GROUND_TRUTH else "  "
        print(f"{mark}{i:<4}{name_of[rid]:<38}{round(s,4):<12}{hit_features[rid]}/{len(flat)}")
    got = {rid for rid, _ in ranked}
    for rid, name in GROUND_TRUTH.items():
        if rid not in got:
            print(f"    ⛔ {name} 仍未进候选")
    # 命中率：四个目标仓在并集里的名次
    pos = {GROUND_TRUTH[rid]: i for i, (rid, _) in enumerate(ranked, 1) if rid in GROUND_TRUTH}
    print("  四个目标仓在并集里的名次:", json.dumps(pos, ensure_ascii=False))


async def main() -> None:
    from asgiref.sync import sync_to_async

    import initiatives.services.repo_association_service as ras
    from initiatives.services.repo_association_service import RepoAssociationService
    from projects.models import Space

    def _load():
        sp = Space.objects.get(id=SPACE_ID)
        return [str(r) for r in sp.repositories.values_list("id", flat=True)]

    repo_ids = await sync_to_async(_load)()
    flat = await sync_to_async(build_features_flat)(include_test_case=False)

    prod_query = RepoAssociationService._build_query(flat)
    ras._QUERY_CHAR_BUDGET = 10**9
    full_query = RepoAssociationService._build_query(flat)

    await probe_embedding_limit(full_query)

    print("\n=== 2. query 形态对比（Stage 0，纯检索）===")
    await stage0_ranks(prod_query, repo_ids, "A. 生产：4000 字符截断")
    await stage0_ranks(SUMMARY_QUERY, repo_ids, "B. 一句话摘要")
    await stage0_ranks("高三数学提分专项 极速提分营", repo_ids, "C. 极短：项目名")

    await per_feature_union(repo_ids, flat, per_k=5)


if __name__ == "__main__":
    asyncio.run(main())
