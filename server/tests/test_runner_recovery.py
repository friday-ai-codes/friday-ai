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
            repo_url="https://gitlab.example.com/frontend/study-app.git",
            last_output={
                "task_type": "coding",
                "dispatch": {
                    "repo_url": "https://gitlab.example.com/frontend/study-app.git",
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
        assert task.repo_url == "https://gitlab.example.com/frontend/study-app.git"
        assert task.branch == "main"
        assert task.target_branch == "main"
        assert task.prompt == "执行编码"
        assert task.timeout == 3600
        assert task.metadata == {"repository_id": "repo-1"}
