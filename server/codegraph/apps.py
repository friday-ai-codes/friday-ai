"""代码图谱 App 配置。"""

from __future__ import annotations

from django.apps import AppConfig


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
