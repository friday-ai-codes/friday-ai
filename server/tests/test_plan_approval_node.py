"""HumanApprovalNode(mode=plan_feishu) 单元测试。

测试方案审批模式的独立执行行为：happy path（waiting_approval）、兜底输入、错误处理、
文档生成失败的非阻塞韧性（C2 合并后由 control/approval.py 的 HumanApprovalNode 承载）。
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.e2e.fixtures.technical_plans import VALID_TECHNICAL_PLAN
from workflows.nodes.base import ExecutionContext, NodeResult
from workflows.nodes.control.approval import HumanApprovalNode


def _make_context(
    *,
    input_data: dict[str, Any] | None = None,
    chat_id: str = "",
    extra_config: dict[str, Any] | None = None,
) -> ExecutionContext:
    """Build a minimal ExecutionContext for plan_feishu 审批 tests.

    Constructs the mock workflow_execution -> workflow -> project chain
    required by HumanApprovalNode._execute_plan_feishu().
    """
    config: dict[str, Any] = {
        "mode": "plan_feishu",
        "chat_id": chat_id,
    }
    if extra_config:
        config.update(extra_config)

    # Build project -> workflow -> workflow_execution mock chain
    mock_project = MagicMock()
    mock_project.id = 1
    mock_project.feishu_doc_folder_token = "folder_token_123"

    mock_workflow = MagicMock()
    mock_workflow.space = mock_project

    mock_execution = MagicMock()
    mock_execution.workflow = mock_workflow
    mock_execution.triggered_by = MagicMock(id=1)

    ctx = ExecutionContext(
        execution_id="00000000-0000-0000-0000-000000000002",
        node_id="00000000-0000-0000-0000-000000000012",
        node_config=config,
        input_data=input_data or {},
        workflow_context={},
        previous_outputs={},
        workflow_execution=mock_execution,
    )
    return ctx


# Plan data with required fields for approval
PLAN_WITH_DETAILS: dict[str, Any] = {
    "title": "用户认证模块重构",
    "summary": "重构现有用户认证模块，添加 JWT 刷新令牌支持",
    "execution_plan": VALID_TECHNICAL_PLAN["execution_plan"],
}


@pytest.mark.django_db(transaction=True)
class TestPlanApprovalNode:
    """Unit tests for HumanApprovalNode(mode=plan_feishu) independent execution."""

    @pytest.mark.asyncio
    @patch(
        "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project"
    )
    async def test_execute_happy_path_with_plan(
        self,
        mock_create_doc_client: MagicMock,
    ) -> None:
        """Input contains plan dict -> returns waiting_approval with plan + pending status."""
        # Arrange
        mock_doc_client = MagicMock()
        mock_doc_client.create_document = AsyncMock(
            return_value={"url": "https://feishu.cn/docs/abc123", "document_id": "doc1"}
        )
        mock_doc_client.app_id = "app_id"
        mock_doc_client.app_secret = "app_secret"
        mock_create_doc_client.return_value = mock_doc_client

        ctx = _make_context(
            input_data={
                "plan": PLAN_WITH_DETAILS,
                "final_answer": "方案已生成",
                "usage": {"input_tokens": 1000, "output_tokens": 500},
            },
        )
        node = HumanApprovalNode()

        # Act
        result: NodeResult = await node.execute(ctx)

        # Assert
        assert result.status == "waiting_approval"
        assert result.output["plan"] == PLAN_WITH_DETAILS
        assert result.output["approval_status"] == "pending"
        assert "final_answer" in result.output

    @pytest.mark.asyncio
    @patch(
        "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project"
    )
    async def test_execute_fallback_input_data(
        self,
        mock_create_doc_client: MagicMock,
    ) -> None:
        """get_input('plan') returns None, but input_data has 'summary' -> fallback works."""
        mock_doc_client = MagicMock()
        mock_doc_client.create_document = AsyncMock(
            return_value={"url": "https://feishu.cn/docs/xyz", "document_id": "doc2"}
        )
        mock_doc_client.app_id = "app_id"
        mock_doc_client.app_secret = "app_secret"
        mock_create_doc_client.return_value = mock_doc_client

        # input_data has 'summary' at top level but no 'plan' key
        fallback_data = {
            "title": "Fallback 方案",
            "summary": "Fallback 方案摘要",
            "execution_plan": [],
        }
        ctx = _make_context(input_data=fallback_data)
        node = HumanApprovalNode()

        result: NodeResult = await node.execute(ctx)

        assert result.status == "waiting_approval"
        # The fallback uses the entire input_data as plan_data
        assert result.output["plan"]["summary"] == "Fallback 方案摘要"

    @pytest.mark.asyncio
    async def test_execute_missing_plan(self) -> None:
        """No plan and input_data has no 'summary' -> returns failed."""
        ctx = _make_context(input_data={"some_other_key": "value"})
        node = HumanApprovalNode()

        result: NodeResult = await node.execute(ctx)

        assert result.status == "failed"
        assert result.error is not None
        assert "技术方案数据" in result.error

    @pytest.mark.asyncio
    async def test_execute_invalid_plan_type(self) -> None:
        """Plan is a string instead of dict -> returns failed with format error."""
        ctx = _make_context(
            input_data={"plan": "This is not a dict, it's a string"},
        )
        node = HumanApprovalNode()

        result: NodeResult = await node.execute(ctx)

        assert result.status == "failed"
        assert result.error is not None
        assert "格式错误" in result.error

    @pytest.mark.asyncio
    @patch(
        "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project"
    )
    async def test_document_creation_failure_non_blocking(
        self,
        mock_create_doc_client: MagicMock,
    ) -> None:
        """create_document raises exception -> node still returns waiting_approval."""
        mock_doc_client = MagicMock()
        mock_doc_client.create_document = AsyncMock(
            side_effect=Exception("Feishu API error: rate limited")
        )
        mock_doc_client.app_id = "app_id"
        mock_doc_client.app_secret = "app_secret"
        mock_create_doc_client.return_value = mock_doc_client

        ctx = _make_context(
            input_data={"plan": PLAN_WITH_DETAILS},
        )
        node = HumanApprovalNode()

        result: NodeResult = await node.execute(ctx)

        # Document creation failure is non-blocking
        assert result.status == "waiting_approval"
        assert result.output["plan"] == PLAN_WITH_DETAILS
        # document_url should be empty string when creation fails
        assert result.output["document_url"] == ""

    @pytest.mark.asyncio
    @patch(
        "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project"
    )
    @patch("workflows.models.WorkflowExecution.objects")
    async def test_output_contains_document_url(
        self,
        mock_we_objects: MagicMock,
        mock_create_doc_client: MagicMock,
    ) -> None:
        """create_document returns url -> output.document_url has value."""
        # 模拟 WorkflowExecution DB 查询返回包含 project 的 mock
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.feishu_doc_folder_token = "folder_token_123"
        mock_workflow = MagicMock()
        mock_workflow.space = mock_project
        mock_we_instance = MagicMock()
        mock_we_instance.workflow = mock_workflow
        mock_we_objects.select_related.return_value.aget = AsyncMock(
            return_value=mock_we_instance
        )

        expected_url = "https://feishu.cn/docs/plan-doc-456"
        mock_doc_client = MagicMock()
        mock_doc_client.create_document = AsyncMock(
            return_value={"url": expected_url, "document_id": "doc3"}
        )
        mock_doc_client.app_id = "app_id"
        mock_doc_client.app_secret = "app_secret"
        mock_create_doc_client.return_value = mock_doc_client

        ctx = _make_context(
            input_data={"plan": PLAN_WITH_DETAILS},
        )
        node = HumanApprovalNode()

        result: NodeResult = await node.execute(ctx)

        assert result.status == "waiting_approval"
        assert result.output["document_url"] == expected_url


@pytest.mark.django_db(transaction=True)
class TestHumanApprovalGenericMode:
    """通用审批模式（mode=generic / 缺省）的 waiting_approval 行为。"""

    @pytest.mark.asyncio
    async def test_generic_mode_returns_waiting_approval(self) -> None:
        """mode=generic：不碰飞书，直接进入 waiting_approval（审批请求带 title/display_data）。"""
        ctx = ExecutionContext(
            execution_id="00000000-0000-0000-0000-000000000002",
            node_id="00000000-0000-0000-0000-000000000012",
            node_config={
                "mode": "generic",
                "title": "请确认上线",
                "show_data": ["version"],
            },
            input_data={"version": "v1.2.3", "ignored": "x"},
            workflow_context={},
            previous_outputs={},
            workflow_execution=None,
        )
        node = HumanApprovalNode()

        result: NodeResult = await node.execute(ctx)

        assert result.status == "waiting_approval"
        assert result.output["title"] == "请确认上线"
        assert result.output["display_data"] == {"version": "v1.2.3"}
        assert "plan" not in result.output

    @pytest.mark.asyncio
    async def test_default_mode_is_generic(self) -> None:
        """缺省 mode 走通用审批（不要求 plan 输入即可进入 waiting_approval）。"""
        ctx = ExecutionContext(
            execution_id="00000000-0000-0000-0000-000000000002",
            node_id="00000000-0000-0000-0000-000000000012",
            node_config={},
            input_data={},
            workflow_context={},
            previous_outputs={},
            workflow_execution=None,
        )
        node = HumanApprovalNode()

        result: NodeResult = await node.execute(ctx)

        assert result.status == "waiting_approval"
