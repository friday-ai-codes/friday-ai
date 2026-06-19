"""Procrastinate durable 后端的真实 Postgres 验证（DURABLE-01）。

全部用例带 ``@pytest.mark.postgres_queue``：需真实 Postgres（CI postgres:17-alpine
service 跑 ``-m postgres_queue``），默认 / SQLite 套件经 ``addopts`` 默认排除
（``-m 'not postgres_queue'``）不收集执行。

覆盖：
- defer 落 ``procrastinate_jobs``（queue / priority / scheduled_at 字段）
- priority 顺序（高 priority 先被领取）
- run_at 调度（scheduled_at 落库）
- worker connector：``get_worker_connector()`` 在 psycopg3 环境返回 ``PsycopgConnector``

真实 kill-worker E2E 不在自动化范围（见 60-VALIDATION.md「Manual-Only
Verifications」，标 human_needed）；本文件用 procrastinate 公开 API 逼近。
"""

from __future__ import annotations

import datetime

import pytest

from durable.queues import QUEUE_MAINTENANCE

# 模块级标记：postgres_queue（默认排除）+ enable_socket（pytest-socket 放行 TCP 连
# Postgres）+ transactional django_db（procrastinate 写不在 ORM 测试事务内）。
pytestmark = [
    pytest.mark.postgres_queue,
    pytest.mark.enable_socket,
    pytest.mark.django_db(transaction=True),
]


async def test_defer_lands_in_procrastinate_jobs(procrastinate_app) -> None:
    """defer 把 job 落 procrastinate_jobs，queue / priority 正确。"""
    from durable.backends import procrastinate_backend

    job_id = await procrastinate_backend.defer(
        "durable_ping",
        {"payload": {"k": "v"}},
        queue=QUEUE_MAINTENANCE,
        priority=5,
    )

    jobs = list(await procrastinate_app.job_manager.list_jobs_async(id=int(job_id)))
    assert len(jobs) == 1
    job = jobs[0]
    assert job.queue == QUEUE_MAINTENANCE
    assert job.priority == 5
    assert job.task_name.endswith("durable_ping")


async def test_higher_priority_fetched_first(procrastinate_app) -> None:
    """同队列高 priority 的 job 先被 worker 领取。"""
    from durable.backends import procrastinate_backend

    await procrastinate_backend.defer(
        "durable_ping", {"payload": {"p": "low"}}, queue=QUEUE_MAINTENANCE, priority=1
    )
    high_id = await procrastinate_backend.defer(
        "durable_ping", {"payload": {"p": "high"}}, queue=QUEUE_MAINTENANCE, priority=10
    )

    worker_id = await procrastinate_app.job_manager.register_worker()
    fetched = await procrastinate_app.job_manager.fetch_job([QUEUE_MAINTENANCE], worker_id)

    assert fetched is not None
    assert str(fetched.id) == high_id


async def test_run_at_persisted_as_scheduled_at(procrastinate_app) -> None:
    """run_at 经 schedule_at 落库到 scheduled_at（延迟调度）。"""
    from durable.backends import procrastinate_backend

    run_at = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(hours=1)
    job_id = await procrastinate_backend.defer(
        "durable_ping",
        {"payload": {}},
        queue=QUEUE_MAINTENANCE,
        run_at=run_at,
    )

    jobs = list(await procrastinate_app.job_manager.list_jobs_async(id=int(job_id)))
    assert len(jobs) == 1
    assert jobs[0].scheduled_at is not None
    # 容忍秒级误差（落库往返）
    assert abs((jobs[0].scheduled_at - run_at).total_seconds()) < 5


async def test_get_worker_connector_returns_psycopg_connector(procrastinate_app) -> None:
    """worker 必须用 get_worker_connector()（psycopg3 → PsycopgConnector），
    绝不用 DjangoConnector 跑 worker（PoC 硬前置① / T-60-07）。"""
    from procrastinate import PsycopgConnector

    connector = procrastinate_app.connector.get_worker_connector()
    assert isinstance(connector, PsycopgConnector)
