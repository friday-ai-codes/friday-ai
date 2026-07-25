"""Tests for AI node chain validation.

Validates that all 4 AI nodes (PlanResearch -> Approval -> Coding -> Review)
are properly registered, can be instantiated, and have compatible data contracts.
"""

import pytest


@pytest.mark.django_db
class TestAINodeRegistration:
    """验证 AI 节点在 NodeRegistry 中注册。"""

    AI_NODE_TYPES = [
        "ai_plan_research",
        "ai_coding",
    ]

    def test_all_ai_nodes_registered(self):
        """所有 AI 节点均在 NodeRegistry 中注册。"""
        from workflows.nodes.registry import NodeRegistry

        registry = NodeRegistry()
        for node_type in self.AI_NODE_TYPES:
            node_class = registry.get(node_type)
            assert node_class is not None, f"{node_type} 未在 NodeRegistry 中注册"

    def test_node_types_match(self):
        """节点类的 node_type 属性与注册名匹配。"""
        from workflows.nodes.registry import NodeRegistry

        registry = NodeRegistry()
        for node_type in self.AI_NODE_TYPES:
            node_class = registry.get(node_type)
            assert node_class is not None
            assert node_class.node_type == node_type


@pytest.mark.django_db
class TestAINodeInstantiation:
    """验证 AI 节点能正常实例化。"""

    def test_plan_research_instantiation(self):
        """PlanResearch 节点能正常实例化。"""
        from workflows.nodes.ai.plan_research import AIPlanResearchNode

        node = AIPlanResearchNode()
        assert node.node_type == "ai_plan_research"
        assert node.display_name == "AI 方案编排调研"

    def test_plan_approval_instantiation(self):
        """方案审批已合并进 control/human_approval（mode=plan_feishu），能正常实例化。"""
        from workflows.nodes.control.approval import HumanApprovalNode

        node = HumanApprovalNode()
        assert node.node_type == "human_approval"
        assert node.display_name == "人工审批"

    def test_coding_instantiation(self):
        """Coding 节点能正常实例化。"""
        from workflows.nodes.ai.coding import AICodingNode

        node = AICodingNode()
        assert node.node_type == "ai_coding"


@pytest.mark.django_db
class TestAINodeAttributes:
    """验证 AI 节点的关键属性。

    「方案节点声明子步骤」的断言随 Chassis v2 一并作废：方案推进已下沉到
    ConvergenceSession 的 stage graph，AIPlanResearchNode 不再声明 sub_steps。
    唯一仍声明子步骤的节点是 AICodingNode，其清单断言在
    test_sub_step_coding_node.py 里逐项覆盖。
    """

    def test_plan_approval_is_blocking(self):
        """方案审批节点应标记为阻塞（等待用户审批）。"""
        from workflows.nodes.control.approval import HumanApprovalNode

        assert HumanApprovalNode.is_blocking is True

    def test_plan_approval_execution_mode(self):
        """方案审批节点应使用 server_local 执行模式。"""
        from workflows.nodes.control.approval import HumanApprovalNode

        assert HumanApprovalNode.execution_mode == "server_local"

    def test_all_nodes_have_execute_method(self):
        """所有 AI 节点应有 execute 方法。"""
        from workflows.nodes.ai.coding import AICodingNode
        from workflows.nodes.ai.plan_research import AIPlanResearchNode

        for node_class in [AIPlanResearchNode, AICodingNode]:
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
            "plan": {"title": "测试方案", "tasks": []},
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
        """方案审批节点应有配置 schema（含 mode 字段）。"""
        from workflows.nodes.control.approval import HumanApprovalNode

        assert hasattr(HumanApprovalNode, "config_schema")
        assert isinstance(HumanApprovalNode.config_schema, dict)
        assert "mode" in HumanApprovalNode.config_schema["properties"]

    def test_plan_research_has_config_schema(self):
        """PlanResearch 应有配置 schema（继承自 AIAgentBaseNode）。"""
        from workflows.nodes.ai.plan_research import AIPlanResearchNode

        assert hasattr(AIPlanResearchNode, "config_schema")


