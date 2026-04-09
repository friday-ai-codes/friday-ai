"""Phase: 编码中间产出 (coding_progress) 回调与轮询测试。
覆盖场景:
- _handle_progress 回调在携带/不携带 coding_progress 时的行为
- ConversationRuntime 轮询时从 SubAgentSession.last_output 读取 coding_progress
"""
from __future__ import annotations
from typing import Any
from unittest.mock import AsyncMock, MagicMock
import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from structlog.stdlib import BoundLogger
from subagent.api.callbacks import _handle_progress
from subagent.models import SubAgentSession
def _make_session(last_output: dict[str, Any] | None = None) -> SubAgentSession:
 """构造一个 mock SubAgentSession 实例。"""
 session = MagicMock(spec=SubAgentSession)
 session.last_output = last_output
 session.asave = AsyncMock
 return session
def _make_log -> BoundLogger:
 """构造 mock BoundLogger。"""
 log = MagicMock(spec=BoundLogger)
 log.debug = MagicMock
 return log
# ============================================================================
# TestHandleProgressCodingProgress — _handle_progress 回调扩展
# ============================================================================
class TestHandleProgressCodingProgress:
 """验证 _handle_progress 回调对 coding_progress 字段的处理。"""
 @pytest.mark.asyncio
 async def test_progress_callback_with_coding_progress(self) -> None:
 """发送 progress 回调携带 coding_progress 字段，
 验证 SubAgentSession.last_output 包含 coding_progress 键且内含 modified_files 和 recent_tool_calls。
 """
 session = _make_session
 log = _make_log
 payload: dict[str, Any] = {
 "phase": "coding",
 "progress": 0.5,
 "message": "Implementing feature...",
 "coding_progress": {
 "modified_files": [
 {"path": "src/main.py", "change_type": "modified"},
 {"path": "src/utils.py", "change_type": "created"},
 ],
 "recent_tool_calls": [
 {"tool": "Edit", "summary": "Modified main.py line 42"},
 {"tool": "Write", "summary": "Created utils.py"},
 ],
 },
 }
 response: Response = await _handle_progress(session, payload, log)
 assert response.status_code == status.HTTP_200_OK
 assert response.data == {"status": "ok"}
 # 验证 last_output 被正确设置
 saved_output = session.last_output
 assert "progress" in saved_output
 assert saved_output["progress"]["phase"] == "coding"
 assert saved_output["progress"]["progress"] == 0.5
 # 验证 coding_progress 被正确保存
 assert "coding_progress" in saved_output
 cp = saved_output["coding_progress"]
 assert len(cp["modified_files"]) == 2
 assert cp["modified_files"][0]["path"] == "src/main.py"
 assert len(cp["recent_tool_calls"]) == 2
 assert cp["recent_tool_calls"][0]["tool"] == "Edit"
 assert "updated_at" in cp
 session.asave.assert_awaited_once_with(update_fields=["last_output", "updated_at"])
 @pytest.mark.asyncio
 async def test_progress_callback_without_coding_progress(self) -> None:
 """发送普通 progress 回调（无 coding_progress 字段），
 验证 last_output 只有 progress 键，无 coding_progress 键。
 """
 session = _make_session
 log = _make_log
 payload: dict[str, Any] = {
 "phase": "analyzing",
 "progress": 0.3,
 "message": "Analyzing codebase...",
 }
 response: Response = await _handle_progress(session, payload, log)
 assert response.status_code == status.HTTP_200_OK
 saved_output = session.last_output
 assert "progress" in saved_output
 assert saved_output["progress"]["phase"] == "analyzing"
 # 不携带 coding_progress 时不应有该键
 assert "coding_progress" not in saved_output
 @pytest.mark.asyncio
 async def test_progress_callback_coding_progress_invalid_type(self) -> None:
 """coding_progress 为非 dict 类型（如 string），验证被忽略，last_output 无 coding_progress 键。"""
 session = _make_session
 log = _make_log
 payload: dict[str, Any] = {
 "phase": "coding",
 "progress": 0.1,
 "message": "Starting...",
 "coding_progress": "not-a-dict",
 }
 response: Response = await _handle_progress(session, payload, log)
 assert response.status_code == status.HTTP_200_OK
 saved_output = session.last_output
 assert "progress" in saved_output
 # 非 dict 类型应被忽略
 assert "coding_progress" not in saved_output
 @pytest.mark.asyncio
 async def test_progress_callback_coding_progress_empty_dict(self) -> None:
 """coding_progress 为空 dict 时被忽略（falsy check）。"""
 session = _make_session
 log = _make_log
 payload: dict[str, Any] = {
 "phase": "coding",
 "progress": 0.2,
 "message": "Working...",
 "coding_progress": {},
 }
 response: Response = await _handle_progress(session, payload, log)
 assert response.status_code == status.HTTP_200_OK
 saved_output = session.last_output
 assert "progress" in saved_output
 # 空 dict 为 falsy，应被忽略
 assert "coding_progress" not in saved_output
 @pytest.mark.asyncio
 async def test_progress_callback_coding_progress_partial_fields(self) -> None:
 """coding_progress 只包含 modified_files 没有 recent_tool_calls 时，缺失字段默认空列表。"""
 session = _make_session
 log = _make_log
 payload: dict[str, Any] = {
 "phase": "coding",
 "progress": 0.2,
 "message": "Working...",
 "coding_progress": {
 "modified_files": [
 {"path": "README.md", "change_type": "modified"},
 ],
 },
 }
 response: Response = await _handle_progress(session, payload, log)
 assert response.status_code == status.HTTP_200_OK
 saved_output = session.last_output
 assert "coding_progress" in saved_output
 cp = saved_output["coding_progress"]
 assert len(cp["modified_files"]) == 1
 # recent_tool_calls 缺失时默认空列表
 assert cp["recent_tool_calls"] ==
 assert "updated_at" in cp
