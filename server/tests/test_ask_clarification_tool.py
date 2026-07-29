"""``ask_clarification`` 工具层测试（implementation / work item）。

覆盖：

- 工具注册：``ToolRegistry.get_tool`` 能拿到 ToolDefinition，category 为
  ``COMMUNICATION``，parameters schema 含 question / options / allow_freeform。
- 静态参数校验：空 question / options 数量越界 / id 重复 / label 缺失等。
- 成功路径：返回 ``ToolResult.output`` 携带 ``pending=True`` +
  ``marker="ask_clarification"`` + 原 options 字节级回传。

工具内部不写 DB / 不调外部服务，故全用 ``pytest.mark.asyncio`` 直接 await
``ask_clarification(...)``，无须 Django DB fixture。
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from agents.tools.base import ToolCategory, ToolResult
from agents.tools.clarification import (
    CLARIFICATION_PENDING_MARKER,
    ask_clarification,
)
from agents.tools.registry import ToolRegistry


def _valid_options() -> list[dict[str, Any]]:
    return [
        {
            "id": "opt-A",
            "label": "改后端 API",
            "hint": "修改 friday-server",
            "implies": {"selected_repository_ids": ["uuid-1"]},
        },
        {
            "id": "opt-B",
            "label": "改前端 UI",
            "hint": "修改 friday-web",
            "implies": {"selected_repository_ids": ["uuid-2"]},
        },
    ]


class TestAskClarificationRegistry:
    """工具注册到 ToolRegistry，category 正确，schema 完整。"""

    def test_register_visible(self) -> None:
        tool_def = ToolRegistry.get_tool("ask_clarification")
        assert tool_def is not None
        assert tool_def.name == "ask_clarification"

    def test_category_is_communication(self) -> None:
        tool_def = ToolRegistry.get_tool("ask_clarification")
        assert tool_def is not None
        assert tool_def.category == ToolCategory.COMMUNICATION

    def test_schema_required_keys(self) -> None:
        tool_def = ToolRegistry.get_tool("ask_clarification")
        assert tool_def is not None
        props = tool_def.parameters.get("properties", {})
        assert "question" in props
        assert "options" in props
        assert "allow_freeform" in props
        assert "conversation_id" in props
        assert "auto-injected" in props["conversation_id"]["description"]
        required = set(tool_def.parameters.get("required", []))
        assert {"question", "options"}.issubset(required)
        assert "conversation_id" not in required


class TestAskClarificationValidation:
    """静态校验：错误入参返回 ``ToolResult(success=False)`` 不抛异常。"""

    @pytest.mark.asyncio
    async def test_empty_question_rejected(self) -> None:
        result = await ask_clarification("", _valid_options())
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "question" in (result.error or "")

    @pytest.mark.asyncio
    async def test_too_short_question_rejected(self) -> None:
        result = await ask_clarification("hi", _valid_options())
        assert result.success is False

    @pytest.mark.asyncio
    async def test_too_few_options_rejected(self) -> None:
        result = await ask_clarification(
            "请帮我确认一下", [{"id": "opt-A", "label": "唯一选项"}],
        )
        assert result.success is False
        assert "options" in (result.error or "")

    @pytest.mark.asyncio
    async def test_too_many_options_rejected(self) -> None:
        opts = [
            {"id": f"opt-{i}", "label": f"选项 {i}"} for i in range(7)
        ]
        result = await ask_clarification("请帮我确认一下", opts)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_duplicate_option_id_rejected(self) -> None:
        opts: list[dict[str, Any]] = [
            {"id": "dup", "label": "选项一"},
            {"id": "dup", "label": "选项二"},
        ]
        result = await ask_clarification("请帮我确认一下", opts)
        assert result.success is False
        assert "重复" in (result.error or "")

    @pytest.mark.asyncio
    async def test_option_missing_label_rejected(self) -> None:
        opts: list[dict[str, Any]] = [
            {"id": "opt-A", "label": "正常"},
            {"id": "opt-B"},  # 缺 label
        ]
        result = await ask_clarification("请帮我确认一下", opts)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_option_label_too_long_rejected(self) -> None:
        opts = [
            {"id": "opt-A", "label": "x" * 200},
            {"id": "opt-B", "label": "正常"},
        ]
        result = await ask_clarification("请帮我确认一下", opts)
        assert result.success is False


class TestAskClarificationSuccess:
    """成功路径：返回 ``pending=True`` + marker + 原 options 字节级回传。"""

    @pytest.mark.asyncio
    async def test_returns_pending_marker(self) -> None:
        opts = _valid_options()
        result = await ask_clarification(
            question="你想改哪个仓库？", options=opts, allow_freeform=True,
        )
        assert result.success is True
        assert isinstance(result.output, dict)
        assert result.output["pending"] is True
        assert result.output["marker"] == CLARIFICATION_PENDING_MARKER
        assert isinstance(result.output["clarification_id"], str)
        assert len(result.output["clarification_id"]) >= 16

    @pytest.mark.asyncio
    async def test_options_echo_byte_level(self) -> None:
        opts = _valid_options()
        result = await ask_clarification("你想改哪个仓库？", opts)
        assert result.success is True
        assert isinstance(result.output, dict)
        echo = result.output["options"]
        assert echo == opts

    @pytest.mark.asyncio
    async def test_allow_freeform_default_true(self) -> None:
        result = await ask_clarification("你想改哪个仓库？", _valid_options())
        assert result.success is True
        assert isinstance(result.output, dict)
        assert result.output["allow_freeform"] is True

    @pytest.mark.asyncio
    async def test_allow_freeform_explicit_false(self) -> None:
        result = await ask_clarification(
            "你想改哪个仓库？", _valid_options(), allow_freeform=False,
        )
        assert result.success is True
        assert isinstance(result.output, dict)
        assert result.output["allow_freeform"] is False

    @pytest.mark.asyncio
    async def test_different_calls_get_unique_clarification_id(self) -> None:
        r1 = await ask_clarification("你想改哪个仓库？", _valid_options())
        r2 = await ask_clarification("你想改哪个仓库？", _valid_options())
        assert r1.success and r2.success
        assert isinstance(r1.output, dict) and isinstance(r2.output, dict)
        assert r1.output["clarification_id"] != r2.output["clarification_id"]


class TestSolutionScopeGuard:
    @staticmethod
    def _bind_project(monkeypatch: pytest.MonkeyPatch, project_id: object) -> None:
        monkeypatch.setattr(
            "agents.tools.clarification._resolve_bound_project",
            AsyncMock(return_value=project_id),
        )

    @pytest.mark.asyncio
    async def test_bound_project_scope_question_is_blocked(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._bind_project(monkeypatch, "project-1")
        options = [
            {"id": "all", "label": "全部 12 个模块"},
            {"id": "some", "label": "只做部分模块"},
        ]
        result = await ask_clarification(
            "本次技术方案覆盖哪些模块？",
            options,
            conversation_id="conversation-1",
        )
        assert result.success is False
        assert "start_feature_solution" in (result.error or "")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("category", ["feature_solution", "full_tech_plan"])
    async def test_solution_category_is_blocked_even_with_weak_question(
        self, monkeypatch: pytest.MonkeyPatch, category: str,
    ) -> None:
        self._bind_project(monkeypatch, "project-1")
        options = _valid_options()
        options[0]["implies"]["task_category"] = category
        result = await ask_clarification(
            "请选择下一步操作",
            options,
            conversation_id="conversation-1",
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_repository_selection_coding_change_is_allowed(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._bind_project(monkeypatch, "project-1")
        options = _valid_options()
        for option in options:
            option["implies"]["task_category"] = "coding_change"
        result = await ask_clarification(
            "请选择要修改哪个仓库",
            options,
            conversation_id="conversation-1",
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_unbound_conversation_scope_question_is_allowed(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._bind_project(monkeypatch, None)
        result = await ask_clarification(
            "本次技术方案覆盖哪些模块？",
            [
                {"id": "all", "label": "全部模块"},
                {"id": "some", "label": "部分模块"},
            ],
            conversation_id="conversation-1",
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_unknown_task_category_is_stripped_without_failing(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._bind_project(monkeypatch, "project-1")
        options = _valid_options()
        options[0]["implies"]["task_category"] = "invented_category"
        result = await ask_clarification(
            "请选择要修改哪个仓库",
            options,
            conversation_id="conversation-1",
        )
        assert result.success is True
        assert "task_category" not in result.output["options"][0]["implies"]
