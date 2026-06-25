"""Tests for resume_from_node (从失败节点继续执行) feature."""

import pytest

from projects.models import Space
from workflows.engine.dag import DAG
from workflows.engine.scheduler import WorkflowEngine
from workflows.models import (
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)
from workflows.models.execution import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
    WorkflowExecution,
)


@pytest.fixture
async def linear_workflow():
    """创建一个 3 节点线性工作流 A -> B -> C，用于测试 resume_from_node。"""
    project = await Space.objects.acreate(
        name="Resume Test Space", description="For resume testing"
    )
    workflow = await Workflow.objects.acreate(
        name="Test Linear Resume", trigger_type="manual", space=project
    )
    node_a = await WorkflowNode.objects.acreate(
        workflow=workflow,
        node_type="manual_trigger",
        name="Node A",
        position_x=0,
        position_y=0,
    )
    node_b = await WorkflowNode.objects.acreate(
        workflow=workflow,
        node_type="condition",
        name="Node B",
        position_x=200,
        position_y=0,
        config={"expression": "true", "cases": []},
    )
    node_c = await WorkflowNode.objects.acreate(
        workflow=workflow,
        node_type="condition",
        name="Node C",
        position_x=400,
        position_y=0,
        config={"expression": "true", "cases": []},
    )
    await WorkflowEdge.objects.acreate(
        workflow=workflow,
        source_node=node_a,
        target_node=node_b,
        source_handle="default",
        target_handle="default",
    )
    await WorkflowEdge.objects.acreate(
        workflow=workflow,
        source_node=node_b,
        target_node=node_c,
        source_handle="default",
        target_handle="default",
    )
    return workflow, node_a, node_b, node_c


async def _create_failed_execution(
    workflow: Workflow,
    node_a: WorkflowNode,
    node_b: WorkflowNode,
    node_c: WorkflowNode,
) -> WorkflowExecution:
    """创建一个模拟的失败执行：A=completed, B=failed, C=pending。"""
    # 构建 workflow_definition 快照
    nodes_snapshot = []
    async for node in workflow.nodes.all():
        nodes_snapshot.append({
            "id": str(node.id),
            "name": node.name,
            "node_type": node.node_type,
            "position": {"x": node.position_x, "y": node.position_y},
            "config": node.config or {},
        })
    edges_snapshot = []
    async for edge in workflow.edges.all():
        edges_snapshot.append({
            "id": str(edge.id),
            "source": str(edge.source_node_id),
            "target": str(edge.target_node_id),
            "sourcePort": edge.source_handle or "default",
            "targetPort": edge.target_handle or "default",
        })

    execution = await WorkflowExecution.objects.acreate(
        workflow=workflow,
        space=workflow.space,
        status=ExecutionStatus.FAILED,
        trigger_type="manual",
        input_data={"test": "data"},
        workflow_definition={"nodes": nodes_snapshot, "edges": edges_snapshot},
        total_nodes=3,
        completed_nodes=1,
        failed_nodes=1,
        error_message="Node B failed",
    )

    # Node A: completed with output
    _ne_a = await NodeExecution.objects.acreate(
        workflow_execution=execution,
        node=node_a,
        status=NodeExecutionStatus.COMPLETED,
        output_data={"result_a": "value_a"},
    )

    # Node B: failed
    _ne_b = await NodeExecution.objects.acreate(
        workflow_execution=execution,
        node=node_b,
        status=NodeExecutionStatus.FAILED,
        error_message="Simulated failure",
    )

    # Node C: skipped (因为 B 失败)
    _ne_c = await NodeExecution.objects.acreate(
        workflow_execution=execution,
        node=node_c,
        status=NodeExecutionStatus.SKIPPED,
        error_message="前置节点失败",
    )

    return execution


