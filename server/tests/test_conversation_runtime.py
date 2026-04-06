"""ConversationService.get_conversation_runtime 单元测试。
覆盖 runtime API 的核心场景：
- OrchestrationRun 状态映射到 runtime 返回值
- inactive when completed / interrupted
- task_progress 从 metadata.progress 中提取
- 超过 1 小时的 running run 视为 error
"""
from __future__ import annotations
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from django.utils import timezone
from orchestration.models import OrchestrationRun
class _AsyncIterator:
 """辅助 async iterator，用于 mock Django async queryset。"""
 def __init__(self, items: list[Any]) -> None:
 self._items = iter(items)
 def __aiter__(self) -> _AsyncIterator:
 return self
 async def __anext__(self) -> Any:
 try:
 return next(self._items)
 except StopIteration:
 raise StopAsyncIteration
def _mock_orch_run(
 *,
 status: str = "running",
 phase: str = "executing",
 run_id: str = "aaaa-bbbb",
 metadata: dict[str, Any] | None = None,
 created_at: Any = None,
) -> MagicMock:
 """构造 mock OrchestrationRun 实例。"""
 mock = MagicMock(spec=OrchestrationRun)
 mock.status = status
 mock.phase = phase
 mock.run_id = run_id
 mock.metadata = metadata or {}
 mock.created_at = created_at or timezone.now
 mock.id = 1
 return mock
def _setup_session_mock(mock_sess_cls: MagicMock, sessions: list[Any] | None = None) -> None:
 """为 SubAgentSession mock 配置 async iterator。"""
 mock_sess_cls.TaskType.EXPLORE = "explore"
 mock_sess_cls.Status.PENDING = "pending"
 mock_sess_cls.Status.RUNNING = "running"
 qs = MagicMock
 qs.order_by.return_value = _AsyncIterator(sessions or )
 mock_sess_cls.objects.filter.return_value = qs
@pytest.mark.asyncio
async def test_runtime_from_orchestration_run -> None:
 """OrchestrationRun running → active=True, 返回 phase/status/orchestration_run_id。"""
 mock_run = _mock_orch_run(status="running", phase="executing", run_id="run-123")
 with (
 patch("chat.conversation_service.OrchestrationRun") as mock_orch_cls,
 patch("subagent.models.SubAgentSession") as mock_sess_cls,
 ):
 mock_orch_cls.Status = OrchestrationRun.Status
 mock_orch_cls.Phase = OrchestrationRun.Phase
 mock_orch_cls.objects.filter.return_value.order_by.return_value.afirst = AsyncMock(
 return_value=mock_run,
 )
 _setup_session_mock(mock_sess_cls)
 from chat.conversation_service import ConversationService
 runtime = await ConversationService.get_conversation_runtime("cid")
 assert runtime["active"] is True
 assert runtime["status"] == "running"
 assert runtime["phase"] == "executing"
 assert runtime["orchestration_run_id"] == "run-123"
 assert runtime["mode"] == "chat"
@pytest.mark.asyncio
async def test_runtime_inactive_when_completed -> None:
 """OrchestrationRun status=completed → active=False。"""
 mock_run = _mock_orch_run(status="completed", phase="completed")
 with (
 patch("chat.conversation_service.OrchestrationRun") as mock_orch_cls,
 patch("subagent.models.SubAgentSession") as mock_sess_cls,
 ):
 mock_orch_cls.Status = OrchestrationRun.Status
 mock_orch_cls.Phase = OrchestrationRun.Phase
 mock_orch_cls.objects.filter.return_value.order_by.return_value.afirst = AsyncMock(
 return_value=mock_run,
 )
 _setup_session_mock(mock_sess_cls)
 from chat.conversation_service import ConversationService
 runtime = await ConversationService.get_conversation_runtime("cid")
 assert runtime["active"] is False
 assert runtime["status"] == "completed"
@pytest.mark.asyncio
async def test_runtime_with_task_progress -> None:
 """metadata 含 progress → runtime 返回 task_progress。"""
 mock_run = _mock_orch_run(
 status="waiting",
 phase="waiting",
 metadata={"progress": {"completed": 2, "total": 3}},
 )
 with (
 patch("chat.conversation_service.OrchestrationRun") as mock_orch_cls,
 patch("subagent.models.SubAgentSession") as mock_sess_cls,
 ):
 mock_orch_cls.Status = OrchestrationRun.Status
 mock_orch_cls.Phase = OrchestrationRun.Phase
 mock_orch_cls.objects.filter.return_value.order_by.return_value.afirst = AsyncMock(
 return_value=mock_run,
 )
 _setup_session_mock(mock_sess_cls)
 from chat.conversation_service import ConversationService
 runtime = await ConversationService.get_conversation_runtime("cid")
 assert runtime["task_progress"] == {"completed": 2, "total": 3}
 assert runtime["active"] is True
@pytest.mark.asyncio
async def test_runtime_timeout_window -> None:
 """超过 1 小时的 running run 视为 error，auto-close。"""
 mock_run = _mock_orch_run(
 status="running",
 phase="executing",
 created_at=timezone.now - timedelta(hours=2),
 )
 with (
 patch("chat.conversation_service.OrchestrationRun") as mock_orch_cls,
 patch("subagent.models.SubAgentSession") as mock_sess_cls,
 ):
 mock_orch_cls.Status = OrchestrationRun.Status
 mock_orch_cls.Phase = OrchestrationRun.Phase
 mock_orch_cls.objects.filter.return_value.order_by.return_value.afirst = AsyncMock(
 return_value=mock_run,
 )
 mock_orch_cls.objects.filter.return_value.aupdate = AsyncMock(return_value=1)
 _setup_session_mock(mock_sess_cls)
 from chat.conversation_service import ConversationService
 runtime = await ConversationService.get_conversation_runtime("cid")
 assert runtime["active"] is False
 assert runtime["status"] == "error"
