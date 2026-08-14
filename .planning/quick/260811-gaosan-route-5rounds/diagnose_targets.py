"""分段归因：四个目标仓在代表性 miss 功能点上死在链路哪一段。

对每个代表功能点：
  1. `_stage0_node_search`（全局节点召回，budget=200）→ 目标仓最佳节点的全局名次、
     命中节点数（回答「进没进召回池」）；
  2. `route(use_llm=False, top_k=12)` → Stage 0 仓级聚合排名 + breakdown
     （回答「聚合打分排第几」）；
  3. 对照昨天 5 轮的最终 top5（回答「Stage 1 LLM 留没留」）。

用法（在 server/ 下）：
    uv run python ../.planning/quick/260811-gaosan-route-5rounds/diagnose_targets.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

sys.path.insert(0, str(Path(__file__).resolve().parent))
from route_5rounds import FEATURE_LIST, parse_feature_points  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent

# 目标仓（DB 名）
TARGETS = {
    "frontend/onion-learning": "OL",
    "frontend/onion-practice": "OP",
    "backend/study-course": "SC",
    "backend/study-user-status": "SUS",
}
# Qdrant payload 里的旧名 → DB 名（260809 发现 06-22 批索引带改名前短名）
PAYLOAD_ALIASES = {
    "onion-practice": "frontend/onion-practice",
    "study-course": "backend/study-course",
}

# 代表功能点：全 miss / 错误赢家 / 对照组
KEYS = ["1A", "2C", "2E", "4A", "5B", "6A", "7A", "9A"]


def normalize(name: str) -> str:
    return PAYLOAD_ALIASES.get(name, name)


async def main() -> None:
    from asgiref.sync import sync_to_async

    from codegraph.services.repo_router_v2 import RepoRouterV2
    from repositories.models import Repository

    # repo_id -> DB name
    rows = await sync_to_async(list)(Repository.objects.values("id", "name"))
    id2name = {str(r["id"]): r["name"] for r in rows}
    target_ids = {str(r["id"]) for r in rows if r["name"] in TARGETS}

    points = {p.key: p for p in parse_feature_points(FEATURE_LIST)}
    report: dict[str, dict] = {}

    for key in KEYS:
        fp = points[key]
        q = fp.query()
        print(f"\n{'=' * 78}\n[{key}] {fp.point_name}  (query {len(q)} chars)", flush=True)

        # ---- 1. 节点级召回：全局 top-200 里目标仓的位置 ----
        searched = await RepoRouterV2._stage0_node_search(q, None, drop_noise_probes=False)
        node_hits = searched[0] if isinstance(searched, tuple) else searched
        per_repo_best: dict[str, int] = {}
        per_repo_count: dict[str, int] = {}
        for rank, hit in enumerate(node_hits, 1):
            payload = (hit.get("payload") if isinstance(hit, dict) else getattr(hit, "payload", None)) or {}
            rid = str(payload.get("repository_id", ""))
            name = normalize(id2name.get(rid, payload.get("repo_name", rid)))
            per_repo_best.setdefault(name, rank)
            per_repo_count[name] = per_repo_count.get(name, 0) + 1

        print(f"  节点召回池：{len(node_hits)} 个节点，覆盖 {len(per_repo_best)} 个仓")
        print("  目标仓节点级位置：")
        for t, ab in TARGETS.items():
            if t in per_repo_best:
                print(f"    {ab:3s} {t:32s} 最佳节点全局 #{per_repo_best[t]:<4d} 命中 {per_repo_count[t]} 节点")
            else:
                print(f"    {ab:3s} {t:32s} ** 不在全局 top-{len(node_hits)} 节点召回池 **")

        # ---- 2. Stage 0 仓级聚合排名（use_llm=False，top_k=12）----
        res = await RepoRouterV2.route(
            q, top_k=12, grouping_repository_ids=None, use_llm=False, corpus_kind="requirement"
        )
        print(f"  Stage0 仓级排名（router={res.router_version}）：")
        stage0_names = []
        for i, c in enumerate(res.candidates, 1):
            name = normalize(c.repo_name)
            stage0_names.append(name)
            mark = f" <== {TARGETS[name]}" if name in TARGETS else ""
            bd = c.breakdown or {}
            bd_s = " ".join(f"{k[:4]}={v:.3f}" for k, v in bd.items()) if isinstance(bd, dict) else ""
            print(f"    #{i:<2d} {name:36s} score={c.score:.4f}  {bd_s}{mark}")

        report[key] = {
            "point": fp.point_name,
            "node_pool_repos": len(per_repo_best),
            "target_node_best_rank": {
                TARGETS[t]: per_repo_best.get(t) for t in TARGETS
            },
            "target_node_count": {TARGETS[t]: per_repo_count.get(t, 0) for t in TARGETS},
            "stage0_top12": stage0_names,
            "stage0_target_rank": {
                TARGETS[t]: (stage0_names.index(t) + 1 if t in stage0_names else None)
                for t in TARGETS
            },
        }

    out = OUT_DIR / "diagnose-targets.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ {out}", flush=True)

    # 汇总表
    print(f"\n{'=' * 78}\n汇总（节点级最佳名次 / Stage0 仓级名次；- = 未进池）：")
    print(f"  {'key':4s} {'OL节点':>7s} {'OL仓':>5s} | {'OP节点':>7s} {'OP仓':>5s} | {'SC节点':>7s} {'SC仓':>5s} | {'SUS节点':>7s} {'SUS仓':>5s}")
    for key in KEYS:
        r = report[key]
        def fmt(ab: str) -> str:
            n = r["target_node_best_rank"][ab]
            s = r["stage0_target_rank"][ab]
            return f"{('#' + str(n)) if n else '-':>7s} {('#' + str(s)) if s else '-':>5s}"
        print(f"  {key:4s} {fmt('OL')} | {fmt('OP')} | {fmt('SC')} | {fmt('SUS')}")


if __name__ == "__main__":
    asyncio.run(main())
