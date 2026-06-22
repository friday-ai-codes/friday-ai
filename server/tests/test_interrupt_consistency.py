"""中断一致性测试 — work item。

覆盖中断流程的关键路径：
- ChatInterruptView 通过 runner_registry 查找并中断活跃 runner
- 中断后更新 OrchestrationRun 状态为 interrupted
- 中断后标记最新 assistant 消息 metadata.status = interrupted
- 无活跃 runner 时 fallback 到 barrier 取消
- 无任何活跃会话时返回 404
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

CONV_UUID = uuid.uuid4()


async def _create_conv_and_user() -> tuple[Any, Any]:
    """创建真实 user + 其拥有的 Conversation（owner gate 要求 created_by 一致）。"""
    from django.contrib.auth import get_user_model

    from chat.models import Conversation
    from projects.models import Project

    User = get_user_model()
    user = await User.objects.acreate_user(
        username=f"intr_{uuid.uuid4().hex[:8]}",
        password="testpass123",
    )
    project = await Project.objects.acreate(name=f"intr-proj-{uuid.uuid4().hex[:6]}")
    conv = await Conversation.objects.acreate(
        project=project, title="interrupt", created_by=user
    )
    return conv, user


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_interrupt_via_active_runner() -> None:
    """ChatInterruptView：有活跃 runner 时通过 runner.interrupt() 中断。"""
    mock_runner = MagicMock()
    mock_runner.interrupt = AsyncMock()

    with (
        patch("orchestration.runner_registry.get_active_runner", return_value=mock_runner),
        patch("orchestration.models.OrchestrationRun") as mock_orch_cls,
        patch("chat.models.Message") as mock_msg_cls,
    ):
        mock_orch_cls.objects.filter.return_value.aupdate = AsyncMock(return_value=1)
        mock_orch_cls.Status.RUNNING = "running"
        mock_orch_cls.Status.WAITING = "waiting"
        mock_orch_cls.Status.INTERRUPTED = "interrupted"

        mock_msg_cls.objects.filter.return_value.order_by.return_value.afirst = AsyncMock(
            return_value=None,
        )
        mock_msg_cls.Role.ASSISTANT = "assistant"

        conv, user = await _create_conv_and_user()

        from adrf.test import AsyncAPIRequestFactory

        from chat.views import ChatInterruptView

        factory = AsyncAPIRequestFactory()
        request = factory.post(f"/api/chat/conversations/{conv.id}/interrupt/")
        request.user = user

        view = ChatInterruptView()
        response = await view.post(request, conv.id)

    assert response.status_code == 200
    assert response.data["status"] == "interrupted"
    mock_runner.interrupt.assert_awaited_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_interrupt_updates_orchestration_run_status() -> None:
    """中断后 OrchestrationRun.status 更新为 interrupted。"""
    mock_runner = MagicMock()
    mock_runner.interrupt = AsyncMock()

    with (
        patch("orchestration.runner_registry.get_active_runner", return_value=mock_runner),
        patch("orchestration.models.OrchestrationRun") as mock_orch_cls,
        patch("chat.models.Message") as mock_msg_cls,
    ):
        mock_update = AsyncMock(return_value=1)
        mock_orch_cls.objects.filter.return_value.aupdate = mock_update
        mock_orch_cls.Status.RUNNING = "running"
        mock_orch_cls.Status.WAITING = "waiting"
        mock_orch_cls.Status.INTERRUPTED = "interrupted"

        mock_msg_cls.objects.filter.return_value.order_by.return_value.afirst = AsyncMock(
            return_value=None,
        )
        mock_msg_cls.Role.ASSISTANT = "assistant"

        conv, user = await _create_conv_and_user()

        from adrf.test import AsyncAPIRequestFactory

        from chat.views import ChatInterruptView

        factory = AsyncAPIRequestFactory()
        request = factory.post(f"/api/chat/conversations/{conv.id}/interrupt/")
        request.user = user

        view = ChatInterruptView()
        await view.post(request, conv.id)

    mock_orch_cls.objects.filter.assert_called()
    mock_update.assert_awaited_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_interrupt_updates_message_metadata() -> None:
    """中断后最新 assistant 消息 metadata 含 status: interrupted。"""
    mock_runner = MagicMock()
    mock_runner.interrupt = AsyncMock()

    mock_msg = MagicMock()
    mock_msg.metadata = {}
    mock_msg.asave = AsyncMock()

    with (
        patch("orchestration.runner_registry.get_active_runner", return_value=mock_runner),
        patch("orchestration.models.OrchestrationRun") as mock_orch_cls,
        patch("chat.models.Message") as mock_msg_cls,
    ):
        mock_orch_cls.objects.filter.return_value.aupdate = AsyncMock(return_value=1)
        mock_orch_cls.Status.RUNNING = "running"
        mock_orch_cls.Status.WAITING = "waiting"
        mock_orch_cls.Status.INTERRUPTED = "interrupted"

        mock_msg_cls.objects.filter.return_value.order_by.return_value.afirst = AsyncMock(
            return_value=mock_msg,
        )
        mock_msg_cls.Role.ASSISTANT = "assistant"

        conv, user = await _create_conv_and_user()

        from adrf.test import AsyncAPIRequestFactory

        from chat.views import ChatInterruptView

        factory = AsyncAPIRequestFactory()
        request = factory.post(f"/api/chat/conversations/{conv.id}/interrupt/")
        request.user = user

        view = ChatInterruptView()
        await view.post(request, conv.id)

    assert mock_msg.metadata["status"] == "interrupted"
    mock_msg.asave.assert_awaited_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_interrupt_no_active_runner_fallback() -> None:
    """ChatInterruptView：无活跃 runner 且无 barrier 时返回 404。"""
    with (
        patch("orchestration.runner_registry.get_active_runner", return_value=None),
        patch("orchestration.barrier.get_barrier_manager") as mock_barrier_fn,
    ):
        mock_bm = MagicMock()
        mock_bm.has_barrier_for_thread.return_value = False
        mock_barrier_fn.return_value = mock_bm

        conv, user = await _create_conv_and_user()

        from adrf.test import AsyncAPIRequestFactory

        from chat.views import ChatInterruptView

        factory = AsyncAPIRequestFactory()
        request = factory.post(f"/api/chat/conversations/{conv.id}/interrupt/")
        request.user = user

        view = ChatInterruptView()
        response = await view.post(request, conv.id)

    assert response.status_code == 404