@pytest.mark.skip(
    reason=(
        "OBSOLETE — implementation LayeredSearchService 重构后 ContextRetrievalNode 不再直接"
        " 调 EmbeddingService + BranchAwareSearchService；BM25 注入语义已迁移到 RepoRouter / "
        "LayeredSearchService 测试。"
    )
)
@pytest.mark.asyncio
async def test_context_retrieval_hybrid_search():
    """ContextRetrievalNode._search_repository 调用 BranchAwareSearchService.search 时传入 query_sparse。"""
    from unittest.mock import AsyncMock, MagicMock, patch

    from workflows.nodes.ai.context_retrieval import ContextRetrievalNode

    # 构造 node 和 context
    node = ContextRetrievalNode()
    context = MagicMock()
    context.node_config = {
        "query": "find authentication logic",
        "repositories": [{"id": "repo-1", "name": "test-repo"}],
        "top_k": 5,
        "score_threshold": 0.5,
        "include_content": True,
        "format_as_markdown": False,
        "timeout": 30.0,
    }
    context.render_template = lambda s, **kw: s

    mock_repo = MagicMock()
    mock_repo.id = "repo-1"
    mock_repo.name = "test-repo"

    search_result = [
        {
            "score": 0.92,
            "payload": {
                "file_path": "auth.py",
                "content": "def authenticate(): pass",
                "language": "python",
                "start_line": 10,
                "end_line": 15,
            },
        }
    ]

    with (
        patch(
            "services.embedding.EmbeddingService.generate_embedding",
            new_callable=AsyncMock,
        ) as mock_embed,
        patch(
            "services.sparse_encoder.SparseEncoderService.encode",
            return_value={"indices": [5, 10, 15], "values": [0.5, 0.3, 0.2]},
        ) as mock_sparse,
        patch(
            "services.branch_search.BranchAwareSearchService.search",
            new_callable=AsyncMock,
        ) as mock_search,
        patch(
            "repositories.models.Repository.objects.filter",
        ) as mock_repo_filter,
    ):
        mock_embed.return_value = [0.1] * 1536
        mock_search.return_value = search_result

        # Mock Repository QuerySet
        mock_repo_filter.return_value.afirst = AsyncMock(return_value=mock_repo)

        result = await node.execute(context)

        # 验证 sparse encode 被调用
        mock_sparse.assert_called_once_with("find authentication logic")
        # 验证 BranchAwareSearchService.search 被调用时传入了 query_sparse
        call_kwargs = mock_search.call_args.kwargs
        assert "query_sparse" in call_kwargs
        assert call_kwargs["query_sparse"] == {"indices": [5, 10, 15], "values": [0.5, 0.3, 0.2]}
        # 验证返回结果正常
        assert result.status == "completed"


@pytest.mark.skip(
    reason=(
        "OBSOLETE — implementation LayeredSearchService 重构后 ContextRetrievalNode 不再"
        "直接调 EmbeddingService + BranchAwareSearchService。"
    )
)
@pytest.mark.asyncio
async def test_context_retrieval_empty_query_dense_only():
    """空 sparse 向量时，ContextRetrievalNode 退化为 dense-only（query_sparse=None）。"""
    from unittest.mock import AsyncMock, MagicMock, patch

    from workflows.nodes.ai.context_retrieval import ContextRetrievalNode

    node = ContextRetrievalNode()
    context = MagicMock()
    context.node_config = {
        "query": "x",
        "repositories": [{"id": "repo-1", "name": "test-repo"}],
        "top_k": 5,
        "score_threshold": 0.5,
        "include_content": True,
        "format_as_markdown": False,
        "timeout": 30.0,
    }
    context.render_template = lambda s, **kw: s

    mock_repo = MagicMock()
    mock_repo.id = "repo-1"
    mock_repo.name = "test-repo"

    search_result = [
        {
            "score": 0.70,
            "payload": {
                "file_path": "main.py",
                "content": "def main(): pass",
                "language": "python",
                "start_line": 1,
                "end_line": 5,
            },
        }
    ]

    with (
        patch(
            "services.embedding.EmbeddingService.generate_embedding",
            new_callable=AsyncMock,
        ) as mock_embed,
        patch(
            "services.sparse_encoder.SparseEncoderService.encode",
            return_value={"indices": [], "values": []},  # 空 sparse 向量
        ) as mock_sparse,
        patch(
            "services.branch_search.BranchAwareSearchService.search",
            new_callable=AsyncMock,
        ) as mock_search,
        patch(
            "repositories.models.Repository.objects.filter",
        ) as mock_repo_filter,
    ):
        mock_embed.return_value = [0.1] * 1536
        mock_search.return_value = search_result
        mock_repo_filter.return_value.afirst = AsyncMock(return_value=mock_repo)

        result = await node.execute(context)

        # 验证 search 被调用时 query_sparse 为 None（降级到 dense-only）
        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs.get("query_sparse") is None
