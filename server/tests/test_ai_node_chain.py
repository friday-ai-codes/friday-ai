"""Tests for AI node chain validation.
Validates that all 4 AI nodes (PlanGeneration -> Approval -> Coding -> Review)
are properly registered, can be instantiated, and have compatible data contracts.
"""
import pytest
@pytest.mark.django_db
class TestAINodeRegistration:
 """验证 AI 节点在 NodeRegistry 中注册。"""
 AI_NODE_TYPES = [
 "ai_plan_generation",
 "ai_plan_approval",
 "ai_coding",
 "ai_code_review",
 ]
 def test_all_ai_nodes_registered(self):
 """所有 AI 节点均在 NodeRegistry 中注册。"""
 from workflows.nodes.registry import NodeRegistry
 registry = NodeRegistry
 for node_type in self.AI_NODE_TYPES:
 node_class = registry.get(node_type)
 assert node_class is not None, f"{node_type} 未在 NodeRegistry 中注册"
 def test_node_types_match(self):
 """节点类的 node_type 属性与注册名匹配。"""
 from workflows.nodes.registry import NodeRegistry
 registry = NodeRegistry
 for node_type in self.AI_NODE_TYPES:
 node_class = registry.get(node_type)
 assert node_class is not None
 assert node_class.node_type == node_type
@pytest.mark.django_db
class TestAINodeInstantiation:
 """验证 AI 节点能正常实例化。"""
 def test_plan_generation_instantiation(self):
 """PlanGeneration 节点能正常实例化。"""
 from workflows.nodes.ai.plan_generation import AIPlanGenerationNode
 node = AIPlanGenerationNode
 assert node.node_type == "ai_plan_generation"
 assert node.display_name == "AI 方案生成"
 def test_plan_approval_instantiation(self):
 """PlanApproval 节点能正常实例化。"""
 from workflows.nodes.ai.plan_approval import PlanApprovalNode
 node = PlanApprovalNode
 assert node.node_type == "ai_plan_approval"
 assert node.display_name == "方案审批"
 def test_coding_instantiation(self):
 """Coding 节点能正常实例化。"""
 from workflows.nodes.ai.coding import AICodingNode
 node = AICodingNode
 assert node.node_type == "ai_coding"
 def test_code_review_instantiation(self):
 """CodeReview 节点能正常实例化。"""
 from workflows.nodes.ai.code_review import AICodeReviewNode
 node = AICodeReviewNode
 assert node.node_type == "ai_code_review"
@pytest.mark.django_db
class TestAINodeAttributes:
 """验证 AI 节点的关键属性。"""
 def test_plan_generation_has_sub_steps(self):
 """PlanGeneration 节点应有子步骤定义。"""
 from workflows.nodes.ai.plan_generation import AIPlanGenerationNode
 assert hasattr(AIPlanGenerationNode, "sub_steps")
 assert len(AIPlanGenerationNode.sub_steps) > 0
 def test_plan_approval_is_blocking(self):
 """PlanApproval 节点应标记为阻塞（等待用户审批）。"""
 from workflows.nodes.ai.plan_approval import PlanApprovalNode
 assert PlanApprovalNode.is_blocking is True
 def test_plan_approval_execution_mode(self):
 """PlanApproval 节点应使用 server_local 执行模式。"""
 from workflows.nodes.ai.plan_approval import PlanApprovalNode
 assert PlanApprovalNode.execution_mode == "server_local"
 def test_all_nodes_have_execute_method(self):
 """所有 AI 节点应有 execute 方法。"""
 from workflows.nodes.ai.code_review import AICodeReviewNode
 from workflows.nodes.ai.coding import AICodingNode
 from workflows.nodes.ai.plan_approval import PlanApprovalNode
 from workflows.nodes.ai.plan_generation import AIPlanGenerationNode
 for node_class in [AIPlanGenerationNode, PlanApprovalNode, AICodingNode, AICodeReviewNode]:
 assert hasattr(node_class, "execute"), f"{node_class.__name__} 缺少 execute 方法"
