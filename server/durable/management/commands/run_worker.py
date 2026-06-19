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
        self.stdout.write(self.style.SUCCESS(f"启动 durable worker，消费队列：{queues}"))
        asyncio.run(self._run_worker(queues))

    async def _run_worker(self, queues: list[str]) -> None:
        # 本地 import procrastinate：保持适配层隔离边界（仅 backends/tasks/management
        # 允许直接 import），且 SQLite 路径在上面已 CommandError 退出、不会到此。
        from procrastinate.contrib.django import app

        # get_worker_connector()：检测到 psycopg3 → 返回 PsycopgConnector（独立 async
        # 连接，专为长跑 worker）；绝不复用 DjangoConnector 跑 worker。
        connector = app.connector.get_worker_connector()
        async with app.replace_connector(connector) as worker_app:
            # listen_notify=False 必须显式传入（锁定决策）：v1 走 polling，低延迟
            # NOTIFY 唤醒 deferred 到 v2（DURABLEX-01）。
            await worker_app.run_worker_async(queues=queues, listen_notify=False)
