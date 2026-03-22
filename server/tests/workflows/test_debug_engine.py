"""调试引擎核心测试。
覆盖:
-: 调试模式启动后每个节点执行完自动暂停
-: release 命令后暂停节点放行
-: skip 命令后节点标记 SKIPPED 空输出
-: 调试逻辑不修改 BaseNode 子类——通用性验证
- 调试串行分支退化
- start_execution debug_mode 设置 is_debug 标记
"""
import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from projects.models import Project
from workflows.engine.scheduler import WorkflowEngine, _debug_sessions
from workflows.models import (
 ExecutionStatus,
 NodeExecutionStatus,
 Workflow,
 WorkflowEdge,
 WorkflowExecution,
 WorkflowNode,
)
@pytest.fixture
def debug_project(db):
 """调试测试用项目。"""
 return Project.objects.create(
 name="Debug Test Project",
 description="调试引擎测试专用项目",
 )
@pytest.fixture
def debug_workflow(db, debug_project):
 """含 manual_trigger + condition 的 2 节点调试测试工作流。"""
 workflow = Workflow.objects.create(
 name="Debug Workflow",
 project=debug_project,
 trigger_type="manual",
 )
 trigger_node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Start",
 position_x=0,
 position_y=0,
 )
 condition_node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="condition",
 name="Check",
 position_x=200,
 position_y=0,
 config={"expression": "true", "cases": },
 )
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node=trigger_node,
 target_node=condition_node,
 source_handle="default",
 target_handle="default",
 )
 return workflow
