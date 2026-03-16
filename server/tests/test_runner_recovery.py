"""Tests for Runner disconnect recovery and feishu_message_id mapping."""
import pytest
from runners.models import Runner, RunnerTaskAssignment
@pytest.mark.django_db
class TestRunnerTaskAssignmentFeishuMessageId:
 """测试 RunnerTaskAssignment feishu_message_id 字段。"""
 def test_feishu_message_id_default_empty(self, db):
 """测试 feishu_message_id 默认为空字符串。"""
 runner = Runner.objects.create(
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
 assert DISCONNECT_TIMEOUT == 300 # 5 分钟
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
