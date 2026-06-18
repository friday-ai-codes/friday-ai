"""代码图谱 App 配置。"""

from __future__ import annotations

import datetime

from django.apps import AppConfig


def reconcile_orphaned_graph_builds(timeout_minutes: int | None = None) -> int:
    """把超时仍 RUNNING 的 GraphBuildHistory 行标记为 FAILED，并归位仓库状态。

    后台构建任务（``run_in_background``）随进程内存存活，进程重启后这些 RUNNING
    行不会被收尾，永久卡住「准备中」并触发 rebuild 的 ``graph already running``
    互斥。本函数在服务进程启动时由 ``CodegraphConfig._schedule_orphan_graph_build_reconcile``
    调度执行，也可在测试 / 管理命令里直接调用。

    Args:
        timeout_minutes: 超过该分钟数仍 RUNNING 视为孤儿；``None`` 时读
            ``settings.GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES``。

    Returns:
        被回收（置 FAILED）的 GraphBuildHistory 行数。
    """
    import structlog
    from django.conf import settings
    from django.db import close_old_connections
    from django.utils import timezone

    from repositories.models import (
        GraphBuildHistory,
        GraphBuildHistoryStatus,
        Repository,
        RepositoryGraphStatus,
    )

    log = structlog.get_logger(__name__)

    if timeout_minutes is None:
        timeout_minutes = int(
            getattr(settings, "GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES", 30)
        )

    # 后台线程入口：清理可能复用的过期连接，避免拿到陈旧/已关闭的 DB 连接。
    close_old_connections()

    now = timezone.now()
    cutoff = now - datetime.timedelta(minutes=max(0, timeout_minutes))

    # 断点恢复：有可恢复 ResumableTask(kind=graph) 的仓库交给 RecoveryScheduler
    # 续跑（续跑会自行 supersede 旧 RUNNING 历史），此处不回收以免互踩。
    recoverable_ids: set[str] = set()
    try:
        from resumable.models import ResumableTaskKind
        from resumable.recovery import recoverable_target_ids

        recoverable_ids = recoverable_target_ids(ResumableTaskKind.GRAPH)
    except Exception:
        recoverable_ids = set()

    orphan_qs = GraphBuildHistory.objects.filter(
        status=GraphBuildHistoryStatus.RUNNING,
        started_at__lt=cutoff,
    )
    if recoverable_ids:
        orphan_qs = orphan_qs.exclude(repository_id__in=recoverable_ids)
    repo_ids = list(orphan_qs.values_list("repository_id", flat=True).distinct())
    reconciled = orphan_qs.update(
        status=GraphBuildHistoryStatus.FAILED,
        finished_at=now,
        error_message=(
            "构建任务在进程重启后丢失，启动时自动回收为失败"
            "（orphaned RUNNING row reconciled on startup）。"
        ),
    )

    if reconciled:
        # 仓库聚合态若仍停在 RUNNING，同步归位 FAILED 并清空易失进度字段，
        # 让前端徽章 / 进度条立即脱离「准备中」。
        Repository.objects.filter(
            id__in=repo_ids,
            graph_build_status=RepositoryGraphStatus.RUNNING,
        ).update(
            graph_build_status=RepositoryGraphStatus.FAILED,
            graph_stage="",
            current_graph_file="",
        )
        log.info(
            "graph_build_orphans_reconciled",
            reconciled=reconciled,
            repository_count=len(repo_ids),
            timeout_minutes=timeout_minutes,
        )

    return reconciled


