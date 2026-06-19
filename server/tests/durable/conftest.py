"""durable 测试目录共享 fixture。

顶层 ``tests/conftest.py`` 的 autouse ``_reset_background_runner`` 已负责每测试后
等 in-flight 任务落地并重建 worker 线程；这里补 durable 专用项：

- SQLite / fallback：清空 ``durable.backends`` 的进程内 job 状态注册表（autouse）。
- Postgres（``postgres_queue`` 标记）：``procrastinate_app`` fixture 复用 Django
  ``DATABASES["default"]``（指向真实 Postgres）拿已配置好的 procrastinate App；
  非 Postgres 环境（如本地默认 SQLite）``pytest.skip``，不报错。socket 放行由测试
  模块自身的 ``pytest.mark.enable_socket`` + CI 的 ``--allow-hosts`` 负责
  （pytest-socket 默认 ``--disable-socket``）。

复用顶层 conftest 的 adrf monkeypatch（``tests/conftest.py`` 顶层已 patch），此处不重复。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from durable.service import DurableTaskService


@pytest.fixture(autouse=True)
def _reset_durable_inprocess_jobs() -> Iterator[None]:
    """每测试后清空 in-process 后端的 job 状态注册表。"""
    yield
    from durable import backends

    backends._reset_for_tests()


@pytest.fixture
def durable_service() -> type[DurableTaskService]:
    """返回 DurableTaskService（静态方法门面，无需实例化）。"""
    return DurableTaskService


def _is_postgres() -> bool:
    """当前默认 DB 引擎是否为 PostgreSQL（postgres_queue 测试的前置）。"""
    from django.conf import settings

    return "postgresql" in str(settings.DATABASES["default"]["ENGINE"]).lower()


@pytest.fixture
def procrastinate_app() -> Any:
    """返回 ``procrastinate.contrib.django.app``（仅 postgres_queue 测试消费）。

    复用 Django ``DATABASES["default"]``（CI 下指向 postgres:17-alpine）。非 Postgres
    环境（本地默认 SQLite，``procrastinate.contrib.django`` 未注册）直接 ``pytest.skip``，
    保证默认套件即便误触也不报错。
    """
    if not _is_postgres():
        pytest.skip(
            "postgres_queue 测试需真实 Postgres："
            "设 DATABASE_URL=postgres://... DURABLE_TASK_BACKEND=procrastinate"
        )
    from procrastinate.contrib.django import app

    return app


@pytest.fixture
def backdate_worker_heartbeat() -> Any:
    """返回一个 async 回调：把某 worker 的 ``last_heartbeat`` 回拨到过去（伪造心跳过期）。

    用于 forged-heartbeat stalled rescue 自动化（不真 kill worker 进程）：把
    ``procrastinate_workers.last_heartbeat`` 改成 1 小时前，让该 worker 名下 doing
    job 在默认 ``seconds_since_heartbeat=30`` 判定下被认作 stalled。
    """
    from asgiref.sync import sync_to_async

    def _do(worker_id: int, seconds_ago: int = 3600) -> None:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE procrastinate_workers "
                "SET last_heartbeat = NOW() - (%s || ' seconds')::interval "
                "WHERE id = %s",
                [seconds_ago, worker_id],
            )

    async def _abackdate(worker_id: int, seconds_ago: int = 3600) -> None:
        await sync_to_async(_do, thread_sensitive=True)(worker_id, seconds_ago)

    return _abackdate
