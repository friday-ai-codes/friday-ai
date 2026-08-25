"""只读看护：盯 repo_plan 收官（2 仓提交结果 → merge/ai_review），不驱动、不改状态。

与 `rerun_blueprint.py drive` 的差异：那个脚本的终止判据是**确认门**，用在 repo_plan
收官阶段会误判退出（实测 140s 即退），且它调 `FeatureSolutionService.get()` 带副作用。
本脚本纯读 ORM：session stage/status + 9 个 task 状态 + 新增失败事件，只在**变化时**打印。

退出条件：
  - 2 仓都不再 running（各自落 done 或 failed）→ 打印收官摘要退出；
  - session 落 done/failed 终态 → 退出；
  - 超时。
"""

import os
import sys
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

SESSION_ID = "4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6"
WATCHED = ("frontend/onion-learning", "backend/study-course")


def snapshot() -> tuple[str, str, dict, list[str]]:
    from delivery.models import ConvergenceSession
    from delivery.models.research_task import RepoResearchTask

    s = ConvergenceSession.objects.get(id=SESSION_ID)
    by: dict[str, int] = {}
    watched: list[str] = []
    for t in (
        RepoResearchTask.objects.filter(session=s).select_related("repository").order_by("id")
    ):
        by[t.status] = by.get(t.status, 0) + 1
        name = getattr(t.repository, "name", "?")
        if name in WATCHED:
            watched.append(f"{name.split('/')[-1]}={t.status}")
    return s.current_stage, s.status, by, watched


def recent_events(limit: int = 6) -> list[str]:
    from delivery.models import ConvergenceSession
    from delivery.models.convergence_session_event import ConvergenceSessionEvent

    s = ConvergenceSession.objects.get(id=SESSION_ID)
    out = []
    for e in ConvergenceSessionEvent.objects.filter(session=s).order_by("-created_at")[:limit]:
        out.append(f"{e.created_at:%H:%M:%S} {getattr(e, 'event', '?')}")
    return out


def main() -> None:
    minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    deadline = time.time() + minutes * 60
    last = ""
    while time.time() < deadline:
        stage, status, by, watched = snapshot()
        line = (
            f"stage={stage} status={status} | "
            + ", ".join(f"{k}={v}" for k, v in sorted(by.items()))
            + " | "
            + " ".join(watched)
        )
        if line != last:
            print(f"[{time.strftime('%H:%M:%S')}] {line}", flush=True)
            last = line

        if status in ("done", "failed"):
            print(f"[watch] session terminal: {status}", flush=True)
            break
        if not any("running" in w for w in watched):
            print("[watch] 两仓均已落终态", flush=True)
            break
        time.sleep(30)

    stage, status, by, watched = snapshot()
    print(f"\n[final] stage={stage} status={status} | "
          + ", ".join(f"{k}={v}" for k, v in sorted(by.items()))
          + " | " + " ".join(watched), flush=True)
    print("[events]", flush=True)
    for e in recent_events(10):
        print(f"  {e}", flush=True)


if __name__ == "__main__":
    main()
