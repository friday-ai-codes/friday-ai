"""重派 repo_plan 阶段里「status=running 却无容器在途」的孤儿 task。

前提由调用方保证：`docker ps -a` 已确认无任何 friday-task 容器（否则可能误杀真在跑的）。

孤儿成因（2026-08-19 实录）：本机有**两个** launchd runner 服务抢同一个 PID 锁
（`ai.friday.runner` /usr/local/bin 与 `ai.friday.runner.dev` ~/.local/share/bin，
共享 config 与 PID 文件）。占锁方切换时，新起的 runner `startup_cleanup` 清掉前一个
留下的在途容器 → 容器消失、正常退出回调永不发出 → task 卡 running，barrier 死等。

处置（与 rescue_repo_plan.py 同口径）：running → mark_failed(落终态) → mark_stale
（WR-01：终态才可置回可派发白名单）→ 一次性 dispatch(mode=plan, 全部孤儿仓)。
plan 模式豁免 `_MAX_ATTEMPTS`（attempt 跨阶段共用），有界重试按 bp-plan 容器数判，
现各 2 个，重派起第 3 个，成功产出合格方案即 done。

⭐ dispatch 后必须等 durable 队列排空再退出（否则最后入队 job 随进程消失）。
"""

import asyncio
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

SESSION_ID = "4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6"
WAIT_S = 45


async def main() -> None:
    from asgiref.sync import sync_to_async

    from delivery.models import ConvergenceSession
    from delivery.models.research_task import RepoResearchTask, RepoResearchTaskStatus
    from delivery.services import ResearchService
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

    @sync_to_async
    def _load():
        s = ConvergenceSession.objects.get(id=SESSION_ID)
        rows = [
            (t, getattr(t.repository, "name", "?"))
            for t in RepoResearchTask.objects.filter(
                session=s, status=RepoResearchTaskStatus.RUNNING
            ).select_related("repository")
        ]
        return s, rows

    session, rows = await _load()
    print(f"stage={session.current_stage} status={session.status}")
    print(f"running 孤儿：{len(rows)} 个")
    for _t, name in rows:
        print(f"  {name}")
    if not rows:
        print("无孤儿，无需处置")
        return
    if "--dry-run" in sys.argv:
        return

    rs = ResearchService()
    repo_ids: set[str] = set()
    for task, name in rows:
        await rs.mark_failed(task, {"reason": "runner_lock_swap_orphaned"})
        await rs.mark_stale([task.id])
        repo_ids.add(str(task.repository_id))
        print(f"  reset {name}")

    result = await BlueprintResearchAdapter().dispatch(
        session, mode="plan", repository_ids=repo_ids
    )
    result = result if isinstance(result, dict) else {}
    print(f"\n[dispatch] dispatched={result.get('dispatched')} degraded={result.get('degraded')}")

    print(f"[wait] 等 durable 队列排空 {WAIT_S}s …")
    await asyncio.sleep(WAIT_S)

    @sync_to_async
    def _snap() -> str:
        s = ConvergenceSession.objects.get(id=SESSION_ID)
        by: dict[str, int] = {}
        for t in RepoResearchTask.objects.filter(session=s):
            by[t.status] = by.get(t.status, 0) + 1
        return f"stage={s.current_stage} status={s.status} | " + ", ".join(
            f"{k}={v}" for k, v in sorted(by.items())
        )

    print(f"[after] {await _snap()}")


if __name__ == "__main__":
    asyncio.run(main())
