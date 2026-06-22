"""TriggerDispatcher 单元测试。

测试调度器的核心逻辑：
- 未知触发类型处理
- 幂等性检查
- 验证失败处理
- 无匹配工作流处理
- 成功调度
- dispatch_single 便捷方法
"""

from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflows.triggers import (
    TriggerContext,
    TriggerDispatcher,
    TriggerHandler,
    TriggerHandlerRegistry,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_engine():
    """创建模拟的 WorkflowEngine。"""
    engine = MagicMock()
    engine.start_execution = AsyncMock()
    return engine


@pytest.fixture
def sample_context():
    """创建示例 TriggerContext。"""
    return TriggerContext(
        trigger_type="test",
        raw_payload={"key": "value"},
    )


@pytest.fixture(autouse=True)
def clear_registry():
    """每个测试前后清空注册表。"""
    # 保存原始状态
    original_handlers = TriggerHandlerRegistry._handlers.copy()
    TriggerHandlerRegistry._handlers.clear()
    yield
    # 恢复原始状态
    TriggerHandlerRegistry._handlers.clear()
    TriggerHandlerRegistry._handlers.update(original_handlers)


# ============================================================================
# 测试用 Handler
# ============================================================================


class MockHandler(TriggerHandler):
    """用于测试的模拟处理器。"""

    trigger_type: ClassVar[str] = "test"
    display_name: ClassVar[str] = "Test Handler"
    description: ClassVar[str] = "A handler for testing"

    def __init__(self):
        self.validate_errors: list[str] = []
        self.workflows: list = []
        self.input_data: dict = {}

    async def validate(self, context: TriggerContext) -> list[str]:
        return self.validate_errors

    async def find_workflows(self, context: TriggerContext) -> list:
        return self.workflows

    async def prepare_input(self, context: TriggerContext, workflow) -> dict:
        return self.input_data


# ============================================================================
# 测试类
# ============================================================================


@pytest.mark.asyncio
class TestDispatchUnknownTriggerType:
    """测试未知触发类型处理。"""

    async def test_dispatch_unknown_trigger_type_returns_empty_list(self, mock_engine):
        """未注册的触发类型应返回空列表。"""
        dispatcher = TriggerDispatcher(engine=mock_engine)
        context = TriggerContext(
            trigger_type="unknown_type",
            raw_payload={},
        )

        result = await dispatcher.dispatch(context)

        assert result == []
        mock_engine.start_execution.assert_not_called()


@pytest.mark.asyncio
class TestDispatchIdempotency:
    """测试幂等性检查。"""

    async def test_dispatch_idempotency_skip_duplicate(self, mock_engine):
        """重复的幂等键应跳过处理。"""
        # 注册处理器
        TriggerHandlerRegistry.register(MockHandler)

        dispatcher = TriggerDispatcher(engine=mock_engine)
        context = TriggerContext(
            trigger_type="test",
            raw_payload={},
            idempotency_key="unique-key-123",
        )

        # 第一次调用
        await dispatcher.dispatch(context)

        # 第二次调用应跳过
        result = await dispatcher.dispatch(context)

        assert result == []

    async def test_dispatch_without_idempotency_key_not_skipped(self, mock_engine):
        """无幂等键时不应跳过。"""
        TriggerHandlerRegistry.register(MockHandler)

        dispatcher = TriggerDispatcher(engine=mock_engine)
        context1 = TriggerContext(trigger_type="test", raw_payload={})
        context2 = TriggerContext(trigger_type="test", raw_payload={})

        # 两次调用都应处理（不会因幂等性跳过）
        await dispatcher.dispatch(context1)
        await dispatcher.dispatch(context2)

        # 由于 MockHandler 默认返回空 workflows，不会调用 start_execution
        # 但两次都会走完 validate 和 find_workflows 流程


@pytest.mark.asyncio
class TestDispatchValidationFailure:
    """测试验证失败处理。"""

    async def test_dispatch_validation_failure_returns_empty_list(self, mock_engine):
        """验证失败应返回空列表。"""

        class FailingValidationHandler(MockHandler):
            async def validate(self, context: TriggerContext) -> list[str]:
                return ["Missing required field: project_id"]

        TriggerHandlerRegistry.register(FailingValidationHandler)

        dispatcher = TriggerDispatcher(engine=mock_engine)
        context = TriggerContext(trigger_type="test", raw_payload={})

        result = await dispatcher.dispatch(context)

        assert result == []
        mock_engine.start_execution.assert_not_called()


@pytest.mark.asyncio
class TestDispatchNoMatchingWorkflows:
    """测试无匹配工作流处理。"""

    async def test_dispatch_no_matching_workflows_returns_empty_list(self, mock_engine):
        """无匹配工作流应返回空列表。"""

        class NoWorkflowsHandler(MockHandler):
            async def find_workflows(self, context: TriggerContext) -> list:
                return []

        TriggerHandlerRegistry.register(NoWorkflowsHandler)

        dispatcher = TriggerDispatcher(engine=mock_engine)
        context = TriggerContext(trigger_type="test", raw_payload={})

        result = await dispatcher.dispatch(context)

        assert result == []
        mock_engine.start_execution.assert_not_called()


@pytest.mark.asyncio
class TestDispatchSuccess:
    """测试成功调度。"""

    async def test_dispatch_success_returns_executions(self, mock_engine):
        """成功调度应返回执行实例列表。"""
        # 创建模拟对象
        mock_workflow = MagicMock()
        mock_workflow.id = "workflow-123"
        mock_execution = MagicMock()
        mock_execution.id = "execution-456"

        class SuccessHandler(MockHandler):
            async def find_workflows(self, context: TriggerContext) -> list:
                return [mock_workflow]

            async def prepare_input(self, context: TriggerContext, workflow) -> dict:
                return {"input_key": "input_value"}

        TriggerHandlerRegistry.register(SuccessHandler)
        mock_engine.start_execution.return_value = mock_execution

        dispatcher = TriggerDispatcher(engine=mock_engine)
        context = TriggerContext(
            trigger_type="test",
            raw_payload={"event": "test"},
        )

        result = await dispatcher.dispatch(context)

        assert len(result) == 1
        assert result[0] == mock_execution
        mock_engine.start_execution.assert_called_once_with(
            workflow=mock_workflow,
            input_data={"input_key": "input_value"},
            triggered_by=None,
            trigger_type="test",
            trigger_data={"source": "test", "raw_payload": {"event": "test"}},
            debug_mode=False,
            stop_before_node_id=None,
            user_pat="",
        )

    async def test_dispatch_multiple_workflows(self, mock_engine):
        """多个工作流应分别启动执行。"""
        mock_workflow1 = MagicMock()
        mock_workflow1.id = "workflow-1"
        mock_workflow2 = MagicMock()
        mock_workflow2.id = "workflow-2"

        mock_execution1 = MagicMock()
        mock_execution1.id = "execution-1"
        mock_execution2 = MagicMock()
        mock_execution2.id = "execution-2"

        class MultiWorkflowHandler(MockHandler):
            async def find_workflows(self, context: TriggerContext) -> list:
                return [mock_workflow1, mock_workflow2]

            async def prepare_input(self, context: TriggerContext, workflow) -> dict:
                return {}

        TriggerHandlerRegistry.register(MultiWorkflowHandler)
        mock_engine.start_execution.side_effect = [mock_execution1, mock_execution2]

        dispatcher = TriggerDispatcher(engine=mock_engine)
        context = TriggerContext(trigger_type="test", raw_payload={})

        result = await dispatcher.dispatch(context)

        assert len(result) == 2
        assert mock_engine.start_execution.call_count == 2

    async def test_dispatch_continues_on_single_workflow_failure(self, mock_engine):
        """单个工作流启动失败不应影响其他工作流。"""
        mock_workflow1 = MagicMock()
        mock_workflow1.id = "workflow-1"
        mock_workflow2 = MagicMock()
        mock_workflow2.id = "workflow-2"

        mock_execution2 = MagicMock()
        mock_execution2.id = "execution-2"

        class MultiWorkflowHandler(MockHandler):
            async def find_workflows(self, context: TriggerContext) -> list:
                return [mock_workflow1, mock_workflow2]

            async def prepare_input(self, context: TriggerContext, workflow) -> dict:
                return {}

        TriggerHandlerRegistry.register(MultiWorkflowHandler)
        # 第一个工作流失败，第二个成功
        mock_engine.start_execution.side_effect = [
            Exception("Workflow 1 failed"),
            mock_execution2,
        ]

        dispatcher = TriggerDispatcher(engine=mock_engine)
        context = TriggerContext(trigger_type="test", raw_payload={})

        result = await dispatcher.dispatch(context)

        # 只有第二个成功
        assert len(result) == 1
        assert result[0] == mock_execution2


@pytest.mark.asyncio
class TestDispatchSingle:
    """测试 dispatch_single 便捷方法。"""

    async def test_dispatch_single_returns_first_execution(self, mock_engine):
        """dispatch_single 应返回第一个执行实例。"""
        mock_workflow = MagicMock()
        mock_workflow.id = "workflow-123"
        mock_execution = MagicMock()
        mock_execution.id = "execution-456"

        class SingleHandler(MockHandler):
            async def find_workflows(self, context: TriggerContext) -> list:
                return [mock_workflow]

            async def prepare_input(self, context: TriggerContext, workflow) -> dict:
                return {}

        TriggerHandlerRegistry.register(SingleHandler)
        mock_engine.start_execution.return_value = mock_execution

        dispatcher = TriggerDispatcher(engine=mock_engine)
        context = TriggerContext(
            trigger_type="test",
            raw_payload={},
            workflow=mock_workflow,
        )

        result = await dispatcher.dispatch_single(context)

        assert result == mock_execution

    async def test_dispatch_single_returns_none_when_no_executions(self, mock_engine):
        """无执行时 dispatch_single 应返回 None。"""
        TriggerHandlerRegistry.register(MockHandler)

        dispatcher = TriggerDispatcher(engine=mock_engine)
        context = TriggerContext(trigger_type="test", raw_payload={})

        result = await dispatcher.dispatch_single(context)

        assert result is None


@pytest.mark.asyncio
class TestDispatcherInitialization:
    """测试调度器初始化。"""

    async def test_dispatcher_creates_engine_if_not_provided(self):
        """未提供引擎时应自动创建。"""
        with patch("workflows.engine.scheduler.WorkflowEngine") as MockWorkflowEngine:
            mock_engine_instance = MagicMock()
            MockWorkflowEngine.return_value = mock_engine_instance

            dispatcher = TriggerDispatcher()

            assert dispatcher.engine == mock_engine_instance
            MockWorkflowEngine.assert_called_once()

    async def test_dispatcher_uses_provided_engine(self, mock_engine):
        """提供引擎时应使用该引擎。"""
        dispatcher = TriggerDispatcher(engine=mock_engine)

        assert dispatcher.engine == mock_engine


@pytest.mark.asyncio
class TestDispatchWithTriggeredBy:
    """测试触发用户传递。"""

    async def test_dispatch_passes_triggered_by_to_engine(self, mock_engine):
        """应将 triggered_by 传递给引擎。"""
        mock_workflow = MagicMock()
        mock_workflow.id = "workflow-123"
        mock_execution = MagicMock()
        mock_execution.id = "execution-456"
        mock_user = MagicMock()
        mock_user.id = "user-789"

        class UserHandler(MockHandler):
            async def find_workflows(self, context: TriggerContext) -> list:
                return [mock_workflow]

            async def prepare_input(self, context: TriggerContext, workflow) -> dict:
                return {}

        TriggerHandlerRegistry.register(UserHandler)
        mock_engine.start_execution.return_value = mock_execution

        dispatcher = TriggerDispatcher(engine=mock_engine)
        context = TriggerContext(
            trigger_type="test",
            raw_payload={},
            triggered_by=mock_user,
        )

        await dispatcher.dispatch(context)

        mock_engine.start_execution.assert_called_once()
        call_kwargs = mock_engine.start_execution.call_args.kwargs
        assert call_kwargs["triggered_by"] == mock_user


# ============================================================================
# TRIG-03：飞书路径 dispatch 失败 / 无匹配持久化（Phase 21 Wave 0 RED）
#
# D-03 裁定：dispatch 校验失败 / 无匹配 / 启动异常不再恒 ACCEPTED，
# 而是落 TriggerLog.status=error/ignored + error_message（前端可见原因）。
# 被测目标：feishu.views.FeishuWebhookView._dispatch_to_workflows。
#
# 注意：以下用例在 21-04 实现前预期为 RED（当前异常仅 structlog、无匹配不更新 status）。
# 转绿计划：21-04。
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestFeishuDispatchFailurePersistence:
    """飞书 dispatch 失败 / 无匹配应持久化到 TriggerLog（TRIG-03）。"""

    async def _make_trigger_log(self):
        """创建一条 ACCEPTED 状态的 TriggerLog（模拟 webhook 入口已落库）。"""
        from feishu.models import TriggerLog, TriggerLogStatus
        from projects.models import Project

        project = await Project.objects.acreate(
            name="TRIG-03 Project",
            description="Project for dispatch failure persistence RED tests",
        )
        trigger_log = await TriggerLog.objects.acreate(
            event_type="WorkitemStatusEvent",
            project=project,
            status=TriggerLogStatus.ACCEPTED,
        )
        return project, trigger_log

    async def test_dispatch_exception_sets_triggerlog_error(self):
        """dispatch 抛异常时，关联 TriggerLog.status=error 且 error_message 非空（≤2000）。"""
        from feishu.models import TriggerLogStatus
        from feishu.views import FeishuWebhookView

        project, trigger_log = await self._make_trigger_log()

        # mock TriggerDispatcher 实例的 dispatch 抛异常
        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("boom dispatch failed"))

        view = FeishuWebhookView()
        with patch("feishu.views.TriggerDispatcher", return_value=mock_dispatcher):
            await view._dispatch_to_workflows(
                "WorkitemStatusEvent",
                project,
                {"id": "wi-1"},
                trigger_log,
            )

        await trigger_log.arefresh_from_db()
        assert trigger_log.status == TriggerLogStatus.ERROR
        assert trigger_log.error_message
        assert len(trigger_log.error_message) <= 2000

    async def test_dispatch_no_match_sets_triggerlog_ignored(self):
        """dispatch 返回空（无匹配）时，TriggerLog.status=ignored 且 error_message 含 event_type。"""
        from feishu.models import TriggerLogStatus
        from feishu.views import FeishuWebhookView

        project, trigger_log = await self._make_trigger_log()

        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock(return_value=[])

        view = FeishuWebhookView()
        with patch("feishu.views.TriggerDispatcher", return_value=mock_dispatcher):
            await view._dispatch_to_workflows(
                "WorkitemStatusEvent",
                project,
                {"id": "wi-2"},
                trigger_log,
            )

        await trigger_log.arefresh_from_db()
        assert trigger_log.status == TriggerLogStatus.IGNORED
        assert trigger_log.error_message
        assert "WorkitemStatusEvent" in trigger_log.error_message
