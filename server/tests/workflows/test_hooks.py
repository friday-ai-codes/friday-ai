"""HookManager 事件注册和触发测试。

验证所有引擎触发的事件名都在 HookManager.EVENTS 中注册，
防止类似 contract（node_waiting_event 未注册）的回归 bug。
"""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from projects.models import Space
from workflows.engine.scheduler import WorkflowEngine
from workflows.hooks.base import BaseHook, HookManager
from workflows.hooks.builtin import NotificationHook
from workflows.models import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
)


class TestHookManagerEvents:
    """验证 HookManager.EVENTS 列表完整性"""

    def test_node_waiting_event_registered(self) -> None:
        """contract: node_waiting_event 必须在 EVENTS 列表中"""
        assert "node_waiting_event" in HookManager.EVENTS

    def test_register_hook_for_node_waiting_event(self) -> None:
        """node_waiting_event 可以注册钩子（不抛 ValueError）"""
        manager = HookManager()

        class DummyHook(BaseHook):
            async def execute(self, event: str, **kwargs) -> None:
                pass

        # 不应抛出 ValueError
        manager.register_hook("node_waiting_event", DummyHook())

    @pytest.mark.asyncio
    async def test_trigger_node_waiting_event_calls_hook(self) -> None:
        """trigger('node_waiting_event') 能触发已注册的钩子"""
        manager = HookManager()

        mock_hook = AsyncMock(spec=BaseHook)
        mock_hook.priority = 100
        mock_hook.execute = AsyncMock()

        manager.register_hook("node_waiting_event", mock_hook)
        await manager.trigger("node_waiting_event", execution=None)

        mock_hook.execute.assert_called_once_with(
            "node_waiting_event", execution=None
        )

    def test_all_scheduler_events_registered(self) -> None:
        """所有 scheduler.py 中触发的事件名都必须在 EVENTS 中注册（防止回归）"""
        scheduler_path = (
            Path(__file__).resolve().parent.parent.parent
            / "workflows"
            / "engine"
            / "scheduler.py"
        )
        assert scheduler_path.exists(), f"scheduler.py 未找到: {scheduler_path}"

        content = scheduler_path.read_text()

        # 提取所有 hooks.trigger("event_name", ...) 调用中的事件名
        # 匹配模式：hooks.trigger("xxx" 或 self.hooks.trigger("xxx"
        pattern = r'hooks\.trigger\(\s*["\'](\w+)["\']'
        triggered_events = set(re.findall(pattern, content))

        assert triggered_events, "未在 scheduler.py 中找到任何 hooks.trigger 调用"

        missing = triggered_events - set(HookManager.EVENTS)
        assert not missing, (
            f"scheduler.py 中触发的事件未在 HookManager.EVENTS 中注册: {missing}"
        )

    def test_register_unknown_event_raises_error(self) -> None:
        """注册未知事件应抛出 ValueError"""
        manager = HookManager()

        class DummyHook(BaseHook):
            async def execute(self, event: str, **kwargs) -> None:
                pass

        with pytest.raises(ValueError, match="未知事件"):
            manager.register_hook("nonexistent_event", DummyHook())

    def test_workflow_engine_registers_notification_hook_for_target_events(self) -> None:
        """WorkflowEngine 初始化后应只在目标事件注册 NotificationHook。"""
        engine = WorkflowEngine()

        target_events = {
            "execution_completed",
            "execution_failed",
            "node_waiting_approval",
        }

        for event in target_events:
            hooks = engine.hooks._hooks[event]
            assert any(isinstance(hook, NotificationHook) for hook in hooks), (
                f"NotificationHook 未注册到 {event}"
            )

        for event in set(HookManager.EVENTS) - target_events:
            hooks = engine.hooks._hooks[event]
            assert not any(isinstance(hook, NotificationHook) for hook in hooks), (
                f"NotificationHook 不应注册到 {event}"
            )


@pytest.fixture
def scheduler_project(db):
    return Space.objects.create(
        name="Scheduler Event Test Space",
        description="Scheduler terminal event semantics tests",
    )


