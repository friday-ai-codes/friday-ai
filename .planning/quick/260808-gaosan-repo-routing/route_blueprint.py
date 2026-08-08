"""三分量融合路由（能力树 + 章程 + 历史）对照跑：只喂需求材料，不带项目。

与同目录 `route_feature_list.py`（纯 `RepoRouterV2`）的差别只有一处：走
`BlueprintRouteAdapter`，多了章程分量与历史分量。`project_id` 留空 + `ignore_pin=True`
⇒ 不做项目 pin、候选范围是全库，与纯路由那次可比。

材料取自 DB 工件（`initiatives.Artifact`）：
  - feature list：结构化 JSON，逐模块建 `requirement_spec` 喂进去
  - 测试用例：**不喂**。它是验收细节，路由 query 上限 2000 字（`_MAX_QUERY_CHARS`），
    灌进去只会把功能点语义挤掉
  - PRD：库里没有，feature list 只记了来源路径

逐模块跑而非整单跑，同样是为了绕开 2000 字截断：整单 45 个功能点拼起来远超预算，
后面的模块根本进不了 query。

用法（在 server/ 下）：
    uv run python ../.planning/quick/260808-gaosan-repo-routing/route_blueprint.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

OUT_DIR = Path(__file__).resolve().parent
PROJECT_NAME = "高三提分专项"
TOP_K = 5
CONCURRENCY = 3
# 单个功能点 description 的截断：45 个功能点分散在 9 个模块，留足余量给 2000 字 query
DESC_CHARS = 260


def load_feature_list() -> list[dict]:
    from initiatives.models import Artifact, Project

    project = Project.objects.get(name=PROJECT_NAME)
    artifact = Artifact.objects.get(project=project, title__contains="Feature List")
    return json.loads(artifact.content_ref)["modules"]


def resolve_actor_id() -> str:
    """历史分量需要发起用户，否则降级为 no_acting_user（权限 fail-closed，不伪造）。"""
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(is_superuser=True).order_by("date_joined").first()
    return str(user.id) if user else ""


def build_spec(module: dict) -> dict:
    """由一个模块建 requirement_spec。

    不给 intent：feature list 没这个字段，`_resolve_dominant_intent` 会落到保守的
    brownfield（更信能力树），这正是「改造既有产品」场景该有的默认。
    """
    return {
        "goal": f"{PROJECT_NAME}｜{module['module']}",
        "feature_points": [
            {
                "title": f["name"],
                "description": str(f.get("source") or "").strip()[:DESC_CHARS],
            }
            for f in module["features"]
        ],
    }


async def route_module(module: dict, actor_id: str, sem: asyncio.Semaphore) -> dict:
    from services.process_runtime.stage_sandbox import arun_route_stage

    name = module["module"]
    spec = build_spec(module)
    async with sem:
        started = time.monotonic()
        try:
            summary = await arun_route_stage(
                requirement_spec=spec,
                project_id="",  # 不带项目
                ignore_pin=True,  # 不走人工绑定短路
                top_k=TOP_K,
                initiated_by_user_id=actor_id,
            )
        except Exception as exc:  # noqa: BLE001 — 单模块失败不打断整批
            print(f"  [{name[:20]}] 失败 {type(exc).__name__}: {exc}", flush=True)
            return {"module": name, "error": f"{type(exc).__name__}: {exc}"}

        elapsed = int((time.monotonic() - started) * 1000)
        cands = summary.get("candidates") or []
        top = cands[0]["repository_name"] if cands else "-"
        print(
            f"  [{name[:22]:22s}] intent={summary.get('intent',''):11s} "
            f"top1={top} ({elapsed}ms)",
            flush=True,
        )
        return {"module": name, "duration_ms": elapsed, "spec_points": len(spec["feature_points"]), **summary}


async def main(modules: list[dict], actor_id: str) -> None:
    sem = asyncio.Semaphore(CONCURRENCY)
    started = time.monotonic()
    results = await asyncio.gather(*(route_module(m, actor_id, sem) for m in modules))
    total = int((time.monotonic() - started) * 1000)

    out = OUT_DIR / "blueprint-routing-results.json"
    out.write_text(
        json.dumps(
            {"subject": PROJECT_NAME, "top_k": TOP_K, "total_ms": total, "results": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n完成 {len(results)} 个模块，耗时 {total}ms → {out}", flush=True)


if __name__ == "__main__":
    # DB 读取留在事件循环外：同步 ORM 进 async 上下文会被 Django 拦下
    _modules = load_feature_list()
    _actor_id = resolve_actor_id()
    print(f"模块数 {len(_modules)}，发起用户 ={_actor_id or '<无>'}\n", flush=True)
    asyncio.run(main(_modules, _actor_id))
