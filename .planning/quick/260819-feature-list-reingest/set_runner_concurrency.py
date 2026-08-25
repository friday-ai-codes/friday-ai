"""把 Runner 的服务端并发容量对齐到 config.toml（本轮：2 → 10），并校正 current_tasks 漂移。

为什么必须动 DB：并发在**两层**把关，只改一层不生效。
  1) runner 本地信号量 —— `scheduler.New(config.GetConcurrent())`，读 config.toml，
     进程启动时固化（无热加载，故已重启进程）。
  2) 服务端派发门 —— `runners/dispatcher.py::_try_assign` 的 `current_tasks < concurrent`，
     读 `Runner.concurrent`。该字段**只在注册接口写入**（`runners/views.py`），
     hello/heartbeat 只把 `max_concurrent` 记进指标 detail，不回写模型 ⇒ 改配置重启后
     DB 仍是旧值。

顺带校正 `current_tasks`：它由 `_increment_tasks` 自增、任务终态时递减。容器被孤儿化
（runner 重启 / OOM 杀）时递减那一步永不发生 ⇒ 计数虚高且**永不自愈**，虚高到 >= concurrent
就把派发门彻底焊死。真值以「当前实际在跑的容器数」为准，由调用方传入。

用法：
  python set_runner_concurrency.py                  # 只读快照
  python set_runner_concurrency.py --apply 10 --active 0
"""

import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()


def main() -> None:
    from runners.models import Runner

    apply_to = None
    active = None
    if "--apply" in sys.argv:
        apply_to = int(sys.argv[sys.argv.index("--apply") + 1])
    if "--active" in sys.argv:
        active = int(sys.argv[sys.argv.index("--active") + 1])

    rows = list(Runner.objects.all().order_by("name"))
    if not rows:
        raise SystemExit("没有 Runner 记录")

    print(f"{'name':16s} {'status':8s} {'concurrent':>10s} {'current_tasks':>14s} {'paused':>7s}")
    for r in rows:
        print(
            f"{r.name:16s} {r.status:8s} {r.concurrent:>10d} "
            f"{r.current_tasks:>14d} {str(r.is_paused):>7s}"
        )

    if apply_to is None:
        return

    online = [r for r in rows if r.status == "online" and r.is_active]
    if not online:
        raise SystemExit("无在线 Runner，拒绝改（改了也没人接活）")

    for r in online:
        fields = ["concurrent"]
        r.concurrent = apply_to
        if active is not None and r.current_tasks != active:
            print(f"  {r.name}: current_tasks {r.current_tasks} → {active}（按实际容器数校正漂移）")
            r.current_tasks = active
            fields.append("current_tasks")
        r.save(update_fields=fields)
        print(f"  {r.name}: concurrent → {apply_to}")

    print("\n改后：")
    for r in Runner.objects.filter(id__in=[x.id for x in online]).order_by("name"):
        print(f"  {r.name:16s} concurrent={r.concurrent} current_tasks={r.current_tasks}")


if __name__ == "__main__":
    main()
