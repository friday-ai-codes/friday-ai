"""把确认门丢掉的选仓证据回填进锁定关联，然后重跑 merge。

背景：确认门锁定时对 ``fitness.citations`` 做白名单过滤，白名单取自当时版本的
``content["citations"]`` —— 但文档级引用池要到 merge 阶段才建立，锁定那一刻它是空 dict。
空集 ∩ 任何引用 = 空 ⇒ 调研阶段产出的选仓证据被 100% 丢弃。下游 ``_project_rationale``
取「源 rationale.citations ∪ fitness.citations」，两边都空 ⇒ 8 条
``repo_associations[].rationale`` 全部无引用 ⇒ 审查规则②逐条判 BLOCKER，引用覆盖率
被拉到 0.75（基线 0.80）。

代码侧的修复见 ``blueprint_confirm_gate``（改为「先建池再过滤」）。本脚本只做**数据修复**：
确认门是人工裁决点，不能为了补引用把它重新打开，因此直接按修复后的口径把证据补回最新
版本 —— 从 ``PartialPlan.content["fitness"]["citations"]`` 取裸引用串，用与 merge 逐字节
一致的 ``build_citation_entries`` 归一成池条目与 ``cit_`` id，写回 ``fitness.citations``
并入池，再 rewind 到 merge 重跑。

merge 读的是 artifact 的**最新**版本（``_aload_baseline`` 按 ``-version_no`` 取），故补在
最新版本上；补进去的是池内 id 而非裸串，整份 content 仍过 ``validate_blueprint``。

审查侧无需手工清线程：``_aland_findings`` 的收尾循环会把「本轮已不再命中」的既有 finding
线程自动 resolve。

用法::

    uv run python ../.planning/quick/260820-citation-backfill/backfill_fitness_citations.py --dry-run
    uv run python ../.planning/quick/260820-citation-backfill/backfill_fitness_citations.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

SESSION_ID = "4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6"
ARTIFACT_ID = "7b67b615-8830-4980-bf0f-3572fded41fa"

# 与确认门 `_MAX_LIST_ITEMS` 同值：单仓证据上界，超出部分不入 fitness.citations。
MAX_CITATIONS_PER_REPO = 10


def _content_hash(content: dict) -> str:
    """与 ArtifactService 同口径：canonical JSON 的 sha256。"""
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


async def _acollect_research_citations() -> dict[str, list[str]]:
    """仓 id → 调研产出的裸引用串（同仓多份产物取最新一份）。"""
    from delivery.models import PartialPlan

    by_repo: dict[str, list[str]] = {}
    queryset = (
        PartialPlan.objects.filter(research_task__session_id=SESSION_ID, valid=True)
        .select_related("research_task")
        .order_by("created_at")
    )
    async for partial in queryset:
        content = partial.content if isinstance(partial.content, dict) else {}
        fitness = content.get("fitness") if isinstance(content.get("fitness"), dict) else {}
        raws = [str(c).strip() for c in (fitness.get("citations") or []) if str(c or "").strip()]
        if not raws:
            continue
        # 升序遍历 ⇒ 同仓后写的覆盖先写的，天然取到最新一份产物。
        by_repo[str(partial.research_task.repository_id)] = raws
    return by_repo


async def main() -> None:
    from delivery.models import ArtifactVersion, ConvergenceSession
    from delivery.services import ConvergenceSessionService
    from services.process_runtime.blueprint_citations import build_citation_entries
    from services.process_runtime.blueprint_resume import arun_blueprint_resume
    from services.process_runtime.blueprint_schema import validate_blueprint

    dry_run = "--dry-run" in sys.argv

    session = await ConvergenceSession.objects.aget(id=SESSION_ID)
    version = await (
        ArtifactVersion.objects.filter(artifact_id=ARTIFACT_ID).order_by("-version_no").afirst()
    )
    if version is None:
        raise SystemExit("找不到 artifact 版本，拒绝修复")
    if str(session.current_artifact_version_id) != str(version.id):
        raise SystemExit(
            f"会话指针与最新版本不一致（pinned={session.current_artifact_version_id} "
            f"latest={version.id}），merge 会读最新版本，拒绝在指针漂移时修复"
        )

    content = json.loads(json.dumps(version.content))  # 深拷贝，失败时原对象不受污染
    associations = content.get("repo_associations")
    if not isinstance(associations, list) or not associations:
        raise SystemExit("最新版本没有 repo_associations，拒绝修复")

    pool = content.get("citations") if isinstance(content.get("citations"), dict) else {}
    research = await _acollect_research_citations()
    print(
        f"[guard] v{version.version_no} associations={len(associations)} "
        f"pool={len(pool)} 调研有证据的仓={len(research)}"
    )

    already_cited = [
        assoc
        for assoc in associations
        if isinstance(assoc, dict) and (assoc.get("fitness") or {}).get("citations")
    ]
    if already_cited:
        raise SystemExit(
            f"{len(already_cited)} 条关联已有 fitness.citations —— 说明修复已生效或数据形态"
            "与预期不符，拒绝重复回填"
        )

    filled = 0
    missing: list[str] = []
    for assoc in associations:
        if not isinstance(assoc, dict):
            continue
        repository_id = str(assoc.get("repository_id") or "")
        raws = research.get(repository_id) or []
        if not raws:
            missing.append(assoc.get("repository_name") or repository_id)
            continue
        raws = raws[:MAX_CITATIONS_PER_REPO]
        entries, cite_map = build_citation_entries(raws)
        for entry in entries:
            pool.setdefault(entry["citation_id"], entry)
        citation_ids = [cite_map[raw] for raw in raws if raw in cite_map]
        if not citation_ids:
            missing.append(assoc.get("repository_name") or repository_id)
            continue
        fitness = assoc.get("fitness") if isinstance(assoc.get("fitness"), dict) else {}
        fitness["citations"] = citation_ids
        assoc["fitness"] = fitness
        filled += 1
        print(f"  [fill] {assoc.get('repository_name') or repository_id} ← {len(citation_ids)} 条")

    content["citations"] = pool
    print(f"[fill] 已回填 {filled}/{len(associations)} 条关联，池 {len(pool)} 条")
    if missing:
        print(f"[warn] 以下仓在调研产物里找不到 fitness.citations：{missing}")
    if not filled:
        raise SystemExit("一条都没回填上，拒绝继续")

    ok, detail = validate_blueprint(content)
    if not ok:
        raise SystemExit(f"回填后 content 非法，拒绝落库：{detail}")
    print("[guard] validate_blueprint 通过")

    if dry_run:
        print("[dry-run] 守卫全过；未修改 DB")
        return

    version.content = content
    version.content_hash = _content_hash(content)
    await version.asave(update_fields=["content", "content_hash"])
    print(f"[save] v{version.version_no} 已就地更新（hash={version.content_hash[:12]}）")

    applied = await ConvergenceSessionService().arewind_to_stage(
        session,
        stage="merge",
        reason="operator: backfill gate-dropped fitness citations, rerun merge",
    )
    print(f"[rewind] applied={applied}")
    if not applied:
        raise SystemExit("并发驱动已改变会话，拒绝继续")

    result = await arun_blueprint_resume(SESSION_ID, initiated_by_user_id="system")
    print(f"[drive] {result}")


if __name__ == "__main__":
    asyncio.run(main())
