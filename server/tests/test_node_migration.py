"""Phase 迁移验证测试。
验证 AICodingNode 和 AgentLoop 工具从轮询模式迁移到回调驱动模式。
"""
import pytest
from workflows.nodes.ai.coding import AICodingNode
class TestCallbackDrivenMigration:
 """回调驱动迁移验证测试。"""
 def test_schedule_workflow_resume_available(self):
 """验证 _schedule_workflow_resume 函数可导入。"""
 from subagent.api.callbacks import _schedule_workflow_resume
 assert callable(_schedule_workflow_resume)
 def test_schedule_agent_loop_resume_available(self):
 """验证 _schedule_agent_loop_resume 函数可导入。"""
 from subagent.api.callbacks import _schedule_agent_loop_resume
 assert callable(_schedule_agent_loop_resume)
 def test_subagent_session_duration_ms(self):
 """验证 SubAgentSession.duration_ms 属性存在。"""
 from subagent.models import SubAgentSession
 assert hasattr(SubAgentSession, 'duration_ms')
 def test_subagent_session_resource_fields(self):
 """验证 SubAgentSession 资源消耗字段存在。"""
 from subagent.models import SubAgentSession
 assert hasattr(SubAgentSession, 'cpu_usage_percent')
 assert hasattr(SubAgentSession, 'memory_usage_mb')
class TestAICodingNodeBehavior:
 """AICodingNode 行为验证测试。"""
 def test_ai_coding_node_is_blocking(self):
 """验证 AICodingNode 是阻塞节点。"""
 assert AICodingNode.is_blocking is True
 def test_ai_coding_node_type(self):
 """验证 AICodingNode 节点类型。"""
 assert AICodingNode.node_type == "ai_coding"
 def test_ai_coding_node_has_resume_logic(self):
 """验证 AICodingNode 有恢复逻辑。"""
 node = AICodingNode
 assert hasattr(node, '_resume_after_containers')
 assert callable(node._resume_after_containers)
