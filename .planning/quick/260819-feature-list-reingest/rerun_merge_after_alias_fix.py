"""协作仓别名归一修复后，收尾旧 merge 澄清并只重跑 merge。

旧线程同时包含一条假阳性（``onion-learning`` 实为已锁定的
``frontend/onion-learning``）和两个真实缺仓（``course-business`` / ``onion-auth``）。
别名修复后必须重跑 merge 才能生成只含真实缺口的新线程；不能把旧线程直接当成人工问题。
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
STALE_THREAD_ID = "3fb0a02e-e176-466d-8bbb-c0a370ea171a"


async def main() -> None:
    from delivery.models import ArtifactVersion, ConvergenceSession
    from delivery.models.blueprint_thread import BlueprintThread
    from delivery.services import ConvergenceSessionService
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
    from services.process_runtime.blueprint_resume import arun_blueprint_resume

    session = await ConvergenceSession.objects.aget(id=SESSION_ID)
    version = await ArtifactVersion.objects.aget(id=session.current_artifact_version_id)
    thread = await BlueprintThread.objects.prefetch_related("messages").aget(id=STALE_THREAD_ID)
    messages = [message.body async for message in thread.messages.all()]
    body = "\n".join(messages)

    if str(version.artifact_id) != ARTIFACT_ID:
        raise SystemExit("Artifact 漂移，拒绝恢复")
    if session.current_stage != "merge" or session.status != "waiting_clarification":
        raise SystemExit(
            f"会话不在预期停点：stage={session.current_stage} status={session.status}"
        )
    if (
        str(thread.artifact_id) != ARTIFACT_ID
        or thread.status != "open"
        or not thread.blocking
        or thread.return_stage != "merge"
    ):
        raise SystemExit("旧 merge thread 形状漂移，拒绝恢复")
    for marker in ("onion-learning", "course-business", "onion-auth"):
        if marker not in body:
            raise SystemExit(f"旧 merge thread 缺少标记 {marker}，拒绝恢复")

    print(f"[guard] merge thread={thread.id} 命中 1 条假阳性 + 2 个真实缺仓")
    if "--dry-run" in sys.argv:
        print("[dry-run] 守卫通过；未修改 DB")
        return

    await BlueprintLifecycleService().resolve_thread(
        thread,
        resolution=(
            "[别名归一后重算] 旧线程把已锁定的 frontend/onion-learning 短名误判成缺仓；"
            "本线程作废，真实缺口由重跑 merge 后的新线程承载。"
        ),
        initiated_by_user_id="system",
        dismissed=True,
    )
    print(f"[thread] dismissed {thread.id}")

    applied = await ConvergenceSessionService().arewind_to_stage(
        session,
        stage="merge",
        reason="operator: rerun merge after support repository alias canonicalization",
    )
    print(f"[rewind] applied={applied}")
    if not applied:
        raise SystemExit("并发驱动已改变会话，拒绝继续")

    result = await arun_blueprint_resume(SESSION_ID, initiated_by_user_id="system")
    print(f"[drive] {result}")


if __name__ == "__main__":
    asyncio.run(main())
