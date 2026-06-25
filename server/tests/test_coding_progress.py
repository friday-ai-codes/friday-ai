"""编码中间产出 (coding_progress) 回调与轮询测试。

覆盖场景:
- _handle_progress 回调在携带/不携带 coding_progress 时的行为
- ConversationRuntime 轮询时从 SubAgentSession.last_output 读取 coding_progress
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
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
    session.asave = AsyncMock()
    return session


def _make_log() -> BoundLogger:
    """构造 mock BoundLogger。"""
    log = MagicMock(spec=BoundLogger)
    log.debug = MagicMock()
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
        session = _make_session()
        log = _make_log()

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
        session = _make_session()
        log = _make_log()

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
        session = _make_session()
        log = _make_log()

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
        session = _make_session()
        log = _make_log()

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
        session = _make_session()
        log = _make_log()

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
        assert cp["recent_tool_calls"] == []
        assert "updated_at" in cp

    # ------------------------------------------------------------------
    # implementation G1 + G5 Wave 新增（RED → GREEN）
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_progress_callback_extracts_details_suggested_commit_message(
        self,
    ) -> None:
        """G1: _handle_progress 提取 details.suggested_commit_message 到 last_output。

        regression: 容器通过 progress 回调 details.suggested_commit_message
        传递 AI 生成的 commit message，但原 callbacks.py 内联拼装逻辑未提取该字段，
        导致 GET /commit-confirm/ 返回空字符串。本测试验证 Wave 修复后 session.last_output
        顶层携带 suggested_commit_message，证明 parse_progress_payload 被正确调用。
        """
        session = _make_session()
        log = structlog.get_logger("test")

        payload: dict[str, Any] = {
            "phase": "coding_complete",
            "progress": 1.0,
            "message": "done",
            "details": {"suggested_commit_message": "feat: add authentication"},
        }

        response: Response = await _handle_progress(session, payload, log)

        assert response.status_code == status.HTTP_200_OK
        assert session.last_output is not None
        # G1: details.suggested_commit_message 已透传到 last_output 顶层
        assert (
            session.last_output["suggested_commit_message"]
            == "feat: add authentication"
        )
        # 既有 progress 字段保留（parse_progress_payload 规范化输出）
        assert session.last_output["progress"]["phase"] == "coding_complete"
        assert session.last_output["progress"]["progress"] == 1.0
        session.asave.assert_awaited()

    @pytest.mark.asyncio
    async def test_progress_callback_merges_and_preserves_meta(self) -> None:
        """G5: session.last_output 采用 merge 语义，预设 meta 完整保留。

        regression: 原 callbacks.py 使用 session.last_output = output 整体覆盖，
        会丢失既有 task_type / source / conversation_id / logs 等 meta 字段。
        本测试验证 Wave 修复后使用 {**(session.last_output or {}), **output} merge 语义，
        预设的 4 个 meta key 在 progress 回调写入后全部保留。
        """
        preset_meta = {
            "task_type": "coding",
            "source": "web",
            "conversation_id": "conv-123",
            "logs": [{"ts": "2026-04-09T00:00:00Z", "msg": "start"}],
        }
        session = _make_session(last_output=dict(preset_meta))
        log = structlog.get_logger("test")

        payload: dict[str, Any] = {
            "phase": "coding",
            "progress": 0.5,
            "message": "halfway",
        }

        response: Response = await _handle_progress(session, payload, log)

        assert response.status_code == status.HTTP_200_OK
        assert session.last_output is not None

        # 所有预设 meta 必须保留（G5 merge 语义核心证据）
        assert session.last_output["task_type"] == "coding"
        assert session.last_output["source"] == "web"
        assert session.last_output["conversation_id"] == "conv-123"
        assert session.last_output["logs"] == [
            {"ts": "2026-04-09T00:00:00Z", "msg": "start"}
        ]

        # 新增 progress 字段必须 merge 入同一 dict（不是覆盖）
        assert session.last_output["progress"]["phase"] == "coding"
        assert session.last_output["progress"]["progress"] == 0.5

        # 既有 meta 与新 progress 共存
        assert "task_type" in session.last_output
        assert "progress" in session.last_output


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
            space=project,
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
                    "updated_at": timezone.now().isoformat(),
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
            space=project,
            title="Test Conversation 2",
        )

        await CodingSession.objects.acreate(
            conversation=conversation,
            repository=repository,
            status=CodingSession.Status.RUNNING,
            tech_plan="# Test Plan",
            affected_files=[],
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
            space=project,
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
            last_output={},  # 空 dict
        )

        await CodingSession.objects.acreate(
            conversation=conversation,
            repository=repository,
            status=CodingSession.Status.RUNNING,
            tech_plan="# Test Plan",
            affected_files=[],
            subagent_session=subagent_session,
        )

        runtime = await ConversationService.get_conversation_runtime(
            str(conversation.id),
        )

        assert runtime["active"] is True
        assert runtime["mode"] == "coding"
        cs = runtime["coding_session"]
        assert "coding_progress" not in cs


# ============================================================================
# TestProgressPayloadSerializer — implementation G1 阻塞前置条件（Wave）
# ============================================================================


class TestProgressPayloadSerializer:
    """验证 ProgressPayloadSerializer 声明了 details 字段，避免 DRF 静默丢弃。

    implementation G4 依赖 G1 阻塞前置条件：若 serializer 未声明 details，
    则 callbacks.py 的 _handle_progress 永远无法从 validated_data 中拿到 details，
    导致下游 parse_progress_payload 的 suggested_commit_message 提取永远失败。
    """

    def test_details_field_accepted(self) -> None:
        """serializer 应接受并保留 details 字段的内容。"""
        from subagent.api.serializers import ProgressPayloadSerializer

        serializer = ProgressPayloadSerializer(
            data={
                "phase": "coding",
                "details": {"suggested_commit_message": "feat: test"},
            }
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["details"] == {
            "suggested_commit_message": "feat: test"
        }

    def test_details_field_defaults_to_empty_dict_when_missing(self) -> None:
        """未提供 details 时应默认为空 dict，消费侧可安全 .get('details', {})。"""
        from subagent.api.serializers import ProgressPayloadSerializer

        serializer = ProgressPayloadSerializer(data={"phase": "coding"})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data.get("details") == {}


# ============================================================================
# TestWSProgressParsesViaCommon — implementation G4 WS 路径调用公共 parser（Wave）
# ============================================================================


class TestWSProgressParsesViaCommon:
    """验证 runners.consumers.RunnerConsumer._handle_progress 实际调用
    parse_progress_payload 并采用 merge 语义写入 session.last_output。

    HTTP 路径（callbacks.py）的一致性断言推迟到 plan（那时 HTTP 路径也已修复）。
    """

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_ws_handle_progress_uses_parse_progress_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """WS 路径端到端：构造真实 SubAgentSession，调用 _handle_progress，
        DB 回读验证 suggested_commit_message 透传 + 预设 meta 保留 + nested dict。
        """
        import uuid

        from agents.models import AgentSession
        from runners.consumers import RunnerConsumer

        # 预设 meta 用于验证 merge 语义（task_type/source）
        task_id = f"ws-test-{uuid.uuid4().hex[:8]}"

        agent_session = await AgentSession.objects.acreate(
            session_id=f"main-{task_id}",
        )
        await SubAgentSession.objects.acreate(
            session_id=task_id,
            main_session=agent_session,
            repo_url="https://github.com/test/repo.git",
            task_type="coding",
            status=SubAgentSession.Status.RUNNING,
            last_output={"task_type": "coding", "source": "web"},
        )

        # 构造 payload：同时含 phase/progress/message/coding_progress/details
        payload: dict[str, Any] = {
            "phase": "coding",
            "progress": 0.5,
            "message": "hi",
            "coding_progress": {
                "modified_files": ["a.py"],
                "recent_tool_calls": [],
            },
            "details": {"suggested_commit_message": "feat: test"},
        }

        # monkeypatch _append_runtime_log 为 AsyncMock 避免触发 runtime log 外部副作用
        mock_append_log = AsyncMock()
        monkeypatch.setattr(
            "runners.consumers._append_runtime_log",
            mock_append_log,
        )

        # _handle_progress 是实例方法，但函数体内不使用 self.* 属性（仅 SubAgentSession 全局查询）
        # 以类方法形式 invoke，self 用 MagicMock 填充（兼容 CPython bound method 语义）
        await RunnerConsumer._handle_progress(MagicMock(), task_id, payload)

        # DB 回读验证
        session_reloaded = await SubAgentSession.objects.aget(session_id=task_id)
        last_output = session_reloaded.last_output
        assert last_output is not None

        # 1) details.suggested_commit_message 透传生效（证明 parse_progress_payload 被调用）
        assert last_output["suggested_commit_message"] == "feat: test"

        # 2) progress nested dict 正确
        assert last_output["progress"]["phase"] == "coding"
        assert last_output["progress"]["progress"] == 0.5

        # 3) coding_progress nested dict 正确
        assert last_output["coding_progress"]["modified_files"] == ["a.py"]

        # 4) merge 语义：预设 meta (task_type/source) 必须保留
        assert last_output["task_type"] == "coding"
        assert last_output["source"] == "web"

        # 5) _append_runtime_log 被调用（验证原有副作用保留）
        mock_append_log.assert_awaited_once()


# ============================================================================
# TestProgressParsingConsistency — implementation G4 Wave HTTP + WS 双路径一致性
# ============================================================================


class TestProgressParsingConsistency:
    """G4: HTTP 与 WS 两条 progress 路径对同一 payload 产生一致的 session.last_output。

    plan (Wave) 已独立验证 WS 路径的端到端正确性（TestWSProgressParsesViaCommon）。
    plan (Wave) 的本测试是 G4 端到端闭环的核心证据：
    - HTTP 路径（callbacks.py:_handle_progress）Wave 修复后也调用 parse_progress_payload
    - 两条路径对同一 payload 产生字段级等价的 session.last_output
    - 两条路径均遵守 merge 语义，保留预设 meta
    """

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_ws_and_http_paths_produce_identical_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HTTP 路径 (_handle_progress) 与 WS 路径 (RunnerConsumer._handle_progress)
        对同一 payload 产生一致的 session.last_output（除 updated_at 时间戳外）。
        """
        import uuid

        from agents.models import AgentSession
        from runners.consumers import RunnerConsumer

        # 避免 WS 路径触发 runtime log 外部副作用
        mock_append_log = AsyncMock()
        monkeypatch.setattr(
            "runners.consumers._append_runtime_log",
            mock_append_log,
        )

        run_tag = uuid.uuid4().hex[:8]
        http_sid = f"http-sid-checkpoint-{run_tag}"
        ws_sid = f"ws-sid-checkpoint-{run_tag}"

        # 预设 meta 用于验证 merge 语义
        preset_meta = {"task_type": "coding", "source": "web"}

        agent_session = await AgentSession.objects.acreate(
            session_id=f"main-{run_tag}",
        )
        await SubAgentSession.objects.acreate(
            session_id=http_sid,
            main_session=agent_session,
            repo_url="https://github.com/test/repo.git",
            task_type="coding",
            status=SubAgentSession.Status.RUNNING,
            last_output=dict(preset_meta),
        )
        await SubAgentSession.objects.acreate(
            session_id=ws_sid,
            main_session=agent_session,
            repo_url="https://github.com/test/repo.git",
            task_type="coding",
            status=SubAgentSession.Status.RUNNING,
            last_output=dict(preset_meta),
        )

        payload: dict[str, Any] = {
            "phase": "coding",
            "progress": 0.5,
            "message": "hi",
            "coding_progress": {
                "modified_files": ["a.py"],
                "recent_tool_calls": [],
            },
            "details": {"suggested_commit_message": "feat: test"},
        }
        log = structlog.get_logger("test")

        # HTTP 路径: _handle_progress 需要 session 对象作为第一参数
        http_session = await SubAgentSession.objects.aget(session_id=http_sid)
        await _handle_progress(http_session, payload, log)
        http_session = await SubAgentSession.objects.aget(session_id=http_sid)

        # WS 路径: RunnerConsumer._handle_progress 是实例方法但未使用 self.*
        await RunnerConsumer._handle_progress(MagicMock(), ws_sid, payload)
        ws_session = await SubAgentSession.objects.aget(session_id=ws_sid)

        http_last = http_session.last_output
        ws_last = ws_session.last_output
        assert http_last is not None
        assert ws_last is not None

        # 1) details.suggested_commit_message 两路径均透传
        assert (
            http_last["suggested_commit_message"]
            == ws_last["suggested_commit_message"]
            == "feat: test"
        )

        # 2) progress nested dict phase/progress 字段一致（updated_at 除外，为时间戳）
        assert (
            http_last["progress"]["phase"]
            == ws_last["progress"]["phase"]
            == "coding"
        )
        assert (
            http_last["progress"]["progress"]
            == ws_last["progress"]["progress"]
            == 0.5
        )
        assert (
            http_last["progress"]["message"]
            == ws_last["progress"]["message"]
            == "hi"
        )

        # 3) coding_progress nested dict 两路径字段一致
        assert (
            http_last["coding_progress"]["modified_files"]
            == ws_last["coding_progress"]["modified_files"]
            == ["a.py"]
        )
        assert (
            http_last["coding_progress"]["recent_tool_calls"]
            == ws_last["coding_progress"]["recent_tool_calls"]
            == []
        )

        # 4) merge 语义：预设 meta (task_type/source) 两路径均保留
        assert (
            http_last["task_type"]
            == ws_last["task_type"]
            == "coding"
        )
        assert http_last["source"] == ws_last["source"] == "web"


