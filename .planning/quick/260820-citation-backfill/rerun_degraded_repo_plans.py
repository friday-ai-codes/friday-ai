"""失效 5 个降级仓级方案并按修复后的校验链重新派发。

只处理目标蓝图里已确认为 ``degraded`` 的 5 个仓；另外 3 个有真实实现项的方案原样保留。
direct 仓走容器，indirect 仓由服务端合成。派发后进程保活，避免 durable job 随脚本退出丢失。
"""

from __future__ import annotations

import asyncio
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

SESSION_ID = "4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6"
ARTIFACT_ID = "7b67b615-8830-4980-bf0f-3572fded41fa"
EXPECTED_DEGRADED = {
    "frontend/onion-practice",
    "backend/study-stream",
    "backend/basic-resource",
    "backend/study-course",
    "frontend/onion-learning",
}
EXPECTED_READY = {
    "backend/study-practice",
    "frontend/study-app",
    "backend/study-user-status",
}
WAIT_SECONDS = 75


async def main() -> None:
    from asgiref.sync import sync_to_async

    from delivery.models import ArtifactVersion, ConvergenceSession, RepoResearchTask
    from delivery.services import ConvergenceSessionService, ResearchService
    from services.process_runtime.blueprint_repo_plan import (
        BlueprintRepoPlanAdapter,
        _repo_plan_delivery_status,
    )

    @sync_to_async
    def _load():
        session = ConvergenceSession.objects.get(id=SESSION_ID)
        version = ArtifactVersion.objects.get(id=session.current_artifact_version_id)
        tasks = {
            str(task.repository_id): task
            for task in RepoResearchTask.objects.filter(session=session).select_related("repository")
        }
        return session, version, tasks

    session, version, tasks = await _load()
    if str(version.artifact_id) != ARTIFACT_ID:
        raise SystemExit("Artifact 漂移，拒绝恢复")

    adapter = BlueprintRepoPlanAdapter()
    locked = await adapter.acollect_locked_repos(session)
    plans = await adapter.acollect_repo_plans(session)
    names = {str(repo["repository_id"]): str(repo.get("repository_name") or "") for repo in locked}
    statuses = {repository_id: _repo_plan_delivery_status(plan) for repository_id, plan in plans.items()}
    degraded_names = {names[rid] for rid, status in statuses.items() if status == "degraded"}
    ready_names = {names[rid] for rid, status in statuses.items() if status == "ready"}

    print(f"[before] stage={session.current_stage} status={session.status}")
    print(f"[guard] degraded={sorted(degraded_names)}")
    print(f"[guard] ready={sorted(ready_names)}")
    if degraded_names != EXPECTED_DEGRADED:
        raise SystemExit(
            f"降级仓集合漂移：expected={sorted(EXPECTED_DEGRADED)}, actual={sorted(degraded_names)}"
        )
    if ready_names != EXPECTED_READY:
        raise SystemExit(
            f"正常仓集合漂移：expected={sorted(EXPECTED_READY)}, actual={sorted(ready_names)}"
        )

    target_ids = {rid for rid, name in names.items() if name in EXPECTED_DEGRADED}
    target_tasks = [tasks[rid] for rid in target_ids if rid in tasks]
    if len(target_tasks) != len(EXPECTED_DEGRADED):
        raise SystemExit("目标仓 task 不完整，拒绝恢复")

    if "--dry-run" in sys.argv:
        print("[dry-run] 守卫通过；未修改 DB")
        return

    invalidated = await ResearchService().mark_stale([task.id for task in target_tasks])
    print(f"[invalidate] tasks={len(target_tasks)} partials={invalidated}")

    applied = await ConvergenceSessionService().arewind_to_stage(
        session,
        stage="repo_plan",
        reason="operator: rerun five degraded repo plans after normalization and delivery guards",
    )
    print(f"[rewind] applied={applied}")
    if not applied:
        raise SystemExit("并发驱动已改变会话，拒绝继续")

    result = await adapter.dispatch_plans(session)
    print(f"[dispatch] {result}")
    print(f"[wait] 等 durable 队列排空 {WAIT_SECONDS}s …")
    await asyncio.sleep(WAIT_SECONDS)

    @sync_to_async
    def _snapshot() -> tuple[str, str, list[tuple[str, str, int]]]:
        fresh = ConvergenceSession.objects.get(id=SESSION_ID)
        rows = [
            (getattr(task.repository, "name", "?"), task.status, task.attempt)
            for task in RepoResearchTask.objects.filter(session=fresh).select_related("repository")
            if str(task.repository_id) in target_ids
        ]
        return fresh.current_stage, fresh.status, sorted(rows)

    stage, status, rows = await _snapshot()
    print(f"[after] stage={stage} status={status}")
    for name, task_status, attempt in rows:
        print(f"  {name}: status={task_status} attempt={attempt}")


if __name__ == "__main__":
    asyncio.run(main())
