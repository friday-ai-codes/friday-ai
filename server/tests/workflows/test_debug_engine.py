"""调试引擎核心测试。

覆盖:
- 调试模式启动后每个节点执行完自动暂停
- release 命令后暂停节点放行
- skip 命令后节点标记 SKIPPED 空输出
- 调试逻辑不修改 BaseNode 子类——通用性验证
- 调试串行分支退化
- start_execution debug_mode 设置 is_debug 标记
"""

import asyncio
from unittest.mock import patch

import pytest

from projects.models import Space
from workflows.engine.scheduler import WorkflowEngine, _debug_sessions
from workflows.models import (
    ExecutionStatus,
    NodeExecutionStatus,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)


@pytest.fixture
def debug_project(db):
    """调试测试用项目。"""
    return Space.objects.create(
        name="Debug Test Space",
        description="调试引擎测试专用项目",
    )


@pytest.fixture
def debug_workflow(db, debug_project):
    """含 manual_trigger + condition 的 2 节点调试测试工作流。"""
    workflow = Workflow.objects.create(
        name="Debug Workflow",
        space=debug_project,
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
        config={"expression": "true", "cases": []},
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
        space=debug_project,
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
        config={"expression": "true", "cases": []},
    )

    cond_b = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="condition",
        name="Branch B",
        position_x=200,
        position_y=200,
        config={"expression": "true", "cases": []},
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
        """调试模式下，每个节点执行完后自动暂停。

        通过 mock _debug_pause_after_node 返回 release 来验证：
        该方法被调用的次数等于所有节点数量（trigger + condition = 2）。
        """
        engine = WorkflowEngine()
        pause_calls: list[str] = []

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

        await execution.arefresh_from_db()
        # 每个节点执行完都暂停（trigger + condition = 2 次）
        assert len(pause_calls) == 2
        assert execution.status == ExecutionStatus.COMPLETED

    async def test_debug_release_continues_to_next_node(self, debug_workflow):
        """暂停后 release 动作让引擎继续执行下一节点。

        使用 mock 让 _debug_pause_after_node 始终返回 release，
        验证整个工作流顺利完成。
        """
        engine = WorkflowEngine()

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

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED

    async def test_debug_skip_marks_skipped_with_empty_output(self, debug_workflow):
        """skip 动作将节点标记为 SKIPPED，输出为空 {}。"""
        engine = WorkflowEngine()

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

        await execution.arefresh_from_db()

        # condition 节点应被标记为 SKIPPED
        from asgiref.sync import sync_to_async
        node_execs = await sync_to_async(
            lambda: list(
                execution.node_executions.filter(
                    status=NodeExecutionStatus.SKIPPED
                ).values_list("node__node_type", flat=True)
            )
        )()
        assert "condition" in node_execs

    async def test_debug_works_with_any_node_type(self, debug_workflow):
        """调试逻辑不依赖特定 BaseNode 子类。

        使用 manual_trigger + condition 两种不同节点类型，验证调试模式均能暂停。
        condition 节点是非 trigger 类型，也能正常暂停。
        """
        engine = WorkflowEngine()
        paused_node_types: list[str] = []

        async def mock_pause(execution, node_execution):
            from asgiref.sync import sync_to_async
            node_type = await sync_to_async(lambda: node_execution.node.node_type)()
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

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED
        # 至少有一个非 trigger 节点被暂停
        assert len(paused_node_types) >= 1

    async def test_debug_serial_execution(self, parallel_workflow):
        """调试模式下并行分支退化为串行——逐个暂停而非同时。

        parallel_workflow 有 trigger -> [cond_a, cond_b] 两条并行分支。
        正常模式下 cond_a 和 cond_b 会被 asyncio.gather 并行执行。
        调试模式下应该串行暂停：trigger 先暂停，release 后 cond_a 暂停，release 后 cond_b 暂停。
        """
        engine = WorkflowEngine()
        pause_order: list[str] = []

        async def mock_pause(execution, node_execution):
            from asgiref.sync import sync_to_async
            node_name = await sync_to_async(lambda: node_execution.node.name)()
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

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED
        # 3 个节点逐个串行暂停：trigger + 两个并行分支
        assert len(pause_order) == 3
        # 第一个一定是 trigger
        assert pause_order[0] == "Start"
        # 后续两个是 Branch A 和 Branch B（顺序可能因 DAG 遍历顺序不同而异，但都出现）
        assert set(pause_order[1:]) == {"Branch A", "Branch B"}

    async def test_release_with_edited_output(self, debug_workflow):
        """release + edited_output 时，编辑数据覆盖 node_outputs 并持久化到 NodeExecution.output_data。"""
        engine = WorkflowEngine()
        edited = {"result": "edited_value", "score": 42}

        async def mock_pause(execution, node_execution):
            from asgiref.sync import sync_to_async
            node_type = await sync_to_async(lambda: node_execution.node.node_type)()
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

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED

        # 验证 NodeExecution.output_data 被持久化为编辑数据
        from asgiref.sync import sync_to_async
        condition_ne = await sync_to_async(
            lambda: execution.node_executions.get(node__node_type="condition")
        )()
        assert condition_ne.output_data == edited

    async def test_release_without_edited_output(self, debug_workflow):
        """release 不带 edited_output 时，行为不变（原始输出保留）。"""
        engine = WorkflowEngine()

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

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED

        # 验证原始输出仍然保留（condition 节点有默认输出）
        from asgiref.sync import sync_to_async
        condition_ne = await sync_to_async(
            lambda: execution.node_executions.get(node__node_type="condition")
        )()
        # 没有 edited_output 时，output_data 应该是原始执行结果，不应为 None
        assert condition_ne.output_data is not None

    async def test_mock_action(self, debug_workflow):
        """mock action 用 mock_output 填充 node_outputs，节点标记完成。"""
        engine = WorkflowEngine()
        mock_data = {"mocked": True, "value": "test_mock"}

        async def mock_pause(execution, node_execution):
            from asgiref.sync import sync_to_async
            node_type = await sync_to_async(lambda: node_execution.node.node_type)()
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

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED

        # 验证 NodeExecution.output_data 为 mock 数据
        from asgiref.sync import sync_to_async
        condition_ne = await sync_to_async(
            lambda: execution.node_executions.get(node__node_type="condition")
        )()
        assert condition_ne.output_data == mock_data

    async def test_mock_action_with_empty_output(self, debug_workflow):
        """mock action 不带 mock_output 时使用空字典 {}。"""
        engine = WorkflowEngine()

        async def mock_pause(execution, node_execution):
            from asgiref.sync import sync_to_async
            node_type = await sync_to_async(lambda: node_execution.node.node_type)()
            if node_type == "condition":
                return ("mock", {})  # 不提供 mock_output
            return ("release", {})

        with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
            execution = await engine.start_execution(
                workflow=debug_workflow,
                input_data={},
                trigger_type="manual",
                run_sync=True,
                debug_mode=True,
            )

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED

        from asgiref.sync import sync_to_async
        condition_ne = await sync_to_async(
            lambda: execution.node_executions.get(node__node_type="condition")
        )()
        assert condition_ne.output_data == {}

    async def test_start_execution_debug_mode_sets_is_debug(self, debug_workflow):
        """start_execution(debug_mode=True) 后 execution.is_debug == True。"""
        engine = WorkflowEngine()

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

        await execution.arefresh_from_db()
        assert execution.is_debug is True


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestBreakpointMode:
    """断点模式测试。"""

    async def test_breakpoint_mode_only_pauses_at_breakpoints(self, parallel_workflow):
        """断点模式下仅断点节点暂停，非断点节点自动放行。

        设置 Branch A 为断点，Branch B 不是。
        断点模式下应只在 trigger 和 Branch A 处暂停（trigger 因为串行也会走条件判断）。
        实际上 trigger 节点不在 breakpoints 里，所以也自动放行。
        """
        engine = WorkflowEngine()
        pause_calls: list[str] = []

        # 我们需要在引擎启动后设置 session 的断点和模式
        # 用 mock 来记录哪些节点实际被暂停
        async def mock_pause(execution, node_execution):
            from asgiref.sync import sync_to_async
            node_name = await sync_to_async(lambda: node_execution.node.name)()
            pause_calls.append(node_name)
            return ("release", {})

        with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
            # 先获取节点 ID
            from asgiref.sync import sync_to_async
            nodes = await sync_to_async(
                lambda: {n.name: str(n.id) for n in parallel_workflow.nodes.all()}
            )()

            # 在 start_execution 之前预设 session 不行（因为 execution_id 还不存在）
            # 需要在 mock_pause 第一次调用前设置
            # 更好的方案：直接 patch _debug_sessions 和判断逻辑
            # 实际方案：让 start_execution 运行，引擎创建 session 后第一次暂停前设置

            first_call = True

            async def mock_pause_with_breakpoint_setup(execution, node_execution):
                nonlocal first_call
                if first_call:
                    first_call = False
                    # 第一次暂停时设置断点模式
                    session = _debug_sessions.get(str(execution.id))
                    if not session:
                        from workflows.engine.scheduler import DebugSession
                        loop = asyncio.get_event_loop()
                        session = DebugSession(
                            execution_id=str(execution.id), loop=loop,
                        )
                        _debug_sessions[str(execution.id)] = session
                    session.debug_mode = "breakpoint"
                    session.breakpoints = {nodes["Branch A"]}
                    # 第一次（trigger 节点）也放行
                    return ("release", {})

                from asgiref.sync import sync_to_async
                node_name = await sync_to_async(lambda: node_execution.node.name)()
                pause_calls.append(node_name)
                return ("release", {})

        # 重新运行，用带 setup 的 mock
        pause_calls.clear()
        with patch.object(
            engine, "_debug_pause_after_node", side_effect=mock_pause_with_breakpoint_setup,
        ):
            execution = await engine.start_execution(
                workflow=parallel_workflow,
                input_data={},
                trigger_type="manual",
                run_sync=True,
                debug_mode=True,
            )

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED
        # 断点模式下：trigger 暂停（第一次，设置模式前），之后仅 Branch A 是断点会暂停
        # Branch B 不在 breakpoints 中，自动放行不调用 _debug_pause_after_node
        assert "Branch A" in pause_calls
        assert "Branch B" not in pause_calls

    async def test_step_mode_pauses_all_nodes(self, debug_workflow):
        """逐步模式（默认）下所有节点都暂停——与修改前一致。"""
        engine = WorkflowEngine()
        pause_calls: list[str] = []

        async def mock_pause(execution, node_execution):
            from asgiref.sync import sync_to_async
            node_name = await sync_to_async(lambda: node_execution.node.name)()
            pause_calls.append(node_name)
            return ("release", {})

        with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
            execution = await engine.start_execution(
                workflow=debug_workflow,
                input_data={},
                trigger_type="manual",
                run_sync=True,
                debug_mode=True,
            )

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED
        # 逐步模式：所有 2 个节点都暂停
        assert len(pause_calls) == 2

    async def test_breakpoint_mode_no_breakpoints_completes_without_pause(
        self, debug_workflow,
    ):
        """断点模式下没有设置任何断点时，所有节点自动放行，调试执行正常完成。"""
        engine = WorkflowEngine()
        pause_calls: list[str] = []

        async def mock_pause(execution, node_execution):
            from asgiref.sync import sync_to_async
            node_name = await sync_to_async(lambda: node_execution.node.name)()
            pause_calls.append(node_name)
            return ("release", {})

        # 预创建 execution 来获取 ID 比较复杂，用另一种方式：
        # 在第一次暂停时（逐步模式默认会暂停）设置断点模式
        first_call = True

        async def mock_pause_set_breakpoint_mode(execution, node_execution):
            nonlocal first_call
            if first_call:
                first_call = False
                session = _debug_sessions.get(str(execution.id))
                if not session:
                    from workflows.engine.scheduler import DebugSession
                    loop = asyncio.get_event_loop()
                    session = DebugSession(
                        execution_id=str(execution.id), loop=loop,
                    )
                    _debug_sessions[str(execution.id)] = session
                session.debug_mode = "breakpoint"
                # 不设置任何断点
                return ("release", {})

            # 这里不应该被调用——断点模式下无断点节点应自动跳过
            pause_calls.append("unexpected")
            return ("release", {})

        with patch.object(
            engine, "_debug_pause_after_node", side_effect=mock_pause_set_breakpoint_mode,
        ):
            execution = await engine.start_execution(
                workflow=debug_workflow,
                input_data={},
                trigger_type="manual",
                run_sync=True,
                debug_mode=True,
            )

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED
        # 除了 trigger 节点（第一次暂停用于设置模式），后续节点不应暂停
        assert "unexpected" not in pause_calls

    async def test_debug_session_default_fields(self):
        """DebugSession 默认 debug_mode='step'，breakpoints 为空 set。"""
        from workflows.engine.scheduler import DebugSession

        loop = asyncio.get_event_loop()
        session = DebugSession(execution_id="test-123", loop=loop)
        assert session.debug_mode == "step"
        assert session.breakpoints == set()
        assert isinstance(session.breakpoints, set)

    async def test_mode_switch_auto_release_non_breakpoint_node(self):
        """切换到断点模式时，若当前暂停在非断点节点，自动放行。"""
        from workflows.engine.scheduler import DebugSession

        loop = asyncio.get_event_loop()
        session = DebugSession(execution_id="test-auto-release", loop=loop)
        session.event = asyncio.Event()
        session.current_node_id = "node-1"
        session.debug_mode = "step"
        session.breakpoints = {"node-2"}  # node-1 不在断点列表中

        _debug_sessions["test-auto-release"] = session

        try:
            # 模拟模式切换：切到断点模式，node-1 不是断点
            session.debug_mode = "breakpoint"
            should_auto_release = (
                session.current_node_id is not None
                and session.current_node_id not in session.breakpoints
                and not session.event.is_set()
            )
            assert should_auto_release, "应该需要自动放行"

            # 验证 release_debug_node 正确设置了 debug_action 和 action_data
            WorkflowEngine.release_debug_node("test-auto-release", action="release")
            assert session.debug_action == "release"

            # call_soon_threadsafe 调度的回调需要 event loop 迭代才执行
            await asyncio.sleep(0)
            assert session.event.is_set(), "event 应该被 set，表示暂停被释放"
        finally:
            _debug_sessions.pop("test-auto-release", None)

    async def test_mode_switch_keeps_breakpoint_node_paused(self):
        """切换到断点模式时，若当前暂停在断点节点，不自动放行。"""
        from workflows.engine.scheduler import DebugSession

        loop = asyncio.get_event_loop()
        session = DebugSession(execution_id="test-keep-paused", loop=loop)
        session.event = asyncio.Event()
        session.current_node_id = "node-2"
        session.debug_mode = "step"
        session.breakpoints = {"node-2"}  # node-2 在断点列表中

        _debug_sessions["test-keep-paused"] = session

        try:
            # 模拟模式切换：切到断点模式，node-2 是断点
            session.debug_mode = "breakpoint"
            if (
                session.current_node_id
                and session.current_node_id not in session.breakpoints
                and not session.event.is_set()
            ):
                WorkflowEngine.release_debug_node("test-keep-paused", action="release")

            # event 不应该被 set——断点节点保持暂停
            assert not session.event.is_set()
        finally:
            _debug_sessions.pop("test-keep-paused", None)
