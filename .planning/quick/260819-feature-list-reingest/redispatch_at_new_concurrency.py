"""并发 2 → 10 后重派本轮 7 个调研任务（含 attempt 复位）。

背景：为加载新并发必须重启 runner 进程（信号量在 `scheduler.New()` 固化，无热加载）。
重启把 2 个在途容器 + 5 个躺在 runner **内存队列**里的任务一起清零 —— 服务端却仍标
7 个 `running`，回调永不回来。

为什么要复位 `attempt`：这 7 个的 `attempt` 已是 2，正好等于
`blueprint_research_adapter._MAX_ATTEMPTS`。直接重派会在派发口被当场判
`max_attempts_exhausted` 永久失败。而这两次「失败」**没有一次是 agent 真的失败**：
第一次是 launchd 重启 runner 杀容器，第二次是本次为换并发主动重启。把基础设施事故
记在任务的重试额度上是错的口径，故复位为 0 给回完整额度。

⚠️ `attempt` 复位没有服务面（`ResearchService` 只有 `bump_attempt` 自增 /
`retry_task` 自增，无 setter），故此处直接 ORM update —— 这是运维修复，不是产品行为，
⛔ 不要把这个口径搬进 server 代码。

状态推进仍走服务面（WR-01：置 STALE 前必须先落终态）：mark_failed → mark_stale，
STALE ∈ `_DISPATCHABLE_STATUSES` 才会被 dispatch 捡起。只碰 `running` 的那批，
⛔ 绝不动已 `done` 的 2 个（会连带把它们的 PartialPlan 判失效）。
"""

import asyncio
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

SESSION_ID = "4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6"
FAIL_REASON = "runner_restart_for_concurrency_bump"


async def main() -> None:
    from asgiref.sync import sync_to_async

    from delivery.models import ConvergenceSession
    from delivery.models.research_task import RepoResearchTask, RepoResearchTaskStatus
    from delivery.services import ResearchService
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

    @sync_to_async
    def _load():
        s = ConvergenceSession.objects.get(id=SESSION_ID)
        tasks = list(
            RepoResearchTask.objects.filter(
                session=s, status=RepoResearchTaskStatus.RUNNING
            ).select_related("repository")
        )
        return s, [(t, getattr(t.repository, "name", "?"), t.attempt) for t in tasks]

    session, rows = await _load()
    print(f"待复位（status=running，容器已随 runner 重启消失）：{len(rows)} 个")
    for _t, name, attempt in rows:
        print(f"  {name:34s} attempt={attempt} → 0")

    if not rows:
        print("无需复位")
        return
    if "--dry-run" in sys.argv:
        return

    rs = ResearchService()

    @sync_to_async
    def _reset_attempt(task_id) -> None:
        RepoResearchTask.objects.filter(id=task_id).update(attempt=0)

    for task, name, _attempt in rows:
        await rs.mark_failed(task, {"reason": FAIL_REASON})
        await rs.mark_stale([task.id])
        await _reset_attempt(task.id)
        print(f"  reset {name}")

    result = await BlueprintResearchAdapter().dispatch(session)
    result = result if isinstance(result, dict) else {}
    print(
        f"\n[dispatch] dispatched={result.get('dispatched')} "
        f"synthesized={result.get('synthesized')} degraded={result.get('degraded')}"
    )

    @sync_to_async
    def _snap() -> str:
        s = ConvergenceSession.objects.get(id=SESSION_ID)
        by: dict[str, int] = {}
        for t in RepoResearchTask.objects.filter(session=s):
            by[t.status] = by.get(t.status, 0) + 1
        return ", ".join(f"{k}={v}" for k, v in sorted(by.items()))

    print(f"[after] research: {await _snap()}")


if __name__ == "__main__":
    asyncio.run(main())