# ============================================================================
# TestConversationRuntimeCodingProgress — ConversationRuntime 轮询扩展
# ============================================================================
class TestConversationRuntimeCodingProgress:
 """验证 ConversationRuntime 轮询时从 SubAgentSession 获取 coding_progress 中间产出。"""
 @pytest.mark.asyncio
 @pytest.mark.django_db(transaction=True)
 async def test_runtime_returns_coding_progress(
 self, user: Any, project: Any, repository: Any
 ) -> None:
 """创建 running CodingSession + 关联 SubAgentSession（last_output 包含 coding_progress），
 调用 get_conversation_runtime，验证返回的 coding_progress 包含 modified_files 和 recent_tool_calls。
 """
 from agents.models import AgentSession
 from chat.conversation_service import ConversationService
 from chat.models import CodingSession, Conversation
 # 创建对话
 conversation = await Conversation.objects.acreate(
 project=project,
 title="Test Conversation",
 )
 # 创建 AgentSession（SubAgentSession 的 main_session 外键需要）
 agent_session = await AgentSession.objects.acreate(
 session_id="main-test-001",
 user=user,
 )
 # 创建 SubAgentSession，last_output 包含 coding_progress
 subagent_session = await SubAgentSession.objects.acreate(
 session_id="sub-test-001",
 main_session=agent_session,
 repo_url="https://github.com/test/repo.git",
 task_type="coding",
 status=SubAgentSession.Status.RUNNING,
 last_output={
 "progress": {
 "phase": "coding",
 "progress": 0.6,
 "message": "Working on feature",
 "updated_at": timezone.now.isoformat,
 },
 "coding_progress": {
 "modified_files": [
 {"path": "src/app.py", "change_type": "modified"},
 ],
 "recent_tool_calls": [
 {"tool": "Edit", "summary": "Updated app.py"},
 ],
 "updated_at": "2026-04-09T10:00:00Z",
 },
 },
 )
 # 创建 running CodingSession，关联 SubAgentSession
 await CodingSession.objects.acreate(
 conversation=conversation,
 repository=repository,
 status=CodingSession.Status.RUNNING,
 tech_plan="# Test Plan",
 affected_files=["src/app.py"],
 subagent_session=subagent_session,
 )
 runtime = await ConversationService.get_conversation_runtime(
 str(conversation.id),
 )
 assert runtime["active"] is True
 assert runtime["mode"] == "coding"
 assert "coding_session" in runtime
 cs = runtime["coding_session"]
 assert "coding_progress" in cs
 cp = cs["coding_progress"]
 assert len(cp["modified_files"]) == 1
 assert cp["modified_files"][0]["path"] == "src/app.py"
 assert len(cp["recent_tool_calls"]) == 1
 assert cp["recent_tool_calls"][0]["tool"] == "Edit"
 assert cp["updated_at"] == "2026-04-09T10:00:00Z"
 @pytest.mark.asyncio
 @pytest.mark.django_db(transaction=True)
 async def test_runtime_no_coding_progress_when_no_subagent(
 self, user: Any, project: Any, repository: Any
 ) -> None:
 """创建 running CodingSession 但无 SubAgentSession，
 验证 runtime["coding_session"] 不包含 coding_progress 键。
 """
 from chat.conversation_service import ConversationService
 from chat.models import CodingSession, Conversation
 conversation = await Conversation.objects.acreate(
 project=project,
 title="Test Conversation 2",
 )
 await CodingSession.objects.acreate(
 conversation=conversation,
 repository=repository,
 status=CodingSession.Status.RUNNING,
 tech_plan="# Test Plan",
 affected_files=,
 # subagent_session=None（默认）
 )
 runtime = await ConversationService.get_conversation_runtime(
 str(conversation.id),
 )
 assert runtime["active"] is True
 assert runtime["mode"] == "coding"
 cs = runtime["coding_session"]
 assert "coding_progress" not in cs
 @pytest.mark.asyncio
 @pytest.mark.django_db(transaction=True)
 async def test_runtime_no_coding_progress_when_empty_output(
 self, user: Any, project: Any, repository: Any
 ) -> None:
 """SubAgentSession.last_output 为空 dict，
 验证 runtime["coding_session"] 不包含 coding_progress 键。
 """
 from agents.models import AgentSession
 from chat.conversation_service import ConversationService
 from chat.models import CodingSession, Conversation
 conversation = await Conversation.objects.acreate(
 project=project,
 title="Test Conversation 3",
 )
 agent_session = await AgentSession.objects.acreate(
 session_id="main-test-003",
 user=user,
 )
 subagent_session = await SubAgentSession.objects.acreate(
 session_id="sub-test-003",
 main_session=agent_session,
 repo_url="https://github.com/test/repo.git",
 task_type="coding",
 status=SubAgentSession.Status.RUNNING,
 last_output={}, # 空 dict
 )
 await CodingSession.objects.acreate(
 conversation=conversation,
 repository=repository,
 status=CodingSession.Status.RUNNING,
 tech_plan="# Test Plan",
 affected_files=,
 subagent_session=subagent_session,
 )
 runtime = await ConversationService.get_conversation_runtime(
 str(conversation.id),
 )
 assert runtime["active"] is True
 assert runtime["mode"] == "coding"
 cs = runtime["coding_session"]
 assert "coding_progress" not in cs
