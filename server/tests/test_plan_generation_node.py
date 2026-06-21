"""implementation Wave（task）：AIPlanGenerationNode 测试 mock 迁移。

迁移前（implementation / Wave 之前）：通过 ``unittest.mock.patch`` 拦截老 SDK 子工厂 runner 整个替掉；
迁移后（work item / contract）：统一走 conftest `fake_chat_model_factory` 注入
`agents.llm_factory.build_chat_model` + `agents.langchain_runner.build_chat_model` seam，
让真实 `LangChainAgentRunner` 跑完 stream 主循环（由 FakeChatModel 回放 responses / tool_calls）。

AIPlanGenerationNode **源码零改动**（继承 AIAgentBaseNode.execute），本文件只动测试侧。

新增覆盖（implementation plan `<action>` §3/§4）：
- ``test_plan_generation_tool_loop_with_fake_model``：verify_plan / send_plan_card 两轮工具
  调用回放，验证继承链路 + FakeChatModel tool_calls 契约（work item / contract）。
- ``test_plan_generation_sub_step_emit_order``：sub_step 三态 analyze / generate_plan /
  review 的 RUNNING→COMPLETED 序列守护（success criterion）。

Fixture 策略（checkpoint-03 conftest / work item）：
- ``fake_chat_model_factory`` / ``mock_aresolve_ok`` / ``make_minimal_context`` 从
  ``server/tests/conftest.py`` 引入，**禁止**在本文件重复定义（checkpoint 静态扫描守护）。
- 为避免真实 DB 查询（WorkflowExecution/Project），对 ``AIAgentBaseNode._get_project``
  / ``_get_user`` 走 monkeypatch stub 返回 MagicMock；这是节点级单测惯用姿势，与
  test_base_agent.py 的 workflow_execution=None 路径不同（plan_generation.execute 内的
  `self._get_project(context)` 被显式调用，返回 None 会影响 Prompt Center 查询，故用
  stub 注入稳定值）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from tests.e2e.fixtures.technical_plans import VALID_TECHNICAL_PLAN
from workflows.nodes.ai.plan_generation import AIPlanGenerationNode
from workflows.nodes.base import ExecutionContext, NodeResult


# ============================================================================
# 本地 helper：统一注入 _get_project / _get_user stub（避免触碰真实 DB）
# ============================================================================


def _stub_project_user(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    """Stub AIAgentBaseNode._get_project / _get_user / _ensure_agent_session。

    _ensure_agent_session 也必须 stub 成 None：否则只要有 chat_id + project 就会调
    ``AgentSession.objects.aupdate_or_create(project_id=mock_project.id, ...)``
    触发真实 DB 外键约束失败（MagicMock project 不在 projects_project 表里）。
    """
    mock_project = MagicMock()
    # Project.id 是 UUIDField；render_prompt 会用此值做 project_id 查询
    mock_project.id = "00000000-0000-0000-0000-000000000001"
    mock_project.feishu_doc_folder_token = "folder_token_123"

    mock_user = MagicMock(id=1)

    async def _get_project_stub(self: Any, context: ExecutionContext) -> Any:
        return mock_project

    async def _get_user_stub(self: Any, context: ExecutionContext) -> Any:
        return mock_user

    async def _ensure_session_stub(
        self: Any,
        session_id: str,
        project: Any,
        user: Any,
        chat_id: str,
    ) -> None:
        return None

    monkeypatch.setattr(
        "workflows.nodes.ai.base_agent.AIAgentBaseNode._get_project",
        _get_project_stub,
    )
    monkeypatch.setattr(
        "workflows.nodes.ai.base_agent.AIAgentBaseNode._get_user",
        _get_user_stub,
    )
    monkeypatch.setattr(
        "workflows.nodes.ai.base_agent.AIAgentBaseNode._ensure_agent_session",
        _ensure_session_stub,
    )
    return mock_project, mock_user


def _build_plan_context(
    make_minimal_context: Any,
    *,
    user_prompt: str = "实现用户认证模块",
    system_prompt: str = "",
    extra_config: dict[str, Any] | None = None,
) -> ExecutionContext:
    """构造 AIPlanGenerationNode 所需的 ExecutionContext。"""
    node_config: dict[str, Any] = {
        "user_prompt": user_prompt,
        "model": "claude-sonnet-4-20250514",
        "chat_id": "",
    }
    if system_prompt:
        node_config["system_prompt"] = system_prompt
    if extra_config:
        node_config.update(extra_config)

    # workflow_execution 用 MagicMock 模拟，但 _get_project / _get_user 已由
    # _stub_project_user 劫持为直接返回 stub project/user，不会真的去查 DB
    mock_execution = MagicMock()
    mock_execution.workflow = MagicMock()
    mock_execution.workflow.project = MagicMock()
    mock_execution.workflow.project.id = "00000000-0000-0000-0000-000000000001"
    mock_execution.triggered_by = MagicMock(id=1)

    return make_minimal_context(
        node_config=node_config,
        execution_id="00000000-0000-0000-0000-000000000001",
        node_id="00000000-0000-0000-0000-000000000011",
        workflow_execution=mock_execution,
    )


# ============================================================================
# execute 主干测试（FakeChatModel 驱动真实 LangChainAgentRunner）
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_execute_happy_path_with_fake_model(
    monkeypatch: pytest.MonkeyPatch,
    fake_chat_model_factory: Any,
    mock_aresolve_ok: Any,
    make_minimal_context: Any,
) -> None:
    """FakeChatModel 单 turn 返回含 VALID_TECHNICAL_PLAN 的 JSON → status=completed + plan 提取。

    覆盖 map_output 中 `_extract_json_from_text` 从 final_answer 提取 ```json``` 代码块路径。
    """
    import json

    _stub_project_user(monkeypatch)
    mock_aresolve_ok(source="system", provider_type="anthropic")

    plan_json_str = json.dumps(VALID_TECHNICAL_PLAN, ensure_ascii=False)
    final_answer = f"方案已生成：\n```json\n{plan_json_str}\n```"
    fake_chat_model_factory(responses=[final_answer])

    ctx = _build_plan_context(make_minimal_context)
    node = AIPlanGenerationNode()

    result: NodeResult = await node.execute(ctx)

    assert result.status == "completed"
    assert result.next_handle == "default"
    assert result.output["plan"] == VALID_TECHNICAL_PLAN
    assert "usage" in result.output


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_execute_empty_user_prompt() -> None:
    """Empty user_prompt → 立即返回 failed，不触发昂贵 DB/Prompt 查询。

    注意：plan_generation.execute() 自身（覆写版）在 super().execute 之前做了 user_prompt
    短路检查，与 base execute 不同，这里 error 中含 "User Prompt"（base 中是 "User Prompt cannot be empty"）。
    """
    # 不依赖任何 seam / fixture；user_prompt 空分支优先于一切资源解析
    ctx = ExecutionContext(
        execution_id="00000000-0000-0000-0000-000000000001",
        node_id="00000000-0000-0000-0000-000000000011",
        node_config={"user_prompt": "", "model": "claude-sonnet-4-20250514"},
        input_data={},
        workflow_context={},
        previous_outputs={},
    )
    node = AIPlanGenerationNode()

    result: NodeResult = await node.execute(ctx)

    assert result.status == "failed"
    assert result.error is not None
    assert "User Prompt" in result.error


# ============================================================================
# tool_calls 回放测试（implementation plan §3 新增 / work item 继承受益验证）
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_plan_generation_tool_loop_with_fake_model(
    monkeypatch: pytest.MonkeyPatch,
    fake_chat_model_factory: Any,
    mock_aresolve_ok: Any,
    make_minimal_context: Any,
) -> None:
    """work item + contract：AIPlanGenerationNode 多轮工具调用回放（verify_plan）。

    回放序列：
      turn 1: AIMessage(content=..., tool_calls=[verify_plan]) → LangChain 归一化
      turn 2: AIMessage(content=最终方案 JSON, tool_calls=[])  → 退出 loop

    说明：LangChainAgentRunner 真实执行工具（_execute_tool），verify_plan 是已注册
    且在 D1 解耦后仍属默认工具集的工具；FakeChatModel 只控制 AIMessage 序列。
    D1 解耦：send_plan_card 已移出默认工具集（方案推送交下游节点），故不再回放。
    """
    import json

    _stub_project_user(monkeypatch)
    mock_aresolve_ok(source="system", provider_type="anthropic")

    plan_json_str = json.dumps(VALID_TECHNICAL_PLAN, ensure_ascii=False)
    fake_chat_model_factory(
        responses=[
            "我先调用 verify_plan 验证方案结构",
            f"方案已验证通过，以下是最终计划：\n```json\n{plan_json_str}\n```",
        ],
        tool_calls=[
            [
                {
                    "name": "verify_plan",
                    "args": {"plan_json": plan_json_str},
                    "id": "call_verify_1",
                }
            ],
            [],  # 第二轮无工具 → Runner 把它作为 final_answer 退出
        ],
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        },
    )

    ctx = _build_plan_context(make_minimal_context)
    node = AIPlanGenerationNode()

    result: NodeResult = await node.execute(ctx)

    # 继承路径受益：节点状态进入 completed（即使工具执行失败/被 Runner 归一化为
    # ToolMessage，Runner 也能正常推进到 final_answer turn）
    assert result.status == "completed", (
        f"tool_calls 回放应走通 3 turn 并进入 final，实际 {result.status} "
        f"error={result.error}"
    )
    # final_answer 的 JSON 块被 _extract_json_from_text 识别
    assert result.output["plan"] == VALID_TECHNICAL_PLAN


# ============================================================================
# sub_step 三态 emit 序列守护（implementation plan §4 / success criterion）
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_plan_generation_sub_step_emit_order(
    monkeypatch: pytest.MonkeyPatch,
    fake_chat_model_factory: Any,
    mock_aresolve_ok: Any,
    make_minimal_context: Any,
) -> None:
    """work item / success criterion：sub_step analyze / generate_plan / review 三态 emit 序列守护。

    断言：
    - analyze / generate_plan / review 三个 step_type 均至少发射 1 次 RUNNING 和 1 次 COMPLETED
    - 对每个 step_type，RUNNING 必须在 COMPLETED 之前
    - 整体顺序 analyze → generate_plan → review（按首次 RUNNING 的 index 排序）
    """
    from workflows.models.execution import SubStepStatus

    _stub_project_user(monkeypatch)
    mock_aresolve_ok(source="system", provider_type="anthropic")
    fake_chat_model_factory(responses=["完成方案生成（sub_step 守护）"])

    emit_log: list[tuple[str, str]] = []

    async def _fake_emit(
        self: Any,
        context: Any,
        step_type: str,
        status: str,
        output_data: dict[str, Any] | None = None,
    ) -> None:
        emit_log.append((step_type, status))

    # emit_sub_step 在 SubStepMixin 上；覆盖以免真实写库
    monkeypatch.setattr(
        "workflows.nodes.ai.sub_step_mixin.SubStepMixin.emit_sub_step",
        _fake_emit,
    )

    # _init_sub_steps 也 stub 掉（避免 NodeSubStep bulk_create 写库）
    async def _noop_init(self: Any, context: Any) -> None:
        return None

    monkeypatch.setattr(
        "workflows.nodes.ai.sub_step_mixin.SubStepMixin._init_sub_steps",
        _noop_init,
    )

    ctx = _build_plan_context(make_minimal_context)
    node = AIPlanGenerationNode()
    result = await node.execute(ctx)
    assert result.status == "completed"

    # 三个步骤都必须有 RUNNING 和 COMPLETED
    step_types = {"analyze", "generate_plan", "review"}
    for st in step_types:
        statuses_for_step = [s for (t, s) in emit_log if t == st]
        assert SubStepStatus.RUNNING in statuses_for_step, (
            f"step_type={st} 缺少 RUNNING emit；emit_log={emit_log}"
        )
        assert SubStepStatus.COMPLETED in statuses_for_step, (
            f"step_type={st} 缺少 COMPLETED emit；emit_log={emit_log}"
        )
        running_idx = next(
            i for i, (t, s) in enumerate(emit_log)
            if t == st and s == SubStepStatus.RUNNING
        )
        completed_idx = next(
            i for i, (t, s) in enumerate(emit_log)
            if t == st and s == SubStepStatus.COMPLETED
        )
        assert running_idx < completed_idx, (
            f"step_type={st} RUNNING(idx={running_idx}) 必须在 COMPLETED(idx={completed_idx}) 之前"
        )

    # 整体次序：analyze → generate_plan → review（按首 RUNNING 索引）
    first_running_idx = {
        st: next(
            i for i, (t, s) in enumerate(emit_log)
            if t == st and s == SubStepStatus.RUNNING
        )
        for st in step_types
    }
    assert first_running_idx["analyze"] < first_running_idx["generate_plan"], (
        f"analyze 必须在 generate_plan 之前，emit_log={emit_log}"
    )
    assert first_running_idx["generate_plan"] < first_running_idx["review"], (
        f"generate_plan 必须在 review 之前，emit_log={emit_log}"
    )


# ============================================================================
# Hook / map_output 单元测试（不进 execute，纯函数行为）
# ============================================================================


def test_get_system_prompt_includes_schema() -> None:
    """get_system_prompt 返回字符串包含 JSON Schema 关键字段。"""
    ctx = ExecutionContext(
        execution_id="00000000-0000-0000-0000-000000000001",
        node_id="00000000-0000-0000-0000-000000000011",
        node_config={"user_prompt": "demo"},
        input_data={},
        workflow_context={},
        previous_outputs={},
    )
    node = AIPlanGenerationNode()

    prompt = node.get_system_prompt(ctx)

    assert isinstance(prompt, str)
    assert "JSON Schema" in prompt or "json" in prompt.lower()
    assert "title" in prompt
    assert "execution_plan" in prompt
    assert "verify_plan" in prompt


def test_get_enabled_tools_includes_defaults() -> None:
    """get_enabled_tools 返回方案生成必需工具白名单（非 None 非空）。

    D1 解耦：方案生成只产出方案，不再承担「自动推送」职责——send_plan_card /
    create_feishu_document 已从默认工具集移除（推送/审批交给下游 human_approval /
    feishu_doc_create / notify_feishu_im）。保留 verify_plan / search_repository_code /
    ask_user_question（澄清 HITL）/ fetch_feishu_document（只读取材）。
    """
    ctx = ExecutionContext(
        execution_id="00000000-0000-0000-0000-000000000001",
        node_id="00000000-0000-0000-0000-000000000011",
        node_config={"user_prompt": "demo"},
        input_data={},
        workflow_context={},
        previous_outputs={},
    )
    node = AIPlanGenerationNode()

    tools = node.get_enabled_tools(ctx)

    assert tools is not None
    assert "verify_plan" in tools
    assert "search_repository_code" in tools
    assert "ask_user_question" in tools
    assert "fetch_feishu_document" in tools
    # D1 解耦：自动推送类工具不再默认启用
    assert "send_plan_card" not in tools
    assert "create_feishu_document" not in tools


def test_map_output_no_plan() -> None:
    """AgentResult 无可提取 plan → output.plan=None + error 注入。"""
    from agents.core.result import AgentResult

    node = AIPlanGenerationNode()
    result = AgentResult(
        output=[],
        status="completed",
        final_answer="I could not generate a plan.",
        usage={"input_tokens": 500, "output_tokens": 100},
        metadata={},
    )

    output = node.map_output(result)

    assert output["plan"] is None
    assert "error" in output
    assert output["final_answer"] == "I could not generate a plan."


def test_map_output_plan_from_verify_tool_in_output() -> None:
    """AgentResult.output 中含 verify_plan 工具调用 → map_output 抽取 plan。"""
    from agents.core.result import AgentResult

    node = AIPlanGenerationNode()
    tool_output = [
        {"tool": "search_code", "input": {"query": "auth"}, "output": "..."},
        {
            "tool": "verify_plan",
            "input": {"plan": VALID_TECHNICAL_PLAN},
            "output": {"valid": True},
        },
    ]
    result = AgentResult(
        output=tool_output,
        status="completed",
        final_answer="方案已验证通过",
        usage={"input_tokens": 2000, "output_tokens": 800},
        metadata={},
    )

    output = node.map_output(result)

    assert output["plan"] == VALID_TECHNICAL_PLAN
