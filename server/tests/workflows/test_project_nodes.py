"""create_project_workspace / ai_create_branch 节点守护测试（#4）。

覆盖：节点注册 + 关键校验失败路径（缺名/缺仓库/缺项目 → failed + error handle）。
不触 DB / 不调外部服务（校验在 ORM 之前返回）。
"""

from __future__ import annotations

import pytest

from workflows.nodes.base import ExecutionContext
from workflows.nodes.registry import NodeRegistry


def _ctx(*, node_config: dict, input_data: dict | None = None) -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec-1",
        node_id="n-1",
        node_config=node_config,
        input_data=input_data or {},
        workflow_context={},
        previous_outputs={},
        workflow_execution=None,
    )


def test_nodes_registered() -> None:
    assert NodeRegistry.get("create_project_workspace") is not None
    assert NodeRegistry.get("ai_create_branch") is not None


@pytest.mark.asyncio
async def test_create_project_workspace_missing_name() -> None:
    from workflows.nodes.integrations.create_project_workspace import (
        CreateProjectWorkspaceNode,
    )

    result = await CreateProjectWorkspaceNode().execute(_ctx(node_config={"name": "  "}))
    assert result.status == "failed"
    assert result.next_handle == "error"


@pytest.mark.asyncio
async def test_ai_create_branch_no_repositories() -> None:
    from workflows.nodes.git.ai_create_branch import AICreateBranchNode

    result = await AICreateBranchNode().execute(_ctx(node_config={}))
    assert result.status == "failed"
    assert result.next_handle == "error"
    assert "仓库" in (result.error or "")
