"""initial implementation plan Task 01 — contract ContextWindowExceededError → SSE ERROR payload 契约。

覆盖 contract 验收项：AIAgentBaseNode.execute 捕获 ContextWindowExceededError 时，
NodeResult.output 必须包含结构化 payload：

    {
        "error_code": "context_window_exceeded",
        "detail": "<error message>",
        "estimated_tokens": <int>,
        "max_tokens": <int>,
        "exceeded_by": <int>,
        "model": "<string>",
        "recommended_actions": [
            {"id": "trim_prompt", "label": ..., "action_type": "navigate", "target": "/prompts/"},
            {"id": "switch_model", "label": ..., "action_type": "navigate", "target": "settings.model"},
            {"id": "cleanup_history", "label": ..., "action_type": "dialog", "target": "CleanupDialog"},
        ],
    }

Test matrix:
    A: 标准消息格式 → regex 命中 → 5 字段齐全
    B: regex 不匹配 → fallback 0 值但 error_code / recommended_actions 仍写入
"""
from __future__ import annotations

import pytest

from agents.langchain_runner import ContextWindowExceededError


# ============================================================================
# 复用 Task 1 execute() 捕获分支：构造最小 AIAgentBaseNode 子类
# ============================================================================


class _RaiseContextExceeded:
    """测试桩：让 base_agent.execute 在 try 块内抛 ContextWindowExceededError。

    方案：monkeypatch AIAgentBaseNode._resolve_from_snapshot_or_runtime，
    使其直接 raise 指定错误消息 —— 流程会走到 except ContextWindowExceededError 分支。
    """

    def __init__(self, message: str) -> None:
        self.message = message

    async def __call__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise ContextWindowExceededError(self.message)


async def _run_execute_and_capture(
    make_minimal_context,
    monkeypatch,
    error_message: str,
    model_config: str = "claude-3-5-sonnet-20241022",
):
    """执行 AIAgentBaseNode.execute 并返回 NodeResult（except 分支输出）。

    使用最小化 AIAgentBaseNode 子类（注意：AIPromptNode 直接继承 BaseNode，
    不走 AIAgentBaseNode.execute 的 except 分支；本测试使用专门的 _FakeAIAgent 走 base 路径）。
    """
    from workflows.nodes.ai.base_agent import AIAgentBaseNode

    class _FakeAIAgent(AIAgentBaseNode):
        node_type = "fake_ai_agent"

        def get_system_prompt(self, ctx) -> str:  # type: ignore[no-untyped-def]
            return ctx.node_config.get("system_prompt", "")

        def get_user_prompt(self, ctx) -> str:  # type: ignore[no-untyped-def]
            return ctx.node_config.get("user_prompt", "")

    node = _FakeAIAgent()

    # 让 _resolve_from_snapshot_or_runtime raise ContextWindowExceededError。
    # 直接 patch 到 base class（所有 AI 节点 MRO 命中），raising=False 避免
    # 属性已存在/未存在的严格检查失败。
    monkeypatch.setattr(
        AIAgentBaseNode,
        "_resolve_from_snapshot_or_runtime",
        _RaiseContextExceeded(error_message),
        raising=False,
    )

    # 最小 ctx：system_prompt / user_prompt 走 config
    ctx = make_minimal_context(
        node_config={
            "system_prompt": "you are helpful",
            "user_prompt": "hi",
            "model": model_config,
        },
    )
    return await node.execute(ctx)


# ============================================================================
# Test A — 标准消息格式：regex 命中 → 5 字段 + recommended_actions
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_context_exceeded_payload_has_structured_fields(
    make_minimal_context,
    monkeypatch,
) -> None:
    """Behavior A：标准 langchain_runner 消息格式 → 5 字段 + 3 actions。"""
    msg = (
        "context too long: 200000 tokens > budget 150000 "
        "(max_input=128000, max_output=22000, buffer=800)"
    )
    result = await _run_execute_and_capture(
        make_minimal_context, monkeypatch, msg, model_config="claude-3-5-sonnet-20241022"
    )

    assert result.status == "failed"
    assert result.next_handle == "error"
    assert isinstance(result.output, dict)

    output = result.output
    assert output["error_code"] == "context_window_exceeded"
    assert output["detail"] == msg
    assert output["estimated_tokens"] == 200000
    assert output["max_tokens"] == 150000
    assert output["exceeded_by"] == 50000
    assert output["model"] == "claude-3-5-sonnet-20241022"

    # recommended_actions 必为 3 items，按风险倒序
    actions = output["recommended_actions"]
    assert isinstance(actions, list)
    assert len(actions) == 3

    action_ids = [a["id"] for a in actions]
    assert action_ids == ["trim_prompt", "switch_model", "cleanup_history"]

    # 每个 action 必含四字段
    for action in actions:
        assert "id" in action
        assert "label" in action
        assert "action_type" in action
        assert "target" in action

    # 具体目标契约（work item §I-6）
    by_id = {a["id"]: a for a in actions}
    assert by_id["trim_prompt"]["action_type"] == "navigate"
    assert by_id["trim_prompt"]["target"] == "/prompts/"
    assert by_id["switch_model"]["action_type"] == "navigate"
    assert by_id["switch_model"]["target"] == "settings.model"
    assert by_id["cleanup_history"]["action_type"] == "dialog"
    assert by_id["cleanup_history"]["target"] == "CleanupDialog"


# ============================================================================
# Test B — regex 不匹配：fallback 0 值但 error_code / recommended_actions 仍写入
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_context_exceeded_non_standard_message_falls_back_to_zero_tokens(
    make_minimal_context,
    monkeypatch,
) -> None:
    """Behavior B：消息格式不匹配 regex → estimated=0 max_tokens=0 exceeded_by=0，
    但 error_code 和 recommended_actions 仍写入（未来 Provider 消息格式变化下的容错路径）。
    """
    msg = "some non-standard context window error"
    result = await _run_execute_and_capture(
        make_minimal_context, monkeypatch, msg, model_config="some-model"
    )

    assert result.status == "failed"
    assert result.output["error_code"] == "context_window_exceeded"
    assert result.output["detail"] == msg
    assert result.output["estimated_tokens"] == 0
    assert result.output["max_tokens"] == 0
    assert result.output["exceeded_by"] == 0
    assert result.output["model"] == "some-model"
    # actions 仍然 3 个
    assert len(result.output["recommended_actions"]) == 3
