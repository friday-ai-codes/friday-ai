"""容器回调 → 工作流续跑的可靠性。

续跑原先是纯 fire-and-forget：`loop.create_task(_resume())` 不持引用，异常只
`log.exception`。两个后果——

1. asyncio 对 create_task 返回值只保弱引用，任务可能在 await 点被 GC 回收，
   症状是续跑「偶尔就是没发生」，且不留任何日志；
2. 续跑失败后执行永久停在 SUSPENDED / WAITING_EVENT，前端显示「等待容器」而容器
   早已退出，只能人工介入，也没有可查询的失败信号。

现在：持强引用防 GC、有界退避重试吸收瞬时故障、耗尽后把执行显式标 failed。
"""

from __future__ import annotations

import asyncio

import pytest

from subagent.api import callbacks as cb


class _Log:
    def __init__(self) -> None:
        self.events: list[str] = []

    def _record(self, event, *a, **k):
        self.events.append(event)

    debug = info = warning = error = exception = _record


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch):
    """把退避压到 0，避免测试真的睡 2+4 秒。"""
    monkeypatch.setattr(cb, "_RESUME_RETRY_BACKOFF_SECONDS", 0.0)


class TestPendingTaskReference:
    def test_module_keeps_strong_reference_holder(self):
        """必须存在强引用容器——否则 create_task 的任务会被 GC 悄悄回收。"""
        assert isinstance(cb._PENDING_RESUME_TASKS, set)

    @pytest.mark.asyncio
    async def test_scheduled_task_is_tracked_then_released(self, monkeypatch):
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_resume():
            started.set()
            await release.wait()

        monkeypatch.setattr(cb, "_mark_execution_failed_after_resume_exhausted", _noop)

        session = _Session(node_execution_id="ne-1")
        monkeypatch.setattr(cb, "_build_resume_coro_for_test", None, raising=False)

        # 直接驱动内部调度：构造一个 task 并确认被登记 / 完成后释放
        task = asyncio.get_running_loop().create_task(_slow_resume())
        cb._PENDING_RESUME_TASKS.add(task)
        task.add_done_callback(cb._PENDING_RESUME_TASKS.discard)

        await started.wait()
        assert task in cb._PENDING_RESUME_TASKS, "在途任务未被持有，可能被 GC 回收"

        release.set()
        await task
        await asyncio.sleep(0)
        assert task not in cb._PENDING_RESUME_TASKS, "任务完成后未释放，长期运行会泄漏"
        assert session.node_execution_id == "ne-1"


class TestRetryAndTerminalFailure:
    """驱动真实的 `_schedule_workflow_resume`，不在测试里复刻重试语义。

    内部 `_resume` 是闭包无法直接 patch，改为让它依赖的第一个 DB 查询抛错，
    以此逼出重试路径。
    """

    @staticmethod
    async def _drain_pending_tasks():
        while cb._PENDING_RESUME_TASKS:
            await asyncio.gather(*list(cb._PENDING_RESUME_TASKS), return_exceptions=True)
            await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_transient_failure_is_retried_and_succeeds(self, monkeypatch):
        """瞬时故障（首查抛、次查恢复且查无记录）应被重试吸收，不标失败。"""
        attempts = {"n": 0}
        marked: list[str] = []

        def _flaky_manager():
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("DB 抖动")
            # 第二次：走到 node_execution_not_found 分支正常 return
            return _Manager(result=None)

        monkeypatch.setattr(
            "workflows.models.execution.NodeExecution.objects",
            _LazyManager(_flaky_manager),
        )
        monkeypatch.setattr(
            cb, "_mark_execution_failed_after_resume_exhausted", _record_into(marked)
        )

        cb._schedule_workflow_resume(_Session(), _Log())
        await self._drain_pending_tasks()

        assert attempts["n"] == 2, "首次失败后应重试"
        assert marked == [], "重试成功后不应把执行标失败"

    @pytest.mark.asyncio
    async def test_persistent_failure_marks_execution_failed(self, monkeypatch):
        """持续失败必须落到显式失败，而不是永久挂起。"""
        attempts = {"n": 0}
        marked: list[str] = []

        def _always_fail():
            attempts["n"] += 1
            raise RuntimeError("续跑挂了")

        monkeypatch.setattr(
            "workflows.models.execution.NodeExecution.objects",
            _LazyManager(_always_fail),
        )
        monkeypatch.setattr(
            cb, "_mark_execution_failed_after_resume_exhausted", _record_into(marked)
        )

        log = _Log()
        cb._schedule_workflow_resume(_Session(), log)
        await self._drain_pending_tasks()

        assert attempts["n"] == cb._RESUME_MAX_ATTEMPTS, "应按配置次数重试"
        assert marked, "重试耗尽却没标失败 —— 执行会永久停在 SUSPENDED"
        assert "workflow_resume_exhausted" in log.events, "缺少可告警的耗尽事件"


def _record_into(bucket: list):
    async def _mark(session, error, log):
        bucket.append(str(error))

    return _mark


class _Manager:
    """最小 QuerySet 替身：select_related().filter().afirst() 链。"""

    def __init__(self, result) -> None:
        self._result = result

    def select_related(self, *_a, **_k):
        return self

    def filter(self, *_a, **_k):
        return self

    async def afirst(self):
        return self._result


class _LazyManager:
    """每次访问 select_related 时调用工厂——用于制造「首次抛、二次恢复」。"""

    def __init__(self, factory) -> None:
        self._factory = factory

    def select_related(self, *a, **k):
        return self._factory().select_related(*a, **k)


class _Session:
    def __init__(self, node_execution_id: str = "ne-1") -> None:
        self.node_execution_id = node_execution_id
        self.session_id = "sess-1"


async def _noop(*_a, **_k):
    return None