@pytest.fixture
def scheduler_single_node_workflow(db, scheduler_project):
    workflow = Workflow.objects.create(
        name="Scheduler Single Node Workflow",
        space=scheduler_project,
        trigger_type="manual",
    )
    WorkflowNode.objects.create(
        workflow=workflow,
        node_type="manual_trigger",
        name="Start",
        position_x=0,
        position_y=0,
    )
    return workflow


@pytest.fixture
def scheduler_failing_workflow(db, scheduler_project):
    workflow = Workflow.objects.create(
        name="Scheduler Failing Workflow",
        space=scheduler_project,
        trigger_type="manual",
    )
    trigger_node = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="manual_trigger",
        name="Start",
        position_x=0,
        position_y=0,
    )
    broken_node = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="nonexistent_node_type",
        name="Broken Node",
        position_x=200,
        position_y=0,
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=trigger_node,
        target_node=broken_node,
        source_handle="default",
        target_handle="default",
    )
    return workflow


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestSchedulerTerminalEvents:
    """失败/成功终态事件语义回归测试。"""

    async def test_start_execution_dag_validation_error_triggers_failed_event_once(
        self,
        scheduler_single_node_workflow,
    ) -> None:
        engine = WorkflowEngine()
        events: list[str] = []

        async def capture_event(event: str, **kwargs) -> None:
            del kwargs
            events.append(event)

        fake_dag = SimpleNamespace(
            nodes={},
            validate=lambda: ["dag invalid for test"],
        )

        with (
            patch.object(engine.hooks, "trigger", new=AsyncMock(side_effect=capture_event)),
            patch(
                "workflows.engine.scheduler.DAG.afrom_workflow",
                new=AsyncMock(return_value=fake_dag),
            ),
        ):
            execution = await engine.start_execution(
                workflow=scheduler_single_node_workflow,
                input_data={},
                trigger_type="manual",
                run_sync=True,
            )

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.FAILED
        assert events.count("execution_failed") == 1
        assert "execution_completed" not in events

    async def test_run_execution_with_failed_nodes_emits_execution_failed_only(
        self,
        scheduler_failing_workflow,
    ) -> None:
        engine = WorkflowEngine()
        events: list[str] = []

        async def capture_event(event: str, **kwargs) -> None:
            del kwargs
            events.append(event)

        with patch.object(engine.hooks, "trigger", new=AsyncMock(side_effect=capture_event)):
            execution = await engine.start_execution(
                workflow=scheduler_failing_workflow,
                input_data={},
                trigger_type="manual",
                run_sync=True,
            )

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.FAILED
        assert events.count("execution_failed") == 1
        assert "execution_completed" not in events

    async def test_check_execution_complete_failed_state_emits_execution_failed(
        self,
        scheduler_single_node_workflow,
    ) -> None:
        engine = WorkflowEngine()
        events: list[str] = []
        node = await WorkflowNode.objects.filter(workflow=scheduler_single_node_workflow).afirst()
        assert node is not None

        execution = await WorkflowExecution.objects.acreate(
            workflow=scheduler_single_node_workflow,
            space=scheduler_single_node_workflow.space,
            trigger_type="manual",
            status=ExecutionStatus.RUNNING,
        )
        await NodeExecution.objects.acreate(
            workflow_execution=execution,
            node=node,
            status=NodeExecutionStatus.FAILED,
            error_message="test failure",
        )

        async def capture_event(event: str, **kwargs) -> None:
            del kwargs
            events.append(event)

        with patch.object(engine.hooks, "trigger", new=AsyncMock(side_effect=capture_event)):
            await engine._check_execution_complete(execution)

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.FAILED
        assert events.count("execution_failed") == 1
        assert "execution_completed" not in events

    async def test_check_execution_complete_success_emits_execution_completed(
        self,
        scheduler_single_node_workflow,
    ) -> None:
        engine = WorkflowEngine()
        events: list[str] = []
        node = await WorkflowNode.objects.filter(workflow=scheduler_single_node_workflow).afirst()
        assert node is not None

        execution = await WorkflowExecution.objects.acreate(
            workflow=scheduler_single_node_workflow,
            space=scheduler_single_node_workflow.space,
            trigger_type="manual",
            status=ExecutionStatus.RUNNING,
        )
        await NodeExecution.objects.acreate(
            workflow_execution=execution,
            node=node,
            status=NodeExecutionStatus.COMPLETED,
            output_data={"ok": True},
        )

        async def capture_event(event: str, **kwargs) -> None:
            del kwargs
            events.append(event)

        with patch.object(engine.hooks, "trigger", new=AsyncMock(side_effect=capture_event)):
            await engine._check_execution_complete(execution)

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED
        assert events.count("execution_completed") == 1
        assert "execution_failed" not in events


