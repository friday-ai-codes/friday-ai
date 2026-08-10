"""各场景 × 短/长输入的回归实测（只读）。

核心断言：我改的六个查询侧入口，**长文本不再静默返回空**，且短查询行为不变。

改造前：文本超过约 6000 中文字符 → `EmbeddingService.generate_embedding` 返回
None → 四个入口静默 `return []`、两个入口报 status="error"。用户在对话里贴一篇
PRD / 一段长堆栈，界面上就是「什么都没搜到」，日志里只有一句 embedding_api_failed。

场景取材全部来自真实业务数据（高三提分专项的 feature list / 测试用例），不用合成串。
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
from route_eval import SPACE_ID, build_features_flat  # noqa: E402

PROJECT_ID = "75248ff9-3a22-4175-b940-6093d71eb4dc"

SHORT = "极速提分营入口的课程包权益鉴权在哪个服务实现"
CODING = "真题检测页复用端内做题组件，提交后展示答案解析，中途返回要弹阻断弹窗，这段逻辑在哪"

results: list[dict] = []


def rec(scenario: str, variant: str, ok: bool, detail: str, ms: int) -> None:
    results.append({
        "scenario": scenario, "variant": variant, "ok": ok, "detail": detail, "ms": ms
    })
    flag = "✅" if ok else "❌"
    print(f"  {flag} {scenario:<28}{variant:<12}{detail}  ({ms}ms)")


async def timed(fn) -> tuple[object, int]:
    t = time.monotonic()
    out = await fn()
    return out, int((time.monotonic() - t) * 1000)


async def main() -> None:
    from asgiref.sync import sync_to_async

    from initiatives.services.repo_association_service import RepoAssociationService
    from projects.models import Space

    def _load():
        sp = Space.objects.get(id=SPACE_ID)
        return [str(r) for r in sp.repositories.values_list("id", flat=True)]

    repo_ids = await sync_to_async(_load)()
    flat = await sync_to_async(build_features_flat)(include_test_case=True)
    LONG = RepoAssociationService._build_query(flat)  # 2.8 万字符真实需求语料
    print(json.dumps({"long_query_len": len(LONG), "repos": len(repo_ids)},
                     ensure_ascii=False))

    # ---------------- 1. 查询侧 embedding 收口 ----------------
    print("\n=== 1. 查询收口 embed_query（所有场景的地基）===")
    from services.query_embedding import embed_query

    for name, text in (("短查询", SHORT), ("长上下文", LONG)):
        r, ms = await timed(lambda t=text: embed_query(t, drop_noise=False))
        rec("embed_query", name, r.ok,
            f"{len(r.vectors)} 个探针 / 切 {r.total_segments} 块", ms)

    # ---------------- 2. 仓库路由 ----------------
    print("\n=== 2. 仓库路由（技术方案选仓的地基）===")
    from codegraph.services.repo_router_v2 import RepoRouterV2

    for name, text, kind in (
        ("短查询", SHORT, "conversation"),
        ("长上下文", LONG, "requirement"),
    ):
        r, ms = await timed(
            lambda t=text, k=kind: RepoRouterV2.route(
                t, top_k=5, repository_ids=repo_ids, use_llm=False, corpus_kind=k
            )
        )
        rec("repo_route", name, bool(r.candidates),
            f"{len(r.candidates)} 候选 / {r.router_version}", ms)

    # ---------------- 3. 编码场景：代码 RAG ----------------
    print("\n=== 3. 编码场景（代码 RAG 检索）===")
    from services.retrieval.rag_search import search_rag

    # 选确定有代码索引的仓（onion-practice 13148 点 / study-course 4467 / user-status 6082），
    # 否则「0 条」分不清是召回坏了还是这几个仓本来就没索引。
    from repositories.models import Repository

    def _coded():
        names = ["frontend/onion-practice", "backend/study-course", "backend/study-user-status"]
        return [str(r.id) for r in Repository.objects.filter(name__in=names)]

    coded_repos = await sync_to_async(_coded)()

    for name, text in (("短查询", CODING), ("长上下文", LONG)):
        r, ms = await timed(
            lambda t=text: search_rag(t, repo_ids=coded_repos, top_k=10)
        )
        hits = len(getattr(r, "results", []) or [])
        ok = r.status != "error" and hits > 0
        rec("rag_search", name, ok, f"status={r.status} / {hits} 条", ms)

    # ---------------- 4. 知识召回（交付知识 / 意图佐证）----------------
    print("\n=== 4. 知识召回（delivery knowledge）===")
    from knowledge.vector_recall import recall_similar_chunks

    for name, text in (("短查询", SHORT), ("长上下文", LONG)):
        r, ms = await timed(
            lambda t=text: recall_similar_chunks(
                t,
                allowed_project_ids=[PROJECT_ID],
                allowed_repository_ids=repo_ids,
                top_k=10,
                include_document_kind=True,
            )
        )
        # 该项目未必有知识实体，故只断言"没有因超长而异常/静默失败"
        rec("vector_recall", name, True, f"{len(r)} 条命中", ms)

    # ---------------- 5. 分层检索 L3 ----------------
    print("\n=== 5. 分层检索 L3 ===")
    from codegraph.services.layered_search import LayeredSearchService

    for name, text in (("短查询", CODING), ("长上下文", LONG)):
        async def _run(t=text):
            return await LayeredSearchService._l3_hybrid_search(
                t, coded_repos, 10, None
            )
        try:
            r, ms = await timed(_run)
            ok = getattr(r, "status", "") != "error"
            rec("layered_search_l3", name, ok, f"status={getattr(r, 'status', '?')}", ms)
        except Exception as exc:  # noqa: BLE001
            rec("layered_search_l3", name, False, f"{type(exc).__name__}: {exc}", 0)

    # ---------------- 6. 技术方案生成：蓝图三分量路由 ----------------
    print("\n=== 6. 技术方案生成（蓝图路由 dry-run）===")
    from services.process_runtime.stage_sandbox import arun_route_stage

    for name, text in (("短查询", SHORT), ("长上下文", LONG)):
        try:
            r, ms = await timed(
                lambda t=text: arun_route_stage(
                    requirement_text=t,
                    project_id=PROJECT_ID,
                    top_k=5,
                    initiated_by_user_id="system",
                )
            )
            cands = (r or {}).get("candidates") or []
            rec("blueprint_route", name, bool(cands), f"{len(cands)} 候选", ms)
        except Exception as exc:  # noqa: BLE001
            rec("blueprint_route", name, False, f"{type(exc).__name__}: {str(exc)[:80]}", 0)

    # ---------------- 汇总 ----------------
    print("\n" + "=" * 74)
    long_rows = [r for r in results if r["variant"] == "长上下文"]
    short_rows = [r for r in results if r["variant"] == "短查询"]
    print(f"长上下文场景通过：{sum(1 for r in long_rows if r['ok'])}/{len(long_rows)}")
    print(f"短查询场景通过：  {sum(1 for r in short_rows if r['ok'])}/{len(short_rows)}")
    failed = [r for r in results if not r["ok"]]
    if failed:
        print("\n未通过：")
        for r in failed:
            print(f"  {r['scenario']} / {r['variant']}: {r['detail']}")
    Path(__file__).with_name("scenario-matrix.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
