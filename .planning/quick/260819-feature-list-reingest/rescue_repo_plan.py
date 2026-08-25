"""捞起 repo_plan 阶段搁浅的 4 个仓并重派（3 个 container_failed + 1 个 invalid stale）。

死因（2026-08-19 15:27~15:31 实录）：
- 3 仓（study-course / onion-learning / study-user-status）：agent 探索全部完成、
  正要提交 RepoPlan 的**最后一次 LLM 调用**被上游掐断（"socket connection was closed
  unexpectedly"，此前已连串 api_retry）→ SDK exit 1 → 回调按 container_failed 落终态。
  上游瞬时抖动，非方案逻辑问题。
- 1 仓（study-app）：方案已提交但没过 schema 校验 → `repo_plan_invalid_retrying`
  置 stale 等第二轮。

为什么必须人工捞（产品缺口，暂不改产品代码）：阶段死锁 ——
`aall_repo_plans_ready` 判「有 repo_plan 段 或 task=failed」，stale 的 study-app
两者都不是 ⇒ barrier 恒 False ⇒ 续驱不发生；而 `repo_plan_invalid_retrying`
分支只置 stale **不派发**，能派 stale 的又只有 barrier 续驱。互相等，永不自愈。

重派口径：
- failed 的 3 仓先 `mark_stale`（WR-01：终态才可置回），study-app 已 stale 跳过；
- 一次 `dispatch(mode="plan", repository_ids={4 仓})`；有界重试上界按 bp-plan 容器数
  判（≤ MAX_REPO_PLAN_ATTEMPTS+1 = 3 个），4 仓现各 1 个，额度充足；
- ⭐ dispatch 后必须等 durable 队列排空再退出（教训见 redispatch_one.py）。
"""

import asyncio
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

SESSION_ID = "4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6"
# task_id 前缀 → 期望现状（从 blueprint.repo_plan.repo_failed 事件核对）
TASKS = {
    "e26fcd9d": "frontend/onion-learning (container_failed)",
    "efdf0a70": "backend/study-course (container_failed)",
    "0fbdbb9f": "backend/study-user-status (container_failed)",
    "0aae5922": "frontend/study-app (repo_plan_invalid_retrying)",
}
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
        out = []
        for prefix in TASKS:
            t = (
                RepoResearchTask.objects.filter(session=s, id__startswith=prefix)
                .select_related("repository")
                .first()
            )
            out.append((prefix, t))
        return s, out

    session, rows = await _load()
    rs = ResearchService()
    repo_ids: set[str] = set()

    for prefix, task in rows:
        label = TASKS[prefix]
        if task is None:
            print(f"  ✗ 没找到 task {prefix}（{label}）")
            continue
        print(f"  {label}: status={task.status}")
        if task.status == RepoResearchTaskStatus.DONE:
            print("    已 done，跳过")
            continue
        if task.status == RepoResearchTaskStatus.FAILED:
            await rs.mark_stale([task.id])
            print("    failed → stale")
        repo_ids.add(str(task.repository_id))

    if not repo_ids:
        print("无可重派仓")
        return
    if "--dry-run" in sys.argv:
        return

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
