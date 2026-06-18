"""手动触发一轮可恢复任务恢复扫描（排障 / 运维入口）。

用法::

    python manage.py recover_tasks

对齐已有 ``recover_orphaned_runs`` 命令风格：领取租约过期的 RUNNING 任务并
按 kind 路由续跑，打印本轮汇总。
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "扫描并恢复租约过期的 RUNNING 可恢复任务（索引 / 图谱构建等）"

    def handle(self, *args: Any, **options: Any) -> None:
        # 确保 handler 已注册（独立 manage.py 进程不一定走 apps.ready 的调度路径）。
        from resumable.handlers import register_default_handlers
        from resumable.recovery import run_recovery

        register_default_handlers()
        summary = run_recovery()
        self.stdout.write(
            self.style.SUCCESS(
                "recover_tasks 完成："
                f"scanned={summary['scanned']} "
                f"recovered={summary['recovered']} "
                f"exhausted={summary['exhausted']} "
                f"skipped={summary['skipped']}"
            )
        )