# ===== Engine Tests =====


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_downstream_nodes(linear_workflow):
    """_get_downstream_nodes 应该正确收集所有递归下游节点。"""
    workflow, node_a, node_b, node_c = linear_workflow
    dag = await DAG.afrom_workflow(workflow)
    engine = WorkflowEngine()

    # 从 A 开始，下游应该是 B 和 C
    downstream_a = engine._get_downstream_nodes(dag, str(node_a.id))
    assert str(node_b.id) in downstream_a
    assert str(node_c.id) in downstream_a
    assert str(node_a.id) not in downstream_a  # 不包含起始节点

    # 从 B 开始，下游应该只有 C
    downstream_b = engine._get_downstream_nodes(dag, str(node_b.id))
    assert str(node_c.id) in downstream_b
    assert str(node_b.id) not in downstream_b
    assert str(node_a.id) not in downstream_b

    # 从 C 开始，没有下游
    downstream_c = engine._get_downstream_nodes(dag, str(node_c.id))
    assert len(downstream_c) == 0


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_compare_definitions_unchanged(linear_workflow):
    """_compare_workflow_definitions 定义未变时应返回 False。"""
    workflow, node_a, node_b, node_c = linear_workflow

    # 构建快照
    nodes_snapshot = []
    async for node in workflow.nodes.all():
        nodes_snapshot.append({
            "id": str(node.id),
            "name": node.name,
            "node_type": node.node_type,
            "position": {"x": node.position_x, "y": node.position_y},
            "config": node.config or {},
        })
    edges_snapshot = []
    async for edge in workflow.edges.all():
        edges_snapshot.append({
            "id": str(edge.id),
            "source": str(edge.source_node_id),
            "target": str(edge.target_node_id),
            "sourcePort": edge.source_handle or "default",
        })

    snapshot = {"nodes": nodes_snapshot, "edges": edges_snapshot}

    engine = WorkflowEngine()
    changed = await engine._compare_workflow_definitions(snapshot, workflow)
    assert changed is False


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_compare_definitions_node_added(linear_workflow):
    """_compare_workflow_definitions 节点增加时应返回 True。"""
    workflow, node_a, node_b, node_c = linear_workflow

    # 先构建快照
    nodes_snapshot = []
    async for node in workflow.nodes.all():
        nodes_snapshot.append({
            "id": str(node.id),
            "name": node.name,
            "node_type": node.node_type,
            "position": {"x": node.position_x, "y": node.position_y},
            "config": node.config or {},
        })
    edges_snapshot = []
    async for edge in workflow.edges.all():
        edges_snapshot.append({
            "id": str(edge.id),
            "source": str(edge.source_node_id),
            "target": str(edge.target_node_id),
            "sourcePort": edge.source_handle or "default",
        })
    snapshot = {"nodes": nodes_snapshot, "edges": edges_snapshot}

    # 添加新节点
    await WorkflowNode.objects.acreate(
        workflow=workflow,
        node_type="condition",
        name="Node D",
        position_x=600,
        position_y=0,
        config={"expression": "true", "cases": []},
    )

    engine = WorkflowEngine()
    changed = await engine._compare_workflow_definitions(snapshot, workflow)
    assert changed is True


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_compare_definitions_config_changed(linear_workflow):
    """_compare_workflow_definitions 节点配置变更时应返回 True。"""
    workflow, node_a, node_b, node_c = linear_workflow

    # 先构建快照
    nodes_snapshot = []
    async for node in workflow.nodes.all():
        nodes_snapshot.append({
            "id": str(node.id),
            "name": node.name,
            "node_type": node.node_type,
            "position": {"x": node.position_x, "y": node.position_y},
            "config": node.config or {},
        })
    edges_snapshot = []
    async for edge in workflow.edges.all():
        edges_snapshot.append({
            "id": str(edge.id),
            "source": str(edge.source_node_id),
            "target": str(edge.target_node_id),
            "sourcePort": edge.source_handle or "default",
        })
    snapshot = {"nodes": nodes_snapshot, "edges": edges_snapshot}

    # 修改节点配置
    node_b.config = {"expression": "false", "cases": [{"label": "new"}]}
    await node_b.asave(update_fields=["config"])

    engine = WorkflowEngine()
    changed = await engine._compare_workflow_definitions(snapshot, workflow)
    assert changed is True


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_compare_definitions_ignores_position(linear_workflow):
    """_compare_workflow_definitions 应忽略 position 变化。"""
    workflow, node_a, node_b, node_c = linear_workflow

    # 先构建快照
    nodes_snapshot = []
    async for node in workflow.nodes.all():
        nodes_snapshot.append({
            "id": str(node.id),
            "name": node.name,
            "node_type": node.node_type,
            "position": {"x": node.position_x, "y": node.position_y},
            "config": node.config or {},
        })
    edges_snapshot = []
    async for edge in workflow.edges.all():
        edges_snapshot.append({
            "id": str(edge.id),
            "source": str(edge.source_node_id),
            "target": str(edge.target_node_id),
            "sourcePort": edge.source_handle or "default",
        })
    snapshot = {"nodes": nodes_snapshot, "edges": edges_snapshot}

    # 只修改位置（不应触发变更检测）
    node_b.position_x = 999
    node_b.position_y = 999
    await node_b.asave(update_fields=["position_x", "position_y"])

    engine = WorkflowEngine()
    changed = await engine._compare_workflow_definitions(snapshot, workflow)
    assert changed is False


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_resume_creates_new_execution(linear_workflow):
    """resume_from_node 应创建新执行实例，resumed_from 指向原执行。"""
    workflow, node_a, node_b, node_c = linear_workflow
    original = await _create_failed_execution(workflow, node_a, node_b, node_c)

    engine = WorkflowEngine()
    new_exec = await engine.resume_from_node(
        original_execution=original,
        failed_node_id=str(node_b.id),
        run_sync=True,
    )

    assert new_exec.id != original.id
    assert new_exec.trigger_type == "resume"
    assert new_exec.resumed_from_id == original.id


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_resume_skipped_nodes_copy_output(linear_workflow):
    """resume_from_node 应将 skipped 节点的 output_data 从原执行复制。"""
    workflow, node_a, node_b, node_c = linear_workflow
    original = await _create_failed_execution(workflow, node_a, node_b, node_c)

    engine = WorkflowEngine()
    new_exec = await engine.resume_from_node(
        original_execution=original,
        failed_node_id=str(node_b.id),
        run_sync=True,
    )

    # Node A 应该是 skipped，且 output_data 从原执行复制
    ne_a = await NodeExecution.objects.filter(
        workflow_execution=new_exec,
        node=node_a,
    ).afirst()
    assert ne_a is not None
    assert ne_a.status == NodeExecutionStatus.SKIPPED
    assert ne_a.output_data == {"result_a": "value_a"}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_resume_rejects_non_failed_execution(linear_workflow):
    """resume_from_node 应拒绝非失败执行。"""
    workflow, node_a, node_b, node_c = linear_workflow
    original = await _create_failed_execution(workflow, node_a, node_b, node_c)

    # 强制设为 completed
    original.status = ExecutionStatus.COMPLETED
    await original.asave(update_fields=["status"])

    engine = WorkflowEngine()
    with pytest.raises(ValueError, match="只能从失败、已取消或超时的执行继续"):
        await engine.resume_from_node(
            original_execution=original,
            failed_node_id=str(node_b.id),
        )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_resume_rejects_definition_changed(linear_workflow):
    """resume_from_node 定义已变更时应拒绝继续。"""
    workflow, node_a, node_b, node_c = linear_workflow
    original = await _create_failed_execution(workflow, node_a, node_b, node_c)

    # 修改工作流定义
    await WorkflowNode.objects.acreate(
        workflow=workflow,
        node_type="condition",
        name="Node D",
        position_x=600,
        position_y=0,
        config={"expression": "true", "cases": []},
    )

    engine = WorkflowEngine()
    with pytest.raises(ValueError, match="工作流定义已修改"):
        await engine.resume_from_node(
            original_execution=original,
            failed_node_id=str(node_b.id),
        )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_resume_from_timeout_execution(linear_workflow):
    """timeout 状态的执行允许恢复。"""
    workflow, node_a, node_b, node_c = linear_workflow
    original = await _create_failed_execution(workflow, node_a, node_b, node_c)

    # 改为 timeout 状态
    original.status = ExecutionStatus.TIMEOUT
    await original.asave(update_fields=["status"])

    engine = WorkflowEngine()
    new_exec = await engine.resume_from_node(
        original_execution=original,
        failed_node_id=str(node_b.id),
        run_sync=True,
    )
    assert new_exec is not None
    assert new_exec.trigger_type == "resume"
    assert new_exec.resumed_from_id == original.id


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_resume_mutex_rejects_concurrent(linear_workflow):
    """互斥锁定：当存在活跃恢复执行时拒绝新恢复。"""
    workflow, node_a, node_b, node_c = linear_workflow
    original = await _create_failed_execution(workflow, node_a, node_b, node_c)

    engine = WorkflowEngine()

    # 第一次恢复成功
    new_exec = await engine.resume_from_node(
        original_execution=original,
        failed_node_id=str(node_b.id),
        run_sync=True,
    )

    # 手动将新执行设为 RUNNING（模拟正在运行）
    new_exec.status = ExecutionStatus.RUNNING
    await new_exec.asave(update_fields=["status"])

    # 第二次恢复应被拒绝
    with pytest.raises(ValueError, match="已有恢复执行正在运行"):
        await engine.resume_from_node(
            original_execution=original,
            failed_node_id=str(node_b.id),
            run_sync=True,
        )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_resume_mutex_allows_after_completion(linear_workflow):
    """互斥锁定：活跃恢复执行完成后允许再次恢复。"""
    workflow, node_a, node_b, node_c = linear_workflow
    original = await _create_failed_execution(workflow, node_a, node_b, node_c)

    engine = WorkflowEngine()

    # 第一次恢复
    new_exec = await engine.resume_from_node(
        original_execution=original,
        failed_node_id=str(node_b.id),
        run_sync=True,
    )

    # 标记为已完成（不再阻塞）
    new_exec.status = ExecutionStatus.COMPLETED
    await new_exec.asave(update_fields=["status"])

    # 重新设置原执行为 FAILED（因为恢复后可能被改了状态）
    original.status = ExecutionStatus.FAILED
    await original.asave(update_fields=["status"])

    # 第二次恢复应被允许
    new_exec_2 = await engine.resume_from_node(
        original_execution=original,
        failed_node_id=str(node_b.id),
        run_sync=True,
    )
    assert new_exec_2.id != new_exec.id
