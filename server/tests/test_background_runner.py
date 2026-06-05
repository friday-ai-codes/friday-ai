"""services/background_runner.py 单元测试。

覆盖契约：
- worker loop 起在独立 daemon 线程，不与调用方共享 thread ident
- run_in_background 接受 factory，返回 concurrent.futures.Future
- ORM 调用（sync_to_async）在 worker loop 上能成功跑（关键回归点）
- coroutine 抛异常时 Future.exception() 拿得到原始异常
- 多次提交不重复创建 worker 线程
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future

import pytest
from asgiref.sync import sync_to_async

from services import background_runner

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_worker():
    """每个测试结束后拆掉 worker 线程，避免 state 泄漏。"""
    yield
    background_runner._reset_for_tests()


async def test_run_in_background_returns_concurrent_future():
    async def _coro():
        return 42

    fut = background_runner.run_in_background(lambda: _coro())
    try:
        assert isinstance(fut, Future)
        result = await asyncio.get_event_loop().run_in_executor(None, fut.result, 5.0)
        assert result == 42
    finally:
        if not fut.done():
            fut.cancel()


async def test_task_runs_on_separate_thread():
    """worker loop 必须跑在独立线程（不能复用调用方线程）。"""
    caller_tid = threading.get_ident()
    observed: dict[str, int] = {}

    async def _coro():
        observed["tid"] = threading.get_ident()
        return None

    fut = background_runner.run_in_background(lambda: _coro())
    try:
        await asyncio.get_event_loop().run_in_executor(None, fut.result, 5.0)
    finally:
        if not fut.done():
            fut.cancel()

    assert "tid" in observed
    assert observed["tid"] != caller_tid


async def test_factory_required_to_avoid_cross_loop_coroutine():
    """factory 必须在 worker loop 上下文里被调用 — 这样新建的 coroutine
    绑到 worker loop 而不是调用方 loop。

    把 caller loop 暴露给 factory，断言 factory 调用时所在 loop 不是 caller。
    """
    caller_loop = asyncio.get_event_loop()
    captured: dict[str, asyncio.AbstractEventLoop | None] = {"loop": None}

    def _factory():
        captured["loop"] = asyncio.get_event_loop()

        async def _inner():
            return "ok"

        return _inner()

    fut = background_runner.run_in_background(_factory)
    try:
        await asyncio.get_event_loop().run_in_executor(None, fut.result, 5.0)
    finally:
        if not fut.done():
            fut.cancel()

    assert captured["loop"] is not None
    assert captured["loop"] is not caller_loop


async def test_exception_propagates_through_future():
    class Boom(RuntimeError):
        pass

    async def _coro():
        raise Boom("explode")

    fut = background_runner.run_in_background(lambda: _coro())
    try:
        await asyncio.get_event_loop().run_in_executor(None, fut.result, 5.0)
        pytest.fail("Future 应该抛异常")
    except Boom as exc:
        assert "explode" in str(exc)


async def test_multiple_submits_share_one_worker_thread():
    """连续提交多个任务复用同一个 worker 线程。"""
    seen: set[int] = set()

    async def _coro():
        seen.add(threading.get_ident())
        return None

    futs = [background_runner.run_in_background(lambda: _coro()) for _ in range(5)]
    try:
        for f in futs:
            await asyncio.get_event_loop().run_in_executor(None, f.result, 5.0)
    finally:
        for f in futs:
            if not f.done():
                f.cancel()

    assert len(seen) == 1, f"所有任务应共享同一 worker 线程，实际：{seen}"


@pytest.mark.django_db(transaction=True)
async def test_orm_via_sync_to_async_works_on_worker_loop():
    """关键回归：在 worker loop 上跑 sync_to_async + ORM 必须不能抛
    'CurrentThreadExecutor already quit or is broken'。
    """
    from accounts.models import User

    def _create_user() -> str:
        u = User.objects.create_user(
            username="bg_runner_user",
            email="bg@example.com",
            password="x",
        )
        return str(u.id)

    async def _coro():
        return await sync_to_async(_create_user)()

    fut = background_runner.run_in_background(lambda: _coro())
    try:
        user_id = await asyncio.get_event_loop().run_in_executor(
            None, fut.result, 10.0,
        )
        assert user_id
    finally:
        if not fut.done():
            fut.cancel()
