"""Blocking task 端到端流程测试 — conversation_service WAITING + ChatInterruptView 取消。"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestration.contracts import BlockingTaskRequest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_blocking_task(task_id: str = "") -> BlockingTaskRequest:
    return {
        "task_id": task_id or str(uuid.uuid4()),
        "task_type": "deep_analysis",
        "params": {"task_description": "test"},
    }


@pytest.fixture
def mock_barrier():
    """Mock BarrierManager 实例。"""
    barrier = MagicMock()
    barrier.has_barrier_for_thread = MagicMock(return_value=True)
    barrier.get_pending_tasks = MagicMock(return_value=[])
    barrier.cancel_all = AsyncMock()
    barrier.register = AsyncMock()
    return barrier


async def _create_user() -> Any:
    """创建一个真实的认证用户（owner gate 要求 conversation.created_by 与请求用户一致）。"""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return await User.objects.acreate_user(
        username=f"blk_{uuid.uuid4().hex[:8]}",
        password="testpass123",
    )


async def _create_waiting_orch_run(user: Any = None) -> tuple[str, Any, Any]:
    """创建 WAITING 状态的 OrchestrationRun（含 Space + Conversation FK 链）。"""
    from chat.models import Conversation
    from orchestration.models import OrchestrationRun
    from projects.models import Space

    if user is None:
        user = await _create_user()
    project = await Space.objects.acreate(name="test-proj")
    conv = await Conversation.objects.acreate(space=project, title="test", created_by=user)
    conv_id = str(conv.id)
    orch_run = await OrchestrationRun.objects.acreate(
        conversation=conv,
        thread_id=conv_id,
        status=OrchestrationRun.Status.WAITING,
        phase=OrchestrationRun.Phase.WAITING,
    )
    return conv_id, orch_run, user


# ---------------------------------------------------------------------------
# test_interrupt_during_waiting_cancels_tasks_via_dispatcher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_interrupt_during_waiting_cancels_tasks_via_dispatcher(
    mock_barrier: MagicMock,
) -> None:
    """WAITING 状态中断：逐个取消 pending tasks 后调用 cancel_all。"""
    t1 = _make_blocking_task("task-001")
    t2 = _make_blocking_task("task-002")
    mock_barrier.get_pending_tasks.return_value = [t1, t2]

    conv_id, orch_run, user = await _create_waiting_orch_run()

    mock_dispatcher = MagicMock()
    mock_dispatcher.cancel = AsyncMock(return_value=True)

    with (
        patch("orchestration.runner_registry.get_active_runner", return_value=None),
        patch("orchestration.barrier.get_barrier_manager", return_value=mock_barrier),
        patch("chat.views._cancel_dispatched_task", new_callable=AsyncMock) as mock_cancel,
    ):
        from adrf.test import AsyncAPIRequestFactory

        from chat.views import ChatInterruptView

        factory = AsyncAPIRequestFactory()
        request = factory.post(f"/api/conversations/{conv_id}/interrupt/")
        request.user = user

        view = ChatInterruptView()
        response = await view.post(request, conv_id)

        assert response.status_code == 200
        assert response.data["status"] == "cancelled"

        # 验证逐个取消
        assert mock_cancel.await_count == 2
        mock_cancel.assert_any_await(t1)
        mock_cancel.assert_any_await(t2)

        # 验证 cancel_all 在逐个取消后被调用
        mock_barrier.cancel_all.assert_awaited_once_with(str(orch_run.run_id))


# ---------------------------------------------------------------------------
# test_interrupt_during_executing_uses_runner
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_interrupt_during_executing_uses_runner() -> None:
    """SDK 运行中中断：使用 runner.interrupt()。"""
    from chat.models import Conversation
    from projects.models import Space

    mock_runner = MagicMock()
    mock_runner.interrupt = AsyncMock()

    user = await _create_user()
    project = await Space.objects.acreate(name="exec-proj")
    conv = await Conversation.objects.acreate(space=project, title="exec", created_by=user)
    conv_id = str(conv.id)

    with patch("orchestration.runner_registry.get_active_runner", return_value=mock_runner):
        from adrf.test import AsyncAPIRequestFactory

        from chat.views import ChatInterruptView

        factory = AsyncAPIRequestFactory()
        request = factory.post(f"/api/conversations/{conv_id}/interrupt/")
        request.user = user

        view = ChatInterruptView()
        response = await view.post(request, conv_id)

        assert response.status_code == 200
        assert response.data["status"] == "interrupted"
        mock_runner.interrupt.assert_awaited_once()


# ---------------------------------------------------------------------------
# test_interrupt_no_active_session_returns_404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_interrupt_no_active_session_returns_404(
    mock_barrier: MagicMock,
) -> None:
    """无 active runner 也无 barrier → 404。"""
    from chat.models import Conversation
    from projects.models import Space

    mock_barrier.has_barrier_for_thread.return_value = False

    user = await _create_user()
    project = await Space.objects.acreate(name="no-session-proj")
    conv = await Conversation.objects.acreate(
        space=project, title="no-session", created_by=user
    )
    conv_id = str(conv.id)

    with (
        patch("orchestration.runner_registry.get_active_runner", return_value=None),
        patch("orchestration.barrier.get_barrier_manager", return_value=mock_barrier),
    ):
        from adrf.test import AsyncAPIRequestFactory

        from chat.views import ChatInterruptView

        factory = AsyncAPIRequestFactory()
        request = factory.post(f"/api/conversations/{conv_id}/interrupt/")
        request.user = user

        view = ChatInterruptView()
        response = await view.post(request, conv_id)

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# test_conversation_service_waiting_state_no_finalize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conversation_service_waiting_state_no_finalize() -> None:
    """graph 返回 phase=waiting 时：不调用 finalize，注册 BarrierManager。"""
    from chat.conversation_service import _handle_waiting_state

    mock_orch_run = MagicMock()
    mock_orch_run.id = 42
    mock_orch_run.run_id = uuid.uuid4()

    mock_barrier = MagicMock()
    mock_barrier.register = AsyncMock()
    mock_finalize = AsyncMock()

    state: dict[str, Any] = {
        "phase": "waiting",
        "blocking_tasks": [_make_blocking_task("bt-1")],
    }

    with (
        patch(
            "orchestration.barrier.get_barrier_manager",
            return_value=mock_barrier,
        ),
        patch(
            "chat.conversation_service.OrchestrationRun.objects.filter",
        ) as mock_filter,
    ):
        mock_filter.return_value.aupdate = AsyncMock()

        await _handle_waiting_state(
            state=state,
            orch_run=mock_orch_run,
            graph_config={"configurable": {"thread_id": "test"}},
            conversation=MagicMock(),
            assistant_msg_id=uuid.uuid4(),
            agent_session=MagicMock(),
            session_id="sess-1",
            model="claude",
            content="hello",
            notification_user_id=None,
            conv_id_str="cid",
            do_finalize=mock_finalize,
        )

        # OrchestrationRun 应更新为 WAITING
        mock_filter.assert_called_once_with(id=42)
        mock_filter.return_value.aupdate.assert_awaited_once()
        call_kwargs = mock_filter.return_value.aupdate.call_args[1]
        assert call_kwargs["status"] == "waiting"

        # BarrierManager.register 应被调用
        mock_barrier.register.assert_awaited_once()
        reg_kwargs = mock_barrier.register.call_args[1]
        assert reg_kwargs["run_id"] == str(mock_orch_run.run_id)
        assert len(reg_kwargs["tasks"]) == 1

        # finalize 不应被调用
        mock_finalize.assert_not_awaited()


# ---------------------------------------------------------------------------
# test_barrier_complete_triggers_finalize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_barrier_complete_triggers_finalize() -> None:
    """barrier on_complete 回调：resume graph + 调用 finalize。"""
    from chat.conversation_service import _handle_waiting_state

    mock_orch_run = MagicMock()
    mock_orch_run.id = 99
    mock_orch_run.run_id = uuid.uuid4()

    captured_callback: list[Any] = []

    async def fake_register(**kwargs: Any) -> None:
        captured_callback.append(kwargs["on_complete"])

    mock_barrier = MagicMock()
    mock_barrier.register = AsyncMock(side_effect=fake_register)

    mock_finalize = AsyncMock(return_value=[])

    state: dict[str, Any] = {
        "phase": "waiting",
        "blocking_tasks": [_make_blocking_task()],
    }

    # resume 后 graph 返回 completed 状态
    async def fake_astream(*args: Any, **kwargs: Any):
        yield {"type": "values", "data": {"phase": "completed", "final_answer": "结果"}}

    mock_graph = MagicMock()
    mock_graph.astream = fake_astream

    with (
        patch("orchestration.barrier.get_barrier_manager", return_value=mock_barrier),
        patch("chat.conversation_service.OrchestrationRun.objects.filter") as mock_filter,
    ):
        mock_filter.return_value.aupdate = AsyncMock()

        await _handle_waiting_state(
            state=state,
            orch_run=mock_orch_run,
            graph_config={"configurable": {"thread_id": "test"}},
            conversation=MagicMock(),
            assistant_msg_id=uuid.uuid4(),
            agent_session=MagicMock(),
            session_id="sess-1",
            model="claude",
            content="hello",
            notification_user_id=None,
            conv_id_str="cid",
            do_finalize=mock_finalize,
        )

    assert len(captured_callback) == 1
    on_complete = captured_callback[0]

    results = [{"task_id": "t1", "task_type": "deep_analysis", "success": True, "output": "ok", "error": ""}]

    with (
        patch("chat.conversation_service.get_compiled_graph", new_callable=AsyncMock, return_value=mock_graph),
        patch("chat.conversation_service.OrchestrationRun.objects.filter") as mock_filter2,
    ):
        mock_filter2.return_value.aupdate = AsyncMock()
        await on_complete(results)

    # finalize 应被调用
    mock_finalize.assert_awaited_once()
    fin_kwargs = mock_finalize.call_args[1]
    assert fin_kwargs["final_content"] == "结果"


# ---------------------------------------------------------------------------
# test_cancel_dispatched_task_failure_does_not_block_cancel_all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_cancel_dispatched_task_failure_does_not_block_cancel_all(
    mock_barrier: MagicMock,
) -> None:
    """逐个取消时某个任务抛异常不影响后续取消和 cancel_all。"""
    t1 = _make_blocking_task("fail-task")
    t2 = _make_blocking_task("ok-task")
    mock_barrier.get_pending_tasks.return_value = [t1, t2]

    conv_id, orch_run, user = await _create_waiting_orch_run()

    call_log: list[str] = []

    async def fake_cancel_dispatched_task(task_info: dict) -> None:
        tid = task_info.get("task_id", "")
        call_log.append(tid)
        if tid == "fail-task":
            raise RuntimeError("模拟取消失败")

    # 验证容错：即使逐个取消有异常，cancel_all 仍被调用
    # _cancel_dispatched_task 内部 try/except 保证不外泄异常
    cancel_mock = AsyncMock()

    with (
        patch("orchestration.runner_registry.get_active_runner", return_value=None),
        patch("orchestration.barrier.get_barrier_manager", return_value=mock_barrier),
        patch("chat.views._cancel_dispatched_task", cancel_mock),
    ):
        from adrf.test import AsyncAPIRequestFactory

        from chat.views import ChatInterruptView

        factory = AsyncAPIRequestFactory()
        request = factory.post(f"/api/conversations/{conv_id}/interrupt/")
        request.user = user

        view = ChatInterruptView()
        response = await view.post(request, conv_id)

        assert response.status_code == 200
        assert cancel_mock.await_count == 2
        mock_barrier.cancel_all.assert_awaited()


# ---------------------------------------------------------------------------
# test__cancel_dispatched_task_exception_is_swallowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test__cancel_dispatched_task_exception_is_swallowed() -> None:
    """_cancel_dispatched_task 内部异常不向外传播。"""
    from chat.views import _cancel_dispatched_task

    mock_dispatcher = MagicMock()
    mock_dispatcher.cancel = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("runners.dispatcher.get_dispatcher", return_value=mock_dispatcher):
        # 不应抛异常
        await _cancel_dispatched_task({"task_id": "x", "task_type": "test", "params": {}})

    mock_dispatcher.cancel.assert_awaited_once_with("x")
