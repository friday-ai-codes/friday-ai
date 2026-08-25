"""恢复被 runner 重启打成孤儿的调研任务（runner 14:14 重启，杀掉在途 7 个容器）。

现象：7 个 RepoResearchTask 僵在 `running`，容器已不存在、回调永不回来，barrier 死等。
根因：runner 进程重启 → 它手里的 docker 容器成孤儿被杀 → 新 runner 无记忆。

修复（对每个假 running）：
  1) mark_failed（落终态，reason=runner_restart_orphaned）
  2) mark_stale（STALE ∈ 可派发白名单，WR-01 要求先终态才能置回）
然后 BlueprintResearchAdapter().dispatch(session) 走**增量**重派：只派 PENDING/STALE
（2 个 done 天然跳过），派到当前在线 runner。容器回调打到正在跑的 server，barrier 续推。

⚠️ 只处理**超时无更新**的 running（默认 > 20 分钟无 updated_at），避免误杀真正在跑的容器。
"""

import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

SESSION_ID = "4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6"
STALE_AFTER_SECONDS = 20 * 60


async def main() -> None:
    from asgiref.sync import sync_to_async
    from django.utils import timezone

    from delivery.models import ConvergenceSession
    from delivery.models.research_task import RepoResearchTask, RepoResearchTaskStatus
    from delivery.services import ResearchService
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

    now = timezone.now()

    @sync_to_async
    def _load_orphans():
        s = ConvergenceSession.objects.get(id=SESSION_ID)
        out = []
        for t in RepoResearchTask.objects.filter(
            session=s, status=RepoResearchTaskStatus.RUNNING
        ).select_related("repository"):
            age = (now - t.updated_at).total_seconds()
            out.append((t, getattr(t.repository, "name", "?"), age))
        return s, out

    session, orphans = await _load_orphans()
    stale = [(t, name, age) for (t, name, age) in orphans if age >= STALE_AFTER_SECONDS]

    print(f"running total={len(orphans)}  超时(≥{STALE_AFTER_SECONDS}s)={len(stale)}")
    for _t, name, age in orphans:
        flag = "→ 打回" if age >= STALE_AFTER_SECONDS else "  跳过(可能真在跑)"
        print(f"  {name:32s} {int(age):5d}s no-update  {flag}")

    if not stale:
        print("无超时孤儿，无需恢复")
        return
    if "--dry-run" in sys.argv:
        return

    rs = ResearchService()
    for t, name, _age in stale:
        await rs.mark_failed(t, {"reason": "runner_restart_orphaned"})
        await rs.mark_stale([t.id])
        print(f"  reset {name}")

    adapter = BlueprintResearchAdapter()
    result = await adapter.dispatch(session)
    result = result if isinstance(result, dict) else {}
    print(
        f"[dispatch] dispatched={result.get('dispatched')} "
        f"synthesized={result.get('synthesized')} degraded={result.get('degraded')}"
    )

    @sync_to_async
    def _snap():
        s = ConvergenceSession.objects.get(id=SESSION_ID)
        by = {}
        for t in RepoResearchTask.objects.filter(session=s):
            by[t.status] = by.get(t.status, 0) + 1
        return ", ".join(f"{k}={v}" for k, v in sorted(by.items()))

    print(f"[after] research: {await _snap()}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
