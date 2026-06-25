"""执行分析 API 测试。

覆盖 work item 到 work item 需求的后端端点验证。
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

if TYPE_CHECKING:
    pass

from agents.models import AgentSession
from subagent.models import SubAgentSession, TokenUsage
from workflows.models.execution import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
    WorkflowExecution,
)
from workflows.models.node import WorkflowNode
from workflows.models.workflow import Workflow


@pytest.fixture
def analytics_workflow(db: None, project: "Space") -> Workflow:  # type: ignore[name-defined]  # noqa: F821
    """创建分析测试用的工作流。"""
    return Workflow.objects.create(name="Analytics Test Workflow", space=project)


@pytest.fixture
def sample_analytics_data(
    db: None,
    analytics_workflow: Workflow,
) -> dict:
    """创建分析测试样本数据。

    Returns:
        包含创建的执行记录和节点信息的字典。
    """
    now = timezone.now()

    # 创建不同类型的节点
    node_coding = WorkflowNode.objects.create(
        workflow=analytics_workflow,
        node_type="ai_coding",
        name="Coding Node",
    )
    node_review = WorkflowNode.objects.create(
        workflow=analytics_workflow,
        node_type="ai_prompt",
        name="Prompt Node",
    )

    # 创建 5 个 WorkflowExecution（3 completed + 1 failed + 1 running）
    exec1 = WorkflowExecution.objects.create(
        workflow=analytics_workflow,
        space=analytics_workflow.space,
        status=ExecutionStatus.COMPLETED,
        trigger_type="webhook",
        started_at=now - timedelta(days=2, hours=1),
        completed_at=now - timedelta(days=2),
    )
    exec2 = WorkflowExecution.objects.create(
        workflow=analytics_workflow,
        space=analytics_workflow.space,
        status=ExecutionStatus.COMPLETED,
        trigger_type="webhook",
        started_at=now - timedelta(days=1, minutes=30),
        completed_at=now - timedelta(days=1),
    )
    exec3 = WorkflowExecution.objects.create(
        workflow=analytics_workflow,
        space=analytics_workflow.space,
        status=ExecutionStatus.COMPLETED,
        trigger_type="manual",
        started_at=now - timedelta(hours=5),
        completed_at=now - timedelta(hours=4, minutes=50),
    )
    exec_failed = WorkflowExecution.objects.create(
        workflow=analytics_workflow,
        space=analytics_workflow.space,
        status=ExecutionStatus.FAILED,
        trigger_type="webhook",
        started_at=now - timedelta(days=1, hours=2),
        completed_at=now - timedelta(days=1, hours=1),
    )
    _exec_running = WorkflowExecution.objects.create(
        workflow=analytics_workflow,
        space=analytics_workflow.space,
        status=ExecutionStatus.RUNNING,
        trigger_type="webhook",
        started_at=now - timedelta(minutes=10),
    )

    # 为每个完成的执行创建 NodeExecution
    completed_execs = [exec1, exec2, exec3]
    for exec_obj in completed_execs:
        ne = NodeExecution.objects.create(
            workflow_execution=exec_obj,
            node=node_coding,
            status=NodeExecutionStatus.COMPLETED,
            started_at=exec_obj.started_at,
            completed_at=exec_obj.completed_at,
        )
        # 创建 SubAgentSession + TokenUsage
        agent_session = AgentSession.objects.create(
            session_id=f"agent-session-{exec_obj.pk}",
            status=AgentSession.Status.COMPLETED,
        )
        session = SubAgentSession.objects.create(
            session_id=f"test-session-{exec_obj.pk}",
            main_session=agent_session,
            repo_url="https://github.com/test/repo.git",
            task_type=SubAgentSession.TaskType.CODING,
            node_execution=ne,
        )
        TokenUsage.objects.create(
            session=session,
            input_tokens=1000,
            output_tokens=500,
            total_cost_usd=Decimal("0.015000"),
            model="claude-sonnet-4-20250514",
        )

    # 为失败执行也创建 NodeExecution
    NodeExecution.objects.create(
        workflow_execution=exec_failed,
        node=node_review,
        status=NodeExecutionStatus.FAILED,
        started_at=exec_failed.started_at,
        completed_at=exec_failed.completed_at,
    )

    return {
        "workflow": analytics_workflow,
        "completed_execs": completed_execs,
        "failed_exec": exec_failed,
        "nodes": {"coding": node_coding, "review": node_review},
    }


# ============================================================================
# Overview Tests (work item)
# ============================================================================


@pytest.mark.django_db
class TestAnalyticsOverview:
    """GET /api/analytics/overview/ 测试。"""

    def test_returns_kpi_data(
        self,
        authenticated_client: APIClient,
        sample_analytics_data: dict,
    ) -> None:
        """验证 overview 端点返回正确的 KPI 数据。"""
        response = authenticated_client.get("/api/analytics/overview/")
        assert response.status_code == 200

        data = response.json()
        assert data["total_executions"] == 5  # 3 completed + 1 failed + 1 running
        assert data["success_rate"] == 75.0  # 3/(3+1) * 100
        assert data["avg_duration_seconds"] is not None
        assert data["avg_duration_seconds"] > 0
        assert data["total_cost_usd"] == pytest.approx(0.045, abs=0.001)  # 3 * 0.015

    def test_date_range_filter(
        self,
        authenticated_client: APIClient,
        sample_analytics_data: dict,
    ) -> None:
        """验证时间范围过滤生效。"""
        # 查询未来日期范围 — 应无数据
        future = (timezone.now() + timedelta(days=10)).date().isoformat()
        response = authenticated_client.get(
            f"/api/analytics/overview/?date_from={future}&date_to={future}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_executions"] == 0
        assert data["success_rate"] == 0.0


# ============================================================================
# Trends Tests (work item)
# ============================================================================


@pytest.mark.django_db
class TestAnalyticsTrends:
    """GET /api/analytics/trends/ 测试。"""

    def test_returns_daily_aggregation(
        self,
        authenticated_client: APIClient,
        sample_analytics_data: dict,
    ) -> None:
        """验证趋势按日聚合返回数据。"""
        response = authenticated_client.get("/api/analytics/trends/")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        # 检查数据结构
        for point in data:
            assert "date" in point
            assert "completed" in point
            assert "failed" in point
            assert "total" in point

        # 验证总数
        total_completed = sum(p["completed"] for p in data)
        total_failed = sum(p["failed"] for p in data)
        assert total_completed == 3
        assert total_failed == 1


# ============================================================================
# Duration Distribution Tests (work item)
# ============================================================================


@pytest.mark.django_db
class TestDurationDistribution:
    """GET /api/analytics/duration-distribution/ 测试。"""

    def test_returns_buckets(
        self,
        authenticated_client: APIClient,
        sample_analytics_data: dict,
    ) -> None:
        """验证时长分布分桶正确。"""
        response = authenticated_client.get("/api/analytics/duration-distribution/")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 7  # 7 个预定义桶

        # 检查数据结构
        for bucket in data:
            assert "bucket_label" in bucket
            assert "count" in bucket
            assert isinstance(bucket["count"], int)

        # 已完成执行应该被分配到某个桶
        total_count = sum(b["count"] for b in data)
        assert total_count == 3  # 3 个 completed 执行


# ============================================================================
# Token Cost Tests (work item)
# ============================================================================


@pytest.mark.django_db
class TestTokenCost:
    """GET /api/analytics/token-cost/ 测试。"""

    def test_returns_daily_aggregation(
        self,
        authenticated_client: APIClient,
        sample_analytics_data: dict,
    ) -> None:
        """验证 token 成本按日聚合。"""
        response = authenticated_client.get("/api/analytics/token-cost/")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)

        # 验证总 token 数
        total_input = sum(p["input_tokens"] for p in data)
        total_output = sum(p["output_tokens"] for p in data)
        assert total_input == 3000  # 3 * 1000
        assert total_output == 1500  # 3 * 500

        # 验证成本
        total_cost = sum(p["total_cost_usd"] for p in data)
        assert total_cost == pytest.approx(0.045, abs=0.001)


# ============================================================================
# Node Performance Tests (work item)
# ============================================================================


@pytest.mark.django_db
class TestNodePerformance:
    """GET /api/analytics/node-performance/ 测试。"""

    def test_returns_node_ranking(
        self,
        authenticated_client: APIClient,
        sample_analytics_data: dict,
    ) -> None:
        """验证节点性能按类型聚合。"""
        response = authenticated_client.get("/api/analytics/node-performance/")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2  # ai_coding + ai_prompt

        # 检查数据结构
        for node in data:
            assert "node_type" in node
            assert "execution_count" in node
            assert "avg_duration_seconds" in node
            assert "success_rate" in node
            assert "total_tokens" in node

        # ai_coding 应排第一（3 次执行 > 1 次）
        assert data[0]["node_type"] == "ai_coding"
        assert data[0]["execution_count"] == 3
        assert data[0]["success_rate"] == 100.0

        # ai_prompt 第二（1 次失败）
        assert data[1]["node_type"] == "ai_prompt"
        assert data[1]["execution_count"] == 1
        assert data[1]["success_rate"] == 0.0


# ============================================================================
# Auth Tests
# ============================================================================


@pytest.mark.django_db
class TestAnalyticsAuth:
    """未认证请求测试。"""

    def test_unauthenticated_returns_401(self, api_client: APIClient) -> None:
        """验证未认证请求返回 401。"""
        endpoints = [
            "/api/analytics/overview/",
            "/api/analytics/trends/",
            "/api/analytics/duration-distribution/",
            "/api/analytics/token-cost/",
            "/api/analytics/node-performance/",
        ]
        for url in endpoints:
            response = api_client.get(url)
            assert response.status_code == 401, f"{url} should return 401 for unauthenticated requests"