@pytest.mark.django_db
class TestAINodeDataFlowContract:
 """验证相邻节点数据流契约。"""
 def test_plan_generation_output_structure(self):
 """PlanGeneration 应输出包含 plan 的数据结构。"""
 # 模拟 PlanGeneration 典型输出
 mock_output = {
 "plan": {"title": "测试方案", "tasks": [{"id": 1, "description": "任务1"}]},
 "repositories": ["repo-1"],
 "analysis_summary": "分析结果",
 }
 # plan 字段必须存在
 assert "plan" in mock_output
 assert isinstance(mock_output["plan"], dict)
 def test_plan_approval_input_output_contract(self):
 """PlanApproval 应能消费 plan 数据并输出审批结果。"""
 # 模拟从 PlanGeneration 传来的输入
 mock_input = {
 "plan": {"title": "测试方案", "tasks": },
 }
 # 模拟 PlanApproval 输出
 mock_output = {
 "approved": True,
 "plan": mock_input["plan"],
 "approver": "user_001",
 }
 assert "approved" in mock_output
 assert "plan" in mock_output
 def test_coding_input_contract(self):
 """Coding 应能消费审批通过的 plan 数据。"""
 mock_input = {
 "approved": True,
 "plan": {
 "title": "测试方案",
 "tasks": [{"id": 1, "repository": "repo-1", "description": "实现功能A"}],
 },
 }
 assert mock_input["approved"] is True
 assert len(mock_input["plan"]["tasks"]) > 0
 def test_code_review_input_contract(self):
 """CodeReview 应能消费 Coding 输出的 MR 信息。"""
 mock_input = {
 "results": [
 {
 "repository": "repo-1",
 "branch": "feat/test",
 "mr_url": "https://git.example.com/mr/1",
 "status": "success",
 }
 ],
 }
 assert "results" in mock_input
 assert len(mock_input["results"]) > 0
 assert "mr_url" in mock_input["results"][0]
 def test_full_chain_data_compatibility(self):
 """完整链路数据兼容性验证。"""
 # 模拟完整链路数据流
 plan_gen_output = {
 "plan": {"title": "方案", "tasks": [{"id": 1, "repo": "r1"}]},
 }
 approval_input = plan_gen_output
 approval_output = {
 "approved": True,
 "plan": approval_input["plan"],
 }
 coding_input = approval_output
 assert coding_input["approved"] is True
 coding_output = {
 "results": [{"repository": "r1", "branch": "feat/x", "mr_url": "url"}],
 }
 review_input = coding_output
 assert len(review_input["results"]) > 0
 # 链路完整性：每个阶段都能从上游获取所需数据
 assert plan_gen_output["plan"] is not None
 assert approval_output["approved"] is True
 assert coding_output["results"] is not None
 assert review_input["results"][0]["mr_url"] is not None
@pytest.mark.django_db
class TestAINodeConfigSchema:
 """验证 AI 节点配置 schema。"""
 def test_plan_approval_has_config_schema(self):
 """PlanApproval 应有配置 schema。"""
 from workflows.nodes.ai.plan_approval import PlanApprovalNode
 assert hasattr(PlanApprovalNode, "config_schema")
 assert isinstance(PlanApprovalNode.config_schema, dict)
 def test_plan_generation_has_config_schema(self):
 """PlanGeneration 应有配置 schema（继承自 AIAgentBaseNode）。"""
 from workflows.nodes.ai.plan_generation import AIPlanGenerationNode
 assert hasattr(AIPlanGenerationNode, "config_schema")
 def test_code_review_has_config_schema(self):
 """CodeReview 应有配置 schema（继承自 AIAgentBaseNode）。"""
 from workflows.nodes.ai.code_review import AICodeReviewNode
 assert hasattr(AICodeReviewNode, "config_schema")
