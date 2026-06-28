"""P9「工作流即端点」接缝测试。

覆盖：
- tool_invoke TriggerHandler：tool_name→trigger 查找、派发、prepare_input 包装；
- input_schema 校验接线：非法入参被拦截（dispatch 返回空，引擎不启动），合法入参放行；
- output_schema 投影：project_output / build_tool_result 纯函数；
- 同步等结果最小实现：await_execution_result 终态返回 / 超时返回 None；
- 端点 view：ToolInvokeView 异步受理（202）与无匹配（404）。

注：本文件位于 workflows/tests/，不复用 server/tests/conftest.py 的 fixture，
对象（Space/Workflow/WorkflowTrigger/WorkflowExecution）就地创建。
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from projects.models import Space
from workflows.models import Workflow, WorkflowExecution, WorkflowTrigger
from workflows.models.execution import ExecutionStatus
from workflows.triggers import (
    TriggerContext,
    TriggerDispatcher,
    await_execution_result,
    build_tool_result,
    project_output,
)
from workflows.triggers.handlers.tool_invoke import ToolInvokeHandler

# ============================================================================
# Helpers
# ============================================================================


async def _make_workflow(*, is_active: bool = True, output_schema: dict | None = None) -> Workflow:
    space = await Space.objects.acreate(name="P9 Space", description="tool invoke seam")
    return await Workflow.objects.acreate(
        name="P9 Tool Workflow",
        space=space,
        is_active=is_active,
        output_schema=output_schema or {},
    )


async def _make_trigger(
    workflow: Workflow,
    *,
    token: str,
    input_schema: dict | None = None,
    is_active: bool = True,
) -> WorkflowTrigger:
    return await WorkflowTrigger.objects.acreate(
        workflow=workflow,
        token=token,
        input_schema=input_schema or {},
        is_active=is_active,
    )


def _mock_engine() -> Any:
    engine = MagicMock()
    engine.start_execution = AsyncMock(return_value=MagicMock(id="exec-1"))
    return engine


def _tool_context(tool_name: str, arguments: dict) -> TriggerContext:
    return TriggerContext(
        trigger_type="tool_invoke",
        raw_payload=arguments,
        metadata={"tool_name": tool_name, "arguments": arguments},
    )


# ============================================================================
# tool_invoke handler / dispatch
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestToolInvokeDispatch:
    async def test_dispatch_success_wraps_arguments(self) -> None:
        """命中 token → 启动执行，input_data 包 {trigger_type, raw_payload, tool_name}。"""
        workflow = await _make_workflow()
        await _make_trigger(workflow, token="echo_tool")

        engine = _mock_engine()
        dispatcher = TriggerDispatcher(engine=engine)
        result = await dispatcher.dispatch(_tool_context("echo_tool", {"x": 1}))

        assert len(result) == 1
        engine.start_execution.assert_awaited_once()
        kwargs = engine.start_execution.call_args.kwargs
        assert kwargs["trigger_type"] == "tool_invoke"
        assert kwargs["input_data"] == {
            "trigger_type": "tool_invoke",
            "raw_payload": {"x": 1},
            "tool_name": "echo_tool",
        }
        assert kwargs["workflow"].id == workflow.id

    async def test_dispatch_unknown_tool_returns_empty(self) -> None:
        """tool_name 无匹配触发器 → 空列表，引擎不启动。"""
        engine = _mock_engine()
        dispatcher = TriggerDispatcher(engine=engine)
        result = await dispatcher.dispatch(_tool_context("missing_tool", {}))

        assert result == []
        engine.start_execution.assert_not_called()

    async def test_dispatch_missing_tool_name_returns_empty(self) -> None:
        """缺 metadata.tool_name → 校验失败 → 空列表。"""
        engine = _mock_engine()
        dispatcher = TriggerDispatcher(engine=engine)
        ctx = TriggerContext(trigger_type="tool_invoke", raw_payload={}, metadata={})
        result = await dispatcher.dispatch(ctx)

        assert result == []
        engine.start_execution.assert_not_called()

    async def test_inactive_trigger_not_matched(self) -> None:
        """禁用触发器不命中。"""
        workflow = await _make_workflow()
        await _make_trigger(workflow, token="off_tool", is_active=False)

        engine = _mock_engine()
        dispatcher = TriggerDispatcher(engine=engine)
        result = await dispatcher.dispatch(_tool_context("off_tool", {}))

        assert result == []
        engine.start_execution.assert_not_called()


# ============================================================================
# input_schema 校验接线
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestInputSchemaValidation:
    _SCHEMA = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    async def test_invalid_input_rejected(self) -> None:
        """缺 required 字段 → input_schema 校验拦截 → 不启动执行。"""
        workflow = await _make_workflow()
        await _make_trigger(workflow, token="schema_tool", input_schema=self._SCHEMA)

        engine = _mock_engine()
        dispatcher = TriggerDispatcher(engine=engine)
        # arguments 缺 name
        result = await dispatcher.dispatch(_tool_context("schema_tool", {"other": 1}))

        assert result == []
        engine.start_execution.assert_not_called()

    async def test_valid_input_passes(self) -> None:
        """满足 schema → 放行启动执行。"""
        workflow = await _make_workflow()
        await _make_trigger(workflow, token="schema_tool2", input_schema=self._SCHEMA)

        engine = _mock_engine()
        dispatcher = TriggerDispatcher(engine=engine)
        result = await dispatcher.dispatch(_tool_context("schema_tool2", {"name": "ok"}))

        assert len(result) == 1
        engine.start_execution.assert_awaited_once()

    async def test_handler_validate_returns_schema_errors(self) -> None:
        """直接调 handler.validate：非法入参返回非空错误列表。"""
        workflow = await _make_workflow()
        await _make_trigger(workflow, token="schema_tool3", input_schema=self._SCHEMA)

        handler = ToolInvokeHandler()
        errors = await handler.validate(_tool_context("schema_tool3", {"name": 123}))
        assert errors  # name 应为 string，123 非法


# ============================================================================
# output_schema 投影（纯函数）
# ============================================================================


class TestProjectOutput:
    def test_empty_schema_returns_copy(self) -> None:
        data = {"a": 1, "b": 2}
        result = project_output(data, {})
        assert result == data
        assert result is not data  # 浅拷贝，不改原对象

    def test_none_schema_returns_copy(self) -> None:
        assert project_output({"a": 1}, None) == {"a": 1}
        assert project_output(None, None) == {}

    def test_projects_declared_properties_only(self) -> None:
        data = {"result": "ok", "secret": "leak", "count": 5}
        schema = {
            "type": "object",
            "properties": {"result": {"type": "string"}, "count": {"type": "integer"}},
        }
        assert project_output(data, schema) == {"result": "ok", "count": 5}

    def test_fills_default_for_missing_key(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "result": {"type": "string"},
                "status": {"type": "string", "default": "unknown"},
            },
        }
        assert project_output({"result": "ok"}, schema) == {
            "result": "ok",
            "status": "unknown",
        }


# ============================================================================
# build_tool_result / await_execution_result
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestResultHelpers:
    _SCHEMA = {"type": "object", "properties": {"result": {"type": "string"}}}

    async def _make_execution(self, **kwargs: Any) -> WorkflowExecution:
        workflow = await _make_workflow(output_schema=self._SCHEMA)
        defaults: dict[str, Any] = {
            "workflow": workflow,
            "space": workflow.space,
            "trigger_type": "tool_invoke",
            "status": ExecutionStatus.COMPLETED,
        }
        defaults.update(kwargs)
        return await WorkflowExecution.objects.acreate(**defaults)

    async def test_build_result_completed(self) -> None:
        execution = await self._make_execution(
            status=ExecutionStatus.COMPLETED,
            output_data={"result": "done", "noise": "x"},
        )
        result = build_tool_result(execution, self._SCHEMA)
        assert result["succeeded"] is True
        assert result["status"] == ExecutionStatus.COMPLETED
        assert result["output"] == {"result": "done"}  # noise 被投影裁剪
        assert result["error"] == ""

    async def test_build_result_failed(self) -> None:
        execution = await self._make_execution(
            status=ExecutionStatus.FAILED,
            error_message="boom",
        )
        result = build_tool_result(execution, self._SCHEMA)
        assert result["succeeded"] is False
        assert result["error"] == "boom"

    async def test_await_returns_on_terminal(self) -> None:
        execution = await self._make_execution(
            status=ExecutionStatus.COMPLETED,
            output_data={"result": "ok"},
        )
        finished = await await_execution_result(
            str(execution.id), timeout=2.0, poll_interval=0.05
        )
        assert finished is not None
        assert finished.status == ExecutionStatus.COMPLETED

    async def test_await_timeout_when_pending(self) -> None:
        execution = await self._make_execution(status=ExecutionStatus.RUNNING)
        finished = await await_execution_result(
            str(execution.id), timeout=0.2, poll_interval=0.05
        )
        assert finished is None

    async def test_await_missing_execution_returns_none(self) -> None:
        finished = await await_execution_result(
            "00000000-0000-0000-0000-000000000000", timeout=0.2, poll_interval=0.05
        )
        assert finished is None


# ============================================================================
# 端点 view（ToolInvokeView）
# ============================================================================


class TestToolInvokeEndpoint:
    """端点 view 测试（同步 APIClient 调 adrf 异步 view，dispatcher 被 mock）。"""

    def test_async_invoke_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """wait=false → 202 + execution_id（不等结果）。"""
        from rest_framework.test import APIClient

        fake_workflow = MagicMock()
        fake_workflow.id = "wf-async"
        fake_workflow.output_schema = {}
        fake_execution = MagicMock()
        fake_execution.id = "exec-async"
        fake_execution.workflow = fake_workflow

        class _FakeDispatcher:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            async def dispatch(self, ctx: TriggerContext) -> list[Any]:
                return [fake_execution]

        monkeypatch.setattr(
            "workflows.api.tool_endpoint.TriggerDispatcher", _FakeDispatcher
        )

        client = APIClient()
        response = client.post(
            "/api/workflows/tools/ep_tool/invoke/",
            {"arguments": {"x": 1}, "wait": False},
            format="json",
        )
        assert response.status_code == 202
        assert response.data["status"] == "accepted"
        assert response.data["execution_id"] == "exec-async"

    def test_no_match_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无匹配 / 校验失败 → 404。"""
        from rest_framework.test import APIClient

        class _EmptyDispatcher:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            async def dispatch(self, ctx: TriggerContext) -> list[Any]:
                return []

        monkeypatch.setattr(
            "workflows.api.tool_endpoint.TriggerDispatcher", _EmptyDispatcher
        )

        client = APIClient()
        response = client.post(
            "/api/workflows/tools/nope/invoke/",
            {"arguments": {}},
            format="json",
        )
        assert response.status_code == 404
        assert response.data["status"] == "not_found"
