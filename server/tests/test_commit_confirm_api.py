"""CommitConfirmView API 测试 -- GET/POST /api/chat/coding-sessions/{id}/commit-confirm/。

验证 commit message 确认流程的 REST API，包括状态校验、错误处理、graph resume。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat.models import CodingSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def awaiting_session(project, repository, user):
    """创建 awaiting_confirmation 状态的 CodingSession。"""
    from chat.models import Conversation

    conversation = Conversation.objects.create(
        project=project, title="测试对话", created_by=user
    )
    return CodingSession.objects.create(
        conversation=conversation,
        repository=repository,
        tech_plan="## 技术方案\n- 步骤 1",
        affected_files=[{"path": "src/main.py", "change_type": "modify"}],
        branch_name="feat20260409.test-coding",
        status=CodingSession.Status.AWAITING_CONFIRMATION,
        confirmation_step="commit_message",
        suggested_commit_message="feat: add new feature",
    )


@pytest.fixture()
def running_session(project, repository, user):
    """创建 running 状态的 CodingSession。"""
    from chat.models import Conversation

    conversation = Conversation.objects.create(
        project=project, title="测试对话 running", created_by=user
    )
    return CodingSession.objects.create(
        conversation=conversation,
        repository=repository,
        tech_plan="## 技术方案",
        branch_name="feat20260409.test-running",
        status=CodingSession.Status.RUNNING,
    )


# ---------------------------------------------------------------------------
# GET 测试
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestCommitConfirmGet:
    """GET /api/chat/coding-sessions/{id}/commit-confirm/ 测试。"""

    def test_get_suggested_commit_message(self, authenticated_client, awaiting_session):
        """awaiting_confirmation + commit_message 步骤返回 200 + 建议消息。"""
        url = f"/api/chat/coding-sessions/{awaiting_session.id}/commit-confirm/"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.data["suggested_commit_message"] == "feat: add new feature"
        assert response.data["affected_files"] == [
            {"path": "src/main.py", "change_type": "modify"}
        ]

    def test_get_wrong_status_returns_409(self, authenticated_client, running_session):
        """running 状态返回 409。"""
        url = f"/api/chat/coding-sessions/{running_session.id}/commit-confirm/"
        response = authenticated_client.get(url)
        assert response.status_code == 409

    def test_get_wrong_step_returns_409(self, authenticated_client, awaiting_session):
        """awaiting_confirmation 但 confirmation_step != commit_message 返回 409。"""
        awaiting_session.confirmation_step = "pr_review"
        awaiting_session.save(update_fields=["confirmation_step"])

        url = f"/api/chat/coding-sessions/{awaiting_session.id}/commit-confirm/"
        response = authenticated_client.get(url)
        assert response.status_code == 409

    def test_get_not_found_returns_404(self, authenticated_client):
        """不存在的 session_id 返回 404。"""
        fake_id = uuid.uuid4()
        url = f"/api/chat/coding-sessions/{fake_id}/commit-confirm/"
        response = authenticated_client.get(url)
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST 测试
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestCommitConfirmPost:
    """POST /api/chat/coding-sessions/{id}/commit-confirm/ 测试。"""

    def test_post_confirm_commit_message(self, authenticated_client, awaiting_session):
        """POST 有效 commit_message 返回 200 + 序列化数据。"""
        mock_compiled = MagicMock()
        mock_compiled.ainvoke = AsyncMock()

        mock_graph_builder = MagicMock()
        mock_graph_builder.compile.return_value = mock_compiled

        with (
            patch(
                "orchestration.coding_graph.build_coding_graph",
                return_value=mock_graph_builder,
            ),
            patch(
                "orchestration.checkpointer.get_checkpointer",
                new_callable=AsyncMock,
            ),
        ):
            url = f"/api/chat/coding-sessions/{awaiting_session.id}/commit-confirm/"
            response = authenticated_client.post(
                url,
                {"commit_message": "feat: user edited message"},
                format="json",
            )

        assert response.status_code == 200
        assert "id" in response.data
        assert "status" in response.data

    def test_post_empty_message_returns_400(self, authenticated_client, awaiting_session):
        """POST 空 commit_message 返回 400。"""
        url = f"/api/chat/coding-sessions/{awaiting_session.id}/commit-confirm/"
        response = authenticated_client.post(
            url,
            {"commit_message": ""},
            format="json",
        )
        assert response.status_code == 400

    def test_post_wrong_status_returns_409(self, authenticated_client, running_session):
        """running 状态 POST 返回 409。"""
        url = f"/api/chat/coding-sessions/{running_session.id}/commit-confirm/"
        response = authenticated_client.post(
            url,
            {"commit_message": "feat: test"},
            format="json",
        )
        assert response.status_code == 409

    def test_post_too_long_message_returns_400(self, authenticated_client, awaiting_session):
        """commit_message 超过 5000 字符返回 400。"""
        long_msg = "x" * 5001
        url = f"/api/chat/coding-sessions/{awaiting_session.id}/commit-confirm/"
        response = authenticated_client.post(
            url,
            {"commit_message": long_msg},
            format="json",
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# State Recovery 测试
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestStateRecovery:
    """验证刷新后 commit-confirm 状态可恢复。"""

    def test_refresh_recovers_state(self, authenticated_client, awaiting_session):
        """awaiting_confirmation 状态可通过 GET 恢复 suggested_commit_message。"""
        url = f"/api/chat/coding-sessions/{awaiting_session.id}/commit-confirm/"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.data["suggested_commit_message"] == "feat: add new feature"

        # 再次 GET 依然可恢复
        response2 = authenticated_client.get(url)
        assert response2.status_code == 200
        assert response2.data["suggested_commit_message"] == "feat: add new feature"


# ---------------------------------------------------------------------------
# implementation Wave work item 端到端测试
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestCommitConfirmE2E:
    """work item 端到端 — progress 回调 → GET /commit-confirm/ 数据流。

    regression 指出：容器通过 progress 回调携带
    details.suggested_commit_message，但服务端 _handle_progress 未提取该字段，
    导致 GET /api/chat/coding-sessions/{id}/commit-confirm/ 返回空字符串。

    本测试覆盖 work item 端到端闭环：
      1. 通过真实调用 _handle_progress(sub_session, payload, log) 模拟容器 progress 回调
      2. 从 sub_session.last_output 提取 suggested_commit_message 写入 CodingSession
      3. 通过 GET /commit-confirm/ 读取，断言返回值非空且等于容器上报值
    """

    def test_suggested_commit_message_flows_from_progress_to_get(
        self,
        authenticated_client,
        project,
        repository,
        user,
    ) -> None:
        """端到端数据流 — progress 回调写入 → GET API 返回真实 AI 建议（非空字符串）。

        关键修复证据：若 Wave G1 未修复，session.last_output 不会包含
        suggested_commit_message，于是 coding_session.suggested_commit_message 无法
        被填充，GET 返回的字段将是空字符串。本测试断言 != "" 即捕捉该回归。
        """
        import asyncio

        import structlog

        from agents.models import AgentSession
        from chat.models import CodingSession, Conversation
        from subagent.api.callbacks import _handle_progress
        from subagent.models import SubAgentSession

        expected_msg = "feat: add user auth per contract"

        # ---- Arrange: 创建 conversation + running CodingSession + SubAgentSession ----
        conversation = Conversation.objects.create(
            project=project, title="work item E2E 测试对话", created_by=user
        )
        coding_session = CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 技术方案\n- 步骤 1",
            affected_files=[{"path": "src/auth.py", "change_type": "create"}],
            branch_name="feat20260410.e2e-suggested",
            status=CodingSession.Status.RUNNING,
        )

        # 创建 AgentSession + SubAgentSession（progress 回调的作用对象）
        agent_session = AgentSession.objects.create(
            session_id=f"main-e2e-{uuid.uuid4().hex[:8]}",
        )
        sub_session = SubAgentSession.objects.create(
            session_id=f"sub-e2e-{uuid.uuid4().hex[:8]}",
            main_session=agent_session,
            repo_url="https://github.com/test/repo.git",
            task_type="coding",
            status=SubAgentSession.Status.RUNNING,
            last_output={"task_type": "coding", "source": "web"},
        )

        # ---- Act 1: 模拟容器 progress 回调（含 details.suggested_commit_message） ----
        payload: dict = {
            "phase": "coding_complete",
            "progress": 1.0,
            "message": "AI suggested commit message generated",
            "details": {"suggested_commit_message": expected_msg},
        }
        log = structlog.get_logger("test")

        # 同步测试中调用 async _handle_progress，用 asyncio.run
        async def _run_progress() -> None:
            # 回到"活对象"语境确保 asave 生效
            fresh = await SubAgentSession.objects.aget(session_id=sub_session.session_id)
            await _handle_progress(fresh, payload, log)

        asyncio.run(_run_progress())

        # 回读 sub_session 确认 G1 + G5 修复生效（verification-level）
        sub_session.refresh_from_db()
        assert sub_session.last_output is not None
        assert sub_session.last_output["suggested_commit_message"] == expected_msg
        # G5 merge 语义：预设 task_type/source 保留
        assert sub_session.last_output["task_type"] == "coding"
        assert sub_session.last_output["source"] == "web"

        # ---- Act 2: 模拟 coding_graph 消费 suggested_commit_message 并推进到 awaiting ----
        # (在生产代码中此步由 _update_coding_session_on_complete / coding_graph 节点完成)
        suggested_from_sub = sub_session.last_output["suggested_commit_message"]

        async def _mark_awaiting() -> None:
            cs = await CodingSession.objects.aget(id=coding_session.id)
            await cs.amark_awaiting_confirmation("commit_message", suggested_from_sub)

        asyncio.run(_mark_awaiting())

        # ---- Act 3: GET /commit-confirm/ 读取数据 ----
        url = f"/api/chat/coding-sessions/{coding_session.id}/commit-confirm/"
        response = authenticated_client.get(url)

        # ---- Assert: GET 返回真实 AI 建议（G1 闭环的核心证据） ----
        assert response.status_code == 200
        assert response.data["suggested_commit_message"] == expected_msg
        # 核心断言：G1 修复前此字段会是空字符串
        assert response.data["suggested_commit_message"] != ""
        # affected_files 也被正确返回
        assert response.data["affected_files"] == [
            {"path": "src/auth.py", "change_type": "create"}
        ]
