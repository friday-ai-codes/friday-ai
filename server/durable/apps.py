"""durable 任务底座 App 配置。"""

from __future__ import annotations

from django.apps import AppConfig


class DurableConfig(AppConfig):
    """durable 任务底座 App。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "durable"
    verbose_name = "durable 任务底座"

    def ready(self) -> None:
        # Procrastinate periodic / task 注册（stalled rescue 等）：仅在 procrastinate
        # 后端真正启用（Postgres + DURABLE_TASK_BACKEND∈{auto,procrastinate}）且当前
        # 进程角色需要跑任务时，才 import durable.tasks 触发 @app.task / @app.periodic
        # 注册。非 procrastinate 路径（SQLite / fallback）短路不 import，保证 dev /
        # pytest 零副作用、绝不触达 procrastinate.contrib.django app。
        from durable.roles import should_run_startup_side_effects
        from durable.service import use_procrastinate_backend

        if not use_procrastinate_backend():
            return

        # 任务注册对 web（defer 侧需任务对象）/ worker（消费）/ scheduler（periodic）
        # 均有意义；migrate / test 角色短路（避免迁移期 import 触发副作用）。
        if not should_run_startup_side_effects(
            job="durable_task_registration",
            allowed=frozenset({"web", "worker", "scheduler"}),
        ):
            return

        # 触发 @app.task / @app.periodic 注册（导入即注册到 procrastinate blueprint，
        # 由 procrastinate.contrib.django.ready() 的 create_app 并入真实 App）。
        from durable import tasks  # noqa: F401
