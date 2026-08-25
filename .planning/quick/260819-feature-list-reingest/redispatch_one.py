"""补派单个仓的调研任务（用于「服务端已派、容器没起来」的漏网户）。

为什么会漏：`BlueprintResearchAdapter.dispatch()` 把每个仓的派发做成 **durable job**
（`runner_dispatch_enqueued` → `durable:dispatch:*`），由进程内 `background_runner`
消费。用一次性脚本调 dispatch 时，脚本在 `dispatch()` 返回后立刻退出 ——
**最后入队的那个 job 还没被消费就随进程一起没了**：服务端已 `mark_running`，
runner 侧却连 `task_queued` 都没收到，于是 barrier 死等一个不存在的容器。

所以本脚本在 dispatch 后**必须停留**，等 durable 队列排空（`--wait` 秒，缺省 30）。
⛔ 不要把 dispatch 放进「调完就退」的脚本里而不等待。
"""

import asyncio
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

SESSION_ID = "4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6"


async def main() -> None:
    from asgiref.sync import sync_to_async

    from delivery.models import ConvergenceSession
    from delivery.models.research_task import RepoResearchTask, RepoResearchTaskStatus
    from delivery.services import ResearchService
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

    repo_id = sys.argv[1]
    wait_s = int(sys.argv[sys.argv.index("--wait") + 1]) if "--wait" in sys.argv else 30

    @sync_to_async
    def _load():
        s = ConvergenceSession.objects.get(id=SESSION_ID)
        t = (
            RepoResearchTask.objects.filter(session=s, repository_id=repo_id)
            .select_related("repository")
            .first()
        )
        return s, t, (getattr(t.repository, "name", "?") if t else "?")

    session, task, name = await _load()
    if task is None:
        raise SystemExit(f"没找到 repository_id={repo_id} 的 task")

    print(f"{name}: status={task.status} attempt={task.attempt}")
    if task.status == RepoResearchTaskStatus.DONE:
        print("已 done，无需补派")
        return

    rs = ResearchService()
    await rs.mark_failed(task, {"reason": "durable_job_lost_with_script_exit"})
    await rs.mark_stale([task.id])
    print(f"  reset {name}")

    result = await BlueprintResearchAdapter().dispatch(session)
    result = result if isinstance(result, dict) else {}
    print(f"[dispatch] dispatched={result.get('dispatched')} degraded={result.get('degraded')}")

    # ⭐ 关键：等 durable 派发队列排空，否则刚入队的 job 会随本进程退出一起消失。
    print(f"[wait] 等 durable 队列排空 {wait_s}s …")
    await asyncio.sleep(wait_s)

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
