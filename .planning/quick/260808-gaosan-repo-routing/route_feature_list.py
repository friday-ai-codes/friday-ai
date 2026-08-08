"""对「高三提分专项」feature list 逐功能点跑**纯仓库路由**（一次性验证脚本）。

刻意只跑 `RepoRouterV2.route()`，且 `grouping_repository_ids=None`：
不带任何项目上下文——不做章程匹配、不看历史落点、不做 pin，
纯粹回答「这段需求文本落到哪个仓」。

用法（在 server/ 下）：
    uv run python ../.planning/quick/260808-gaosan-repo-routing/route_feature_list.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

REPO_ROOT = Path(__file__).resolve().parents[3]
FEATURE_LIST = REPO_ROOT / ".planning" / "feature-list-demo.md"
OUT_DIR = Path(__file__).resolve().parent
TOP_K = 5
CONCURRENCY = 4
SUBJECT = "高三提分专项"


# ---------------------------------------------------------------------------
# feature list 解析
# ---------------------------------------------------------------------------

_MODULE_RE = re.compile(r"^模块\s*(\d+)\s*[：:]\s*(.+?)\s*$")
_POINT_RE = re.compile(r"^功能点\s*([A-Z])\s*[：:]\s*(.+?)\s*$")
# 功能点正文里只取这几类语义行喂给路由：其余（验收项/测试数据/示意图）是验证细节，
# 塞进 query 只会稀释语义信号。
_BODY_PREFIXES = ("功能描述：", "交互逻辑：", "数据流转：", "业务规则与约束：", "影响范围：")


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
        """喂给路由器的需求文本：专项名 + 模块 + 功能点 + 语义正文。"""
        detail = " ".join(self.body)[:600]
        return (
            f"{SUBJECT}｜模块{self.module_no}「{self.module_name}」｜"
            f"功能点：{self.point_name}。{detail}"
        )


def parse_feature_points(path: Path) -> list[FeaturePoint]:
    points: list[FeaturePoint] = []
    module_no = module_name = ""
    current: FeaturePoint | None = None
    collecting = False

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue

        if m := _MODULE_RE.match(line):
            module_no, module_name = m.group(1), m.group(2)
            current, collecting = None, False
            continue

        if m := _POINT_RE.match(line):
            if not module_no:
                continue
            current = FeaturePoint(module_no, module_name, m.group(1), m.group(2))
            points.append(current)
            collecting = True
            continue

        if current is None or not collecting:
            continue
        # 验收项之后全是测试细节，停止收集直到下一个功能点
        if line.startswith("验收项"):
            collecting = False
            continue
        if line.startswith(_BODY_PREFIXES) or (current.body and len(line) > 8):
            current.body.append(line)

    return points


# ---------------------------------------------------------------------------
# 路由执行
# ---------------------------------------------------------------------------


async def route_one(fp: FeaturePoint, sem: asyncio.Semaphore) -> dict:
    from codegraph.services.repo_router_v2 import RepoRouterV2

    async with sem:
        started = time.monotonic()
        try:
            result = await RepoRouterV2.route(
                fp.query(),
                top_k=TOP_K,
                grouping_repository_ids=None,  # 不带项目上下文
            )
        except Exception as exc:  # noqa: BLE001 — 单点失败不打断整批
            return {
                "key": fp.key,
                "module": f"{fp.module_no} {fp.module_name}",
                "point": fp.point_name,
                "error": f"{type(exc).__name__}: {exc}",
            }

        elapsed = int((time.monotonic() - started) * 1000)
        print(
            f"  [{fp.key}] {fp.point_name[:24]:24s} "
            f"{result.router_version:16s} degraded={result.degraded!s:5s} "
            f"top1={result.candidates[0].repo_name if result.candidates else '-'} "
            f"({elapsed}ms)",
            flush=True,
        )
        return {
            "key": fp.key,
            "module": f"{fp.module_no} {fp.module_name}",
            "point": fp.point_name,
            "query": fp.query(),
            "router_version": result.router_version,
            "degraded": result.degraded,
            "degrade_reason": result.degrade_reason,
            "auto_selected": result.auto_selected,
            "duration_ms": elapsed,
            "candidates": [c.to_dict() for c in result.candidates],
        }


async def main() -> None:
    points = parse_feature_points(FEATURE_LIST)
    print(f"解析到 {len(points)} 个功能点\n", flush=True)
    if not points:
        sys.exit("feature list 解析为空，检查 markdown 结构")

    sem = asyncio.Semaphore(CONCURRENCY)
    started = time.monotonic()
    results = await asyncio.gather(*(route_one(fp, sem) for fp in points))
    total = int((time.monotonic() - started) * 1000)

    out = OUT_DIR / "routing-results.json"
    out.write_text(
        json.dumps(
            {"subject": SUBJECT, "top_k": TOP_K, "total_ms": total, "results": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n完成 {len(results)} 条，耗时 {total}ms → {out}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
