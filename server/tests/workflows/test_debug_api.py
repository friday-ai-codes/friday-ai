"""API 层 debug_mode 透传集成测试。

implementation: 验证 debug_mode 从 Serializer → TriggerContext → Dispatcher 的完整透传链。

覆盖:
- WorkflowExecuteSerializer 接受 debug_mode 布尔字段
- TriggerContext 包含 debug_mode 字段（默认 False）
- TriggerDispatcher.dispatch() 透传 debug_mode 到 engine.start_execution()
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflows.api.serializers import WorkflowExecuteSerializer
from workflows.triggers.context import TriggerContext
from workflows.triggers.dispatcher import TriggerDispatcher


class TestExecuteSerializerDebugMode:
    """WorkflowExecuteSerializer debug_mode 字段测试。"""

    def test_accepts_debug_mode_true(self):
        """debug_mode=True 时 validated_data 正确包含该值。"""
        s = WorkflowExecuteSerializer(data={"debug_mode": True})
        assert s.is_valid(), s.errors
        assert s.validated_data["debug_mode"] is True

    def test_defaults_debug_mode_false(self):
        """不传 debug_mode 时默认为 False。"""
        s = WorkflowExecuteSerializer(data={})
        assert s.is_valid(), s.errors
        assert s.validated_data["debug_mode"] is False

    def test_accepts_debug_mode_false_explicitly(self):
        """显式传 debug_mode=False 时正确处理。"""
        s = WorkflowExecuteSerializer(data={"debug_mode": False})
        assert s.is_valid(), s.errors
        assert s.validated_data["debug_mode"] is False


class TestTriggerContextDebugMode:
    """TriggerContext dataclass debug_mode 字段测试。"""

    def test_debug_mode_true(self):
        """显式设置 debug_mode=True。"""
        ctx = TriggerContext(trigger_type="manual", raw_payload={}, debug_mode=True)
        assert ctx.debug_mode is True

    def test_debug_mode_default_false(self):
        """不设置 debug_mode 时默认 False。"""
        ctx = TriggerContext(trigger_type="manual", raw_payload={})
        assert ctx.debug_mode is False


class TestDispatcherDebugModePassthrough:
    """TriggerDispatcher 透传 debug_mode 到 engine.start_execution()。"""

    @pytest.mark.asyncio
    async def test_passes_debug_mode_to_engine(self):
        """dispatch() 将 context.debug_mode 透传到 start_execution。"""
        # 构造 mock 工作流
        mock_workflow = MagicMock()
        mock_workflow.id = "test-workflow-id"
        mock_workflow.is_active = True

        # 构造 mock 执行结果
        mock_execution = MagicMock()
        mock_execution.id = "test-execution-id"

        # 构造 dispatcher，mock 引擎
        dispatcher = TriggerDispatcher()
        dispatcher.engine = MagicMock()
        dispatcher.engine.start_execution = AsyncMock(return_value=mock_execution)

        # 构造带 debug_mode=True 的 context
        context = TriggerContext(
            trigger_type="manual",
            raw_payload={"test": "data"},
            workflow=mock_workflow,
            triggered_by=None,
            debug_mode=True,
        )

        # Mock handler：validate 返回空列表（通过），find_workflows 返回工作流，prepare_input 返回输入
        mock_handler_instance = MagicMock()
        mock_handler_instance.validate = AsyncMock(return_value=[])
        mock_handler_instance.find_workflows = AsyncMock(return_value=[mock_workflow])
        mock_handler_instance.prepare_input = AsyncMock(return_value={"test": "data"})

        mock_handler_class = MagicMock(return_value=mock_handler_instance)

        with patch(
            "workflows.triggers.dispatcher.TriggerHandlerRegistry.get",
            return_value=mock_handler_class,
        ):
            _executions = await dispatcher.dispatch(context)

        # 验证 start_execution 被调用时包含 debug_mode=True
        dispatcher.engine.start_execution.assert_called_once()
        call_kwargs = dispatcher.engine.start_execution.call_args.kwargs
        assert call_kwargs.get("debug_mode") is True, (
            f"debug_mode 未透传到 start_execution, kwargs: {call_kwargs}"
        )
