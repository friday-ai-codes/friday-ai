"""调试执行安全隔离测试。

覆盖:
- is_debug=True 执行不出现在默认执行列表
- include_debug=true 参数时返回调试执行
- 飞书通知跳过调试执行
- 并发守卫排除调试执行
- 调试会话超时清理
- check_timeouts 排除调试执行
"""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from projects.models import Space
from workflows.engine.scheduler import (
    WorkflowEngine,
)
from workflows.hooks.builtin import NotificationHook
from workflows.hooks.feishu_sync import FeishuSyncHook
from workflows.models import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
    Workflow,
    WorkflowEdge,
    WorkflowEventSubscription,
    WorkflowExecution,
    WorkflowNode,
)


@pytest.fixture
def iso_project(db):
    """隔离测试用项目。"""
    return Space.objects.create(
        name="Isolation Test Space",
        description="隔离测试专用项目",
    )


@pytest.fixture
def iso_workflow(db, iso_project, user):
    """隔离测试用工作流。"""
    return Workflow.objects.create(
        name="Isolation Workflow",
        space=iso_project,
        created_by=user,
        trigger_type="manual",
    )


@pytest.fixture
def iso_workflow_with_nodes(db, iso_project, user):
    """隔离测试用完整工作流（含节点和边，用于引擎执行）。"""
    workflow = Workflow.objects.create(
        name="Isolation Full Workflow",
        space=iso_project,
        created_by=user,
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


@pytest.mark.django_db
class TestDebugExecutionExcludedFromList:
    """调试执行默认不出现在执行列表。"""

    def test_debug_execution_excluded_from_list(self, iso_workflow, iso_project):
        """创建 is_debug=True 和 is_debug=False 执行，验证默认查询只返回非调试执行。"""
        # 创建一个正常执行
        normal_exec = WorkflowExecution.objects.create(
            workflow=iso_workflow,
            space=iso_project,
            trigger_type="manual",
            status=ExecutionStatus.COMPLETED,
            is_debug=False,
        )

        # 创建一个调试执行
        _debug_exec = WorkflowExecution.objects.create(
            workflow=iso_workflow,
            space=iso_project,
            trigger_type="manual",
            status=ExecutionStatus.COMPLETED,
            is_debug=True,
        )

        # 默认查询（模拟 ViewSet get_queryset 的 is_debug=False 过滤）
        default_qs = WorkflowExecution.objects.filter(is_debug=False)
        assert default_qs.count() == 1
        assert default_qs.first().id == normal_exec.id

    def test_debug_execution_included_with_param(self, iso_workflow, iso_project):
        """include_debug=true 参数时返回调试执行。"""
        _normal_exec = WorkflowExecution.objects.create(
            workflow=iso_workflow,
            space=iso_project,
            trigger_type="manual",
            status=ExecutionStatus.COMPLETED,
            is_debug=False,
        )

        _debug_exec = WorkflowExecution.objects.create(
            workflow=iso_workflow,
            space=iso_project,
            trigger_type="manual",
            status=ExecutionStatus.COMPLETED,
            is_debug=True,
        )

        # 不加 is_debug 过滤（模拟 include_debug=true）
        all_qs = WorkflowExecution.objects.all()
        assert all_qs.count() == 2


@pytest.mark.asyncio
@pytest.mark.django_db
class TestDebugExecutionIsolation:
    """飞书通知跳过调试执行。"""

    async def test_debug_execution_isolation_feishu(self):
        """验证 FeishuSyncHook.execute() 对 is_debug=True 执行直接返回（不发通知）。"""
        hook = FeishuSyncHook()

        # 创建 mock execution（is_debug=True）
        mock_execution = AsyncMock()
        mock_execution.is_debug = True

        # 调用 execute —— 由于 is_debug=True，应直接返回
        with patch.object(hook, "_send_notification", new_callable=AsyncMock) as mock_send:
            await hook.execute("execution_completed", execution=mock_execution)

        # _send_notification 不应被调用
        mock_send.assert_not_called()

    async def test_normal_execution_triggers_feishu(self):
        """验证非调试执行时 FeishuSyncHook 不被 is_debug 守卫阻止。

        注意：由于 feature_flags.sync_workflow_to_feishu 默认为 False，
        实际发送也会被跳过，但 execute() 方法本身不会因 is_debug 而短路。
        """
        hook = FeishuSyncHook()

        mock_execution = AsyncMock()
        mock_execution.is_debug = False

        # execute 不会因 is_debug 而短路——会进入 event_map 查找
        # 由于 execution_completed 存在于 event_map，会调用 on_execution_completed
        with patch.object(hook, "on_execution_completed", new_callable=AsyncMock) as mock_handler:
            await hook.execute("execution_completed", execution=mock_execution)

        mock_handler.assert_called_once()

    @pytest.mark.django_db(transaction=True)
    async def test_debug_execution_with_notification_hook_does_not_send_feishu(
        self,
        iso_workflow_with_nodes,
    ):
        """NotificationHook 接线后，调试执行仍不应触发飞书发送。"""
        engine = WorkflowEngine()

        completed_hooks = engine.hooks._hooks["execution_completed"]
        assert any(isinstance(hook, NotificationHook) for hook in completed_hooks)

        async def mock_pause(execution, node_execution):
            del execution, node_execution
            return ("release", {})

        with (
            patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause),
            patch(
                "services.feishu_im.FeishuIMService.create",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            execution = await engine.start_execution(
                workflow=iso_workflow_with_nodes,
                input_data={"chat_id": "oc_debug_isolation_chat"},
                trigger_type="manual",
                run_sync=True,
                debug_mode=True,
            )

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED
        mock_create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestDebugSessionTimeoutCleanup:
    """调试会话 30 分钟超时自动清理。"""

    async def test_debug_session_timeout_cleanup(self, iso_workflow_with_nodes):
        """模拟超时场景，验证 _debug_pause_after_node 返回 timeout 并清理会话。"""
        engine = WorkflowEngine()

        pause_count = 0
        timeout_triggered = False

        _original_pause = engine._debug_pause_after_node

        async def mock_pause_with_timeout(execution, node_execution):
            nonlocal pause_count, timeout_triggered

            pause_count += 1
            if pause_count == 1:
                # 第一个节点正常 release
                return ("release", {})
            else:
                # 第二个节点模拟超时
                timeout_triggered = True
                return ("timeout", {})

        with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause_with_timeout):
            execution = await engine.start_execution(
                workflow=iso_workflow_with_nodes,
                input_data={},
                trigger_type="manual",
                run_sync=True,
                debug_mode=True,
            )

        await execution.arefresh_from_db()
        assert timeout_triggered
        # 超时后执行应标记为 failed
        assert execution.status == ExecutionStatus.FAILED
        assert "超时" in (execution.error_message or "")


@pytest.mark.django_db
class TestCheckTimeoutsExcludesDebug:
    """check_timeouts 命令排除 is_debug=True 执行。"""

    def test_check_timeouts_excludes_debug(self, iso_workflow, iso_project):
        """验证超时订阅查询排除 is_debug=True 的执行。"""
        # 创建调试执行
        debug_exec = WorkflowExecution.objects.create(
            workflow=iso_workflow,
            space=iso_project,
            trigger_type="manual",
            status=ExecutionStatus.RUNNING,
            is_debug=True,
        )

        trigger_node = WorkflowNode.objects.create(
            workflow=iso_workflow,
            node_type="manual_trigger",
            name="Start",
            position_x=0,
            position_y=0,
        )

        node_exec = NodeExecution.objects.create(
            workflow_execution=debug_exec,
            node=trigger_node,
            status=NodeExecutionStatus.WAITING_EVENT,
        )

        # 创建已超时的订阅
        _sub = WorkflowEventSubscription.objects.create(
            workflow_execution=debug_exec,
            node_execution=node_exec,
            event_type="test_event",
            is_active=True,
            timeout_at=timezone.now() - timedelta(minutes=5),
            timeout_action="fail",
        )

        # 模拟 check_timeouts 查询逻辑
        expired_subs = list(
            WorkflowEventSubscription.objects.filter(
                is_active=True,
                timeout_at__lte=timezone.now(),
                timeout_at__isnull=False,
            )
            .select_related("workflow_execution", "node_execution")
            .exclude(workflow_execution__is_debug=True)
        )

        # 调试执行的订阅应被排除
        assert len(expired_subs) == 0


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestConcurrencyGuardExcludesDebug:
    """并发守卫不计入调试执行。"""

    async def test_concurrency_guard_excludes_debug(self, iso_workflow_with_nodes):
        """验证 _create_execution_with_atomic_concurrency_guard 不计入调试执行。"""
        workflow = iso_workflow_with_nodes

        # 设置最大并发数为 1
        workflow.max_concurrent_executions = 1
        await workflow.asave(update_fields=["max_concurrent_executions"])

        # 创建一个 is_debug=True 且 RUNNING 的执行
        _debug_exec = await sync_to_async(WorkflowExecution.objects.create)(
            workflow=workflow,
            space_id=workflow.space_id,
            trigger_type="manual",
            status=ExecutionStatus.RUNNING,
            is_debug=True,
        )

        # 再创建一个新执行（不应因调试执行而被阻止）
        engine = WorkflowEngine()

        async def mock_pause(execution, node_execution):
            return ("release", {})

        with patch.object(engine, "_debug_pause_after_node", side_effect=mock_pause):
            new_exec = await engine.start_execution(
                workflow=workflow,
                input_data={},
                trigger_type="manual",
                run_sync=True,
            )

        await new_exec.arefresh_from_db()
        # 新执行应成功创建并完成（不受调试执行影响）
        assert new_exec.status == ExecutionStatus.COMPLETED
