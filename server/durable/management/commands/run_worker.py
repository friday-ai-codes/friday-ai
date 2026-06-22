"""独立 Procrastinate worker 进程命令（DURABLE-01 / PoC 硬前置①）。

worker 必须是**独立进程**，用 ``app.connector.get_worker_connector()``
（psycopg3 在装 → ``PsycopgConnector``，独立 async 连接、适合长跑）消费 durable
队列，**绝不直接拿 ``DjangoConnector`` 跑 worker**——后者仅适合 web 进程内 ``defer``，
不适合长跑 worker（官方明确不支持）。

也可直接用 ``procrastinate.contrib.django`` 自带命令::

    FRIDAY_PROCESS_ROLE=worker python manage.py procrastinate worker --queues index,graph

本命令是对其的一层封装，固定 ``listen_notify=False``（锁定决策：v1 走 polling，
低延迟 NOTIFY 唤醒 deferred 到 v2 DURABLEX-01）。

用法::

    FRIDAY_PROCESS_ROLE=worker python manage.py run_worker --queues index,graph
"""

from __future__ import annotations

import asyncio
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from durable.queues import ALL_QUEUES


class Command(BaseCommand):
    help = "启动独立 Procrastinate worker 进程消费 durable 队列（get_worker_connector）"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--queues",
            default=",".join(ALL_QUEUES),
            help="逗号分隔的队列名，默认消费全部 durable 队列",
        )
        parser.add_argument(
            "--graceful-timeout",
            type=float,
            default=None,
            help=(
                "收到 SIGTERM 后等在途 job 完成的最大秒数，超时则 abort 未完成 job；"
                "默认无限等到完成（None）。优雅停领取/drain 由 Procrastinate 内置信号"
                "处理提供（install_signal_handlers 默认 True），本参数仅控制等待上限。"
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # 仅在 Procrastinate durable 后端真正启用（Postgres + backend∈{auto,
        # procrastinate}）时才允许跑 worker；否则给出明确中文报错退出，绝不退化到
        # DjangoConnector / in-process 跑 worker（PoC 硬前置①）。
        from durable.service import use_procrastinate_backend

        if not use_procrastinate_backend():
            raise CommandError(
                "run_worker 仅在 Procrastinate durable 后端启用时可用："
                "需 Postgres + DURABLE_TASK_BACKEND∈{auto, procrastinate}。"
                "当前为 in-process fallback（非 durable，无独立 worker 进程），"
                "请先配置 Postgres 再启动 worker。"
            )

        queues = [q.strip() for q in str(options["queues"]).split(",") if q.strip()]
        graceful_timeout = options.get("graceful_timeout")
        self.stdout.write(
            self.style.SUCCESS(
                f"启动 durable worker，消费队列：{queues}（graceful_timeout={graceful_timeout}）"
            )
        )
        asyncio.run(self._run_worker(queues, graceful_timeout))

    async def _run_worker(
        self, queues: list[str], graceful_timeout: float | None = None
    ) -> None:
        # 本地 import procrastinate：保持适配层隔离边界（仅 backends/tasks/management
        # 允许直接 import），且 SQLite 路径在上面已 CommandError 退出、不会到此。
        from procrastinate.contrib.django import app

        # get_worker_connector()：检测到 psycopg3 → 返回 PsycopgConnector（独立 async
        # 连接，专为长跑 worker）；绝不复用 DjangoConnector 跑 worker。
        connector = app.connector.get_worker_connector()
        # app.replace_connector 是**同步** @contextlib.contextmanager（仅 __enter__/
        # __exit__），必须用同步 `with`——官方 procrastinate worker 命令亦如此。误用
        # async with 会因缺 __aenter__ 抛 TypeError、worker 一启动即崩（CR-02）。
        # 在 async 函数内对同步 CM 用同步 with 合法：进入/退出只替换 connector、不阻塞。
        with app.replace_connector(connector) as worker_app:
            # 必须先 open_async() 打开 worker connector 的连接池，否则 run_worker_async
            # 内部访问 job_manager 会抛 procrastinate.exceptions.AppNotOpen 而崩溃
            # （replace_connector 仅替换 connector，不会自动建立连接池）。
            async with worker_app.open_async():
                # listen_notify=False 必须显式传入（锁定决策）：v1 走 polling，低延迟
                # NOTIFY 唤醒 deferred 到 v2（DURABLEX-01）。
                # shutdown_graceful_timeout 透传 --graceful-timeout：收到 SIGTERM 后等在途
                # job 完成的上限（None=无限等到完成）；优雅 drain 仍由 Procrastinate 内置
                # install_signal_handlers（默认 True）提供，绝不自写信号循环。
                await worker_app.run_worker_async(
                    queues=queues,
                    listen_notify=False,
                    shutdown_graceful_timeout=graceful_timeout,
                )
