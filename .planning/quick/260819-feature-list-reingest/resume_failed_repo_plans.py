"""部署 poisoned-resume 修复后，安全恢复剩余 2 个分仓方案。

根因不是单纯的上游随机抖动：首次提交前 socket 断连后，跨阶段/残缺 transcript
可能被当作 resume 输入；invalid/container failure 又存在「置 stale 但不唤醒」和
「裸 failed 被 barrier 当 ready」两条状态机缺口。修复后 resume 按 mode/source +
MCP 成功标记 + JSONL/thinking 形状过滤，失败在有界重试耗尽时会物化合法 degraded plan。

恢复脚本必须 fail-closed：
- 当前 Artifact 必须仍是目标蓝图；
- 锁定仓中已有方案必须原样保留；
- eligible 只能是 failed/stale 且**没有 repo_plan** 的两个预期仓；
- 绝不对 DONE task 调 mark_stale（会使其 valid PartialPlan 失效）。

复位入口用 `arewind_to_stage`（⛔ 不用 `areopen_stage`：后者明文禁止从 failed
复位）。它明确支持从任意状态（含 failed）回卷到指定 stage 并置 running，语义正是
「带操作员指令重跑某个节点」，且不碰 `error` —— 失败首因原样留痕。

⭐ dispatch 后必须等 durable 队列排空再退出（否则最后入队的 job 随进程消失）。
"""

import asyncio
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

SESSION_ID = "4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6"
ARTIFACT_ID = "7b67b615-8830-4980-bf0f-3572fded41fa"
EXPECTED_REPOS = {"frontend/onion-learning", "backend/study-course"}
STAGE = "repo_plan"
WAIT_S = 45


async def main() -> None:
    from asgiref.sync import sync_to_async

    from delivery.models import ConvergenceSession
    from delivery.models.artifact import ArtifactVersion
    from delivery.models.research_task import RepoResearchTask, RepoResearchTaskStatus
    from delivery.services import ConvergenceSessionService, ResearchService
    from services.process_runtime.blueprint_repo_plan import BlueprintRepoPlanAdapter
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

    @sync_to_async
    def _load_artifact_id(session):
        version = ArtifactVersion.objects.get(id=session.current_artifact_version_id)
        return str(version.artifact_id)

    @sync_to_async
    def _load_tasks():
        s = ConvergenceSession.objects.get(id=SESSION_ID)
        rows = list(RepoResearchTask.objects.filter(session=s).select_related("repository"))
        return s, rows

    session, tasks = await _load_tasks()
    artifact_id = await _load_artifact_id(session)
    if artifact_id != ARTIFACT_ID:
        raise SystemExit(f"Artifact 漂移：expected={ARTIFACT_ID}, actual={artifact_id}")

    plan_adapter = BlueprintRepoPlanAdapter()
    locked_repos = await plan_adapter.acollect_locked_repos(session)
    plans = await plan_adapter.acollect_repo_plans(session)
    task_by_repo = {str(task.repository_id): task for task in tasks}

    eligible = []
    missing = []
    for repo in locked_repos:
        repository_id = str(repo["repository_id"])
        if plans.get(repository_id):
            continue
        task = task_by_repo.get(repository_id)
        name = getattr(getattr(task, "repository", None), "name", "?")
        missing.append(name)
        if task is not None and task.status in (
            RepoResearchTaskStatus.FAILED,
            RepoResearchTaskStatus.STALE,
        ):
            eligible.append((task, name))

    print(f"[before] stage={session.current_stage} status={session.status}")
    print(
        f"artifact={artifact_id} locked={len(locked_repos)} "
        f"已有方案={len(plans)} 缺方案={len(missing)}"
    )
    for name in missing:
        print(f"  missing: {name}")

    if set(missing) != EXPECTED_REPOS:
        raise SystemExit(
            f"缺方案集合异常，拒绝恢复：expected={sorted(EXPECTED_REPOS)}, actual={sorted(missing)}"
        )
    if {name for _task, name in eligible} != EXPECTED_REPOS:
        raise SystemExit("eligible 集合不是预期两个 failed/stale 仓，拒绝恢复")

    if "--dry-run" in sys.argv:
        print("[dry-run] 守卫通过；未修改会话")
        return

    # ① 会话回卷到 repo_plan 并置 running（正规入口，保留 error 首因与 Artifact 指针）
    applied = await ConvergenceSessionService().arewind_to_stage(
        session,
        stage=STAGE,
        reason="operator: resume only two plan-less repos after poisoned-resume fix",
    )
    print(f"[rewind] applied={applied} → stage={session.current_stage} status={session.status}")
    if not applied:
        print("回卷未生效（并发已推进会话），放弃本次重派")
        return

    # ② 只碰 eligible；⛔ DONE 永不 mark_stale（否则会失效已有方案）
    rs = ResearchService()
    repo_ids: set[str] = set()
    for task, name in eligible:
        if task.status == RepoResearchTaskStatus.FAILED:
            await rs.mark_stale([task.id])
        repo_ids.add(str(task.repository_id))
        print(f"  {name}: {task.status} → stale/dispatchable")

    # ③ 定向重派这 2 仓
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
