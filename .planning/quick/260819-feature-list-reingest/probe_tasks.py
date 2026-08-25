"""只读快照：本轮 9 个调研任务的 status / attempt / 停滞时长。

用途：调并发前判断「重启 runner 会毁掉什么」——server 侧 running 数与实际容器数
的差额就是躺在 runner 内存队列里、重启必丢的那批。
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

SESSION_ID = "4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6"


def main() -> None:
    from django.utils import timezone

    from delivery.models import ConvergenceSession
    from delivery.models.research_task import RepoResearchTask

    session = ConvergenceSession.objects.filter(id=SESSION_ID).first()
    if session is None:
        raise SystemExit(f"session not found: {SESSION_ID}")

    now = timezone.now()
    print(f"session stage={session.current_stage} status={session.status}\n")
    print(f"{'repo':34s} {'status':10s} {'att':>3s} {'no-update':>10s}")
    by: dict[str, int] = {}
    for t in (
        RepoResearchTask.objects.filter(session=session)
        .select_related("repository")
        .order_by("status", "id")
    ):
        name = getattr(t.repository, "name", "?")
        age = int((now - t.updated_at).total_seconds())
        by[t.status] = by.get(t.status, 0) + 1
        print(f"{name:34s} {t.status:10s} {t.attempt:>3d} {age:>9d}s")
    print("\n合计：" + ", ".join(f"{k}={v}" for k, v in sorted(by.items())))


if __name__ == "__main__":
    main()
