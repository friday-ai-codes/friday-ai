"""操作员排除 course-business / onion-auth 后继续融合。

不把这两个仓纳入锁定集；只写入 merge.ignored_support_aliases，作废当前阻塞
澄清，再 rewind+drive 一次。融合会把对应 needs_support 降为 existing，并记入
deferred_ideas。
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
STALE_THREAD_ID = "fd26575f-cc96-4500-837c-5c7a0e7effcc"
IGNORED = ["onion-auth", "course-business", "backend/course-business"]


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
    if session.current_stage != "merge":
        raise SystemExit(f"会话不在 merge：stage={session.current_stage} status={session.status}")
    if (
        str(thread.artifact_id) != ARTIFACT_ID
        or thread.status != "open"
        or not thread.blocking
        or thread.return_stage != "merge"
    ):
        raise SystemExit("merge 阻塞线程形状漂移，拒绝恢复")
    for marker in ("onion-auth", "course-business"):
        if marker not in body:
            raise SystemExit(f"线程缺少标记 {marker}，拒绝恢复")

    merge_bucket = dict((session.stage_state or {}).get("merge") or {})
    merge_bucket["ignored_support_aliases"] = list(IGNORED)
    print(f"[guard] ignore={IGNORED} thread={thread.id}")
    if "--dry-run" in sys.argv:
        print("[dry-run] 守卫通过；未修改 DB")
        return

    await BlueprintLifecycleService().resolve_thread(
        thread,
        resolution=(
            "[操作员裁决] 不纳入 course-business / onion-auth；本轮按外部依赖/本期不做处理，"
            "继续用当前 8 仓融合。"
        ),
        initiated_by_user_id="system",
        dismissed=True,
    )
    print(f"[thread] dismissed {thread.id}")

    applied = await ConvergenceSessionService().arewind_to_stage(
        session,
        stage="merge",
        stage_state_update={"merge": merge_bucket},
        reason="operator: ignore missing collaboration repos and continue merge",
    )
    print(f"[rewind] applied={applied}")
    if not applied:
        raise SystemExit("并发驱动已改变会话，拒绝继续")

    result = await arun_blueprint_resume(SESSION_ID, initiated_by_user_id="system")
    print(f"[drive] {result}")


if __name__ == "__main__":
    asyncio.run(main())