@pytest.fixture
def parallel_workflow(db, debug_project):
 """含 manual_trigger + 2 个并行 condition 节点的工作流（测试串行退化）。"""
 workflow = Workflow.objects.create(
 name="Parallel Debug Workflow",
 project=debug_project,
 trigger_type="manual",
 )
 trigger_node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="manual_trigger",
 name="Start",
 position_x=0,
 position_y=0,
 )
 cond_a = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="condition",
 name="Branch A",
 position_x=200,
 position_y=0,
 config={"expression": "true", "cases": },
 )
 cond_b = WorkflowNode.objects.create(
 workflow=workflow,
 node_type="condition",
 name="Branch B",
 position_x=200,
 position_y=200,
 config={"expression": "true", "cases": },
 )
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node=trigger_node,
 target_node=cond_a,
 source_handle="default",
 target_handle="default",
 )
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node=trigger_node,
 target_node=cond_b,
 source_handle="default",
 target_handle="default",
 )
 return workflow
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestDebugEngine:
 """调试引擎核心测试。"""
 async def test_debug_mode_pauses_after_each_node(self, debug_workflow):
 """: 调试模式下，每个节点执行完后自动暂停。
 通过 mock _debug_pause_after_node 返回 release 来验证：
 该方法被调用的次数等于所有节点数量（trigger + condition = 2）。
 """
 engine = WorkflowEngine
 pause_calls: list[str] =
 async def mock_pause(execution, node_execution):
 pause_calls.append(str(node_execution.node_id))
 return ("release", {})
 with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
 execution = await engine.start_execution(
 workflow=debug_workflow,
 input_data={},
 trigger_type="manual",
 run_sync=True,
 debug_mode=True,
 )
 await execution.arefresh_from_db
 # 每个节点执行完都暂停（trigger + condition = 2 次）
 assert len(pause_calls) == 2
 assert execution.status == ExecutionStatus.COMPLETED
 async def test_debug_release_continues_to_next_node(self, debug_workflow):
 """: 暂停后 release 动作让引擎继续执行下一节点。
 使用 mock 让 _debug_pause_after_node 始终返回 release，
 验证整个工作流顺利完成。
 """
 engine = WorkflowEngine
 async def mock_pause(execution, node_execution):
 return ("release", {})
 with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
 execution = await engine.start_execution(
 workflow=debug_workflow,
 input_data={},
 trigger_type="manual",
 run_sync=True,
 debug_mode=True,
 )
 await execution.arefresh_from_db
 assert execution.status == ExecutionStatus.COMPLETED
 async def test_debug_skip_marks_skipped_with_empty_output(self, debug_workflow):
 """: skip 动作将节点标记为 SKIPPED，输出为空 {}。"""
 engine = WorkflowEngine
 async def mock_pause(execution, node_execution):
 return ("skip", {})
 with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
 execution = await engine.start_execution(
 workflow=debug_workflow,
 input_data={},
 trigger_type="manual",
 run_sync=True,
 debug_mode=True,
 )
 await execution.arefresh_from_db
 # condition 节点应被标记为 SKIPPED
 from asgiref.sync import sync_to_async
 node_execs = await sync_to_async(
 lambda: list(
 execution.node_executions.filter(
 status=NodeExecutionStatus.SKIPPED
 ).values_list("node__node_type", flat=True)
 )
 )
 assert "condition" in node_execs
 async def test_debug_works_with_any_node_type(self, debug_workflow):
 """: 调试逻辑不依赖特定 BaseNode 子类。
 使用 manual_trigger + condition 两种不同节点类型，验证调试模式均能暂停。
 condition 节点是非 trigger 类型，也能正常暂停。
 """
 engine = WorkflowEngine
 paused_node_types: list[str] =
 async def mock_pause(execution, node_execution):
 from asgiref.sync import sync_to_async
 node_type = await sync_to_async(lambda: node_execution.node.node_type)
 paused_node_types.append(node_type)
 return ("release", {})
 with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
 execution = await engine.start_execution(
 workflow=debug_workflow,
 input_data={},
 trigger_type="manual",
 run_sync=True,
 debug_mode=True,
 )
 await execution.arefresh_from_db
 assert execution.status == ExecutionStatus.COMPLETED
 # 至少有一个非 trigger 节点被暂停
 assert len(paused_node_types) >= 1
 async def test_debug_serial_execution(self, parallel_workflow):
 """调试模式下并行分支退化为串行——逐个暂停而非同时。
 parallel_workflow 有 trigger -> [cond_a, cond_b] 两条并行分支。
 正常模式下 cond_a 和 cond_b 会被 asyncio.gather 并行执行。
 调试模式下应该串行暂停：trigger 先暂停，release 后 cond_a 暂停，release 后 cond_b 暂停。
 """
 engine = WorkflowEngine
 pause_order: list[str] =
 async def mock_pause(execution, node_execution):
 from asgiref.sync import sync_to_async
 node_name = await sync_to_async(lambda: node_execution.node.name)
 pause_order.append(node_name)
 return ("release", {})
 with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
 execution = await engine.start_execution(
 workflow=parallel_workflow,
 input_data={},
 trigger_type="manual",
 run_sync=True,
 debug_mode=True,
 )
 await execution.arefresh_from_db
 assert execution.status == ExecutionStatus.COMPLETED
 # 3 个节点逐个串行暂停：trigger + 两个并行分支
 assert len(pause_order) == 3
 # 第一个一定是 trigger
 assert pause_order[0] == "Start"
 # 后续两个是 Branch A 和 Branch B（顺序可能因 DAG 遍历顺序不同而异，但都出现）
 assert set(pause_order[1:]) == {"Branch A", "Branch B"}
 async def test_release_with_edited_output(self, debug_workflow):
 """release + edited_output 时，编辑数据覆盖 node_outputs 并持久化到 NodeExecution.output_data。"""
 engine = WorkflowEngine
 edited = {"result": "edited_value", "score": 42}
 async def mock_pause(execution, node_execution):
 from asgiref.sync import sync_to_async
 node_type = await sync_to_async(lambda: node_execution.node.node_type)
 if node_type == "condition":
 # condition 节点返回 release + edited_output
 return ("release", {"edited_output": edited})
 return ("release", {})
 with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
 execution = await engine.start_execution(
 workflow=debug_workflow,
 input_data={},
 trigger_type="manual",
 run_sync=True,
 debug_mode=True,
 )
 await execution.arefresh_from_db
 assert execution.status == ExecutionStatus.COMPLETED
 # 验证 NodeExecution.output_data 被持久化为编辑数据
 from asgiref.sync import sync_to_async
 condition_ne = await sync_to_async(
 lambda: execution.node_executions.get(node__node_type="condition")
 )
 assert condition_ne.output_data == edited
 async def test_release_without_edited_output(self, debug_workflow):
 """release 不带 edited_output 时，行为不变（原始输出保留）。"""
 engine = WorkflowEngine
 async def mock_pause(execution, node_execution):
 return ("release", {})
 with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
 execution = await engine.start_execution(
 workflow=debug_workflow,
 input_data={},
 trigger_type="manual",
 run_sync=True,
 debug_mode=True,
 )
 await execution.arefresh_from_db
 assert execution.status == ExecutionStatus.COMPLETED
 # 验证原始输出仍然保留（condition 节点有默认输出）
 from asgiref.sync import sync_to_async
 condition_ne = await sync_to_async(
 lambda: execution.node_executions.get(node__node_type="condition")
 )
 # 没有 edited_output 时，output_data 应该是原始执行结果，不应为 None
 assert condition_ne.output_data is not None
 async def test_mock_action(self, debug_workflow):
 """mock action 用 mock_output 填充 node_outputs，节点标记完成。"""
 engine = WorkflowEngine
 mock_data = {"mocked": True, "value": "test_mock"}
 async def mock_pause(execution, node_execution):
 from asgiref.sync import sync_to_async
 node_type = await sync_to_async(lambda: node_execution.node.node_type)
 if node_type == "condition":
 return ("mock", {"mock_output": mock_data})
 return ("release", {})
 with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
 execution = await engine.start_execution(
 workflow=debug_workflow,
 input_data={},
 trigger_type="manual",
 run_sync=True,
 debug_mode=True,
 )
 await execution.arefresh_from_db
 assert execution.status == ExecutionStatus.COMPLETED
 # 验证 NodeExecution.output_data 为 mock 数据
 from asgiref.sync import sync_to_async
 condition_ne = await sync_to_async(
 lambda: execution.node_executions.get(node__node_type="condition")
 )
 assert condition_ne.output_data == mock_data
 async def test_mock_action_with_empty_output(self, debug_workflow):
 """mock action 不带 mock_output 时使用空字典 {}。"""
 engine = WorkflowEngine
 async def mock_pause(execution, node_execution):
 from asgiref.sync import sync_to_async
 node_type = await sync_to_async(lambda: node_execution.node.node_type)
 if node_type == "condition":
 return ("mock", {}) # 不提供 mock_output
 return ("release", {})
 with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
 execution = await engine.start_execution(
 workflow=debug_workflow,
 input_data={},
 trigger_type="manual",
 run_sync=True,
 debug_mode=True,
 )
 await execution.arefresh_from_db
 assert execution.status == ExecutionStatus.COMPLETED
 from asgiref.sync import sync_to_async
 condition_ne = await sync_to_async(
 lambda: execution.node_executions.get(node__node_type="condition")
 )
 assert condition_ne.output_data == {}
 async def test_start_execution_debug_mode_sets_is_debug(self, debug_workflow):
 """start_execution(debug_mode=True) 后 execution.is_debug == True。"""
 engine = WorkflowEngine
 async def mock_pause(execution, node_execution):
 return ("release", {})
 with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
 execution = await engine.start_execution(
 workflow=debug_workflow,
 input_data={},
 trigger_type="manual",
 run_sync=True,
 debug_mode=True,
 )
 await execution.arefresh_from_db
 assert execution.is_debug is True
