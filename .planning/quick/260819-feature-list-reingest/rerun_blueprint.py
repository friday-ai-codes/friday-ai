"""高三提分专项蓝图 —— 从头完整重跑（ignore pin：项目无手动绑定，天然满足）。

步骤：
1) reset：删除旧蓝图会话 ef351b31（级联 RepoResearchTask / 事件）+ 蓝图工件 eea84be4
   （级联 versions / blueprint_threads / reviewers）。
2) start：FeatureSolutionService.start(project_id, entrypoint="mcp") 建新会话并派研。
3) drive：轮询 FeatureSolutionService.get() 驱动 route→repo_research→reroute→repo_confirmation，
   直到停在确认门（waiting_clarification）或终态/失败。

用法：
  python rerun_blueprint.py reset-and-start   # 删旧 + 起新（快，打印新 session_id）
  python rerun_blueprint.py drive <session_id> # 轮询驱动到确认门（长跑）
"""

import asyncio
import os
import sys
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

PROJECT_ID = "75248ff9-3a22-4175-b940-6093d71eb4dc"
OLD_SESSION_PREFIX = "ef351b31"
OLD_ARTIFACT_PREFIX = "eea84be4"


async def reset() -> None:
    from asgiref.sync import sync_to_async

    from delivery.models import ConvergenceSession
    from delivery.models.artifact import Artifact

    @sync_to_async
    def _wipe() -> str:
        out = []
        art = Artifact.objects.filter(id__startswith=OLD_ARTIFACT_PREFIX).first()
        if art is not None:
            info = f"artifact {art.id} threads={art.blueprint_threads.count()} versions={art.versions.count()}"
            art.delete()
            out.append("deleted " + info)
        else:
            out.append("no old artifact")
        sess = ConvergenceSession.objects.filter(id__startswith=OLD_SESSION_PREFIX).first()
        if sess is not None:
            from delivery.models.research_task import RepoResearchTask

            rt = RepoResearchTask.objects.filter(session=sess).count()
            sess.delete()
            out.append(f"deleted session {sess.id} (research_tasks={rt})")
        else:
            out.append("no old session")
        return " | ".join(out)

    print("[reset]", await _wipe())


async def start() -> str:
    from asgiref.sync import sync_to_async
    from django.contrib.auth import get_user_model

    from initiatives.services.feature_solution_service import FeatureSolutionService

    User = get_user_model()
    admin = await sync_to_async(
        lambda: User.objects.filter(is_superuser=True).order_by("id").first()
    )()
    state = await FeatureSolutionService().start(
        project_id=PROJECT_ID,
        entrypoint="mcp",
        actor=admin,
        initiated_by_user_id=getattr(admin, "id", "") or "",
    )
    sid = state.session_id
    print(
        f"[start] session={sid} status={state.status} "
        f"current_status={getattr(state, 'current_status', '?')} "
        f"source={getattr(state, 'source', '?')} feature_count={getattr(state, 'feature_count', '?')} "
        f"questions={len(getattr(state, 'questions', []) or [])}"
    )
    return sid


async def _research_snapshot(session_id: str) -> str:
    from asgiref.sync import sync_to_async

    from delivery.models import ConvergenceSession
    from delivery.models.research_task import RepoResearchTask

    @sync_to_async
    def _snap() -> str:
        s = ConvergenceSession.objects.filter(id=session_id).first()
        if s is None:
            return "session-gone"
        tasks = list(RepoResearchTask.objects.filter(session=s))
        by = {}
        for t in tasks:
            by[t.status] = by.get(t.status, 0) + 1
        detail = ", ".join(f"{k}={v}" for k, v in sorted(by.items()))
        return f"stage={s.current_stage} status={s.status} research[{len(tasks)}]: {detail or '-'}"

    return await _snap()


async def _failures(session_id: str) -> list[str]:
    from asgiref.sync import sync_to_async

    from delivery.models import ConvergenceSession
    from delivery.models.convergence_session_event import ConvergenceSessionEvent

    @sync_to_async
    def _f() -> list[str]:
        s = ConvergenceSession.objects.filter(id=session_id).first()
        if s is None:
            return []
        evs = ConvergenceSessionEvent.objects.filter(session=s).order_by("-created_at")
        out = []
        for e in evs:
            name = str(getattr(e, "event", "") or "")
            if "failed" in name or "error" in name or "unparseable" in name:
                out.append(name)
        return out[:20]

    return await _f()


async def drive(session_id: str, *, max_minutes: int = 40) -> None:
    from asgiref.sync import sync_to_async
    from django.contrib.auth import get_user_model

    from initiatives.services.feature_solution_service import FeatureSolutionService

    User = get_user_model()
    admin = await sync_to_async(
        lambda: User.objects.filter(is_superuser=True).order_by("id").first()
    )()
    svc = FeatureSolutionService()

    deadline = time.time() + max_minutes * 60
    last = ""
    stable = 0
    while time.time() < deadline:
        try:
            state = await svc.get(session_id=session_id, actor=admin)
            status = state.status
            cur = getattr(state, "current_status", "?")
        except Exception as exc:  # noqa: BLE001
            status, cur = f"get_error:{type(exc).__name__}", "?"
        snap = await _research_snapshot(session_id)
        line = f"status={status} current={cur} | {snap}"
        stamp = time.strftime("%H:%M:%S")
        if line != last:
            print(f"[{stamp}] {line}", flush=True)
            last = line
            stable = 0
        else:
            stable += 1
            if stable % 6 == 0:
                print(f"[{stamp}] (stable) {line}", flush=True)

        if status in ("completed", "failed"):
            print(f"[drive] terminal: {status}", flush=True)
            break
        # 确认门：waiting_clarification 且研究已全部结束（无 pending/stale/running）
        if "waiting_clarification" in str(cur) or status == "awaiting_confirmation":
            if all(k not in snap for k in ("pending=", "stale=", "running=", "dispatched=")):
                print("[drive] reached repo_confirmation gate (all research settled)", flush=True)
                break
        await asyncio.sleep(20)

    fails = await _failures(session_id)
    print(f"[drive] failure-events: {fails or 'none'}", flush=True)
    print(f"[drive] final: {await _research_snapshot(session_id)}", flush=True)


async def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "reset-and-start"
    if cmd == "reset-and-start":
        await reset()
        sid = await start()
        print(f"NEW_SESSION_ID={sid}", flush=True)
    elif cmd == "drive":
        # 第三个参数是轮询上限分钟数（缺省 40）。深调研单仓动辄 30 分钟以上，9 个仓
        # 排队时 40 分钟远不够；轮询一停，stage 转移就没人驱动了。
        minutes = int(sys.argv[3]) if len(sys.argv) > 3 else 40
        await drive(sys.argv[2], max_minutes=minutes)
    elif cmd == "reset":
        await reset()
    elif cmd == "start":
        sid = await start()
        print(f"NEW_SESSION_ID={sid}", flush=True)
    else:
        raise SystemExit(f"unknown cmd: {cmd}")


if __name__ == "__main__":
    asyncio.run(main())
