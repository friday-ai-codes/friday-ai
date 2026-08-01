"""蓝图链与其**消费方**之间三道边界接缝的跨边界守卫（同步点 2；审计 §4.1 的 G1/G3/G4）。

⭐ **为什么这个文件必须是跨边界的**：这三处缺陷在六个相位里一路绿灯发布，正因为每个相位
都只在**自己的边界内**验证 —— 蓝图链验「会话确实停在 waiting_clarification 且线程建好了」，
入口侧验「拿到 pending 就挂起」，两边各自都对，中间那道翻译（旧链模型 ↔ 蓝图模型）没有
任何一条测试跨过去。故本文件的每条用例都从**同一条真实蓝图会话**出发，问的是消费方
**实际报出来什么**。

三道接缝与它们各自的「修复前实测行为」：

===  ==============  ==============================================================
G1   workflow        挂起判据用旧链 ``ClarificationService.ahas_pending`` ⇒ 蓝图恒
                     False ⇒ 落终态非 DONE 分支 ⇒ ``status="failed"`` /
                     ``error_code="plan_session_failed"``。**每次提问都判死工作流**。
G3   mcp             主载荷读 blueprint/v1 不存在的顶层 ``execution_plan`` ⇒
                     ``repository_tasks`` 恒 ``[]``（结构合法、语义为空的静默降级）。
G4   feature_list    待答问题取自旧链 ``ClarificationQuestion`` ⇒ 永久
                     ``researching`` + 空问题列表。
===  ==============  ==============================================================

外加**终态映射**：蓝图 ``DONE`` 语义是「等人审」，旧映射把它当 ``completed`` 交给下游
``ai_coding`` —— 未经人审的蓝图直送编码代理，正面违反 RELY-01。

对照组是 chat（``plan_research_tools._map_terminal_blueprint``，唯一做对的那个）；本文件
另有一条**表漂移守卫**证明三处新分档与它共用同一份状态文案表，⛔ 不是第四套约定。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.django_db(transaction=True)

_BLUEPRINT = "technical_blueprint"
_REPO_ID = "11111111-1111-4111-8111-111111111111"
_REPO_NAME = "auth-service"


# ═══════════════════════════════════════════════════════════════════════════
# 夹具：一条**真实**蓝图会话（blueprint/v1 产物 + 可选阻塞线程）
# ═══════════════════════════════════════════════════════════════════════════


def _blueprint_content() -> dict[str, Any]:
    """合法 blueprint/v1 content（单仓最小集，含一条 implementation_overview 实现项）。

    ⭐ **必须真的带 ``implementation_overview.items``**：G3 的修法是从它确定性派生
    ``execution_plan``；夹具若不带实现项，「派生出非空 repository_tasks」这条断言会退化成
    恒假，测不出任何东西。
    """
    return {
        "schema_version": "blueprint/v1",
        "meta": {
            "title": "登录超时修复跨仓蓝图",
            "project_id": "proj-1",
            "summary": [
                {
                    "block_id": "b_sum",
                    "type": "paragraph",
                    "text": "在 auth 仓修复 token 刷新边界。",
                }
            ],
        },
        "requirement_spec": {
            "goal": [{"block_id": "b_goal", "type": "paragraph", "text": "登录态不再意外过期。"}],
            "feature_points": [
                {"id": "fp_01", "title": "刷新边界修复", "intent": "fix"},
            ],
        },
        "repo_associations": [
            {"repository_id": _REPO_ID, "repository_name": _REPO_NAME, "role": "direct"},
        ],
        "current_state_analysis": [],
        "implementation_overview": {
            "requirement_narrative": [
                {"block_id": "b_nar", "type": "paragraph", "text": "在校验处补边界判断。"}
            ],
            "items": [
                {
                    "id": "impl_01",
                    "feature_point_id": "fp_01",
                    "repository_id": _REPO_ID,
                    "change_type": "modify",
                    "title": "补刷新边界判断",
                    "how": [
                        {
                            "block_id": "b_how",
                            "type": "paragraph",
                            "text": "在 session 校验处补判断。",
                        }
                    ],
                    "files_touched": [{"path": "auth/session.py", "action": "modify"}],
                    "wave": 1,
                }
            ],
        },
        "api_contracts": [],
        "impact_analysis": {"business_impact": [], "affected_features": []},
        "interaction_flows": [],
        "must_haves": {"truths": [], "artifacts": [], "key_links": []},
        "citations": {},
    }


async def _amake_blueprint_session(
    *,
    status: str,
    entrypoint: str = "workflow",
    blueprint_status: str = "researching",
    thread_kind: str | None = "ai_clarification",
    thread_status: str = "open",
    blocking: bool = True,
    question: str = "这个需求要不要覆盖移动端登录？",
    mode: str = "",
) -> tuple[Any, Any]:
    """造一条蓝图会话 + 其 Artifact/ArtifactVersion（可选一条阻塞线程）。"""
    from delivery.models import (
        Artifact,
        ArtifactVersion,
        BlueprintThread,
        BlueprintThreadMessage,
        ConvergenceSession,
    )

    # ``decomposition`` 是 ``stage_state`` 的只读视图（INV-6：写恒经 service）。
    stage_state: dict[str, Any] = {}
    if mode:
        stage_state = {"decomposition": {"mode": mode, "feature_meta": {"project_id": "proj-1"}}}

    session = await ConvergenceSession.objects.acreate(
        process_type=_BLUEPRINT,
        entrypoint=entrypoint,
        current_stage="spec_gate",
        status=status,
        stage_state=stage_state,
    )
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    # ⛔ 不经 BlueprintLifecycleService（INV-6 只约束 server/ 源码，测试直写以固定初态）。
    await Artifact.objects.filter(id=artifact.id).aupdate(blueprint_status=blueprint_status)
    version = await ArtifactVersion.objects.acreate(
        artifact=artifact, version_no=1, content=_blueprint_content(), content_hash="h"
    )
    await ConvergenceSession.objects.filter(id=session.id).aupdate(current_artifact_version=version)
    session = await ConvergenceSession.objects.aget(id=session.id)

    if thread_kind is not None:
        thread = await BlueprintThread.objects.acreate(
            artifact=artifact, kind=thread_kind, status=thread_status, blocking=blocking
        )
        await BlueprintThreadMessage.objects.acreate(thread=thread, author_type="ai", body=question)
    return session, artifact


async def _amake_legacy_session(status: str, *, mode: str = "") -> Any:
    """旧链 ``technical_plan`` 会话（零回归对照组）。"""
    from delivery.models import ConvergenceSession

    stage_state: dict[str, Any] = {}
    if mode:
        stage_state = {"decomposition": {"mode": mode, "feature_meta": {"project_id": "proj-1"}}}
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint="workflow",
        current_stage="clarify",
        status=status,
        stage_state=stage_state,
    )


async def _aexecute_node(session: Any, context: Any):
    """跑完整条 ``AIPlanResearchNode.execute``（只在 IO 边界替身：会话解析 + engine 驱动）。

    ⭐ 走 ``execute`` 而不是直接调映射器：**终态分档的分流本身就在 ``execute`` 里**，
    直接调映射器会把「分流有没有接上」这半漏掉。
    """
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    node = AIPlanResearchNode()
    node._resolve_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    node._build_engine = lambda ctx, sess: (  # type: ignore[assignment]
        object(),
        AsyncMock(return_value=session),
    )
    with patch("workflows.models.execution.WorkflowEventSubscription.objects.acreate", AsyncMock()):
        return await node.execute(context)


def _ctx(*, with_execution: bool = True):
    from workflows.nodes.base import ExecutionContext

    return ExecutionContext(
        execution_id="exec-seam-1",
        node_id="node-seam-1",
        node_config={},
        input_data={},
        workflow_context={"project_key": "PK"},
        previous_outputs={},
        workflow_execution=SimpleNamespace(id="we-1", triggered_by_id=7)
        if with_execution
        else None,
        node_execution=SimpleNamespace(id="ne-1") if with_execution else None,
    )


# ═══════════════════════════════════════════════════════════════════════════
# G1 · workflow 入口：每一次澄清都把会话判死
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_g1_blocked_blueprint_suspends_instead_of_being_judged_failed() -> None:
    """⭐ G1 头号靶子：等人回答规格门提问的**健康**蓝图会话必须挂起，⛔ 不是 failed。

    ⭐ 断言写成与修复前**直接对立**的正值（``waiting_event`` + 题面），而不是
    「不等于 failed」—— 后者在实现回退成「返回 None」时仍然为真（None 没有 .status），
    测不出回退。
    """
    from delivery.models import ConvergenceSessionStatus
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    session, artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION
    )

    with patch("workflows.models.execution.WorkflowEventSubscription.objects.acreate", AsyncMock()):
        result = await AIPlanResearchNode()._maybe_suspend(session, _ctx())

    assert result is not None, "修复前实测：返回 None ⇒ 落终态映射 ⇒ plan_session_failed"
    assert result.status == "waiting_event"
    assert result.output["kind"] == "clarification"
    assert result.output["artifact_id"] == str(artifact.id)
    assert result.output["suspension"]["question"] == "这个需求要不要覆盖移动端登录？"
    assert result.output["suspension"]["thread_id"]
    # 键位与旧链逐字一致：thread_id 占 clarification_id 那一位（消费方零改动）。
    assert (
        result.output["suspension"]["clarification_id"] == result.output["suspension"]["thread_id"]
    )
    # ⛔ INV-6：输出体键名不得出现字面 blueprint_status。
    assert "blueprint_status" not in result.output


@pytest.mark.asyncio
async def test_g1_repo_confirmation_hard_gate_also_suspends() -> None:
    """确认硬门（``repo_confirmation``）同样算挂起 —— 判据**不按 kind 过滤**的证据。"""
    from delivery.models import ConvergenceSessionStatus
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION,
        thread_kind="repo_confirmation",
        question="请确认关联仓库清单",
    )

    with patch("workflows.models.execution.WorkflowEventSubscription.objects.acreate", AsyncMock()):
        result = await AIPlanResearchNode()._maybe_suspend(session, _ctx())

    assert result is not None
    assert result.status == "waiting_event"
    assert result.output["suspension"]["question"] == "请确认关联仓库清单"


@pytest.mark.asyncio
async def test_g1_no_open_blocking_thread_does_not_suspend() -> None:
    """非恒真对照：``waiting_clarification`` 但无 open+blocking 线程 ⇒ 不挂起。"""
    from delivery.models import ConvergenceSessionStatus
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION, thread_kind=None
    )

    assert await AIPlanResearchNode()._maybe_suspend(session, _ctx()) is None


@pytest.mark.asyncio
async def test_g1_end_to_end_execute_reports_suspension_not_plan_session_failed() -> None:
    """⭐ 跨边界端到端：整条 ``execute`` 走下来，工作流报的是挂起而不是「方案编排失败」。

    这条是三道接缝里唯一能直接对上审计原文的用例 —— 修复前 ``execute`` 的返回值实测为
    ``status="failed"`` / ``error_code="plan_session_failed"`` / ``next_handle="error"``。
    """
    from delivery.models import ConvergenceSessionStatus
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION
    )

    node = AIPlanResearchNode()
    node._resolve_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    node._build_engine = lambda context, sess: (  # type: ignore[assignment]
        object(),
        AsyncMock(return_value=session),
    )

    with patch("workflows.models.execution.WorkflowEventSubscription.objects.acreate", AsyncMock()):
        result = await node.execute(_ctx())

    assert result.status == "waiting_event"
    assert result.output.get("error_code") != "plan_session_failed"
    assert result.next_handle != "error"


@pytest.mark.asyncio
async def test_g1_suspension_registers_a_timeout_failsafe() -> None:
    """挂起必带**超时兜底**订阅：等不到人回答不能变成无声的永久挂起。"""
    from delivery.models import ConvergenceSessionStatus
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION
    )

    acreate = AsyncMock()
    with patch("workflows.models.execution.WorkflowEventSubscription.objects.acreate", acreate):
        await AIPlanResearchNode()._maybe_suspend(session, _ctx())

    acreate.assert_awaited_once()
    kwargs = acreate.await_args.kwargs
    assert kwargs["timeout_action"] == "fail"
    # ⛔ 独立事件类型：既有 PlanClarifyCallback 消费者按 clarification_id 查 Clarification 行，
    # 对蓝图线程恒查无 ⇒ 复用那个类型等于把用户的回答送进一个死信箱。
    assert kwargs["event_type"] == "BlueprintGateCallback"


@pytest.mark.asyncio
async def test_g1_chat_entry_without_execution_still_suspends_without_subscribing() -> None:
    """无 ``workflow_execution`` 时不建订阅，但**仍然挂起**（兜底缺失不反噬挂起语义）。"""
    from delivery.models import ConvergenceSessionStatus
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION
    )

    acreate = AsyncMock()
    with patch("workflows.models.execution.WorkflowEventSubscription.objects.acreate", acreate):
        result = await AIPlanResearchNode()._maybe_suspend(session, _ctx(with_execution=False))

    assert result is not None and result.status == "waiting_event"
    acreate.assert_not_awaited()


@pytest.mark.asyncio
async def test_g1_legacy_session_still_uses_the_old_criteria() -> None:
    """⭐ 零回归：开关关闭时旧链会话仍走旧判据（蓝图分支不误伤）。"""
    from delivery.models import ConvergenceSessionStatus
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    session = await _amake_legacy_session(ConvergenceSessionStatus.WAITING_CLARIFICATION)

    # 无 Clarification 行 ⇒ 旧链判据返回 None（⛔ 不该跑去查 BlueprintThread）。
    assert await AIPlanResearchNode()._maybe_suspend(session, _ctx()) is None


# ═══════════════════════════════════════════════════════════════════════════
# 终态映射 · pending_review = 等人审，⛔ 不是 completed（RELY-01）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_terminal_pending_review_suspends_for_human_review() -> None:
    """⭐ 要害：``pending_review`` 的蓝图**挂起等人审**，⛔ 绝不沿 default 出边进 ai_coding。

    修复前实测：``DONE`` 无条件 → ``completed`` + ``next_handle="default"`` ⇒ 编码代理拿到
    一份**未经人审**的蓝图去建分支写代码。
    """
    from delivery.models import ConvergenceSessionStatus

    session, artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE,
        blueprint_status="pending_review",
        thread_kind=None,
    )

    result = await _aexecute_node(session, _ctx())

    assert result.status == "waiting_event", "pending_review 报 completed 即违反 RELY-01"
    # ⭐ ``waiting_event`` 在调度器里走 ``amark_waiting_event`` 并直接返回（scheduler
    # ``:1179-1191``），**不遍历任何出边** ⇒ next_handle 无意义，真正的闸是「不产出
    # ``plan`` 载荷」：下游 ai_coding 读的就是它，没有它就不可能拿到未审蓝图。
    assert "plan" not in result.output
    assert result.output["kind"] == "human_review"
    assert result.output["current_status"] == "pending_review"
    assert result.output["artifact_id"] == str(artifact.id)
    assert "blueprint_status" not in result.output


@pytest.mark.asyncio
async def test_terminal_confirmed_blueprint_completes_with_derived_execution_plan() -> None:
    """人审通过后（``confirmed``）才放行，且喂给下游的是**派生后**的 execution_plan。

    直接内联 blueprint/v1 会在工作流侧复刻 G3 那条静默降级：下游 ``ai_coding`` 读
    ``plan.execution_plan``，而 blueprint/v1 根本没有这个顶层键。
    """
    from delivery.models import ConvergenceSessionStatus

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="confirmed", thread_kind=None
    )

    result = await _aexecute_node(session, _ctx())

    assert result.status == "completed"
    assert result.next_handle == "default"
    tasks = result.output["plan"]["execution_plan"]
    assert len(tasks) == 1, "派生为空即等于把 G3 搬到工作流侧"
    assert tasks[0]["repository_id"] == _REPO_ID
    assert tasks[0]["repository_name"] == _REPO_NAME
    assert "auth/session.py" in [f["path"] for f in tasks[0]["files"]]
    # 原始 blueprint content 并列保留（不丢信息）。
    assert result.output["blueprint_content"]["schema_version"] == "blueprint/v1"
    assert result.output["plan_markdown"]


@pytest.mark.asyncio
async def test_terminal_needs_clarification_suspends_rather_than_failing() -> None:
    """终态时蓝图状态为 ``needs_clarification`` ⇒ 回挂起，⛔ 不报失败。"""
    from delivery.models import ConvergenceSessionStatus
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="needs_clarification"
    )

    with patch("workflows.models.execution.WorkflowEventSubscription.objects.acreate", AsyncMock()):
        result = await AIPlanResearchNode()._amap_terminal_blueprint(session, _ctx())

    assert result.status == "waiting_event"
    assert result.output["kind"] == "clarification"


@pytest.mark.asyncio
async def test_terminal_unreviewed_intermediate_status_fails_loudly() -> None:
    """⭐ 会话到终态而蓝图仍停在中间态 ⇒ **如实报错**，⛔ 既不放行也不装作还在跑。

    与 chat 那档「中间态不报失败」刻意不同：chat 只把结果讲给人看，工作流的 completed
    会把载荷**交给编码代理**。判据是下游不同，不是口径漂移。
    """
    from delivery.models import ConvergenceSessionStatus
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="drafting", thread_kind=None
    )

    result = await AIPlanResearchNode()._amap_terminal_blueprint(session, _ctx())

    assert result.status == "failed"
    assert result.output["error_code"] == "blueprint_unreviewed"
    assert result.next_handle == "error"


@pytest.mark.asyncio
async def test_terminal_failed_blueprint_is_a_failure() -> None:
    """``failed`` 才是失败（分档另一端，证明上面几条不是恒真）。"""
    from delivery.models import ConvergenceSession, ConvergenceSessionStatus
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.FAILED, blueprint_status="failed", thread_kind=None
    )
    await ConvergenceSession.objects.filter(id=session.id).aupdate(error={"message": "融合器炸了"})
    session = await ConvergenceSession.objects.aget(id=session.id)

    result = await AIPlanResearchNode()._amap_terminal_blueprint(session, _ctx())

    assert result.status == "failed"
    assert result.output["error_code"] == "blueprint_session_failed"
    assert "融合器炸了" in (result.error or "")


@pytest.mark.asyncio
async def test_terminal_legacy_done_path_is_byte_for_byte_unchanged() -> None:
    """⭐ 零回归：旧链 ``DONE`` 仍是 ``completed`` + 原有键集（蓝图分档不误伤）。"""
    from delivery.models import (
        Artifact,
        ArtifactVersion,
        ConvergenceSession,
        ConvergenceSessionStatus,
    )

    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    version = await ArtifactVersion.objects.acreate(
        artifact=artifact, version_no=1, content={"title": "T", "summary": "s"}, content_hash="h"
    )
    session = await _amake_legacy_session(ConvergenceSessionStatus.DONE)
    await ConvergenceSession.objects.filter(id=session.id).aupdate(current_artifact_version=version)
    session = await ConvergenceSession.objects.aget(id=session.id)

    # ⭐ 走完整 execute：同时证明分流判据没把旧链会话误导进蓝图分档。
    result = await _aexecute_node(session, _ctx())

    assert result.status == "completed"
    assert result.next_handle == "default"
    assert result.output["status"] == "done"
    assert result.output["plan"]["title"] == "T"
    # 蓝图专属键**一个都不该出现**在旧链出口。
    assert "current_status" not in result.output
    assert "blueprint_content" not in result.output


# ═══════════════════════════════════════════════════════════════════════════
# G4 · feature_list 入口：永久 researching + 空问题列表
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_g4_blocked_blueprint_reports_questions_not_endless_researching() -> None:
    """⭐ G4 靶子：阻塞在蓝图线程上的会话必须报 ``awaiting_confirmation`` + 题面。

    修复前实测：``STATUS_RESEARCHING`` + ``questions == []`` —— 调用方看不到要答什么，
    也就永远解不了阻。
    """
    from delivery.models import ConvergenceSessionStatus
    from initiatives.services.feature_solution_service import (
        STATUS_AWAITING_CONFIRMATION,
        FeatureSolutionService,
    )

    session, artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION,
        mode="feature_list",
        question="功能点 3 的灰度范围是什么？",
    )

    state = await FeatureSolutionService()._abuild_state(session)

    assert state.status == STATUS_AWAITING_CONFIRMATION
    assert len(state.questions) == 1
    assert state.questions[0]["question"] == "功能点 3 的灰度范围是什么？"
    assert state.questions[0]["thread_id"]
    # 键位与旧链问题项对齐：question_id 位放 thread_id（调用方零改动）。
    assert state.questions[0]["question_id"] == state.questions[0]["thread_id"]
    assert state.clarification_id == state.questions[0]["thread_id"]
    assert state.artifact_id == str(artifact.id)


@pytest.mark.asyncio
async def test_g4_pending_review_reports_completed_and_says_it_awaits_review() -> None:
    """``pending_review`` ⇒ ``completed``（产物可读）+ ``current_status`` 如实标明等人审。

    ⛔ 与工作流入口不同：这一面没有下游编码代理，报 completed 不会把未审蓝图送进 ai_coding。
    """
    from delivery.models import ConvergenceSessionStatus
    from initiatives.services.feature_solution_service import (
        STATUS_COMPLETED,
        FeatureSolutionService,
    )

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE,
        blueprint_status="pending_review",
        thread_kind=None,
        mode="feature_list",
    )

    state = await FeatureSolutionService()._abuild_state(session)

    assert state.status == STATUS_COMPLETED
    assert state.current_status == "pending_review"
    assert state.plan["schema_version"] == "blueprint/v1"
    # 蓝图走自己的渲染器：v0 的 feature_solution 渲染器对 blueprint/v1 渲不出内容。
    assert "登录超时修复跨仓蓝图" in state.markdown
    assert "current_status" in state.as_dict()


@pytest.mark.asyncio
async def test_g4_intermediate_status_is_still_researching() -> None:
    """非恒真对照：真的还在跑（``drafting`` 且无线程）时仍报 ``researching``。"""
    from delivery.models import ConvergenceSessionStatus
    from initiatives.services.feature_solution_service import (
        STATUS_RESEARCHING,
        FeatureSolutionService,
    )

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_EVENT,
        blueprint_status="drafting",
        thread_kind=None,
        mode="feature_list",
    )

    state = await FeatureSolutionService()._abuild_state(session)

    assert state.status == STATUS_RESEARCHING
    assert state.questions == []


@pytest.mark.asyncio
async def test_g4_confirm_on_a_blueprint_session_fails_loudly() -> None:
    """⭐ ``confirm`` 对蓝图会话**如实拒绝**，⛔ 不返回一个「状态没变」的 200。

    修复前实测：查不到 ``Clarification`` 待答轮 ⇒ 落「没有待答轮 ⇒ 续驱后原样返回」分支
    ⇒ 调用方拿到 200 并读成「答复已收下」，实际一个字都没写进去（115-MJ-04 同形）。
    """
    from delivery.models import ConvergenceSessionStatus
    from initiatives.services.feature_solution_service import (
        FeatureSolutionError,
        FeatureSolutionService,
    )

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION, mode="feature_list"
    )
    service = FeatureSolutionService()
    service._aassert_session_readable = AsyncMock(return_value=None)  # type: ignore[method-assign]

    with pytest.raises(FeatureSolutionError) as excinfo:
        await service.confirm(session_id=session.id, answers=[], actor=SimpleNamespace(id=1))

    assert excinfo.value.code == "blueprint_thread_answer_required"


@pytest.mark.asyncio
async def test_g4_legacy_session_state_is_unchanged() -> None:
    """⭐ 零回归：旧链会话仍走 ``ClarificationQuestion`` 那条路径。"""
    from delivery.models import ConvergenceSessionStatus
    from delivery.services.clarification_service import ClarificationService
    from initiatives.services.feature_solution_service import (
        STATUS_AWAITING_CONFIRMATION,
        FeatureSolutionService,
    )

    session = await _amake_legacy_session(
        ConvergenceSessionStatus.WAITING_CLARIFICATION, mode="feature_list"
    )
    await ClarificationService().create_round(
        session,
        [{"question": "灰度范围？", "type": "single", "options": ["全部"], "recommended": "全部"}],
    )

    state = await FeatureSolutionService()._abuild_state(session)

    assert state.status == STATUS_AWAITING_CONFIRMATION
    assert state.questions[0]["question"] == "灰度范围？"
    # 蓝图专属键在旧链恒为空串。
    assert state.current_status == ""
    assert state.artifact_id == ""


# ═══════════════════════════════════════════════════════════════════════════
# G3 · MCP 入口：主载荷结构合法而语义为空
# ═══════════════════════════════════════════════════════════════════════════


def test_g3_repository_tasks_are_derived_from_the_blueprint() -> None:
    """⭐ G3 靶子：blueprint/v1 也要产出**非空**的 ``repository_tasks``。

    修复前实测：``_map_execution_plan_to_repository_tasks(blueprint_content)`` 返回 ``[]``
    —— blueprint/v1 的 required 键表里根本没有顶层 ``execution_plan``。
    """
    from mcp_tools.technical_plan_service import (
        _map_execution_plan_to_repository_tasks,
        _project_canonical_for_legacy_mapping,
    )

    content = _blueprint_content()

    assert _map_execution_plan_to_repository_tasks(content) == [], "修复前的实测行为"

    tasks = _map_execution_plan_to_repository_tasks(_project_canonical_for_legacy_mapping(content))

    assert len(tasks) == 1
    assert tasks[0]["repository_id"] == _REPO_ID
    assert tasks[0]["repository_name"] == _REPO_NAME
    assert tasks[0]["candidate_files"] == ["auth/session.py"]
    # 下游 _coding_plan_body 读的方案细节键：派生后必须真的有内容。
    assert tasks[0]["coding_instruction"]
    assert tasks[0]["steps"]


def test_g3_projection_also_recovers_title_and_summary() -> None:
    """标题/摘要在 blueprint/v1 的 ``meta`` 下 —— 投影把它们捞回旧响应的两个位。"""
    from mcp_tools.technical_plan_service import _project_canonical_for_legacy_mapping

    view = _project_canonical_for_legacy_mapping(_blueprint_content())

    assert view["title"] == "登录超时修复跨仓蓝图"
    assert "token 刷新边界" in view["summary"]


def test_g3_legacy_content_passes_through_identically() -> None:
    """⭐ 零回归：非 blueprint/v1 的 content **恒等**穿过投影（同一个对象）。"""
    from mcp_tools.technical_plan_service import _project_canonical_for_legacy_mapping

    legacy = {"title": "T", "summary": "s", "execution_plan": [{"id": "t1"}]}

    assert _project_canonical_for_legacy_mapping(legacy) is legacy


@pytest.mark.asyncio
async def test_g3_markdown_uses_the_blueprint_renderer_not_the_v0_one() -> None:
    """⭐ markdown 那一半：蓝图会话换渲染器（v0 渲染器对 blueprint/v1 渲不出内容）。

    这份 markdown 正是写进飞书文档的那一份 —— 渲染错等于给用户一篇空文档。
    """
    from delivery.models import ConvergenceSessionStatus
    from mcp_tools.orchestration_delegate import _load_canonical
    from services.process_runtime import render_merged_plan_markdown

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="pending_review", thread_kind=None
    )

    _av_id, content, markdown = await _load_canonical(session)

    assert content["schema_version"] == "blueprint/v1"
    assert "登录超时修复跨仓蓝图" in markdown
    assert markdown != render_merged_plan_markdown(content), "v0 渲染器渲不出蓝图内容"
    # 未确认水印（render_blueprint_markdown 的闭合白名单之外一律加）。
    assert "未经确认" in markdown


@pytest.mark.asyncio
async def test_g3_legacy_session_still_uses_the_v0_renderer() -> None:
    """⭐ 零回归：旧链会话的 markdown 仍逐字等于 v0 渲染器的输出。"""
    from delivery.models import (
        Artifact,
        ArtifactVersion,
        ConvergenceSession,
        ConvergenceSessionStatus,
    )
    from mcp_tools.orchestration_delegate import _load_canonical
    from services.process_runtime import render_merged_plan_markdown

    legacy_content = {"title": "旧链方案", "summary": "s", "execution_plan": []}
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    version = await ArtifactVersion.objects.acreate(
        artifact=artifact, version_no=1, content=legacy_content, content_hash="h"
    )
    session = await _amake_legacy_session(ConvergenceSessionStatus.DONE)
    await ConvergenceSession.objects.filter(id=session.id).aupdate(current_artifact_version=version)
    session = await ConvergenceSession.objects.aget(id=session.id)

    _av_id, content, markdown = await _load_canonical(session)

    assert markdown == render_merged_plan_markdown(content)


def test_g3_empty_derivation_on_a_non_empty_blueprint_is_logged_as_a_warning() -> None:
    """⭐ 「派生出来还是空」必须可查 —— G3 能潜伏六个相位正因为空载荷不打任何信号。"""
    from structlog.testing import capture_logs

    from mcp_tools.technical_plan_service import _log_blueprint_payload_projection

    content = _blueprint_content()
    # repo_associations 与 items 的 repository_id 对不上 ⇒ 派生器整批丢弃 ⇒ 派生为空。
    content["repo_associations"] = [
        {"repository_id": "other", "repository_name": "other", "role": "direct"}
    ]

    with capture_logs() as cap:
        _log_blueprint_payload_projection(
            SimpleNamespace(session=SimpleNamespace(id="s-1")),
            content,
            {"execution_plan": []},
            [],
        )

    events = [e for e in cap if e["event"] == "mcp_blueprint_payload_projection_empty"]
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert events[0]["category"] == "sampling"
    assert events[0]["component"] == "mcp_tools"
    assert events[0]["blueprint_item_count"] == 1
    assert events[0]["repository_task_count"] == 0


def test_g3_legacy_content_leaves_no_blueprint_trace() -> None:
    """非恒真对照：旧链恒等穿过时**不打**蓝图埋点（⛔ 不给旧链加日志噪声）。"""
    from structlog.testing import capture_logs

    from mcp_tools.technical_plan_service import _log_blueprint_payload_projection

    legacy = {"title": "T", "execution_plan": []}
    with capture_logs() as cap:
        _log_blueprint_payload_projection(SimpleNamespace(session=None), legacy, legacy, [])

    assert [e for e in cap if e["event"].startswith("mcp_blueprint_payload")] == []


# ═══════════════════════════════════════════════════════════════════════════
# 跨接缝纪律：一份状态表、一份枚举、四个开关默认值不动
# ═══════════════════════════════════════════════════════════════════════════


def test_status_message_table_does_not_drift_from_the_chat_reference() -> None:
    """⭐ chat 是对照组 —— 三个新分档与它共用**同一份**状态文案表，⛔ 不是第四套约定。"""
    from agents.tools.plan_research_tools import _BLUEPRINT_STATUS_MESSAGES
    from services.process_runtime.blueprint_observation import BLUEPRINT_STATUS_MESSAGES

    assert dict(_BLUEPRINT_STATUS_MESSAGES) == dict(BLUEPRINT_STATUS_MESSAGES)


def test_blueprint_status_literals_match_the_enum() -> None:
    """三处分档用的字面量必须与 ``BlueprintStatus`` 枚举逐字相等（防漂移）。"""
    from delivery.models import BlueprintStatus
    from initiatives.services.feature_solution_service import (
        _BLUEPRINT_PRODUCED_STATUSES,
        _BLUEPRINT_STATUS_FAILED,
    )
    from workflows.nodes.ai.plan_research import (
        _BLUEPRINT_REVIEWED_STATUSES,
        _BLUEPRINT_STATUS_NEEDS_CLARIFICATION,
        _BLUEPRINT_STATUS_PENDING_REVIEW,
    )
    from workflows.nodes.ai.plan_research import (
        _BLUEPRINT_STATUS_FAILED as _WF_FAILED,
    )

    assert _WF_FAILED == BlueprintStatus.FAILED
    assert _BLUEPRINT_STATUS_FAILED == BlueprintStatus.FAILED
    assert _BLUEPRINT_STATUS_NEEDS_CLARIFICATION == BlueprintStatus.NEEDS_CLARIFICATION
    assert _BLUEPRINT_STATUS_PENDING_REVIEW == BlueprintStatus.PENDING_REVIEW
    assert _BLUEPRINT_REVIEWED_STATUSES == {
        BlueprintStatus.CONFIRMED,
        BlueprintStatus.IMPLEMENTING,
        BlueprintStatus.IMPLEMENTED,
    }
    # ⭐ 工作流的「可放行」集合刻意**不含** pending_review（RELY-01 的那道闸）。
    assert BlueprintStatus.PENDING_REVIEW not in _BLUEPRINT_REVIEWED_STATUSES
    # feature_list 的「已产出」集合则包含它（那一面没有下游编码代理）。
    assert BlueprintStatus.PENDING_REVIEW in _BLUEPRINT_PRODUCED_STATUSES


def test_entry_switch_defaults_are_flipped_now_that_the_seams_are_fixed() -> None:
    """⭐ 断言随同步点 2 收尾**翻面**：四个入口默认值现在全是 ``technical_blueprint``。

    本条此前锁的是相反的东西 —— 「三道接缝还没修好之前**不许**翻默认，先翻就等于把
    G1/G4 直接暴露给第一次澄清」。接缝修好了，前提条件成立，默认随之翻过来；这条断言
    的作用也从「拦住早翻」变成「拦住回退」。

    ⛔ 旧链**不再是任何入口的默认**（退役收口的行为面判据，与
    ``test_technical_plan_retirement.py`` 的注册面判据并列）。
    """
    from services.process_runtime.blueprint_entry_switch import (
        DEFAULT_ENTRY_SWITCH,
        PROCESS_TECHNICAL_BLUEPRINT,
        PROCESS_TECHNICAL_PLAN,
    )

    assert set(DEFAULT_ENTRY_SWITCH) == {"workflow", "chat", "mcp", "feature_list"}
    assert set(DEFAULT_ENTRY_SWITCH.values()) == {PROCESS_TECHNICAL_BLUEPRINT}
    assert PROCESS_TECHNICAL_PLAN not in DEFAULT_ENTRY_SWITCH.values()


@pytest.mark.asyncio
async def test_answer_chain_reenters_a_suspended_workflow_node() -> None:
    """⭐ 作答链的工作流侧回环：人审 / 作答后必须**重入**那个仍挂起的节点。

    没有这一挂，蓝图早已 ``confirmed``、工作流却永远停在 ``waiting_event``
    —— 把「判死」换成「无声挂死」不算修好。
    """
    from delivery.models import ConvergenceSessionStatus
    from services.process_runtime.blueprint_resume import _aresume_workflow_node_if_any
    from workflows.models.execution import NodeExecution, NodeExecutionStatus

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="confirmed", thread_kind=None
    )
    node_exec = SimpleNamespace(
        id="ne-9",
        output_data={"session_id": str(session.id)},
        workflow_execution=SimpleNamespace(id="we-9"),
        asave=AsyncMock(),
    )
    continue_after = AsyncMock()

    with (
        patch.object(
            NodeExecution.objects,
            "filter",
            return_value=SimpleNamespace(
                select_related=lambda *a: SimpleNamespace(afirst=AsyncMock(return_value=node_exec))
            ),
        ),
        patch(
            "workflows.engine.scheduler.WorkflowEngine._continue_after_node",
            continue_after,
        ),
    ):
        await _aresume_workflow_node_if_any(session)

    continue_after.assert_awaited_once()
    assert node_exec.output_data["_resume_from_callback"] is True
    assert NodeExecutionStatus.WAITING_EVENT  # 状态枚举存在性（过滤条件依赖它）


@pytest.mark.asyncio
async def test_answer_chain_reentry_never_bites_back_on_the_gate_action() -> None:
    """重入 best-effort：内部炸了也绝不反噬已持久化的门动作。"""
    from delivery.models import ConvergenceSessionStatus
    from services.process_runtime.blueprint_resume import _aresume_workflow_node_if_any

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="confirmed", thread_kind=None
    )

    with patch(
        "workflows.models.execution.NodeExecution.objects.filter",
        side_effect=RuntimeError("boom"),
    ):
        await _aresume_workflow_node_if_any(session)  # ⛔ 不抛


# ═══════════════════════════════════════════════════════════════════════════
# 同步点 2 收尾 · 节点输出的 blueprint/v1 判别键（前端触点 NodeDataTab 消费）
#
# ⭐ 为什么需要它：蓝图链与 v0 旧链**共用同一个 node_type**（``ai_plan_research``），
# 输出键集又高度相似（都有 ``session_id`` / ``plan`` / ``plan_markdown``）⇒ 执行抽屉
# 此前把蓝图输出当 v0 渲染，看不出这是一份需要人审的结构化蓝图。
# ═══════════════════════════════════════════════════════════════════════════


def test_node_schema_version_literal_matches_the_authoritative_constant() -> None:
    """⭐ 常量对齐：节点里的字面量 == ``blueprint_schema.BLUEPRINT_SCHEMA_VERSION``。

    节点模块的 delivery / process_runtime import 全在函数内（lazy）⇒ 模块级只能写字面量。
    没有这一条，schema 演进时漏改一处就让前端静默按 v0 渲染新版蓝图。
    """
    from services.process_runtime.blueprint_schema import BLUEPRINT_SCHEMA_VERSION
    from workflows.nodes.ai.plan_research import _BLUEPRINT_SCHEMA_VERSION

    assert _BLUEPRINT_SCHEMA_VERSION == BLUEPRINT_SCHEMA_VERSION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("blueprint_status", "thread_kind", "session_status_done"),
    [
        ("pending_review", None, True),
        ("needs_clarification", "ai_clarification", False),
        ("confirmed", None, True),
        ("failed", None, True),
        ("drafting", None, True),
    ],
)
async def test_every_blueprint_branch_carries_the_schema_version(
    blueprint_status: str, thread_kind: str | None, session_status_done: bool
) -> None:
    """⭐ 蓝图**五个分档**的输出都带判别键（挂起 / 人审 / 完成 / 失败 / 未审）。

    漏掉任一档，执行抽屉在那一档就退回「当 v0 渲染」—— 而那正是最需要讲清楚的几档
    （尤其 ``pending_review``：节点停住不是「卡了」，是在等人终审）。
    """
    from delivery.models import ConvergenceSessionStatus

    session, _artifact = await _amake_blueprint_session(
        status=(
            ConvergenceSessionStatus.DONE
            if session_status_done
            else ConvergenceSessionStatus.WAITING_CLARIFICATION
        ),
        blueprint_status=blueprint_status,
        thread_kind=thread_kind,
    )

    result = await _aexecute_node(session, _ctx())

    assert result.output["schema_version"] == "blueprint/v1", (
        f"{blueprint_status} 这一档漏了判别键 ⇒ 抽屉退回按 v0 渲染"
    )


def test_v0_branches_never_carry_the_schema_version() -> None:
    """⭐ 反面：旧链四个分档的源码里**零** ``schema_version`` 写入（v0 输出逐字节不变）。

    只断言蓝图那五档会漏掉「顺手给旧链也加一个」——那会让前端把 v0 方案也渲成蓝图，
    正是本次判别要避免的相反面。判据用源码扫描：v0 的 ``_map_terminal`` /
    ``_maybe_suspend`` 两个函数体内不得出现该键名。
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[3] / "workflows/nodes/ai/plan_research.py").read_text(
        encoding="utf-8"
    )

    for name in ("async def _map_terminal(self", "async def _maybe_suspend(self"):
        start = src.index(name)
        end = src.index("\n    async def ", start + 1)
        body = src[start:end]
        assert not re.search(r'"schema_version"', body), (
            f"{name} 的函数体里出现了判别键 ⇒ v0 输出不再逐字节不变"
        )
