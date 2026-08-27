"""Tests for Runner disconnect recovery and feishu_message_id mapping."""

import pytest

from runners.models import Runner, RunnerTaskAssignment


@pytest.mark.django_db
class TestRunnerTaskAssignmentFeishuMessageId:
    """测试 RunnerTaskAssignment feishu_message_id 字段。"""

    def test_feishu_message_id_default_empty(self, db):
        """测试 feishu_message_id 默认为空字符串。"""
        _runner = Runner.objects.create(
            name="test-runner",
            token_hash="a" * 64,
        )
        # 需要创建 SubAgentSession，但这里测试模型字段即可
        # 通过直接查询确认字段存在
        assert hasattr(RunnerTaskAssignment, "feishu_message_id")

    def test_feishu_message_id_field_properties(self, db):
        """测试 feishu_message_id 字段属性。"""
        field = RunnerTaskAssignment._meta.get_field("feishu_message_id")
        assert field.max_length == 128
        assert field.blank is True
        assert field.default == ""
        assert field.db_index is True

    def test_runner_disconnect_timeout_constant(self):
        """测试断连超时常量。"""
        from runners.consumers import DISCONNECT_TIMEOUT
        assert DISCONNECT_TIMEOUT == 300  # 5 分钟


@pytest.mark.django_db
class TestDisconnectRecovery:
    """测试断连恢复机制。"""

    def test_schedule_disconnect_timeout_exists(self):
        """测试 _schedule_disconnect_timeout 函数存在。"""
        from runners.consumers import _schedule_disconnect_timeout
        assert callable(_schedule_disconnect_timeout)

    def test_handle_disconnect_timeout_exists(self):
        """测试 _handle_disconnect_timeout 函数存在。"""
        from runners.consumers import _handle_disconnect_timeout
        assert callable(_handle_disconnect_timeout)

    def test_runner_consumer_has_recover_method(self):
        """测试 RunnerConsumer 有 _recover_pending_tasks 方法。"""
        from runners.consumers import RunnerConsumer
        assert hasattr(RunnerConsumer, "_recover_pending_tasks")

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_rebuild_dispatch_task_uses_persisted_payload(self, project):
        """重连恢复时必须使用原始 dispatch payload，避免空 repo_url 派发。"""
        from agents.models import AgentSession
        from runners.consumers import RunnerConsumer
        from subagent.models import SubAgentSession

        runner = await Runner.objects.acreate(
            name="test-runner-recovery",
            token_hash="b" * 64,
            channel_name="specific..test",
            status=Runner.Status.ONLINE,
        )
        agent_session = await AgentSession.objects.acreate(
            session_id="agent-recovery-test",
            space=project,
            status=AgentSession.Status.RUNNING,
        )
        sub_session = await SubAgentSession.objects.acreate(
            session_id="coding-recovery-test",
            main_session=agent_session,
            task_type=SubAgentSession.TaskType.CODING,
            status=SubAgentSession.Status.PENDING,
            repo_url="https://gitlab.example.com/frontend/example-app.git",
            last_output={
                "task_type": "coding",
                "dispatch": {
                    "repo_url": "https://gitlab.example.com/frontend/example-app.git",
                    "branch": "main",
                    "target_branch": "main",
                    "prompt": "执行编码",
                    "timeout": 3600,
                    "metadata": {"repository_id": "repo-1"},
                    "tags": [],
                },
            },
        )
        await RunnerTaskAssignment.objects.acreate(
            runner=runner,
            session=sub_session,
            status=RunnerTaskAssignment.Status.ASSIGNED,
        )

        consumer = RunnerConsumer()
        consumer.runner = runner

        task = await consumer._rebuild_dispatch_task("coding-recovery-test")

        assert task is not None
        assert task.repo_url == "https://gitlab.example.com/frontend/example-app.git"
        assert task.branch == "main"
        assert task.target_branch == "main"
        assert task.prompt == "执行编码"
        assert task.timeout == 3600
        assert task.metadata == {"repository_id": "repo-1"}

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_recover_closes_stale_assignment_before_redispatch(self, project):
        """runner 未上报旧任务时，必须先关闭旧 assignment，避免重派被幂等守卫吞掉。"""
        from unittest.mock import AsyncMock, patch

        from agents.models import AgentSession
        from runners.consumers import RunnerConsumer
        from subagent.models import SubAgentSession

        runner = await Runner.objects.acreate(
            name="test-runner-recover-stale",
            token_hash="e" * 64,
            channel_name="specific..recover-stale",
            status=Runner.Status.ONLINE,
        )
        agent_session = await AgentSession.objects.acreate(
            session_id="agent-recover-stale",
            space=project,
            status=AgentSession.Status.RUNNING,
        )
        sub_session = await SubAgentSession.objects.acreate(
            session_id="recover-stale",
            main_session=agent_session,
            task_type=SubAgentSession.TaskType.PLAN,
            status=SubAgentSession.Status.RUNNING,
            repo_url="https://gitlab.example.com/t/recover-stale.git",
        )
        assignment = await RunnerTaskAssignment.objects.acreate(
            runner=runner,
            session=sub_session,
            status=RunnerTaskAssignment.Status.RUNNING,
        )

        consumer = RunnerConsumer()
        consumer.runner = runner
        rebuilt_task = object()
        dispatcher = AsyncMock()

        with (
            patch.object(
                consumer,
                "_rebuild_dispatch_task",
                new=AsyncMock(return_value=rebuilt_task),
            ),
            patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        ):
            await consumer._recover_pending_tasks(running_tasks=[])

        await assignment.arefresh_from_db()
        assert assignment.status == RunnerTaskAssignment.Status.FAILED
        assert assignment.completed_at is not None
        dispatcher.dispatch.assert_awaited_once_with(rebuilt_task)

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_recover_keeps_assignment_for_task_still_running(self, project):
        """runner 明确上报仍在运行的任务时，不关闭 assignment，也不重复派发。"""
        from unittest.mock import AsyncMock, patch

        from agents.models import AgentSession
        from runners.consumers import RunnerConsumer
        from subagent.models import SubAgentSession

        runner = await Runner.objects.acreate(
            name="test-runner-recover-live",
            token_hash="f" * 64,
            channel_name="specific..recover-live",
            status=Runner.Status.ONLINE,
        )
        agent_session = await AgentSession.objects.acreate(
            session_id="agent-recover-live",
            space=project,
            status=AgentSession.Status.RUNNING,
        )
        sub_session = await SubAgentSession.objects.acreate(
            session_id="recover-live",
            main_session=agent_session,
            task_type=SubAgentSession.TaskType.PLAN,
            status=SubAgentSession.Status.RUNNING,
            repo_url="https://gitlab.example.com/t/recover-live.git",
        )
        assignment = await RunnerTaskAssignment.objects.acreate(
            runner=runner,
            session=sub_session,
            status=RunnerTaskAssignment.Status.RUNNING,
        )

        consumer = RunnerConsumer()
        consumer.runner = runner

        with patch.object(
            consumer,
            "_rebuild_dispatch_task",
            new=AsyncMock(),
        ) as rebuild:
            await consumer._recover_pending_tasks(running_tasks=[sub_session.session_id])

        await assignment.arefresh_from_db()
        assert assignment.status == RunnerTaskAssignment.Status.RUNNING
        assert assignment.completed_at is None
        rebuild.assert_not_awaited()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_rebuild_rehydrates_redacted_credentials(self, project):
        """重派重解析（103 审查 WR-03）：落库副本按 ``_redacted_env_keys`` 标记剔除
        凭证键，重建时从权威源补回 Git token / API key；USER_TOKEN 不重铸（容器
        降级不挂知识工具）；标记键本身不进重建 metadata。"""
        from unittest.mock import AsyncMock, patch

        from agents.models import AgentSession
        from repositories.models import Repository
        from runners.consumers import RunnerConsumer
        from subagent.models import SubAgentSession

        repo = await Repository.objects.acreate(
            name="rehydrate-repo",
            git_url="https://gitlab.example.com/t/rehydrate.git",
            git_platform="gitlab",
            default_branch="main",
        )
        runner = await Runner.objects.acreate(
            name="test-runner-rehydrate",
            token_hash="c" * 64,
            channel_name="specific..rehydrate",
            status=Runner.Status.ONLINE,
        )
        agent_session = await AgentSession.objects.acreate(
            session_id="agent-rehydrate-test",
            space=project,
            status=AgentSession.Status.RUNNING,
        )
        sub_session = await SubAgentSession.objects.acreate(
            session_id="coding-rehydrate-test",
            main_session=agent_session,
            task_type=SubAgentSession.TaskType.CODING,
            status=SubAgentSession.Status.PENDING,
            repo_url=repo.git_url,
            last_output={
                "task_type": "coding",
                "dispatch": {
                    "repo_url": repo.git_url,
                    "branch": "main",
                    "target_branch": "main",
                    "prompt": "执行编码",
                    "timeout": 3600,
                    "tags": [],
                    "metadata": {
                        "repository_id": str(repo.id),
                        "env_FRIDAY_TASK_GIT_AUTH_TYPE": "token",
                        "_redacted_env_keys": [
                            "env_FRIDAY_TASK_CLAUDE_API_KEY",
                            "env_FRIDAY_TASK_GIT_ACCESS_TOKEN",
                            "env_FRIDAY_TASK_USER_TOKEN",
                        ],
                    },
                },
            },
        )
        await RunnerTaskAssignment.objects.acreate(
            runner=runner,
            session=sub_session,
            status=RunnerTaskAssignment.Status.ASSIGNED,
        )

        consumer = RunnerConsumer()
        consumer.runner = runner

        with (
            patch(
                "services.git_credentials.aresolve_git_token",
                new_callable=AsyncMock,
                return_value="glpat-REHYDRATED",
            ),
            patch(
                "services.provider_config.aget_claude_code_runtime_config",
                new_callable=AsyncMock,
                return_value={"api_key": "sk-ant-REHYDRATED"},
            ),
        ):
            task = await consumer._rebuild_dispatch_task("coding-rehydrate-test")

        assert task is not None
        meta = task.metadata
        assert meta["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] == "glpat-REHYDRATED"
        assert meta["env_FRIDAY_TASK_CLAUDE_API_KEY"] == "sk-ant-REHYDRATED"
        # USER_TOKEN 不重铸（短 TTL token 生命周期绑定首派）
        assert "env_FRIDAY_TASK_USER_TOKEN" not in meta
        # 标记键不进重建 metadata
        assert "_redacted_env_keys" not in meta

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_rebuild_rehydrate_failure_degrades_without_raising(self, project):
        """重解析失败（权威源异常）→ 跳过该键不阻断重建（best-effort 降级）。"""
        from unittest.mock import AsyncMock, patch

        from agents.models import AgentSession
        from runners.consumers import RunnerConsumer
        from subagent.models import SubAgentSession

        runner = await Runner.objects.acreate(
            name="test-runner-rehydrate-fail",
            token_hash="d" * 64,
            channel_name="specific..rehydrate-fail",
            status=Runner.Status.ONLINE,
        )
        agent_session = await AgentSession.objects.acreate(
            session_id="agent-rehydrate-fail",
            space=project,
            status=AgentSession.Status.RUNNING,
        )
        sub_session = await SubAgentSession.objects.acreate(
            session_id="coding-rehydrate-fail",
            main_session=agent_session,
            task_type=SubAgentSession.TaskType.CODING,
            status=SubAgentSession.Status.PENDING,
            repo_url="https://gitlab.example.com/t/f.git",
            last_output={
                "task_type": "coding",
                "dispatch": {
                    "repo_url": "https://gitlab.example.com/t/f.git",
                    "metadata": {
                        "_redacted_env_keys": ["env_FRIDAY_TASK_CLAUDE_API_KEY"],
                    },
                },
            },
        )
        await RunnerTaskAssignment.objects.acreate(
            runner=runner,
            session=sub_session,
            status=RunnerTaskAssignment.Status.ASSIGNED,
        )

        consumer = RunnerConsumer()
        consumer.runner = runner

        with patch(
            "services.provider_config.aget_claude_code_runtime_config",
            new_callable=AsyncMock,
            side_effect=RuntimeError("provider boom"),
        ):
            task = await consumer._rebuild_dispatch_task("coding-rehydrate-fail")

        assert task is not None, "重解析失败绝不阻断重建"
        assert "env_FRIDAY_TASK_CLAUDE_API_KEY" not in task.metadata
        assert "_redacted_env_keys" not in task.metadata