# ============================================================================
# TestPhaseRuntimePollingSmoke — implementation 方案 B 轮询路径 end-to-end smoke
# ============================================================================


class TestPhaseRuntimePollingSmoke:
    """implementation 方案 B 轮询路径 smoke。

    证明 progress 回调写入 SubAgentSession.last_output 后,
    ConversationRuntime 快照在一次 HTTP 调用内可读到 coding_progress。
    这是 work item "感知延迟 ≤ 2s" 的**后端侧**可达性证据
    (真实延迟由前端 scheduleRuntimePoll 的 setTimeout(2000) 在应用层决定)。

    本用例使用 Option C 结构: payload 同时携带
      - details.suggested_commit_message (证明 implementation G1 顶层透传未回归)
      - coding_progress 嵌套 dict (证明 runtime 快照轮询路径端到端可达)

    implementation 决策详见 project docs
    """

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_progress_suggested_commit_message_visible_via_runtime_snapshot(
        self, user: Any, project: Any, repository: Any
    ) -> None:
        """progress 回调 → session.last_output → runtime 快照一次调用内可达。"""
        from agents.models import AgentSession
        from chat.conversation_service import ConversationService
        from chat.models import CodingSession, Conversation

        # --- Setup: 创建 Conversation + AgentSession + SubAgentSession + CodingSession ---
        conversation = await Conversation.objects.acreate(
            space=project,
            title="implementation smoke",
        )
        agent_session = await AgentSession.objects.acreate(
            session_id="main-phase-smoke",
            user=user,
        )
        subagent_session = await SubAgentSession.objects.acreate(
            session_id="sub-phase-smoke",
            main_session=agent_session,
            repo_url="https://github.com/test/repo.git",
            task_type="coding",
            status=SubAgentSession.Status.RUNNING,
            last_output={},
        )
        await CodingSession.objects.acreate(
            conversation=conversation,
            repository=repository,
            status=CodingSession.Status.RUNNING,
            tech_plan="# implementation smoke plan",
            affected_files=[],
            subagent_session=subagent_session,
        )

        # --- Act 1: 触发 progress 回调(Option C 结构 — 同时带 details + coding_progress) ---
        log = structlog.get_logger("phase.smoke")
        payload: dict[str, Any] = {
            "phase": "coding",
            "progress": 0.6,
            "message": "正在编辑 implementation smoke 文件",
            "details": {"suggested_commit_message": "feat: implementation gap closure"},
            "coding_progress": {
                "modified_files": [
                    {"path": "server/tests/test_coding_progress.py", "change_type": "modified"},
                ],
                "recent_tool_calls": [
                    {"tool": "Edit", "summary": "Added implementation smoke"},
                ],
                "updated_at": "2026-04-10T12:00:00Z",
            },
        }
        response = await _handle_progress(subagent_session, payload, log)
        assert response.status_code == status.HTTP_200_OK

        # --- Act 2: DB 回读验证 implementation G1 顶层透传 + coding_progress 嵌套保留 ---
        await subagent_session.arefresh_from_db()
        saved = subagent_session.last_output
        assert saved is not None, "last_output 应已被 _handle_progress 写入,不应为 None"
        assert saved["suggested_commit_message"] == "feat: implementation gap closure", (
            "implementation G1 regression: details.suggested_commit_message 未透传到 last_output 顶层"
        )
        assert "coding_progress" in saved
        cp = saved["coding_progress"]
        assert len(cp["modified_files"]) == 1
        assert cp["modified_files"][0]["path"] == "server/tests/test_coding_progress.py"
        # NOTE: implementation 公共 parse_progress_payload 会用服务端 timezone.now()
        # 覆盖调用方传入的 updated_at(既有模板用例 test_progress_callback_with_coding_progress
        # 的断言也是"存在即可")。此处断言存在性 + 字符串类型,不校验字面值。
        assert isinstance(cp["updated_at"], str) and cp["updated_at"]

        # --- Act 3: 同一次调用链内立即拉取 runtime 快照(证明后端轮询路径可达) ---
        runtime = await ConversationService.get_conversation_runtime(str(conversation.id))
        assert runtime["active"] is True
        assert runtime["mode"] == "coding"
        assert "coding_session" in runtime
        cs = runtime["coding_session"]
        assert "coding_progress" in cs, (
            "implementation 方案 B 轮询路径断裂: runtime 快照未暴露 coding_progress"
        )
        cp_runtime = cs["coding_progress"]
        assert len(cp_runtime["modified_files"]) == 1
        assert cp_runtime["modified_files"][0]["path"] == "server/tests/test_coding_progress.py"
        # 与 Act 2 一致:updated_at 由生产 parser 统一写入,不校验字面值
        assert isinstance(cp_runtime["updated_at"], str) and cp_runtime["updated_at"]

        # NOTE: 不断言 runtime["coding_session"]["suggested_commit_message"] — 该字段
        # 源自 CodingSession.suggested_commit_message model 字段,只在 _update_coding_session_on_complete
        # (completed 回调) 时才透传写入。本 smoke 不触发 completed,所以该字段仍为空字符串。
        # implementation 决策交叉引用详见 server/agents/core/events.py implementation 决策注释块
        # 与 project docs contract。