class CodegraphConfig(AppConfig):
    """codegraph 图谱数据持久化 App。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "codegraph"
    verbose_name = "代码图谱"

    def ready(self) -> None:
        """启动时注册 implementation volar backend + implementation gopls backend。"""
        from django.conf import settings

        if getattr(settings, "VOLAR_BACKEND_ENABLED", True):
            self._register_volar_backends()

        if getattr(settings, "GOPLS_BACKEND_ENABLED", False):
            self._register_gopls_backend()

        if getattr(settings, "GALAXY_CACHE_ENABLED", True) and getattr(
            settings, "GALAXY_CACHE_WARM_ON_STARTUP", True
        ):
            self._schedule_galaxy_cache_warm()

        if getattr(settings, "GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP", True):
            self._schedule_orphan_graph_build_reconcile()

    @staticmethod
    def _schedule_galaxy_cache_warm() -> None:
        """启动后异步对比签名预热 Galaxy 文件缓存（feishu apps 同模式）。

        - 管理命令（migrate / shell / pytest 等）跳过，仅服务进程执行
        - 延迟 5s 等 Django/DB 完全就绪，daemon 线程不阻塞启动
        - 任何异常仅记日志（缓存预热失败不影响服务可用性）
        """
        import os
        import sys

        argv0 = sys.argv[0] if sys.argv else ""
        if "pytest" in argv0 or "py.test" in argv0:
            return

        is_runserver = any("runserver" in arg for arg in sys.argv)
        if is_runserver and os.environ.get("RUN_MAIN") != "true":
            return

        is_management_cmd = len(sys.argv) > 1 and sys.argv[1] in (
            "migrate", "makemigrations", "collectstatic", "check",
            "shell", "dbshell", "test", "startapp", "createsuperuser",
            "init_superuser", "reset_superuser_password",
        )
        if is_management_cmd:
            return

        import threading

        def delayed_warm() -> None:
            import time

            time.sleep(5)
            try:
                from codegraph.galaxy.cache import GalaxyGraphCache

                GalaxyGraphCache.warm_stale()
            except Exception as exc:
                import structlog

                structlog.get_logger(__name__).warning(
                    "galaxy_cache_warm_startup_failed", error=str(exc)
                )

        threading.Thread(target=delayed_warm, daemon=True).start()

    @staticmethod
    def _schedule_orphan_graph_build_reconcile() -> None:
        """启动后回收孤儿 RUNNING GraphBuildHistory 行（galaxy warm 同模式）。

        后台图谱构建任务通过 ``run_in_background`` 在进程内存中运行，无法跨进程
        重启幸存：一旦 ``make dev`` 重启 / 服务崩溃 / OOM，DB 里的 RUNNING 行就成
        了永远不会被收尾的幽灵，既让前端永久停在「准备中」，又会让 rebuild 命中
        ``graph already running`` 互斥而无法重建。

        - 管理命令（migrate / shell / pytest 等）跳过，仅服务进程执行
        - 延迟 5s 等 Django/DB 就绪，daemon 线程不阻塞启动
        - 仅回收 ``started_at`` 早于 ``GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES`` 的行，
          给多 worker 部署留安全边界（避免误杀另一 worker 刚创建的 RUNNING 行）
        - 任何异常仅记日志（回收失败不影响服务可用性）
        """
        import os
        import sys

        argv0 = sys.argv[0] if sys.argv else ""
        if "pytest" in argv0 or "py.test" in argv0:
            return

        is_runserver = any("runserver" in arg for arg in sys.argv)
        if is_runserver and os.environ.get("RUN_MAIN") != "true":
            return

        is_management_cmd = len(sys.argv) > 1 and sys.argv[1] in (
            "migrate", "makemigrations", "collectstatic", "check",
            "shell", "dbshell", "test", "startapp", "createsuperuser",
            "init_superuser", "reset_superuser_password",
        )
        if is_management_cmd:
            return

        import threading

        def delayed_reconcile() -> None:
            import time

            time.sleep(5)
            try:
                from codegraph.apps import reconcile_orphaned_graph_builds

                reconcile_orphaned_graph_builds()
            except Exception as exc:
                import structlog

                structlog.get_logger(__name__).warning(
                    "graph_build_orphan_reconcile_startup_failed", error=str(exc)
                )

        threading.Thread(target=delayed_reconcile, daemon=True).start()

    def _register_volar_backends(self) -> None:
        """5 项 BACKEND_REGISTRY 替换为 make_volar_backend(lang)。

        kill-switch ``settings.VOLAR_BACKEND_ENABLED=False`` 时跳过整段，
        BACKEND_REGISTRY 5 项保持 tree-sitter 默认。

        闭包注册 lazy：``make_volar_backend(language)`` 返工厂闭包，首次
        ``factory(lang)`` 调用才实例化 ``VolarBackend``；保 settings 加载顺序安全
        （per Pitfall P-checkpoint）。
        """
        from codegraph.extractors.registry import register_backend
        from codegraph.lsp.volar_backend import make_volar_backend

        for language in ("vue", "typescript", "tsx", "javascript", "jsx"):
            register_backend(language, make_volar_backend(language))

    def _register_gopls_backend(self) -> None:
        """gopls backend 注册；GOPLS_BACKEND_ENABLED=True 时触发。

        默认 False —— implementation 仅落基础设施不切 BACKEND_REGISTRY["go"]。
        implementation 切 True 完成 Stage C 切换。
        """
        import structlog as _structlog
        from codegraph.extractors.registry import register_backend
        from codegraph.lsp.gopls_backend import make_gopls_backend

        register_backend("go", make_gopls_backend("go"))
        _structlog.get_logger(__name__).info(
            "go_backend_switched",
            backend="gopls",
            phase=268,
        )
