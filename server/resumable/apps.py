"""可恢复任务 App 配置：启动时调度恢复扫描。"""

from __future__ import annotations

import os
import sys

from django.apps import AppConfig


class ResumableConfig(AppConfig):
    """断点恢复基础设施 App。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "resumable"
    verbose_name = "可恢复任务"

    def ready(self) -> None:
        # 注册索引 / 图谱恢复 handler（导入即注册，测试也可直接调用）。
        from resumable.handlers import register_default_handlers

        register_default_handlers()

        from django.conf import settings

        if getattr(settings, "RESUMABLE_RECOVERY_ON_STARTUP", True):
            self._schedule_recovery()

    @staticmethod
    def _schedule_recovery() -> None:
        """启动后异步执行恢复扫描（galaxy warm / graph reconcile 同模式）。

        - 管理命令（migrate / shell / pytest 等）跳过，仅服务进程执行。
        - runserver autoreload 仅在主进程（RUN_MAIN）执行，避免双跑。
        - 延迟首扫等 DB 就绪；并做几次递增间隔的补扫，覆盖"快速重启时老租约
          尚未过期"的窗口（lease TTL 默认 90s）。
        """
        argv0 = sys.argv[0] if sys.argv else ""
        if "pytest" in argv0 or "py.test" in argv0:
            return

        is_runserver = any("runserver" in arg for arg in sys.argv)
        if is_runserver and os.environ.get("RUN_MAIN") != "true":
            return

        is_management_cmd = len(sys.argv) > 1 and sys.argv[1] in (
            "migrate",
            "makemigrations",
            "collectstatic",
            "check",
            "shell",
            "dbshell",
            "test",
            "startapp",
            "createsuperuser",
            "init_superuser",
            "reset_superuser_password",
        )
        if is_management_cmd:
            return

        import threading

        from django.conf import settings

        # 补扫时刻（秒）：覆盖 lease TTL 内的快速重启窗口。
        sweep_delays = getattr(
            settings, "RESUMABLE_RECOVERY_SWEEP_DELAYS", (8, 35, 100)
        )

        def delayed_recover() -> None:
            import time

            import structlog

            from resumable.recovery import run_recovery

            log = structlog.get_logger(__name__)
            for delay in sweep_delays:
                time.sleep(delay)
                try:
                    summary = run_recovery()
                    if summary.get("recovered") or summary.get("exhausted"):
                        log.info("resumable_recovery_sweep", **summary)
                except Exception as exc:  # noqa: BLE001
                    log.warning("resumable_recovery_sweep_failed", error=str(exc))

        threading.Thread(target=delayed_recover, daemon=True).start()
