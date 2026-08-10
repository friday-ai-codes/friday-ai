"""对比多版评测结果：展示 agent 倾向选哪些仓 + 四仓命中率变化。

用法:
    uv run python compare_results.py v1.json v2.json [v3.json ...]
每个文件输出：平均命中率、四仓 per-repo recall、top 候选分布（agent 倾向）。
"""
from __future__ import annotations

import json
import sys
from collections import Counter

GT = {
    "050e49b2-633a-44ad-96e8-9262546756db": "frontend/onion-learning",
    "cee27ee1-cc73-4937-9a9e-730edd6c93b2": "frontend/onion-practice",
    "a1bef5cc-b5e4-4869-8a5a-e1c4f5db4663": "backend/study-user-status",
    "47991a7f-c8e4-4da6-b42c-2ce81d8b137f": "backend/study-course",
}
GT_NAMES = set(GT.values())


def load(path: str) -> dict:
    return json.load(open(path))


def short(name: str) -> str:
    return name.replace("frontend/", "f/").replace("backend/", "b/")


def report(path: str) -> None:
    d = load(path)
    runs = d.get("runs", [])
    n = len(runs)
    label = path.split("/")[-1].replace("result-", "").replace(".json", "")
    print(f"\n{'='*70}\n■ {label}  ({n} runs)\n{'='*70}")

    # 四仓命中率（按 repo_id）
    recall = Counter()
    full = 0
    total_hit = 0
    pick_counter = Counter()  # agent 倾向：所有出现过的候选
    top1_counter = Counter()  # top1 倾向
    for r in runs:
        ids = [c["repo_id"] for c in r["candidates"]]
        hits = {GT[i] for i in ids if i in GT}
        total_hit += len(hits)
        for g in GT_NAMES:
            if g in hits:
                recall[g] += 1
        if len(hits) == len(GT_NAMES):
            full += 1
        for c in r["candidates"]:
            pick_counter[c["repo_name"]] += 1
        if r["candidates"]:
            top1_counter[r["candidates"][0]["repo_name"]] += 1

    print(f"平均命中: {total_hit/n:.2f}/4   全召回(4/4)轮数: {full}/{n}")
    print("四仓召回:")
    for g in sorted(GT_NAMES):
        bar = "█" * recall[g] + "·" * (n - recall[g])
        print(f"  {short(g):28s} {recall[g]}/{n}  {bar}")

    print("\nagent 倾向（候选出现频次，≥1 即列出，✓=正仓）:")
    for name, cnt in pick_counter.most_common():
        tag = "✓" if name in GT_NAMES else " "
        print(f"  {tag} {short(name):32s} {cnt}/{n}")
    print("\ntop1 倾向:")
    for name, cnt in top1_counter.most_common():
        tag = "✓" if name in GT_NAMES else " "
        print(f"  {tag} {short(name):32s} {cnt}/{n}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        report(p)
