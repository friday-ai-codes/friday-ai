"""「高三提分专项」仓库路由 5 次复跑评测（只读，不写业务库）。

复用生产选仓链路：语料 → RepoAssociationService._build_query → RepoRouterV2.route
（Stage 0 hybrid + Stage 1 LLM 树推理），与 propose 唯一的差别是**不落
RepoAssociation**，避免污染线上业务数据。

Stage 1 自带输入哈希缓存（key 前缀 repo_router_v2:stage1:，TTL 24h），直接跑 5 次
会是 1 次真实调用 + 4 次缓存命中。本脚本用代理对象只旁路该前缀的读写（其余缓存
如 last_commit 照常走），让 5 次都是真实上游调用。

用法：
    uv run python ../.planning/quick/260809-repo-route-eval/route_eval.py \
        --runs 5 --corpus feature_list+test_case
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

PROJECT_ID = "75248ff9-3a22-4175-b940-6093d71eb4dc"
SPACE_ID = "2f6ae28d-444d-4dd7-8eac-97a85f94fcae"

# 人工指定的四个仓（ground truth）。按 repo_id 比对——候选里的 repo_name 来自
# Qdrant payload，有时不带 backend/ frontend/ 前缀（如 onion-practice vs
# frontend/onion-practice），按名字比对会漏判。
GROUND_TRUTH = {
    "050e49b2-633a-44ad-96e8-9262546756db": "frontend/onion-learning",
    "cee27ee1-cc73-4937-9a9e-730edd6c93b2": "frontend/onion-practice",
    "a1bef5cc-b5e4-4869-8a5a-e1c4f5db4663": "backend/study-user-status",
    "47991a7f-c8e4-4da6-b42c-2ce81d8b137f": "backend/study-course",
}

STAGE1_CACHE_PREFIX = "repo_router_v2:stage1:"


class _Stage1CacheBypass:
    """只旁路 Stage 1 输入哈希缓存的代理；其余 key 透传真实 cache。"""

    def __init__(self, real):
        self._real = real
        self.bypassed_gets = 0

    def get(self, key, *args, **kwargs):
        if str(key).startswith(STAGE1_CACHE_PREFIX):
            self.bypassed_gets += 1
            return None
        return self._real.get(key, *args, **kwargs)

    def set(self, key, *args, **kwargs):
        if str(key).startswith(STAGE1_CACHE_PREFIX):
            return None
        return self._real.set(key, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def build_features_flat(include_test_case: bool) -> list[dict]:
    """从项目 feature_list（+可选 test_case）工件拼 features_flat（module/name/description）。"""
    from initiatives.models import Artifact

    flat: list[dict] = []

    fl = Artifact.objects.filter(project_id=PROJECT_ID, type__key="feature_list").first()
    data = json.loads(fl.content_ref)
    for mod in data.get("modules", []):
        module = str(mod.get("module") or "").strip()
        for feat in mod.get("features") or []:
            name = str(feat.get("name") or "").strip()
            if not name:
                continue
            # description 取功能点原文，缺省回退验收项拼接
            desc = str(feat.get("source") or "").strip()
            if not desc:
                desc = " ".join(str(a) for a in (feat.get("acceptance") or []))
            flat.append({"module": module, "name": name, "description": desc})

    if include_test_case:
        tc = Artifact.objects.filter(project_id=PROJECT_ID, type__key="test_case").first()
        if tc is not None:
            # 测试用例是缩进树 markdown：只取「测试标题：」行作为功能语料，
            # 前置条件/操作步骤是执行细节，对选仓无区分度且极占字符预算。
            titles = [
                line.strip().lstrip("- ").replace("测试标题：", "").strip()
                for line in (tc.content_ref or "").splitlines()
                if "测试标题：" in line
            ]
            for t in titles:
                if t:
                    flat.append({"module": "测试用例", "name": t, "description": ""})

    return flat


async def run_once(query: str, repo_ids: list[str], top_k: int) -> dict:
    from agents.call_source import CallSource, use_call_source
    from codegraph.services.repo_router_v2 import RepoRouterV2
    from initiatives.services.repo_association_service import RepoAssociationService

    started = time.monotonic()
    with use_call_source(CallSource.AUX_REPO_ROUTER):
        result = await RepoRouterV2.route(
            query,
            top_k=top_k,
            repository_ids=repo_ids,
            use_llm=True,
            corpus_kind="requirement",
        )
    svc = RepoAssociationService()
    acting_user_id = os.environ.get("ROUTE_EVAL_USER_ID", "1522e7ee-9cdd-4d2c-bcfe-957dd7b194f8")
    candidates = await svc._fuse_extended_signals(
        query=query,
        result=result,
        repo_ids=repo_ids,
        initiated_by_user_id=acting_user_id,
    )
    duration_ms = int((time.monotonic() - started) * 1000)

    out_candidates = [
        {
            "repo_id": str(c["repo_id"]),
            "repo_name": c.get("repo_name") or "",
            "score": round(float(c.get("score") or 0.0), 4),
            "confidence": c.get("confidence") or "",
            "reasoning": (c.get("reason") or "")[:300],
            "matched_node_paths": list(c.get("matched_node_paths") or [])[:5],
            "breakdown": dict(c.get("breakdown") or {}),
        }
        for c in candidates
    ]
    return {
        "duration_ms": duration_ms,
        "router_version": result.router_version,
        "degraded": getattr(result, "degraded", None),
        "degrade_reason": getattr(result, "degrade_reason", None),
        "auto_selected": getattr(result, "auto_selected", None),
        "candidates": out_candidates,
    }


def score_run(run: dict) -> dict:
    ids = [c["repo_id"] for c in run["candidates"]]
    hit = [GROUND_TRUTH[i] for i in ids if i in GROUND_TRUTH]
    missed = sorted(GROUND_TRUTH[i] for i in GROUND_TRUTH if i not in set(ids))
    extra = [c["repo_name"] for c in run["candidates"] if c["repo_id"] not in GROUND_TRUTH]
    return {
        "returned_ids": ids,
        "hit": hit,
        "hit_count": len(hit),
        "missed": missed,
        "extra": extra,
        "full_recall": len(missed) == 0,
        "exact_set": set(ids) == set(GROUND_TRUTH),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--corpus",
        default="feature_list+test_case",
        choices=["feature_list", "feature_list+test_case"],
    )
    parser.add_argument("--no-query-budget", action="store_true",
                        help="跳过 _build_query 的 4000 字符预算截断（诊断用）")
    parser.add_argument("--stage1-timeout", type=float, default=0.0,
                        help="覆盖 REPO_ROUTER_STAGE1_TIMEOUT_SECONDS（0=用生产值 90s）")
    parser.add_argument("--stage1-budget", type=float, default=0.0,
                        help="覆盖 REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS（0=用生产值 120s）")
    parser.add_argument("--stage0-node-k", type=int, default=0,
                        help="覆盖 STAGE0_NODE_K 全局节点召回预算（0=用生产值 50）")
    parser.add_argument("--stage1-max-candidates", type=int, default=0,
                        help="覆盖喂给 Stage 1 LLM 的候选仓数（0=用生产值 8）")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if args.stage1_timeout or args.stage1_budget:
        from django.conf import settings as dj_settings

        if args.stage1_timeout:
            dj_settings.REPO_ROUTER_STAGE1_TIMEOUT_SECONDS = args.stage1_timeout
        if args.stage1_budget:
            dj_settings.REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS = args.stage1_budget

    from django.core.cache import cache as real_cache

    from codegraph.services import repo_router_v2 as rrv2
    from initiatives.services.repo_association_service import RepoAssociationService
    from projects.models import Space

    bypass = _Stage1CacheBypass(real_cache)
    rrv2.cache = bypass
    if args.stage0_node_k:
        rrv2.STAGE0_NODE_K = args.stage0_node_k
    if args.stage1_max_candidates:
        from django.conf import settings as dj_settings2

        dj_settings2.REPO_ROUTER_STAGE1_MAX_CANDIDATES = args.stage1_max_candidates

    from asgiref.sync import sync_to_async

    flat = await sync_to_async(build_features_flat)(
        include_test_case="test_case" in args.corpus
    )
    if args.no_query_budget:
        import initiatives.services.repo_association_service as ras

        ras._QUERY_CHAR_BUDGET = 10**9
    query = RepoAssociationService._build_query(flat)

    def _load_space():
        sp = Space.objects.get(id=SPACE_ID)
        return sp.name, [str(r) for r in sp.repositories.values_list("id", flat=True)]

    space_name, repo_ids = await sync_to_async(_load_space)()

    header = {
        "project": "高三提分专项",
        "project_id": PROJECT_ID,
        "space": space_name,
        "corpus": args.corpus,
        "features_in_corpus": len(flat),
        "query_len": len(query),
        "query_budget_applied": not args.no_query_budget,
        "candidate_repo_count": len(repo_ids),
        "top_k": args.top_k,
        "stage0_node_k": args.stage0_node_k or rrv2.STAGE0_NODE_K,
        "stage1_max_candidates": args.stage1_max_candidates or 8,
        "stage1_timeout_s": args.stage1_timeout or 90.0,
        "stage1_budget_s": args.stage1_budget or 120.0,
        "ground_truth": sorted(GROUND_TRUTH.values()),
    }
    print(json.dumps(header, ensure_ascii=False, indent=2))
    print("=" * 80)

    runs = []
    for i in range(1, args.runs + 1):
        run = await run_once(query, repo_ids, args.top_k)
        run["scoring"] = score_run(run)
        runs.append(run)
        s = run["scoring"]
        print(
            f"[run {i}] {run['duration_ms']}ms | {run['router_version']} | "
            f"命中 {s['hit_count']}/4 | 全中={s['full_recall']} | 完全一致={s['exact_set']}"
        )
        for c in run["candidates"]:
            mark = "✅" if c["repo_id"] in GROUND_TRUTH else "❌"
            print(f"    {mark} {c['repo_name']:<34} {c['score']:<8} {c['confidence']}")
        if s["missed"]:
            print(f"    漏: {', '.join(s['missed'])}")

    print("=" * 80)
    full = sum(1 for r in runs if r["scoring"]["full_recall"])
    exact = sum(1 for r in runs if r["scoring"]["exact_set"])
    avg_hit = sum(r["scoring"]["hit_count"] for r in runs) / len(runs)
    print(f"全中 4/4 的次数: {full}/{len(runs)}")
    print(f"候选集完全等于 4 仓的次数: {exact}/{len(runs)}")
    print(f"平均命中: {avg_hit:.2f}/4")
    print(f"Stage1 缓存旁路次数: {bypass.bypassed_gets}")

    per_repo = {
        g: sum(1 for r in runs if g in r["scoring"]["hit"])
        for g in sorted(GROUND_TRUTH.values())
    }
    print("各目标仓被召回次数:")
    for k, v in per_repo.items():
        print(f"    {k:<34} {v}/{len(runs)}")

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {"header": header, "runs": runs, "summary": {
                    "full_recall_runs": full, "exact_set_runs": exact,
                    "avg_hit": avg_hit, "per_repo_recall": per_repo}},
                ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n明细已写入 {args.out}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
