"""AICodingDispatcherNode 澄清能力单测（Chassis v2 · P3）。

覆盖（mirror test_clarification_card_node 范式，IO 边界 mock）：
- Test 1 注册 + 端口 shape 契约：clarify(out, clarification_request) / resume(in, clarification_answer)。
- Test 2 缺失仓挂起：execution_plan 引用不存在仓 → 发卡（mock）+ 建 ClarifyCardCallback 订阅 →
  waiting_event，output 携 missing_repo_refs / questions_meta（与答复回流按 order 对齐）。
- Test 3 澄清续推（resume）：output_data 带回流标记 + 答复 → 据答复把缺失仓重映射到目标仓 →
  派发成功（completed）。
- Test 4 已澄清仍缺失 → failed（不再二次追问，防无限挂起）。
- Test 5 关闭澄清 → 缺失仓直接 failed（不挂起）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflows.nodes.base import ExecutionContext
from workflows.nodes.registry import NodeRegistry

_MOD = "workflows.nodes.ai.coding_dispatcher"


def _plan(repo_id: str) -> dict:
    """构造一份单任务技术方案（execution_plan 引用 repo_id）。"""
    return {
        "title": "T",
        "summary": "s",
        "execution_plan": [
            {
                "id": "t1",
                "name": "任务1",
                "description": "d",
                "repository_id": repo_id,
                "repository_name": "r",
                "branch_strategy": "feature",
                "coding_instruction": "do it",
            }
        ],
        "total_tasks": 1,
        "global_context": "ctx",
    }


def _ctx(
    plan_data: dict | None,
    *,
    config: dict | None = None,
    with_execution: bool = False,
    node_output_data: dict | None = None,
    workflow_context: dict | None = None,
) -> ExecutionContext:
    workflow_execution = None
    node_execution = None
    if with_execution:
        workflow_execution = MagicMock()
        workflow_execution.id = uuid.uuid4()
        workflow_execution.triggered_by_id = None
        workflow_execution.global_params = {}
        node_execution = MagicMock()
        node_execution.id = uuid.uuid4()
        node_execution.output_data = node_output_data or {}
    return ExecutionContext(
        execution_id="exec-cd-001",
        node_id="node-cd-001",
        node_config=config or {},
        input_data={},
        workflow_context=workflow_context or {},
        previous_outputs={"plan": plan_data} if plan_data is not None else {},
        workflow_execution=workflow_execution,
        node_execution=node_execution,
    )


# ---------------------------------------------------------------------------
# Test 1：注册 + 端口 shape 契约
# ---------------------------------------------------------------------------


def test_registration_and_clarify_slot_shapes() -> None:
    node_cls = NodeRegistry.get("ai_coding_dispatcher")
    assert node_cls is not None

    schema = node_cls.get_schema()
    inputs = {p["name"]: p for p in schema["inputs"]}
    outputs = {p["name"]: p for p in schema["outputs"]}
    assert inputs["resume"]["shape"] == "clarification_answer"
    assert outputs["clarify"]["shape"] == "clarification_request"


# ---------------------------------------------------------------------------
# Test 2：缺失仓 → 发卡 + 订阅 + waiting_event
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_missing_repo_suspends_for_clarification() -> None:
    from workflows.nodes.ai.coding_dispatcher import AICodingDispatcherNode

    missing = str(uuid.uuid4())  # 合法 UUID 但不存在 → 触发澄清（非 UUID 会让 id__in 查询抛错）
    ctx = _ctx(
        _plan(missing),
        with_execution=True,
        workflow_context={"chat_id": "oc_chat", "project_key": "pk"},
    )

    im_client = MagicMock()
    im_client.send_card = AsyncMock(return_value="msg-1")
    sub_mgr = MagicMock()
    sub_mgr.objects.acreate = AsyncMock()

    with (
        patch(f"{_MOD}._get_feishu_credentials", AsyncMock(return_value=("app", "secret"))),
        patch(f"{_MOD}.FeishuIMClient", return_value=im_client),
        patch(f"{_MOD}.WorkflowEventSubscription", sub_mgr),
        patch(f"{_MOD}.build_clarification_card", return_value={"card": "x"}) as mock_card,
    ):
        result = await AICodingDispatcherNode().execute(ctx)

    assert result.status == "waiting_event"
    assert result.output["kind"] == "clarification"
    assert result.output["missing_repo_refs"] == [missing]
    assert result.output["question_count"] == 1
    assert [m["order"] for m in result.output["questions_meta"]] == [0]
    assert result.output["card_sent"] is True
    # 发卡 action 前缀路由到 clarify_card_callback（复用既有，不造两套）
    assert mock_card.call_args.kwargs["action"] == "clarify_card_answer"
    # 订阅事件键
    sub_mgr.objects.acreate.assert_awaited_once()
    assert sub_mgr.objects.acreate.await_args.kwargs["event_type"] == "ClarifyCardCallback"


# ---------------------------------------------------------------------------
# Test 3：澄清续推 → 据答复重映射缺失仓 → 派发成功
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_resume_remaps_missing_repo_and_dispatches() -> None:
    from repositories.models import Repository
    from workflows.nodes.ai.coding_dispatcher import AICodingDispatcherNode

    target = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    missing = str(uuid.uuid4())
    # 节点重入：output_data 带回流标记 + 答复（selected=目标仓 id），按 order 对齐 missing_repo_refs。
    ctx = _ctx(
        _plan(missing),
        with_execution=True,
        node_output_data={
            "kind": "clarification",
            "clarification_answered": True,
            "missing_repo_refs": [missing],
            "clarification_answers": [{"selected": str(target.id), "freeform_text": ""}],
        },
    )

    fake_task = SimpleNamespace(
        id=uuid.uuid4(),
        name="任务1",
        repository_id=target.id,
        status="pending",
        execution_plan_ids=["t1"],
    )
    with patch.object(
        AICodingDispatcherNode, "_create_coding_task", AsyncMock(return_value=fake_task)
    ) as mock_create:
        result = await AICodingDispatcherNode().execute(ctx)

    assert result.status == "completed"
    assert result.output["task_count"] == 1
    # 重映射后用目标仓派发（_create_coding_task 收到的是 override 后的 repository）
    assert mock_create.await_args.args[1].id == target.id


# ---------------------------------------------------------------------------
# Test 4：已澄清仍缺失 → failed（不再二次追问）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_resume_still_missing_fails_without_reclarify() -> None:
    from workflows.nodes.ai.coding_dispatcher import AICodingDispatcherNode

    missing = str(uuid.uuid4())
    # 回流但答复为空 → 无 override → 仓仍缺失；is_resume=True → 失败、不再挂起。
    ctx = _ctx(
        _plan(missing),
        with_execution=True,
        node_output_data={
            "clarification_answered": True,
            "missing_repo_refs": [missing],
            "clarification_answers": [{"selected": None, "freeform_text": ""}],
        },
    )
    result = await AICodingDispatcherNode().execute(ctx)
    assert result.status == "failed"
    assert result.next_handle == "error"
    assert missing in (result.error or "")


# ---------------------------------------------------------------------------
# Test 5：关闭澄清 → 缺失仓直接 failed（不挂起）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_clarification_disabled_fails_on_missing_repo() -> None:
    from workflows.nodes.ai.coding_dispatcher import AICodingDispatcherNode

    ctx = _ctx(
        _plan(str(uuid.uuid4())),
        config={"enable_clarification": False},
        with_execution=True,
    )
    result = await AICodingDispatcherNode().execute(ctx)
    assert result.status == "failed"
    assert result.next_handle == "error"
