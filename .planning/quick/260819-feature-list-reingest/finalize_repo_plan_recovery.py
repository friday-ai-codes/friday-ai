"""收尾本轮 repo_plan：关闭已被合法方案取代的历史机械澄清，并续驱到下一停点。

只适用于会话 4d6984c4 / 蓝图 7b67b615。三条 blocking thread 都来自旧 indirect
合成路径未执行 ``coerce_repo_plan_shapes``，问题正文固定为
``$.risks[0]: 'block_id' is a required property``。现在对应仓已有合法 RepoPlan，
继续阻塞属于陈旧故障留痕，不是待用户决策。

Fail-closed 守卫：
1. Artifact 与会话 ID 必须精确匹配；
2. 锁定仓必须 8/8 均已有 RepoPlan；
3. 只收尾固定三个 thread ID，且每条必须 open+blocking、return_stage=repo_plan，
   消息正文必须命中历史 block_id 机械错误；
4. 两条 degraded nonblocking clarification 保持 open，供人审查看；
5. 不 mark_stale、不重派、不修改任何 PartialPlan。
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
STALE_THREAD_IDS = {
    "8a307bac-0ac0-4a29-8203-a52834fd9853",
    "d9acad19-b6f0-46e5-9022-64776e04dc6f",
    "1422fa32-1e1a-42db-b9b8-c689a6fe744f",
}
MECHANICAL_ERROR = "$.risks[0]: 'block_id' is a required property"


async def main() -> None:
    from delivery.models import ArtifactVersion, ConvergenceSession
    from delivery.models.blueprint_thread import BlueprintThread
    from delivery.services import ConvergenceSessionService
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
    from services.process_runtime.blueprint_repo_plan import BlueprintRepoPlanAdapter
    from services.process_runtime.blueprint_resume import arun_blueprint_resume

    session = await ConvergenceSession.objects.aget(id=SESSION_ID)
    version = await ArtifactVersion.objects.aget(id=session.current_artifact_version_id)
    if str(version.artifact_id) != ARTIFACT_ID:
        raise SystemExit(
            f"Artifact 漂移：expected={ARTIFACT_ID}, actual={version.artifact_id}"
        )

    adapter = BlueprintRepoPlanAdapter()
    locked = await adapter.acollect_locked_repos(session)
    plans = await adapter.acollect_repo_plans(session)
    missing = [
        str(repo["repository_id"])
        for repo in locked
        if not plans.get(str(repo["repository_id"]))
    ]
    if len(locked) != 8 or missing:
        raise SystemExit(
            f"RepoPlan 未齐，拒绝收尾：locked={len(locked)} plans={len(plans)} missing={missing}"
        )

    threads = [
        thread
        async for thread in BlueprintThread.objects.filter(
            id__in=STALE_THREAD_IDS,
            artifact_id=ARTIFACT_ID,
        ).prefetch_related("messages")
    ]
    if {str(thread.id) for thread in threads} != STALE_THREAD_IDS:
        raise SystemExit("历史 blocking thread 集合漂移，拒绝收尾")

    for thread in threads:
        bodies = [message.body async for message in thread.messages.all()]
        if (
            thread.status != "open"
            or not thread.blocking
            or thread.return_stage != "repo_plan"
            or not any(MECHANICAL_ERROR in body for body in bodies)
        ):
            raise SystemExit(f"thread {thread.id} 形状不符，拒绝收尾")

    print(
        f"[guard] artifact={ARTIFACT_ID} plans={len(plans)}/{len(locked)} "
        f"stale_blocking_threads={len(threads)}"
    )
    if "--dry-run" in sys.argv:
        print("[dry-run] 守卫通过；未修改 DB")
        return

    lifecycle = BlueprintLifecycleService()
    for thread in threads:
        await lifecycle.resolve_thread(
            thread,
            resolution=(
                "[自动收尾] 对应仓已产出 schema-valid RepoPlan；原问题为旧合成路径未执行 "
                "coerce_repo_plan_shapes 导致的内部 block_id 机械校验失败，现已修复并由测试覆盖。"
            ),
            initiated_by_user_id="system",
        )
        print(f"[thread] resolved {thread.id}")

    applied = await ConvergenceSessionService().arewind_to_stage(
        session,
        stage="repo_plan",
        reason="operator: finalize 8/8 repo plans after event-specific wait-status fix",
    )
    print(f"[rewind] applied={applied}")
    if not applied:
        raise SystemExit("并发驱动已改变会话，拒绝继续；请重读后再执行")

    result = await arun_blueprint_resume(SESSION_ID, initiated_by_user_id="system")
    print(f"[drive] {result}")


if __name__ == "__main__":
    asyncio.run(main())