def test_feishu_sync_hook_registered_in_engine() -> None:
    """FeishuSyncHook 必须在生产 WorkflowEngine 中注册（work item 回归测试）。"""
    from workflows.hooks.feishu_sync import FeishuSyncHook

    engine = WorkflowEngine()
    # 验证 node_started 事件中有 FeishuSyncHook 实例
    node_started_hooks = engine.hooks._hooks.get("node_started", [])
    assert any(isinstance(h, FeishuSyncHook) for h in node_started_hooks), \
        "FeishuSyncHook 未注册到 node_started 事件"
    # 验证 execution_completed 事件中也有
    exec_completed_hooks = engine.hooks._hooks.get("execution_completed", [])
    assert any(isinstance(h, FeishuSyncHook) for h in exec_completed_hooks), \
        "FeishuSyncHook 未注册到 execution_completed 事件"


# ============================================================================
# OBS-01：WebSocketBroadcastHook 失败广播附带 error 字段（Phase 21 Wave 0 RED）
#
# D-04 裁定：node 失败/超时时，WS 广播 message 追加 error_message/error_code，
# 前端无需 full fetch 即见失败原因；仅失败态追加可选键（Pitfall 5 向后兼容）。
# 被测目标：workflows.hooks.builtin.WebSocketBroadcastHook.execute。
#
# 注意：失败态用例在 21-03/04 实现前预期为 RED（当前 message 不含 error_* 键）。
# 成功态用例编码「仅失败态追加可选键」契约（向后兼容回归保护）。转绿计划：21-03/04。
# ============================================================================


async def _invoke_broadcast_hook(event: str, node_status: str):
    """触发 WebSocketBroadcastHook，返回 group_send 收到的 message dict。

    用 SimpleNamespace 构造 execution / node_execution（不触 DB），
    并 patch channels.layers.get_channel_layer 返回带 AsyncMock group_send 的 channel_layer。
    """
    from workflows.hooks.builtin import WebSocketBroadcastHook

    execution = SimpleNamespace(id="exec-obs-01", status="running")
    node_execution = SimpleNamespace(
        node_id="node-obs-01",
        status=node_status,
        error_message="变量解析失败",
        error_code="VAR_RESOLUTION_FAILED",
    )

    channel_layer = SimpleNamespace(group_send=AsyncMock())
    with patch("channels.layers.get_channel_layer", return_value=channel_layer):
        hook = WebSocketBroadcastHook()
        await hook.execute(event, execution=execution, node_execution=node_execution)

    channel_layer.group_send.assert_called_once()
    # group_send(group_name, message)
    return channel_layer.group_send.call_args.args[1]


@pytest.mark.asyncio
async def test_broadcast_failed_node_includes_error_fields() -> None:
    """OBS-01：node 失败广播 message 应含 error_message / error_code（修复前 RED）。"""
    message = await _invoke_broadcast_hook("node_failed", node_status="failed")
    assert message.get("error_message") == "变量解析失败"
    assert message.get("error_code") == "VAR_RESOLUTION_FAILED"


@pytest.mark.asyncio
async def test_broadcast_timeout_node_includes_error_fields() -> None:
    """OBS-01：node 超时（timeout）同样应附带 error 字段（修复前 RED）。"""
    message = await _invoke_broadcast_hook("node_failed", node_status="timeout")
    assert message.get("error_message") == "变量解析失败"
    assert message.get("error_code") == "VAR_RESOLUTION_FAILED"


@pytest.mark.asyncio
async def test_broadcast_success_node_omits_error_fields() -> None:
    """OBS-01 Pitfall 5：node 非失败态（completed）时 message 不应含 error_* 键（向后兼容）。"""
    message = await _invoke_broadcast_hook("node_completed", node_status="completed")
    assert "error_message" not in message
    assert "error_code" not in message
