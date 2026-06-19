"""durable 任务底座 App 配置。"""

from __future__ import annotations

from django.apps import AppConfig


class DurableConfig(AppConfig):
    """durable 任务底座 App。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "durable"
    verbose_name = "durable 任务底座"

    def ready(self) -> None:
        # 本 plan（60-01）有意为空：仅立适配层 + in-process fallback 地基，
        # 不产生任何启动副作用。Procrastinate periodic / task 注册（stalled
        # rescue 等）由 Plan 60-03 叠加；进程角色门禁收口由 Plan 60-02 实现。
        pass
