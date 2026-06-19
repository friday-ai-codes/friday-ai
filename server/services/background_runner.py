"""后台任务运行器：将耗时 coroutine 调度到独立线程的事件循环。

定位降级（Phase 61 起）
=======================
自 durable 队列底座（Plan 61-01/02）接管生产 index/graph 任务后，``background_runner``
**降级为仅 SQLite dev fallback / 少量非持久轻任务**：

- 生产 index/graph 改走 durable（``DurableTaskService.defer`` → Postgres Procrastinate
  worker），**不再经 background_runner / ResumableTask**，避免 background_runner /
  ResumableTask / durable 三套并存。
- 本运行器进程内执行、重启即丢，不提供 durable 持久化；只适合 SQLite dev/pytest 的
  in-process fallback，以及无需断点恢复的轻任务。
- **仅定位降级，运行逻辑零改动**：in-process durable 后端仍复用它（``durable.backends``
  的 in-process 路径），既有调用方零回归。

问题背景
========
索引、overlay 重建等长任务之前用 `asyncio.create_task(coro)` 在 ASGI request
handler 的事件循环里启动。HTTP 请求一返回，asgiref 给该请求绑定的
`CurrentThreadExecutor` 就被关闭，后台 task 后续任何 `sync_to_async`（包括
ORM `arefresh_from_db` / `aget` 等）会立刻抛：

    RuntimeError: CurrentThreadExecutor already quit or is broken

解决方案
========
进程级常驻一个 daemon 线程，里面跑一个长生命周期 event loop。所有需要"脱离请求
生命周期"的后台 coroutine 都用 `run_in_background(coro_factory)` 提交到这个
loop 上。该 loop 不绑定任何 HTTP 请求，asgiref 给它分配的 ThreadPoolExecutor
随线程一直存活，ORM 通过 `sync_to_async` 调用始终可用。

线程安全
========
`run_in_background` 内部跨线程调度到 worker loop，并在干净 context 中创建
coroutine/task。返回标准 `concurrent.futures.Future`。worker 线程懒启动 + 加锁，
单元测试可以在每个测试间用 `_reset_for_tests()` 拆掉重建。
"""

from __future__ import annotations

import asyncio
import contextvars
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")

# 模块级单例：worker 线程 + 它的 event loop
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()
# 防 GC：保留所有 in-flight Future（done 后自动 discard）
_pending: set[Future[Any]] = set()
# 按名称索引后台任务，用于取消运行中的索引。
_named_futures: dict[str, Future[Any]] = {}


def _ensure_worker_loop() -> asyncio.AbstractEventLoop:
    """懒启动 worker 线程，并返回它的事件循环。线程安全。"""
    global _loop, _thread
    with _lock:
        if _loop is not None and _thread is not None and _thread.is_alive():
            return _loop

        ready = threading.Event()
        local_loop: asyncio.AbstractEventLoop | None = None

        def _run() -> None:
            nonlocal local_loop
            local_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(local_loop)
            ready.set()
            try:
                local_loop.run_forever()
            finally:
                # run_forever 退出后保证清理 pending tasks，避免泄漏
                try:
                    pending = asyncio.all_tasks(local_loop)
                    for t in pending:
                        t.cancel()
                    if pending:
                        local_loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True),
                        )
                finally:
                    local_loop.close()

        t = threading.Thread(
            target=_run,
            name="friday-bg-runner",
            daemon=True,
        )
        t.start()
        # 等 loop 起来再返回，避免调用方拿到 None
        ready.wait(timeout=5.0)
        if local_loop is None:
            raise RuntimeError("background runner loop failed to start")

        _loop = local_loop
        _thread = t
        logger.info("background_runner_started")
        return _loop


def run_in_background(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    name: str | None = None,
) -> Future[T]:
    """在常驻 worker 线程的事件循环里运行 coroutine。

    必须传 *factory*（无参函数返回 coroutine）而不是 coroutine 本身，因为
    coroutine 只能在创建它的事件循环里 await — 跨线程提交时由 worker loop
    在自己上下文里 call 这个 factory，得到一个新鲜的、绑定到 worker loop
    的 coroutine 对象。

    这避免了 "coroutine ... was created in a different event loop" 类问题。

    Args:
        coro_factory: 无参 callable，调用时返回 coroutine。
        name: 可选 task 名（仅用于日志/debug，不影响 Future 行为）。

    Returns:
        concurrent.futures.Future — 调用方可以 .result() 同步等待，
        也可以 add_done_callback 异步处理。
    """
    loop = _ensure_worker_loop()

    async def _wrapper() -> T:
        try:
            return await coro_factory()
        except Exception:
            # 显式记录后再抛，确保即使调用方没消费 Future 也能在日志看到原因
            logger.exception("background_task_failed", task_name=name or "<unnamed>")
            raise

    future: Future[T] = Future()
    task_holder: list[asyncio.Task[T]] = []

    def _copy_task_result(task: asyncio.Task[T]) -> None:
        if future.cancelled():
            return

        try:
            future.set_result(task.result())
        except asyncio.CancelledError:
            future.cancel()
        except BaseException as exc:
            future.set_exception(exc)

    def _schedule_on_worker_loop() -> None:
        if future.cancelled():
            return

        try:
            # 关键点：coroutine/task 必须在 worker loop 的干净 context 中创建。
            # 否则 request thread 的 asgiref CurrentThreadExecutor 会随 contextvars
            # 泄漏到后台任务，HTTP 响应结束后再 sync_to_async 就会使用已关闭 executor。
            task = loop.create_task(
                _wrapper(),
                name=name,
                context=contextvars.Context(),
            )
            task_holder.append(task)
            task.add_done_callback(_copy_task_result)
        except BaseException as exc:
            future.set_exception(exc)

    def _cancel_worker_task(done_future: Future[T]) -> None:
        if not done_future.cancelled() or not task_holder:
            return
        loop.call_soon_threadsafe(task_holder[0].cancel)

    if name:
        with _lock:
            _named_futures[name] = future

        def _remove_named_future(done_future: Future[T]) -> None:
            with _lock:
                if _named_futures.get(name) is done_future:
                    del _named_futures[name]

        future.add_done_callback(_remove_named_future)

    future.add_done_callback(_cancel_worker_task)
    loop.call_soon_threadsafe(
        _schedule_on_worker_loop,
        context=contextvars.Context(),
    )
    _pending.add(future)
    future.add_done_callback(lambda f: _pending.discard(f))
    return future


def cancel_background_task(name: str) -> bool:
    """按名称取消一个仍在运行的后台任务。"""
    with _lock:
        future = _named_futures.get(name)

    if future is None or future.done():
        return False

    return future.cancel()


def wait_for_pending(timeout: float = 30.0) -> None:
    """阻塞等待所有 in-flight 后台 Future 完成。仅用于测试 / shutdown。

    生产代码不应依赖它 — 后台任务故意脱离请求生命周期，调用方等结果用
    Future.result() 即可。
    """
    # snapshot：避免迭代时 _pending 被回调改动
    futures = list(_pending)
    for f in futures:
        try:
            f.result(timeout=timeout)
        except Exception:
            # 错误已经在 _wrapper 里 logger.exception 过了，这里继续等其它
            pass


def _reset_for_tests() -> None:
    """测试钩子：停掉 worker 线程，清空状态，下次调用会重新拉起。

    严禁在生产代码里调用。
    """
    global _loop, _thread
    with _lock:
        loop = _loop
        thread = _thread
        _loop = None
        _thread = None
        _pending.clear()
        _named_futures.clear()

    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(loop.stop)
    if thread is not None:
        thread.join(timeout=5.0)
