"""工作流测试共享 fixtures。

提供 Workflow、WorkflowNode、WorkflowExecution、NodeExecution、
SubAgentSession、ActionLog、TokenUsage 等测试数据工厂。
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from agents.models import AgentSession
from projects.models import Project
from subagent.models import ActionLog, SubAgentSession, TokenUsage
from workflows.models import (
    NodeExecution,
    Workflow,
    WorkflowExecution,
    WorkflowNode,
)


@pytest.fixture
def obs_project(db):
    """可观测性测试用项目。"""
    return Project.objects.create(
        name="Obs Test Project",
        description="Project for observability API tests",
    )


@pytest.fixture
def obs_workflow(db, obs_project, user):
    """可观测性测试用工作流。"""
    return Workflow.objects.create(
        name="Obs Test Workflow",
        project=obs_project,
        created_by=user,
    )


@pytest.fixture
def obs_nodes(obs_workflow):
    """创建 3 个测试节点（用于 timeline 瓶颈标识测试）。"""
    _now = timezone.now()
    node1 = WorkflowNode.objects.create(
        workflow=obs_workflow,
        node_type="ai_coding",
        name="AI Coding Node",
        position_x=100,
        position_y=100,
    )
    node2 = WorkflowNode.objects.create(
        workflow=obs_workflow,
        node_type="create_branch",
        name="Create Branch",
        position_x=300,
        position_y=100,
    )
    node3 = WorkflowNode.objects.create(
        workflow=obs_workflow,
        node_type="ai_code_review",
        name="Code Review",
        position_x=500,
        position_y=100,
    )
    return node1, node2, node3


@pytest.fixture
def obs_execution(obs_workflow, user):
    """可观测性测试用工作流执行。"""
    now = timezone.now()
    return WorkflowExecution.objects.create(
        workflow=obs_workflow,
        project=obs_workflow.project,
        trigger_type="manual",
        triggered_by=user,
        status="completed",
        started_at=now - timedelta(seconds=300),
        completed_at=now,
    )


@pytest.fixture
def obs_node_executions(obs_execution, obs_nodes):
    """创建 3 个节点执行（不同耗时，用于 timeline 瓶颈标识）。"""
    node1, node2, node3 = obs_nodes
    now = timezone.now()

    ne1 = NodeExecution.objects.create(
        workflow_execution=obs_execution,
        node=node1,
        status="completed",
        started_at=now - timedelta(seconds=200),
        completed_at=now - timedelta(seconds=100),  # 100s duration (最慢 -> critical)
    )
    ne2 = NodeExecution.objects.create(
        workflow_execution=obs_execution,
        node=node2,
        status="completed",
        started_at=now - timedelta(seconds=100),
        completed_at=now - timedelta(seconds=60),  # 40s duration (第二 -> warning)
    )
    ne3 = NodeExecution.objects.create(
        workflow_execution=obs_execution,
        node=node3,
        status="completed",
        started_at=now - timedelta(seconds=60),
        completed_at=now - timedelta(seconds=40),  # 20s duration (第三 -> warning)
    )
    return ne1, ne2, ne3


@pytest.fixture
def obs_agent_session(db, obs_project, user):
    """创建 AgentSession（SubAgentSession 的 FK 依赖）。"""
    return AgentSession.objects.create(
        session_id="test-agent-session-001",
        project=obs_project,
        user=user,
        status="completed",
    )


@pytest.fixture
def obs_subagent_session(obs_agent_session, obs_node_executions):
    """创建关联到第一个 NodeExecution 的 SubAgentSession。"""
    ne1 = obs_node_executions[0]
    return SubAgentSession.objects.create(
        session_id="sub-test-001",
        main_session=obs_agent_session,
        repo_url="https://github.com/test/repo.git",
        task_type="coding",
        status="completed",
        node_execution=ne1,
    )


@pytest.fixture
def obs_action_logs(obs_subagent_session):
    """创建 3 条 ActionLog 记录。"""
    now = timezone.now()
    log1 = ActionLog.objects.create(
        session=obs_subagent_session,
        action_type="llm_request",
        timestamp=now - timedelta(seconds=10),
        sequence=1,
        payload={"prompt": "Generate code for feature X"},
        duration_ms=500,
    )
    log2 = ActionLog.objects.create(
        session=obs_subagent_session,
        action_type="tool_call",
        timestamp=now - timedelta(seconds=8),
        sequence=2,
        payload={"tool": "write_file", "path": "src/feature.py", "content": "x" * 300},
        duration_ms=200,
    )
    log3 = ActionLog.objects.create(
        session=obs_subagent_session,
        action_type="llm_response",
        timestamp=now - timedelta(seconds=5),
        sequence=3,
        payload={"response": "Code generated successfully"},
        duration_ms=1000,
    )
    return log1, log2, log3


@pytest.fixture
def obs_token_usages(obs_subagent_session):
    """创建 2 条 TokenUsage 记录（不同模型）。"""
    usage1 = TokenUsage.objects.create(
        session=obs_subagent_session,
        input_tokens=1000,
        output_tokens=500,
        cache_read_tokens=200,
        cache_write_tokens=100,
        total_cost_usd=Decimal("0.015000"),
        model="claude-sonnet-4-20250514",
    )
    usage2 = TokenUsage.objects.create(
        session=obs_subagent_session,
        input_tokens=2000,
        output_tokens=800,
        cache_read_tokens=300,
        cache_write_tokens=150,
        total_cost_usd=Decimal("0.045000"),
        model="claude-opus-4-20250514",
    )
    return usage1, usage2
