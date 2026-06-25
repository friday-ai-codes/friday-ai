"""CodingSession 模型测试 — 状态机、辅助方法、默认值 + API 测试。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat.models import CodingSession


@pytest.mark.django_db
class TestCodingSessionDefaults:
    """验证 CodingSession 创建时的默认值。"""

    def test_coding_session_model_defaults(self, project, repository):
        """创建 CodingSession 后 status 默认为 draft，revision_count 默认为 0。"""
        from chat.models import Conversation

        conversation = Conversation.objects.create(space=project, title="测试对话")
        session = CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 技术方案\n- 步骤 1",
        )
        assert session.status == CodingSession.Status.DRAFT
        assert session.revision_count == 0
        assert session.pr_url == ""
        assert session.error_message == ""
        assert session.branch_name == ""
        assert session.subagent_session is None


@pytest.mark.django_db(transaction=True)
class TestCodingSessionStateMachine:
    """验证 CodingSession 状态转换方法的约束。"""

    @pytest.fixture
    def draft_session(self, project, repository):
        """创建 draft 状态的 CodingSession。"""
        from chat.models import Conversation

        conversation = Conversation.objects.create(space=project, title="测试对话")
        return CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 初始方案",
        )

    @pytest.mark.asyncio
    async def test_aconfirm_from_draft(self, draft_session):
        """draft -> confirmed 转换成功。"""
        await draft_session.aconfirm()
        await draft_session.arefresh_from_db()
        assert draft_session.status == CodingSession.Status.CONFIRMED

    @pytest.mark.asyncio
    async def test_aconfirm_from_non_draft_raises(self, draft_session):
        """非 draft 状态调用 aconfirm() 抛出 ValueError。"""
        # confirmed 状态
        await draft_session.aconfirm()
        with pytest.raises(ValueError, match="只有 draft 状态可确认"):
            await draft_session.aconfirm()

        # running 状态
        draft_session.status = CodingSession.Status.RUNNING
        await draft_session.asave(update_fields=["status"])
        with pytest.raises(ValueError, match="只有 draft 状态可确认"):
            await draft_session.aconfirm()

        # completed 状态
        draft_session.status = CodingSession.Status.COMPLETED
        await draft_session.asave(update_fields=["status"])
        with pytest.raises(ValueError, match="只有 draft 状态可确认"):
            await draft_session.aconfirm()

        # failed 状态
        draft_session.status = CodingSession.Status.FAILED
        await draft_session.asave(update_fields=["status"])
        with pytest.raises(ValueError, match="只有 draft 状态可确认"):
            await draft_session.aconfirm()

    @pytest.mark.asyncio
    async def test_amark_running_sets_subagent(self, draft_session):
        """confirmed -> running 转换成功。"""
        draft_session.status = CodingSession.Status.CONFIRMED
        await draft_session.asave(update_fields=["status"])

        await draft_session.amark_running()
        await draft_session.arefresh_from_db()
        assert draft_session.status == CodingSession.Status.RUNNING

    @pytest.mark.asyncio
    async def test_amark_completed_sets_pr_url(self, draft_session):
        """running -> completed 转换成功，并设置 pr_url。"""
        draft_session.status = CodingSession.Status.RUNNING
        await draft_session.asave(update_fields=["status"])

        await draft_session.amark_completed(pr_url="https://github.com/test/repo/pull/1")
        await draft_session.arefresh_from_db()
        assert draft_session.status == CodingSession.Status.COMPLETED
        assert draft_session.pr_url == "https://github.com/test/repo/pull/1"

    @pytest.mark.asyncio
    async def test_amark_failed_sets_error(self, draft_session):
        """running -> failed 转换成功，并设置 error_message。"""
        draft_session.status = CodingSession.Status.RUNNING
        await draft_session.asave(update_fields=["status"])

        await draft_session.amark_failed(error="容器执行超时")
        await draft_session.arefresh_from_db()
        assert draft_session.status == CodingSession.Status.FAILED
        assert draft_session.error_message == "容器执行超时"

    @pytest.mark.asyncio
    async def test_aupdate_plan_increments_revision(self, draft_session):
        """aupdate_plan 更新 tech_plan 并递增 revision_count。"""
        assert draft_session.revision_count == 0

        await draft_session.aupdate_plan(
            tech_plan="## 更新后方案\n- 新步骤",
            affected_files=[{"path": "src/main.py", "change_type": "modify"}],
        )
        await draft_session.arefresh_from_db()
        assert draft_session.revision_count == 1
        assert draft_session.tech_plan == "## 更新后方案\n- 新步骤"
        assert draft_session.affected_files == [{"path": "src/main.py", "change_type": "modify"}]


# ============================================================================
# Confirm API 测试 (task, implementation contract 改造)
# ============================================================================


def _make_graph_mocks():
    """构造 build_coding_graph / get_checkpointer 的 mock 套件。

    confirm view 应直接 await graph.ainvoke 跑到首个 interrupt，确保响应返回前
    已创建 SubAgentSession 并 dispatch 到 Runner。
    """
    from unittest.mock import AsyncMock, MagicMock

    mock_graph_compiled = MagicMock()
    mock_graph_compiled.ainvoke = AsyncMock(return_value={"phase": "waiting_coding"})
    mock_graph_builder = MagicMock()
    mock_graph_builder.compile = MagicMock(return_value=mock_graph_compiled)
    mock_build_coding_graph = MagicMock(return_value=mock_graph_builder)

    mock_checkpointer = MagicMock()
    mock_get_checkpointer = AsyncMock(return_value=mock_checkpointer)

    return {
        "build_coding_graph": mock_build_coding_graph,
        "graph_builder": mock_graph_builder,
        "graph_compiled": mock_graph_compiled,
        "get_checkpointer": mock_get_checkpointer,
        "checkpointer": mock_checkpointer,
    }


@pytest.mark.django_db(transaction=True)
class TestCodingSessionConfirmAPI:
    """CodingSession confirm API 端点测试（implementation contract 改造后）。

    view 改为启动 coding_graph 后台任务，状态推进 confirmed -> running 下沉到
    dispatch_coding_node。这里只验证 view 同步前置（aconfirm + Runner 探测 + graph 启动），
    graph 节点的行为由 test_coding_session_graph_e2e.py 覆盖。
    """

    @pytest.fixture
    def draft_session(self, project, repository, user):
        """创建 draft 状态的 CodingSession（含 Conversation + 有效分支名）。"""
        from chat.models import Conversation

        conversation = Conversation.objects.create(
            space=project, title="测试对话", created_by=user
        )
        return CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 技术方案\n- 步骤 1\n- 步骤 2",
            affected_files=[{"path": "src/main.py", "change_type": "modify"}],
            branch_name="feat20260409.test-coding",
        )

    def test_confirm_only_draft(self, authenticated_client, draft_session):
        """POST /api/chat/coding-sessions/{id}/confirm/ 对 draft CodingSession 返回 200。

        view 不再同步推进到 running；graph 后台任务负责。
        view 同步前置成功后 status=confirmed（aconfirm 已切换），200 + graph 启动。
        """
        from unittest.mock import AsyncMock, patch

        mocks = _make_graph_mocks()

        with (
            patch("chat.views.check_runner_online", new_callable=AsyncMock, return_value=True),
            patch("chat.views.build_coding_graph", new=mocks["build_coding_graph"]),
            patch("chat.views.get_checkpointer", new=mocks["get_checkpointer"]),
        ):
            url = f"/api/chat/coding-sessions/{draft_session.id}/confirm/"
            response = authenticated_client.post(url)

        assert response.status_code == 200
        draft_session.refresh_from_db()
        # view 同步前置 aconfirm 之后状态应为 confirmed；running 推进由 graph 节点完成
        assert draft_session.status == CodingSession.Status.CONFIRMED
        # graph 必须在响应返回前跑到首个 interrupt，避免 confirmed 卡住但无容器
        mocks["graph_compiled"].ainvoke.assert_awaited_once()
        # checkpointer + build_coding_graph 各调一次
        mocks["get_checkpointer"].assert_called_once()
        mocks["build_coding_graph"].assert_called_once()

    def test_confirm_non_confirmable_running_returns_400(self, authenticated_client, draft_session):
        """POST confirm 对不可重新派发的 non-draft 状态返回 400。"""
        draft_session.status = CodingSession.Status.RUNNING
        draft_session.save(update_fields=["status"])

        url = f"/api/chat/coding-sessions/{draft_session.id}/confirm/"
        response = authenticated_client.post(url)
        assert response.status_code == 400

    def test_confirmed_without_subagent_restarts_graph(self, authenticated_client, draft_session):
        """confirmed 但尚未创建 SubAgentSession 的卡住状态可幂等重启 graph。"""
        from unittest.mock import AsyncMock, patch

        draft_session.status = CodingSession.Status.CONFIRMED
        draft_session.subagent_session = None
        draft_session.save(update_fields=["status", "subagent_session"])

        mocks = _make_graph_mocks()

        with (
            patch("chat.views.check_runner_online", new_callable=AsyncMock, return_value=True),
            patch("chat.views.build_coding_graph", new=mocks["build_coding_graph"]),
            patch("chat.views.get_checkpointer", new=mocks["get_checkpointer"]),
        ):
            url = f"/api/chat/coding-sessions/{draft_session.id}/confirm/"
            response = authenticated_client.post(url)

        assert response.status_code == 200
        draft_session.refresh_from_db()
        assert draft_session.status == CodingSession.Status.CONFIRMED
        mocks["graph_compiled"].ainvoke.assert_awaited_once()

    def test_confirm_starts_graph_with_correct_thread_id(self, authenticated_client, draft_session):
        """confirm 成功后 graph 启动时 thread_id 格式必须是 coding-{coding_session.id}。

        implementation contract 关键契约：thread_id 决定了 callback resume 时能否
        找到对应 graph thread。CommitConfirmView / PRConfirmView 也依赖同款格式。
        """
        from unittest.mock import AsyncMock, patch

        mocks = _make_graph_mocks()

        with (
            patch("chat.views.check_runner_online", new_callable=AsyncMock, return_value=True),
            patch("chat.views.build_coding_graph", new=mocks["build_coding_graph"]),
            patch("chat.views.get_checkpointer", new=mocks["get_checkpointer"]),
        ):
            url = f"/api/chat/coding-sessions/{draft_session.id}/confirm/"
            response = authenticated_client.post(url)

        assert response.status_code == 200
        # graph compile 被调一次（带 checkpointer 关键字参数）
        mocks["graph_builder"].compile.assert_called_once_with(checkpointer=mocks["checkpointer"])
        # graph 在请求内直接推进到首个 interrupt，不再依赖易丢失的后台 task
        mocks["graph_compiled"].ainvoke.assert_awaited_once()

    def test_confirm_runner_offline_returns_503(self, authenticated_client, draft_session):
        """Runner 不在线时返回 503，CodingSession 回滚到 draft，graph 不启动。"""
        from unittest.mock import AsyncMock, patch

        mocks = _make_graph_mocks()

        with (
            patch("chat.views.check_runner_online", new_callable=AsyncMock, return_value=False),
            patch("chat.views.build_coding_graph", new=mocks["build_coding_graph"]),
            patch("chat.views.get_checkpointer", new=mocks["get_checkpointer"]),
        ):
            url = f"/api/chat/coding-sessions/{draft_session.id}/confirm/"
            response = authenticated_client.post(url)

        assert response.status_code == 503
        draft_session.refresh_from_db()
        assert draft_session.status == CodingSession.Status.DRAFT
        # graph 不应被启动
        mocks["build_coding_graph"].assert_not_called()

    def test_confirm_not_found_returns_404(self, authenticated_client):
        """传入不存在 UUID 返回 404。"""
        import uuid

        fake_id = uuid.uuid4()
        url = f"/api/chat/coding-sessions/{fake_id}/confirm/"
        response = authenticated_client.post(url)
        assert response.status_code == 404

    def test_confirm_unauthenticated_returns_401(self, api_client, draft_session):
        """未认证请求返回 401。"""
        url = f"/api/chat/coding-sessions/{draft_session.id}/confirm/"
        response = api_client.post(url)
        assert response.status_code in (401, 403)


# ============================================================================
# 回调处理扩展测试 (task)
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestCodingSessionCallback:
    """CodingSession 回调处理扩展测试。"""

    @pytest.fixture
    def running_session_with_subagent(self, project, repository):
        """创建 running 状态的 CodingSession + 关联 SubAgentSession (兼容旧流程 task_type=explore)。"""
        from agents.models import AgentSession
        from chat.models import Conversation
        from subagent.models import SubAgentSession

        conversation = Conversation.objects.create(space=project, title="回调测试对话")
        agent_session = AgentSession.objects.create(
            session_id="agent-coding-test-001",
            space=project,
            status=AgentSession.Status.RUNNING,
        )
        # task_type=EXPLORE 测试兼容旧流程路径（非 graph 管理的 session）
        # graph 管理路径 (coding/coding_commit) 的测试在 test_commit_confirm_api.py 中
        sub_session = SubAgentSession.objects.create(
            session_id="coding-test-001",
            main_session=agent_session,
            task_type=SubAgentSession.TaskType.EXPLORE,
            status=SubAgentSession.Status.RUNNING,
            repo_url="https://github.com/test/repo.git",
        )
        coding_session = CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 技术方案",
            status=CodingSession.Status.RUNNING,
            subagent_session=sub_session,
        )
        return coding_session, sub_session

    @pytest.mark.asyncio
    async def test_callback_updates_pr_url(self, running_session_with_subagent):
        """completed 回调后 CodingSession.status=completed, pr_url 被回填（兼容旧流程）。"""
        from subagent.api.callbacks import _update_coding_session_on_complete
        from subagent.models import TaskResult

        coding_session, sub_session = running_session_with_subagent

        # 创建 TaskResult with pr_url
        await TaskResult.objects.acreate(
            session=sub_session,
            result_type=TaskResult.ResultType.GIT,
            pr_url="https://github.com/test/repo/pull/1",
            raw_output={"text": "done"},
        )
        await sub_session.amark_completed()

        await _update_coding_session_on_complete(sub_session)

        await coding_session.arefresh_from_db()
        assert coding_session.status == CodingSession.Status.COMPLETED
        assert coding_session.pr_url == "https://github.com/test/repo/pull/1"

    @pytest.mark.asyncio
    async def test_callback_failed_updates_error(self, running_session_with_subagent):
        """failed 回调后 CodingSession.status=failed, error_message 被设置（兼容旧流程）。"""
        from subagent.api.callbacks import _update_coding_session_on_fail

        coding_session, sub_session = running_session_with_subagent

        await _update_coding_session_on_fail(sub_session, "容器执行超时")

        await coding_session.arefresh_from_db()
        assert coding_session.status == CodingSession.Status.FAILED
        assert coding_session.error_message == "容器执行超时"

    @pytest.mark.asyncio
    async def test_graph_resume_failure_marks_failed_instead_of_completed(
        self, running_session_with_subagent
    ):
        """graph resume 失败时不能静默 completed，否则 PR 阶段会被吞掉。"""
        from subagent.api.callbacks import _update_coding_session_on_complete

        coding_session, sub_session = running_session_with_subagent
        sub_session.last_output = {"task_type": "coding_commit"}
        await sub_session.asave(update_fields=["last_output", "updated_at"])

        mock_compiled = MagicMock()
        mock_compiled.ainvoke = AsyncMock(side_effect=RuntimeError("checkpoint missing"))
        mock_graph_builder = MagicMock()
        mock_graph_builder.compile.return_value = mock_compiled

        with (
            patch("orchestration.coding_graph.build_coding_graph", return_value=mock_graph_builder),
            patch("orchestration.checkpointer.get_checkpointer", new_callable=AsyncMock),
        ):
            await _update_coding_session_on_complete(sub_session)

        await coding_session.arefresh_from_db()
        assert coding_session.status == CodingSession.Status.FAILED
        assert "提交后 PR 流程恢复失败" in coding_session.error_message
        assert coding_session.pr_url == ""

    @pytest.mark.asyncio
    async def test_callback_no_coding_session_passes(self, project):
        """无关联 CodingSession 的 session 回调不报错。"""
        from agents.models import AgentSession
        from subagent.api.callbacks import (
            _update_coding_session_on_complete,
            _update_coding_session_on_fail,
        )
        from subagent.models import SubAgentSession

        agent_session = await AgentSession.objects.acreate(
            session_id="agent-no-coding-001",
            space=project,
            status=AgentSession.Status.RUNNING,
        )
        sub_session = await SubAgentSession.objects.acreate(
            session_id="no-coding-001",
            main_session=agent_session,
            task_type=SubAgentSession.TaskType.EXPLORE,
            status=SubAgentSession.Status.COMPLETED,
            repo_url="https://github.com/test/repo.git",
        )

        # 不应抛出异常
        await _update_coding_session_on_complete(sub_session)
        await _update_coding_session_on_fail(sub_session, "some error")


# ============================================================================
# 查询恢复 API 测试 (task)
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestCodingSessionQueryAPI:
    """CodingSession 查询恢复 API 测试。"""

    @pytest.fixture
    def conversation_with_sessions(self, project, repository, user):
        """创建一个 conversation 并关联 2 个 CodingSession。"""
        from chat.models import Conversation

        conversation = Conversation.objects.create(
            space=project, title="查询测试对话", created_by=user
        )
        session1 = CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 方案 1",
            status=CodingSession.Status.COMPLETED,
            pr_url="https://github.com/test/repo/pull/1",
        )
        session2 = CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 方案 2",
            status=CodingSession.Status.DRAFT,
        )
        return conversation, session1, session2

    def test_list_by_conversation(self, authenticated_client, conversation_with_sessions):
        """GET /api/chat/coding-sessions/?conversation_id=xxx 返回 2 条。"""
        conversation, _, _ = conversation_with_sessions
        url = f"/api/chat/coding-sessions/?conversation_id={conversation.id}"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert len(response.data) == 2

    def test_list_empty_conversation(self, authenticated_client, project):
        """GET 带无 CodingSession 的 conversation_id 返回空列表。"""
        from chat.models import Conversation

        conversation = Conversation.objects.create(space=project, title="空对话")
        url = f"/api/chat/coding-sessions/?conversation_id={conversation.id}"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert len(response.data) == 0

    def test_list_missing_param_returns_400(self, authenticated_client):
        """GET 不带 conversation_id 返回 400。"""
        url = "/api/chat/coding-sessions/"
        response = authenticated_client.get(url)
        assert response.status_code == 400

    def test_detail_returns_session(self, authenticated_client, conversation_with_sessions):
        """GET /api/chat/coding-sessions/{id}/ 返回完整字段。"""
        _, session1, _ = conversation_with_sessions
        url = f"/api/chat/coding-sessions/{session1.id}/"
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.data["id"] == str(session1.id)
        assert response.data["status"] == "completed"
        assert response.data["pr_url"] == "https://github.com/test/repo/pull/1"
        assert "tech_plan" in response.data
        assert "created_at" in response.data

    def test_detail_not_found_returns_404(self, authenticated_client):
        """GET 不存在 id 返回 404。"""
        import uuid

        fake_id = uuid.uuid4()
        url = f"/api/chat/coding-sessions/{fake_id}/"
        response = authenticated_client.get(url)
        assert response.status_code == 404


# ============================================================================
# CodingSession awaiting_confirmation 状态扩展测试 (task)
# ============================================================================


@pytest.mark.django_db
class TestCodingSessionAwaitingConfirmationDefaults:
    """验证新增的 confirmation_step 和 suggested_commit_message 字段默认值。"""

    def test_new_fields_defaults(self, project, repository):
        """新字段 confirmation_step 和 suggested_commit_message 默认为空字符串。"""
        from chat.models import Conversation

        conversation = Conversation.objects.create(space=project, title="默认值测试")
        session = CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 技术方案",
        )
        assert session.confirmation_step == ""
        assert session.suggested_commit_message == ""

    def test_status_choices_include_awaiting_confirmation(self):
        """Status TextChoices 包含 AWAITING_CONFIRMATION。"""
        assert hasattr(CodingSession.Status, "AWAITING_CONFIRMATION")
        assert CodingSession.Status.AWAITING_CONFIRMATION == "awaiting_confirmation"


@pytest.mark.django_db(transaction=True)
class TestCodingSessionAwaitingConfirmationStateMachine:
    """验证 awaiting_confirmation 双向状态转换。"""

    @pytest.fixture
    def running_session(self, project, repository):
        """创建 running 状态的 CodingSession。"""
        from chat.models import Conversation

        conversation = Conversation.objects.create(space=project, title="状态转换测试")
        return CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 方案",
            status=CodingSession.Status.RUNNING,
        )

    @pytest.mark.asyncio
    async def test_amark_awaiting_confirmation_from_running(self, running_session):
        """running -> awaiting_confirmation 转换成功，设置 step 和 suggested_commit_message。"""
        await running_session.amark_awaiting_confirmation(
            step="commit_message",
            suggested_commit_message="feat: 添加用户认证",
        )
        await running_session.arefresh_from_db()
        assert running_session.status == CodingSession.Status.AWAITING_CONFIRMATION
        assert running_session.confirmation_step == "commit_message"
        assert running_session.suggested_commit_message == "feat: 添加用户认证"

    @pytest.mark.asyncio
    async def test_amark_awaiting_confirmation_without_commit_message(self, running_session):
        """running -> awaiting_confirmation 不传 suggested_commit_message 时保留原值。"""
        running_session.suggested_commit_message = "旧消息"
        await running_session.asave(update_fields=["suggested_commit_message"])

        await running_session.amark_awaiting_confirmation(step="pr_review")
        await running_session.arefresh_from_db()
        assert running_session.status == CodingSession.Status.AWAITING_CONFIRMATION
        assert running_session.confirmation_step == "pr_review"
        # 不传 suggested_commit_message 时保留旧值
        assert running_session.suggested_commit_message == "旧消息"

    @pytest.mark.asyncio
    async def test_amark_awaiting_confirmation_from_non_running_raises(self, running_session):
        """非 running 状态调用 amark_awaiting_confirmation 抛出 ValueError。"""
        # draft 状态
        running_session.status = CodingSession.Status.DRAFT
        await running_session.asave(update_fields=["status"])
        with pytest.raises(ValueError, match="只有 running 状态可进入等待确认"):
            await running_session.amark_awaiting_confirmation(step="commit_message")

        # completed 状态
        running_session.status = CodingSession.Status.COMPLETED
        await running_session.asave(update_fields=["status"])
        with pytest.raises(ValueError, match="只有 running 状态可进入等待确认"):
            await running_session.amark_awaiting_confirmation(step="commit_message")

    @pytest.mark.asyncio
    async def test_aresume_running_from_awaiting_confirmation(self, running_session):
        """awaiting_confirmation -> running 转换成功，清空 confirmation_step。"""
        # 先进入 awaiting_confirmation
        await running_session.amark_awaiting_confirmation(
            step="commit_message",
            suggested_commit_message="feat: test",
        )
        await running_session.arefresh_from_db()
        assert running_session.status == CodingSession.Status.AWAITING_CONFIRMATION

        # 恢复 running
        await running_session.aresume_running()
        await running_session.arefresh_from_db()
        assert running_session.status == CodingSession.Status.RUNNING
        assert running_session.confirmation_step == ""

    @pytest.mark.asyncio
    async def test_aresume_running_from_non_awaiting_raises(self, running_session):
        """非 awaiting_confirmation 状态调用 aresume_running 抛出 ValueError。"""
        # running 状态
        with pytest.raises(ValueError, match="只有 awaiting_confirmation 状态可恢复运行"):
            await running_session.aresume_running()

        # draft 状态
        running_session.status = CodingSession.Status.DRAFT
        await running_session.asave(update_fields=["status"])
        with pytest.raises(ValueError, match="只有 awaiting_confirmation 状态可恢复运行"):
            await running_session.aresume_running()


@pytest.mark.django_db
class TestCodingSessionSerializerNewFields:
    """验证 CodingSessionSerializer 包含新字段。"""

    def test_serializer_includes_confirmation_step(self, project, repository):
        """CodingSessionSerializer 序列化结果包含 confirmation_step。"""
        from chat.models import Conversation
        from chat.serializers import CodingSessionSerializer

        conversation = Conversation.objects.create(space=project, title="序列化测试")
        session = CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 方案",
        )
        serializer = CodingSessionSerializer(session)
        assert "confirmation_step" in serializer.data
        assert serializer.data["confirmation_step"] == ""

    def test_serializer_includes_suggested_commit_message(self, project, repository):
        """CodingSessionSerializer 序列化结果包含 suggested_commit_message。"""
        from chat.models import Conversation
        from chat.serializers import CodingSessionSerializer

        conversation = Conversation.objects.create(space=project, title="序列化测试")
        session = CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 方案",
            suggested_commit_message="feat: 实现功能",
        )
        serializer = CodingSessionSerializer(session)
        assert "suggested_commit_message" in serializer.data
        assert serializer.data["suggested_commit_message"] == "feat: 实现功能"


# ============================================================================
# 分支名校验 + metadata 注入测试 (task)
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestCodingSessionConfirmBranchValidation:
    """CodingSessionConfirmView 分支名校验测试。(work item)

    implementation contract 改造后：
      - view 同步路径只对 request body 传入的 branch_name 做校验（前端实际流程）
      - 已落库的 branch_name 由 graph 的 dispatch_coding_node 在后台校验（dispatch_coding_task 内）
      - dispatch 时的 metadata 注入（env_FRIDAY_TASK_BRANCH_STRATEGY / target_branch）
        归 dispatch_coding_task 单元测试覆盖，不再走 view 端到端断言
    """

    @pytest.fixture
    def draft_session_with_branch(self, project, repository, user):
        """创建带有效分支名的 draft CodingSession。"""
        from chat.models import Conversation

        conversation = Conversation.objects.create(
            space=project, title="测试编码", created_by=user
        )
        return CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 实现 user auth",
            branch_name="feat20260409.user-auth",
        )

    def test_confirm_rejects_protected_branch_in_body(
        self, authenticated_client, draft_session_with_branch,
    ):
        """request body 传入 main（保护分支）时 view 应返回 400。(work item)"""
        from unittest.mock import AsyncMock, patch

        mocks = _make_graph_mocks()

        with (
            patch("chat.views.check_runner_online", new_callable=AsyncMock, return_value=True),
            patch("chat.views.build_coding_graph", new=mocks["build_coding_graph"]),
            patch("chat.views.get_checkpointer", new=mocks["get_checkpointer"]),
        ):
            url = f"/api/chat/coding-sessions/{draft_session_with_branch.id}/confirm/"
            response = authenticated_client.post(url, data={"branch_name": "main"}, format="json")

        assert response.status_code == 400
        # graph 不应启动
        mocks["build_coding_graph"].assert_not_called()
        # 错误信息应包含保护分支提示
        detail_str = str(response.data.get("detail", ""))
        assert "保护分支" in detail_str or "main" in detail_str

    def test_confirm_rejects_dotdot_branch_in_body(
        self, authenticated_client, draft_session_with_branch,
    ):
        """request body 传入含 .. 的非法分支名时 view 应返回 400。(work item)"""
        from unittest.mock import AsyncMock, patch

        mocks = _make_graph_mocks()

        with (
            patch("chat.views.check_runner_online", new_callable=AsyncMock, return_value=True),
            patch("chat.views.build_coding_graph", new=mocks["build_coding_graph"]),
            patch("chat.views.get_checkpointer", new=mocks["get_checkpointer"]),
        ):
            url = f"/api/chat/coding-sessions/{draft_session_with_branch.id}/confirm/"
            response = authenticated_client.post(
                url, data={"branch_name": "feat/../../etc/passwd"}, format="json",
            )

        assert response.status_code == 400
        mocks["build_coding_graph"].assert_not_called()

    def test_confirm_accepts_valid_branch_in_body(
        self, authenticated_client, draft_session_with_branch,
    ):
        """request body 传入合法分支名时 view 应返回 200 并启动 graph。(work item)"""
        from unittest.mock import AsyncMock, patch

        from chat.branch_service import BranchValidationResult

        mocks = _make_graph_mocks()

        with (
            patch("chat.views.check_runner_online", new_callable=AsyncMock, return_value=True),
            patch("chat.views.build_coding_graph", new=mocks["build_coding_graph"]),
            patch("chat.views.get_checkpointer", new=mocks["get_checkpointer"]),
            patch(
                "chat.branch_service.validate_branch_name",
                new_callable=AsyncMock,
                return_value=BranchValidationResult(valid=True),
            ),
        ):
            url = f"/api/chat/coding-sessions/{draft_session_with_branch.id}/confirm/"
            response = authenticated_client.post(
                url, data={"branch_name": "feat20260409.user-auth-v2"}, format="json",
            )

        assert response.status_code == 200
        # branch_name 应该被持久化覆盖
        draft_session_with_branch.refresh_from_db()
        assert draft_session_with_branch.branch_name == "feat20260409.user-auth-v2"
        # graph 在请求内直接推进到首个 interrupt
        mocks["graph_compiled"].ainvoke.assert_awaited_once()


# ============================================================================
# unique_active_plan_repo 部分唯一约束测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestUniqueActivePlanRepoConstraint:
    """同 plan + 同 repo 同一时刻最多 1 个 active session。"""

    @pytest.fixture
    def coding_plan(self, db, project):
        """创建 Conversation + CodingPlan（依赖 implementation 落库的 CodingPlan model）。"""
        from chat.models import CodingPlan, Conversation

        conversation = Conversation.objects.create(space=project, title="work item 对话")
        return CodingPlan.objects.create(
            conversation=conversation,
            tech_plan="## work item 方案",
            affected_files=[],
            title="work item 方案",
        )

    @pytest.fixture
    def coding_plan_other(self, db, project):
        """另一个 Conversation + CodingPlan，用于跨 plan 用例。"""
        from chat.models import CodingPlan, Conversation

        conversation = Conversation.objects.create(space=project, title="另一对话")
        return CodingPlan.objects.create(
            conversation=conversation,
            tech_plan="## 另一方案",
            affected_files=[],
            title="另一方案",
        )

    def test_active_session_conflict_raises_integrity_error(
        self, coding_plan, repository
    ) -> None:
        """同 plan + 同 repo 二次插入 active session → IntegrityError。"""
        from django.db import IntegrityError, transaction

        CodingSession.objects.create(
            conversation=coding_plan.conversation,
            coding_plan=coding_plan,
            repository=repository,
            tech_plan="t",
            status=CodingSession.Status.RUNNING,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CodingSession.objects.create(
                    conversation=coding_plan.conversation,
                    coding_plan=coding_plan,
                    repository=repository,
                    tech_plan="t2",
                    status=CodingSession.Status.DRAFT,
                )

    def test_multiple_completed_sessions_allowed(
        self, coding_plan, repository
    ) -> None:
        """同 plan + 同 repo 多个 completed 历史允许共存（重试场景）。"""
        for _ in range(3):
            CodingSession.objects.create(
                conversation=coding_plan.conversation,
                coding_plan=coding_plan,
                repository=repository,
                tech_plan="t",
                status=CodingSession.Status.COMPLETED,
            )
        assert (
            CodingSession.objects.filter(
                coding_plan=coding_plan, repository=repository
            ).count()
            == 3
        )

    def test_active_session_in_different_plan_allowed(
        self, coding_plan, coding_plan_other, repository
    ) -> None:
        """同 repo 跨 plan 同时 active → 允许（约束限定到 coding_plan 维度）。"""
        CodingSession.objects.create(
            conversation=coding_plan.conversation,
            coding_plan=coding_plan,
            repository=repository,
            tech_plan="t",
            status=CodingSession.Status.RUNNING,
        )
        CodingSession.objects.create(
            conversation=coding_plan_other.conversation,
            coding_plan=coding_plan_other,
            repository=repository,
            tech_plan="t2",
            status=CodingSession.Status.RUNNING,
        )
        assert (
            CodingSession.objects.filter(
                repository=repository,
                status=CodingSession.Status.RUNNING,
            ).count()
            == 2
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestCodingSessionCallbackBranchSync:
    """容器 completed 回调中的真实 Git 分支必须同步回 CodingSession。"""

    async def test_complete_callback_updates_session_branch_from_task_result(
        self, project, repository
    ) -> None:
        """避免后续 PR 阶段继续使用已不存在的旧 source_branch。"""
        from agents.models import AgentSession
        from chat.models import CodingPlan, Conversation
        from subagent.api.callbacks import _update_coding_session_on_complete
        from subagent.models import SubAgentSession, TaskResult

        conversation = await Conversation.objects.acreate(
            space=project,
            title="branch sync",
        )
        plan = await CodingPlan.objects.acreate(
            conversation=conversation,
            title="branch sync",
            tech_plan="## plan",
            affected_files=[],
        )
        agent_session = await AgentSession.objects.acreate(
            session_id="agent-branch-sync",
            space=project,
            status=AgentSession.Status.RUNNING,
        )
        sub_session = await SubAgentSession.objects.acreate(
            session_id="coding-branch-sync",
            main_session=agent_session,
            task_type=SubAgentSession.TaskType.CODING,
            status=SubAgentSession.Status.COMPLETED,
            repo_url=repository.git_url,
        )
        coding_session = await CodingSession.objects.acreate(
            conversation=conversation,
            coding_plan=plan,
            repository=repository,
            subagent_session=sub_session,
            tech_plan="## plan",
            status=CodingSession.Status.RUNNING,
            branch_name="feature/expected-task-branch",
        )
        await TaskResult.objects.acreate(
            session=sub_session,
            result_type=TaskResult.ResultType.TEXT,
            text_output="done",
            branch_name="feat/actual-container-branch",
            commit_sha="abc123",
        )

        with patch("orchestration.checkpointer.get_checkpointer") as checkpointer, patch(
            "orchestration.coding_graph.build_coding_graph"
        ) as build_graph:
            graph = AsyncMock()
            build_graph.return_value.compile.return_value = graph
            await _update_coding_session_on_complete(sub_session)

        await coding_session.arefresh_from_db()
        assert coding_session.branch_name == "feat/actual-container-branch"
        checkpointer.assert_called_once()
        graph.ainvoke.assert_awaited_once()
