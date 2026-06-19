"""周期 stalled rescue + queueing_lock 单例 + 并发竞争的真实 Postgres 验证（DURABLE-03）。

全部用例带 ``@pytest.mark.postgres_queue``：需真实 Postgres（CI postgres:17-alpine
service 跑 ``-m postgres_queue``），默认 / SQLite 套件经 ``addopts`` 默认排除不收集执行。

覆盖：
- forged-heartbeat rescue：伪造心跳过期的 doing job，``get_stalled_jobs`` + ``retry_job``
  重投回 todo（自动化逼近，**不真 kill 进程**）；
- 重投后 priority 保留；
- queueing_lock 单例：同 lock 重复 defer → 第二次幂等吞并，todo 仅一条（不堆积）；
- 并发 worker 竞争同一 job：两连接 fetch 恰一个成功领取。

**Manual-only：** 真实 kill-worker → 另一 worker 经周期 leader rescue 接管在途 stalled
任务，需两个活 worker 进程 + 真实 Postgres + 等心跳过期，在 CI 昂贵/不稳，标 human_needed
（见 60-VALIDATION.md「Manual-Only Verifications」），不在本自动化文件内。
"""

from __future__ import annotations

import pytest

from durable.queues import QUEUE_MAINTENANCE

pytestmark = [
    pytest.mark.postgres_queue,
    pytest.mark.enable_socket,
    pytest.mark.django_db(transaction=True),
]


async def test_forged_heartbeat_job_rescued_to_todo(
    procrastinate_app, backdate_worker_heartbeat
) -> None:
    """伪造心跳过期：doing job 被 retry_stalled 重投回 todo（heartbeat 判定，零 nb_seconds）。"""
    from procrastinate.jobs import Status

    from durable.backends import procrastinate_backend

    job_id = await procrastinate_backend.defer(
        "durable_ping", {"payload": {}}, queue=QUEUE_MAINTENANCE
    )

    # 注册 worker 并领取 job（todo → doing，挂在该 worker 名下）。
    worker_id = await procrastinate_app.job_manager.register_worker()
    fetched = await procrastinate_app.job_manager.fetch_job([QUEUE_MAINTENANCE], worker_id)
    assert fetched is not None
    assert str(fetched.id) == job_id

    # 伪造该 worker 心跳过期（1 小时前）→ 其 doing job 在默认 30s 阈值下判为 stalled。
    await backdate_worker_heartbeat(worker_id)

    stalled = list(await procrastinate_app.job_manager.get_stalled_jobs())
    assert any(j.id == fetched.id for j in stalled)

    # 经后端 retry_stalled（与 periodic retry_stalled_durable_jobs 同算法）重投。
    retried = await procrastinate_backend.retry_stalled()
    assert retried >= 1

    status = await procrastinate_app.job_manager.get_job_status_async(int(job_id))
    assert status == Status.TODO


async def test_rescued_job_keeps_priority(
    procrastinate_app, backdate_worker_heartbeat
) -> None:
    """重投后 job 仍在队列，priority 保留（retry 不丢调度属性）。"""
    from durable.backends import procrastinate_backend

    job_id = await procrastinate_backend.defer(
        "durable_ping", {"payload": {}}, queue=QUEUE_MAINTENANCE, priority=7
    )
    worker_id = await procrastinate_app.job_manager.register_worker()
    await procrastinate_app.job_manager.fetch_job([QUEUE_MAINTENANCE], worker_id)
    await backdate_worker_heartbeat(worker_id)

    await procrastinate_backend.retry_stalled()

    jobs = list(await procrastinate_app.job_manager.list_jobs_async(id=int(job_id)))
    assert len(jobs) == 1
    assert jobs[0].priority == 7


async def test_queueing_lock_singleton_no_pileup(procrastinate_app) -> None:
    """queueing_lock 单例：同 lock 重复 defer → 幂等吞并，todo 仅一条（不堆积）。"""
    from durable.backends import procrastinate_backend

    key = "idem-singleton-key"
    first = await procrastinate_backend.defer(
        "durable_ping", {"payload": {}}, queue=QUEUE_MAINTENANCE, idempotency_key=key
    )
    second = await procrastinate_backend.defer(
        "durable_ping", {"payload": {}}, queue=QUEUE_MAINTENANCE, idempotency_key=key
    )

    # 第二次命中 AlreadyEnqueued → 幂等返回既有 job 标识。
    assert first == second

    todo_jobs = list(
        await procrastinate_app.job_manager.list_jobs_async(
            queueing_lock=key, status="todo"
        )
    )
    assert len(todo_jobs) == 1


async def test_concurrent_workers_only_one_claims(procrastinate_app) -> None:
    """并发 worker 竞争同一 job：恰一个成功领取（DB SKIP LOCKED 保证）。"""
    from durable.backends import procrastinate_backend

    job_id = await procrastinate_backend.defer(
        "durable_ping", {"payload": {}}, queue=QUEUE_MAINTENANCE
    )

    worker_a = await procrastinate_app.job_manager.register_worker()
    worker_b = await procrastinate_app.job_manager.register_worker()

    fetched_a = await procrastinate_app.job_manager.fetch_job([QUEUE_MAINTENANCE], worker_a)
    fetched_b = await procrastinate_app.job_manager.fetch_job([QUEUE_MAINTENANCE], worker_b)

    claimed = [
        f for f in (fetched_a, fetched_b) if f is not None and f.id == int(job_id)
    ]
    assert len(claimed) == 1
