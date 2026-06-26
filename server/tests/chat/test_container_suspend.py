"""ContainerSuspendService 守护测试（PLAN-03，Phase 89）：

- timeout 挂起：CAS RUNNING→SUSPENDED + dispatcher.cancel + parked_at 写入
- reply resume：build_resume_dispatch_env 非空 → re-dispatch（container_resumed）
- session miss 重灌：build_resume_dispatch_env {} → 应用态重灌（container_resume_reloaded）
- 竞态幂等：已 SUSPENDED 再 suspend no-op；非挂起态 resume 短路
- fail-soft：dispatcher.cancel / dispatch_coding_task 抛 → 吞异常不反噬
- arm/cancel_timeout：apscheduler 计时 seam（mock scheduler）+ 不可用降级
- schedule_container_resume 网关：仅挂起态才 resume（活容器答复直达不重起）
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from structlog.testing import capture_logs

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _make_coding_session(*, status: str):
    from chat.models import CodingSession, Conversation
    from projects.models import Space
    from repositories.models import Repository

    space = Space.objects.create(name=f"S-{uuid.uuid4().hex[:6]}")
    repo = Repository.objects.create(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
    )
    conversation = Conversation.objects.create(space=space, title="suspend 测试")
    return CodingSession.objects.create(
        conversation=conversation,
        repository=repo,
        tech_plan="## 技术方案",
        branch_name="feat/suspend-test",
        status=status,
    )


@sync_to_async
def _make_coding_session_with_subagent(*, status: str):
    from agents.models import AgentSession
    from chat.models import CodingSession, Conversation
    from projects.models import Space
    from repositories.models import Repository
    from subagent.models import SubAgentSession

    space = Space.objects.create(name=f"S-{uuid.uuid4().hex[:6]}")
    repo = Repository.objects.create(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
    )
    conversation = Conversation.objects.create(space=space, title="suspend 测试")
    session_id = f"coding-{uuid.uuid4().hex[:12]}"
    agent_session = AgentSession.objects.create(session_id=f"agent-{session_id}")
    sub_session = SubAgentSession.objects.create(
        session_id=session_id,
        main_session=agent_session,
        task_type=SubAgentSession.TaskType.CODING,
        status=SubAgentSession.Status.RUNNING,
        repo_url=repo.git_url,
    )
    cs = CodingSession.objects.create(
        conversation=conversation,
        repository=repo,
        tech_plan="## 技术方案",
        branch_name="feat/suspend-test",
        status=status,
        subagent_session=sub_session,
    )
    return cs, session_id


@sync_to_async
def _refresh_status(coding_session_id):
    from chat.models import CodingSession

    cs = CodingSession.objects.get(id=coding_session_id)
    return cs.status, cs.parked_at


# ---------------------------------------------------------------------------
# suspend
# ---------------------------------------------------------------------------
class TestSuspend:
    @pytest.mark.asyncio
    async def test_timeout_suspends(self) -> None:
        from chat.container_suspend_service import ContainerSuspendService
        from chat.models import CodingSession

        cs = await _make_coding_session(status=CodingSession.Status.RUNNING)

        mock_dispatcher = MagicMock()
        mock_dispatcher.cancel = AsyncMock(return_value=True)
        with patch(
            "runners.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ):
            result = await ContainerSuspendService().suspend(
                coding_session_id=str(cs.id), task_id="task-xyz"
            )

        assert result is True
        mock_dispatcher.cancel.assert_awaited_once_with("task-xyz")
        status, parked_at = await _refresh_status(cs.id)
        assert status == CodingSession.Status.SUSPENDED
        assert parked_at is not None

    @pytest.mark.asyncio
    async def test_suspend_idempotent_when_already_suspended(self) -> None:
        from chat.container_suspend_service import ContainerSuspendService
        from chat.models import CodingSession

        cs = await _make_coding_session(status=CodingSession.Status.SUSPENDED)

        mock_dispatcher = MagicMock()
        mock_dispatcher.cancel = AsyncMock(return_value=True)
        with patch(
            "runners.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ):
            result = await ContainerSuspendService().suspend(
                coding_session_id=str(cs.id), task_id="task-xyz"
            )

        # 已挂起 → CAS 不匹配，幂等短路：不调 cancel、状态不变。
        assert result is False
        mock_dispatcher.cancel.assert_not_awaited()
        status, _ = await _refresh_status(cs.id)
        assert status == CodingSession.Status.SUSPENDED

    @pytest.mark.asyncio
    async def test_suspend_noop_on_terminal_state(self) -> None:
        from chat.container_suspend_service import ContainerSuspendService
        from chat.models import CodingSession

        cs = await _make_coding_session(status=CodingSession.Status.COMPLETED)

        mock_dispatcher = MagicMock()
        mock_dispatcher.cancel = AsyncMock(return_value=True)
        with patch(
            "runners.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ):
            result = await ContainerSuspendService().suspend(
                coding_session_id=str(cs.id), task_id="task-xyz"
            )

        assert result is False
        mock_dispatcher.cancel.assert_not_awaited()
        status, _ = await _refresh_status(cs.id)
        assert status == CodingSession.Status.COMPLETED

    @pytest.mark.asyncio
    async def test_suspend_fail_soft_when_cancel_raises(self) -> None:
        from chat.container_suspend_service import ContainerSuspendService
        from chat.models import CodingSession

        cs = await _make_coding_session(status=CodingSession.Status.RUNNING)

        mock_dispatcher = MagicMock()
        mock_dispatcher.cancel = AsyncMock(side_effect=RuntimeError("runner down"))
        with patch(
            "runners.dispatcher.get_dispatcher", return_value=mock_dispatcher
        ):
            # 停容器抛 → 吞异常不反噬；状态已翻 SUSPENDED 视为成功挂起。
            result = await ContainerSuspendService().suspend(
                coding_session_id=str(cs.id), task_id="task-xyz"
            )

        assert result is True
        status, parked_at = await _refresh_status(cs.id)
        assert status == CodingSession.Status.SUSPENDED
        assert parked_at is not None


# ---------------------------------------------------------------------------
# resume
# ---------------------------------------------------------------------------
class TestResume:
    @pytest.mark.asyncio
    async def test_reply_resumes_with_session_store_env(self) -> None:
        from chat.container_suspend_service import ContainerSuspendService
        from chat.models import CodingSession

        cs = await _make_coding_session(status=CodingSession.Status.SUSPENDED)

        resume_env = {
            "env_FRIDAY_TASK_RESUME_SESSION_ID": "sess-x",
            "env_FRIDAY_TASK_RESUME_TRANSCRIPT_CHUNKS": "1",
            "env_FRIDAY_TASK_RESUME_TRANSCRIPT_0": "body",
        }
        dispatch_mock = AsyncMock(return_value="new-session-id")
        with (
            patch(
                "chat.sdk_resume.build_resume_dispatch_env", return_value=resume_env
            ),
            patch(
                "chat.coding_session_service.dispatch_coding_task", dispatch_mock
            ),
            capture_logs() as logs,
        ):
            result = await ContainerSuspendService().resume(
                coding_session=cs,
                user_reply="请用方案 A 实现",
                initiated_by_user_id="ou_user1",
            )

        assert result is True
        dispatch_mock.assert_awaited_once()
        # re-dispatch 携 coding 任务（其内部 build_resume_dispatch_env 注入 resume env）。
        assert dispatch_mock.await_args.kwargs.get("task_type") == "coding"
        # 命中 SessionStore → container_resumed 事件（区别于 reloaded）。
        events = [e["event"] for e in logs]
        assert "container_resumed" in events
        status, _ = await _refresh_status(cs.id)
        assert status == CodingSession.Status.RUNNING

    @pytest.mark.asyncio
    async def test_session_miss_reloads_fresh_session(self) -> None:
        from chat.container_suspend_service import ContainerSuspendService
        from chat.models import CodingSession

        cs = await _make_coding_session(status=CodingSession.Status.SUSPENDED)

        dispatch_mock = AsyncMock(return_value="fresh-session-id")
        with (
            # SessionStore miss / cwd 漂移 → build_resume_dispatch_env 返回 {}。
            patch("chat.sdk_resume.build_resume_dispatch_env", return_value={}),
            patch(
                "chat.coding_session_service.dispatch_coding_task", dispatch_mock
            ),
            capture_logs() as logs,
        ):
            result = await ContainerSuspendService().resume(
                coding_session=cs,
                user_reply="继续",
                initiated_by_user_id="ou_user1",
            )

        assert result is True
        # 应用态重灌新 session（无 resume 标记）—— 仍走 dispatch_coding_task 全新执行。
        dispatch_mock.assert_awaited_once()
        events = [e["event"] for e in logs]
        assert "container_resume_reloaded" in events
        assert "container_resumed" not in events
        status, _ = await _refresh_status(cs.id)
        assert status == CodingSession.Status.RUNNING

    @pytest.mark.asyncio
    async def test_resume_short_circuits_when_not_suspended(self) -> None:
        from chat.container_suspend_service import ContainerSuspendService
        from chat.models import CodingSession

        # 已 RUNNING（容器存活，用户 5min 内回复）→ CAS 不匹配，绝不重起容器。
        cs = await _make_coding_session(status=CodingSession.Status.RUNNING)

        dispatch_mock = AsyncMock()
        with (
            patch("chat.sdk_resume.build_resume_dispatch_env", return_value={}),
            patch(
                "chat.coding_session_service.dispatch_coding_task", dispatch_mock
            ),
        ):
            result = await ContainerSuspendService().resume(
                coding_session=cs, user_reply="hi"
            )

        assert result is False
        dispatch_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resume_fail_soft_when_dispatch_raises(self) -> None:
        from chat.container_suspend_service import ContainerSuspendService
        from chat.models import CodingSession

        cs = await _make_coding_session(status=CodingSession.Status.SUSPENDED)

        with (
            patch("chat.sdk_resume.build_resume_dispatch_env", return_value={}),
            patch(
                "chat.coding_session_service.dispatch_coding_task",
                AsyncMock(side_effect=RuntimeError("no runner")),
            ),
        ):
            # dispatch 抛 → 吞异常不反噬回调（返回 False）。
            result = await ContainerSuspendService().resume(
                coding_session=cs, user_reply="x"
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_resume_redacts_user_reply_in_prompt(self) -> None:
        from chat.container_suspend_service import ContainerSuspendService
        from chat.models import CodingSession

        cs = await _make_coding_session(status=CodingSession.Status.SUSPENDED)

        dispatch_mock = AsyncMock(return_value="sid")
        with (
            patch("chat.sdk_resume.build_resume_dispatch_env", return_value={}),
            patch(
                "chat.coding_session_service.dispatch_coding_task", dispatch_mock
            ),
        ):
            await ContainerSuspendService().resume(
                coding_session=cs,
                user_reply="密钥是 sk-ant-abcd1234567890efgh 用它",
            )

        prompt = dispatch_mock.await_args.kwargs.get("prompt", "")
        assert "sk-ant-abcd1234567890efgh" not in prompt
        assert "用户回复" in prompt


# ---------------------------------------------------------------------------
# arm / cancel timeout（apscheduler 计时 seam）
# ---------------------------------------------------------------------------
class TestArmCancelTimeout:
    @pytest.mark.asyncio
    async def test_arm_timeout_registers_one_shot_job(self) -> None:
        from chat.container_suspend_service import ContainerSuspendService, _job_id

        scheduler = MagicMock()
        with patch(
            "chat.container_suspend_service._get_timeout_scheduler",
            return_value=scheduler,
        ):
            ok = await ContainerSuspendService().arm_timeout(
                coding_session_id="cs-1",
                task_id="task-1",
                initiated_by_user_id="ou_u",
                minutes=5,
            )

        assert ok is True
        scheduler.add_job.assert_called_once()
        assert scheduler.add_job.call_args.kwargs.get("id") == _job_id("cs-1")
        assert scheduler.add_job.call_args.kwargs.get("replace_existing") is True

    @pytest.mark.asyncio
    async def test_arm_timeout_failsoft_when_scheduler_unavailable(self) -> None:
        from chat.container_suspend_service import ContainerSuspendService

        with patch(
            "chat.container_suspend_service._get_timeout_scheduler",
            return_value=None,
        ):
            ok = await ContainerSuspendService().arm_timeout(
                coding_session_id="cs-1", task_id="task-1"
            )
        assert ok is False

    @pytest.mark.asyncio
    async def test_cancel_timeout_removes_job(self) -> None:
        from chat.container_suspend_service import ContainerSuspendService, _job_id

        scheduler = MagicMock()
        with patch(
            "chat.container_suspend_service._get_timeout_scheduler",
            return_value=scheduler,
        ):
            ok = await ContainerSuspendService().cancel_timeout(coding_session_id="cs-1")

        assert ok is True
        scheduler.remove_job.assert_called_once_with(_job_id("cs-1"))

    @pytest.mark.asyncio
    async def test_cancel_timeout_noop_when_job_missing(self) -> None:
        from chat.container_suspend_service import ContainerSuspendService

        scheduler = MagicMock()
        scheduler.remove_job.side_effect = Exception("JobLookupError")
        with patch(
            "chat.container_suspend_service._get_timeout_scheduler",
            return_value=scheduler,
        ):
            ok = await ContainerSuspendService().cancel_timeout(coding_session_id="cs-1")
        assert ok is False


# ---------------------------------------------------------------------------
# schedule_container_resume 网关（仅挂起态 resume）
# ---------------------------------------------------------------------------
class TestScheduleResumeGate:
    @pytest.mark.asyncio
    async def test_async_gate_resumes_only_when_suspended(self) -> None:
        from chat.container_suspend_service import _do_resume_async
        from chat.models import CodingSession

        cs, session_id = await _make_coding_session_with_subagent(
            status=CodingSession.Status.SUSPENDED
        )

        with (
            patch(
                "chat.container_suspend_service.ContainerSuspendService.cancel_timeout",
                new_callable=AsyncMock,
            ) as cancel_mock,
            patch(
                "chat.container_suspend_service.ContainerSuspendService.resume",
                new_callable=AsyncMock,
            ) as resume_mock,
        ):
            await _do_resume_async(
                session_id=session_id, user_reply="ok", responder_id="ou_u"
            )

        cancel_mock.assert_awaited_once()
        resume_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_gate_skips_resume_when_running(self) -> None:
        from chat.container_suspend_service import _do_resume_async
        from chat.models import CodingSession

        # 活容器（RUNNING）：答复直达，绝不重起容器 → resume 不调用，仅取消计时。
        cs, session_id = await _make_coding_session_with_subagent(
            status=CodingSession.Status.RUNNING
        )

        with (
            patch(
                "chat.container_suspend_service.ContainerSuspendService.cancel_timeout",
                new_callable=AsyncMock,
            ) as cancel_mock,
            patch(
                "chat.container_suspend_service.ContainerSuspendService.resume",
                new_callable=AsyncMock,
            ) as resume_mock,
        ):
            await _do_resume_async(
                session_id=session_id, user_reply="ok", responder_id="ou_u"
            )

        cancel_mock.assert_awaited_once()
        resume_mock.assert_not_awaited()
