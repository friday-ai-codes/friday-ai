"""对「高三提分专项」feature list（**含测试用例**）跑 5 轮纯仓库路由，看命中稳定性。

与同项目 260808 那次纯路由脚本的差别：
  1. **把验收项 / 测试数据一起喂进 query**（那次刻意在「验收项」处停止收集）；
  2. `corpus_kind="requirement"`——整篇都是检索意图，全切全探（那次走默认对话型）；
  3. **跑 5 轮**，每轮开跑前清掉 Stage 1 LLM 幂等缓存（`repo_router_v2:stage1:*`），
     否则第 2~5 轮全命中缓存、逐字复现第 1 轮，5 轮就没有意义。清缓存后每轮都是
     一次真实的 Stage 0 检索 + Stage 1 LLM 推理，暴露真实（非）确定性。

只跑仓库路由这一个节点：`RepoRouterV2.route(..., grouping_repository_ids=None)`，
不带项目上下文——不做章程匹配、不看历史落点、不做 pin，纯粹回答「这段需求落到哪个仓」。

用法（在 server/ 下）：
    uv run python ../.planning/quick/260811-gaosan-route-5rounds/route_5rounds.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

REPO_ROOT = Path(__file__).resolve().parents[3]
FEATURE_LIST = REPO_ROOT / ".planning" / "feature-list-demo.md"
OUT_DIR = Path(__file__).resolve().parent
TOP_K = 5
CONCURRENCY = 6
ROUNDS = 5
SUBJECT = "高三提分专项"
# 单个功能点 query 上限：embed_query 会自动分块（4000 字/块，最多 8 探针），
# 这里给个宽松上界，避免个别超长功能点把探针预算吃满。
MAX_QUERY_CHARS = 3500


# ---------------------------------------------------------------------------
# feature list 解析（含测试用例）
# ---------------------------------------------------------------------------

_MODULE_RE = re.compile(r"^模块\s*(\d+)\s*[：:]\s*(.+?)\s*$")
_POINT_RE = re.compile(r"^功能点\s*([A-Z])\s*[：:]\s*(.+?)\s*$")


@dataclass
class FeaturePoint:
    module_no: str
    module_name: str
    point_id: str
    point_name: str
    body: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.module_no}{self.point_id}"

    def query(self) -> str:
        """喂给路由器的需求文本：专项名 + 模块 + 功能点 + 语义正文 + 验收项/测试数据。"""
        detail = "\n".join(self.body)[:MAX_QUERY_CHARS]
        return (
            f"{SUBJECT}｜模块{self.module_no}「{self.module_name}」｜"
            f"功能点：{self.point_name}\n{detail}"
        )


def parse_feature_points(path: Path) -> list[FeaturePoint]:
    """逐行解析：功能点正文一直收集到下一个「功能点」/「模块」为止（含验收项、测试数据）。"""
    points: list[FeaturePoint] = []
    module_no = module_name = ""
    current: FeaturePoint | None = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue

        if m := _MODULE_RE.match(line):
            module_no, module_name = m.group(1), m.group(2)
            current = None
            continue

        if m := _POINT_RE.match(line):
            if not module_no:
                continue
            current = FeaturePoint(module_no, module_name, m.group(1), m.group(2))
            points.append(current)
            continue

        # 收集功能点下的所有正文行——包括「验收项」及其后的「测试数据」用例。
        if current is not None:
            current.body.append(line)

    return points


# ---------------------------------------------------------------------------
# Stage 1 缓存清理（让每一轮都是真实推理）
# ---------------------------------------------------------------------------

def clear_stage1_cache() -> str:
    from django.core.cache import cache

    try:
        deleted = cache.delete_pattern("repo_router_v2:stage1:*")  # django_redis
        return f"deleted={deleted}"
    except AttributeError:
        try:
            cache.clear()  # locmem 无 delete_pattern，整体清（本地裸跑才会走到）
            return "cleared_all(locmem)"
        except Exception as exc:  # noqa: BLE001
            return f"noop({type(exc).__name__})"
    except Exception as exc:  # noqa: BLE001 — 清缓存失败不该打断评测
        return f"error({type(exc).__name__})"


# ---------------------------------------------------------------------------
# 路由执行
# ---------------------------------------------------------------------------


async def route_one(fp: FeaturePoint, sem: asyncio.Semaphore, round_no: int) -> dict:
    from codegraph.services.repo_router_v2 import RepoRouterV2

    async with sem:
        started = time.monotonic()
        try:
            result = await RepoRouterV2.route(
                fp.query(),
                top_k=TOP_K,
                grouping_repository_ids=None,  # 不带项目上下文
                corpus_kind="requirement",  # 需求型语料，全切全探
            )
        except Exception as exc:  # noqa: BLE001 — 单点失败不打断整批
            return {"key": fp.key, "error": f"{type(exc).__name__}: {exc}"}

        elapsed = int((time.monotonic() - started) * 1000)
        def _r(v: float | None, fallback: float | None = 0.0) -> float:
            v = v if v is not None else fallback
            return round(v, 4) if v is not None else 0.0

        cands = [
            {
                "repo": c.repo_name,
                "score": _r(c.score),
                "score_ranked": _r(getattr(c, "score_ranked", None), c.score),
                "confidence": c.confidence,
            }
            for c in result.candidates
        ]
        top1 = cands[0]["repo"] if cands else "-"
        print(
            f"  [r{round_no}][{fp.key:3s}] {fp.point_name[:20]:20s} "
            f"top1={top1:32s} degraded={result.degraded!s:5s} ({elapsed}ms)",
            flush=True,
        )
        return {
            "key": fp.key,
            "module": f"{fp.module_no} {fp.module_name}",
            "point": fp.point_name,
            "router_version": result.router_version,
            "degraded": result.degraded,
            "auto_selected": result.auto_selected,
            "top1": top1,
            "hits": [c["repo"] for c in cands],
            "candidates": cands,
            "duration_ms": elapsed,
        }


async def run_round(points: list[FeaturePoint], round_no: int) -> dict:
    clear_info = clear_stage1_cache()
    print(f"\n===== Round {round_no}/{ROUNDS}  (stage1 cache {clear_info}) =====", flush=True)
    sem = asyncio.Semaphore(CONCURRENCY)
    started = time.monotonic()
    results = await asyncio.gather(*(route_one(fp, sem, round_no) for fp in points))
    total = int((time.monotonic() - started) * 1000)
    print(f"  round {round_no} 完成，耗时 {total}ms", flush=True)
    return {"round": round_no, "cache": clear_info, "total_ms": total, "results": results}


# ---------------------------------------------------------------------------
# 汇总分析
# ---------------------------------------------------------------------------


def summarize(points: list[FeaturePoint], rounds: list[dict]) -> dict:
    keys = [fp.key for fp in points]
    by_key_round: dict[str, dict[int, dict]] = {k: {} for k in keys}
    for rd in rounds:
        for item in rd["results"]:
            if "key" in item and "error" not in item:
                by_key_round[item["key"]][rd["round"]] = item

    # 每轮：命中仓库并集 + top1 分布
    per_round = []
    for rd in rounds:
        hit_union: Counter = Counter()
        top1_counter: Counter = Counter()
        for item in rd["results"]:
            if "error" in item:
                continue
            top1_counter[item["top1"]] += 1
            for repo in item["hits"]:
                hit_union[repo] += 1
        per_round.append(
            {
                "round": rd["round"],
                "distinct_repos_hit": len(hit_union),
                "top1_distribution": top1_counter.most_common(),
                "repo_hit_counts": hit_union.most_common(),
            }
        )

    # 跨轮稳定性：每个功能点 top1 是否 5 轮一致；候选集合是否一致
    stability = []
    top1_stable = 0
    set_stable = 0
    for k in keys:
        rounds_seen = by_key_round[k]
        top1s = [rounds_seen[r]["top1"] for r in sorted(rounds_seen)]
        sets = [tuple(rounds_seen[r]["hits"]) for r in sorted(rounds_seen)]
        setsets = [frozenset(s) for s in sets]
        is_top1_stable = len(set(top1s)) <= 1 and len(top1s) == len(rounds)
        is_set_stable = len(set(setsets)) <= 1 and len(setsets) == len(rounds)
        top1_stable += int(is_top1_stable)
        set_stable += int(is_set_stable)
        stability.append(
            {
                "key": k,
                "top1_stable": is_top1_stable,
                "candidate_set_stable": is_set_stable,
                "top1_per_round": top1s,
                "distinct_top1": sorted(set(top1s)),
            }
        )

    # 全局：每个仓库在 (轮 × 功能点) 里被命中的总次数，以及被选为 top1 的总次数
    global_hit: Counter = Counter()
    global_top1: Counter = Counter()
    for rd in rounds:
        for item in rd["results"]:
            if "error" in item:
                continue
            global_top1[item["top1"]] += 1
            for repo in item["hits"]:
                global_hit[repo] += 1

    n = len(keys)
    return {
        "feature_points": n,
        "rounds": len(rounds),
        "per_round": per_round,
        "cross_round_stability": {
            "top1_stable_points": top1_stable,
            "top1_stable_ratio": round(top1_stable / n, 4) if n else 0,
            "candidate_set_stable_points": set_stable,
            "candidate_set_stable_ratio": round(set_stable / n, 4) if n else 0,
            "per_point": stability,
        },
        "global_repo_hit_counts": global_hit.most_common(),
        "global_top1_counts": global_top1.most_common(),
    }


def print_summary(summary: dict) -> None:
    print("\n" + "=" * 72, flush=True)
    print(f"汇总：{summary['feature_points']} 个功能点 × {summary['rounds']} 轮", flush=True)
    st = summary["cross_round_stability"]
    print(
        f"跨轮稳定性：top1 全轮一致 {st['top1_stable_points']}/{summary['feature_points']} "
        f"({st['top1_stable_ratio']:.0%})；"
        f"候选集合全轮一致 {st['candidate_set_stable_points']}/{summary['feature_points']} "
        f"({st['candidate_set_stable_ratio']:.0%})",
        flush=True,
    )
    print("\n每轮 top1 分布：", flush=True)
    for pr in summary["per_round"]:
        dist = "  ".join(f"{r}×{c}" for r, c in pr["top1_distribution"])
        print(f"  Round {pr['round']}: 命中 {pr['distinct_repos_hit']} 个仓  | top1: {dist}", flush=True)

    print("\n全局 top1 次数（越大=越常被选为首选仓）：", flush=True)
    for repo, c in summary["global_top1_counts"]:
        print(f"  {c:4d}  {repo}", flush=True)

    print("\n全局候选命中次数（进入 top5 的总次数）：", flush=True)
    for repo, c in summary["global_repo_hit_counts"]:
        print(f"  {c:4d}  {repo}", flush=True)

    unstable = [p for p in st["per_point"] if not p["top1_stable"]]
    if unstable:
        print(f"\ntop1 在 5 轮里发生漂移的功能点（{len(unstable)} 个）：", flush=True)
        for p in unstable:
            print(f"  {p['key']:3s}  {' -> '.join(p['top1_per_round'])}", flush=True)
    else:
        print("\ntop1 全部功能点 5 轮完全稳定（无漂移）。", flush=True)


async def main() -> None:
    points = parse_feature_points(FEATURE_LIST)
    print(f"解析到 {len(points)} 个功能点（含验收项/测试数据）\n", flush=True)
    if not points:
        sys.exit("feature list 解析为空，检查 markdown 结构")

    rounds: list[dict] = []
    started = time.monotonic()
    for r in range(1, ROUNDS + 1):
        rounds.append(await run_round(points, r))
    total = int((time.monotonic() - started) * 1000)

    summary = summarize(points, rounds)

    out = OUT_DIR / "route-5rounds-results.json"
    out.write_text(
        json.dumps(
            {
                "subject": SUBJECT,
                "top_k": TOP_K,
                "rounds": ROUNDS,
                "concurrency": CONCURRENCY,
                "corpus_kind": "requirement",
                "includes_test_cases": True,
                "total_ms": total,
                "summary": summary,
                "rounds_detail": rounds,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print_summary(summary)
    print(f"\n全部完成，总耗时 {total // 1000}s → {out}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
