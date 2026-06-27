"""AIPlanResearchNode 节点单测（ENTRY-01，41-03 Task 2）。

覆盖：建 PlanSession(entrypoint=workflow) + 驱动 engine 到 done（adapters mock 在 IO 边界）→
NodeResult completed（plan_version_id 非空）/ clarifying 挂起 waiting_event / failed 映射 /
schema 合法 + 自动注册。用真实 PlanSession/PlanSessionService + 真实 engine，IO 边界 mock。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from delivery.models import Clarification, PlanSession, PlanSessionStatus
from delivery.services import PlanSessionService
from services.plan_orchestration import ClarifyAdapter, PlanOrchestrationEngine
from workflows.nodes.ai.plan_research import AIPlanResearchNode
from workflows.nodes.base import ExecutionContext
from workflows.nodes.registry import NodeRegistry

# async ORM 测试用 transaction=True（真实 commit + 表间清理，对齐 test_research_completion_callback）
pytestmark = pytest.mark.django_db(transaction=True)


def _ctx(config: dict | None = None) -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec-pr-001",
        node_id="node-pr-001",
        node_config=config or {"requirement_text": "为多仓需求做方案编排"},
        input_data={},
        workflow_context={},
        previous_outputs={},
    )


def _bind_engine(node: AIPlanResearchNode, engine: PlanOrchestrationEngine) -> None:
    node._build_engine = lambda context, session: engine  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_drive_to_done_emits_merged_plan_ref() -> None:
    """建 session + 驱动到 done → completed + output.plan_version_id 非空 + status done。"""
    pv_id = uuid.uuid4()

    router = AsyncMock()
    router.route = AsyncMock(
        return_value={
            "candidates": [
                {"repo_id": "r1", "confidence": "high"},
                {"repo_id": "r2", "confidence": "high"},
            ]
        }
    )
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={"hits": [], "query": "q", "kinds": []})
    research = AsyncMock()
    research.dispatch = AsyncMock(return_value={})  # 无 task → barrier 直通 merging
    clarify = AsyncMock()
    clarify.clarify = AsyncMock(return_value={"needs_clarification": False})

    async def _merge_side(session):
        await PlanSessionService().set_current_plan_version(session, pv_id)
        return {"validation_status": "passed", "attempt": 0}

    merge = AsyncMock()
    merge.merge = AsyncMock(side_effect=_merge_side)

    engine = PlanOrchestrationEngine(
        router=router, recall=recall, research=research, merge=merge, clarify=clarify
    )
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    result = await node.execute(_ctx())

    assert result.status == "completed"
    assert result.output["plan_version_id"] == str(pv_id)
    assert result.output["status"] == "done"
    session = await PlanSession.objects.aget(id=result.output["session_id"])
    assert session.status == PlanSessionStatus.DONE
    assert session.entrypoint == "workflow"


@pytest.mark.asyncio
async def test_done_inlines_merged_plan_content_for_downstream() -> None:
    """D2 产物迁移（点3）：done → output["plan"] 内联 §7 MergedPlan content（含
    execution_plan）+ 注入 plan_version_id，供下游 human_approval / ai_coding 直接消费。"""
    from delivery.models import PlanVersion, TechnicalPlan

    merged_content = {
        "title": "跨仓主方案",
        "summary": "融合 repoA/repoB 的跨仓方案",
        "execution_plan": [
            {
                "id": "t1",
                "name": "A 暴露契约",
                "repository_id": "repo-a",
                "repository_name": "repoA",
                "branch_strategy": "feature",
                "coding_instruction": "实现 ContractX",
                "dependencies": [],
            }
        ],
    }
    tech_plan = await TechnicalPlan.objects.acreate(origin="orchestration")
    plan_version = await PlanVersion.objects.acreate(
        plan=tech_plan, version=1, content=merged_content
    )

    router = AsyncMock()
    router.route = AsyncMock(
        return_value={"candidates": [{"repo_id": "r1", "confidence": "high"}]}
    )
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={"hits": [], "query": "q", "kinds": []})
    research = AsyncMock()
    research.dispatch = AsyncMock(return_value={})
    clarify = AsyncMock()
    clarify.clarify = AsyncMock(return_value={"needs_clarification": False})

    async def _merge_side(session):
        await PlanSessionService().set_current_plan_version(session, plan_version.id)
        return {"validation_status": "passed", "attempt": 0}

    merge = AsyncMock()
    merge.merge = AsyncMock(side_effect=_merge_side)

    engine = PlanOrchestrationEngine(
        router=router, recall=recall, research=research, merge=merge, clarify=clarify
    )
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    result = await node.execute(_ctx())

    assert result.status == "completed"
    assert result.output["plan_version_id"] == str(plan_version.id)
    # 内联 MergedPlan content（下游 get_input("plan") 直接消费）
    plan = result.output["plan"]
    assert plan["title"] == "跨仓主方案"
    assert plan["summary"] == "融合 repoA/repoB 的跨仓方案"
    assert plan["execution_plan"][0]["repository_id"] == "repo-a"
    # plan_version_id 注入 plan（ai_coding wave 模式据此解析 canonical PlanVersion）
    assert plan["plan_version_id"] == str(plan_version.id)


@pytest.mark.asyncio
async def test_resume_via_session_id_ignores_conflicting_input() -> None:
    """D2 点4 二义性契约：本节点 output_data.session_id 在场时，resume 续推**同一**
    session，完全忽略 input/config 中冲突的 requirement_text，且不新建 session。"""
    from unittest.mock import MagicMock

    from delivery.models import PlanSession, PlanSessionStatus

    # 预置一个已 DONE 的 session（模拟 clarifying/researching 挂起后续推到终态）
    existing = await PlanSession.objects.acreate(
        entrypoint="workflow",
        status=PlanSessionStatus.DONE,
        decomposition={"requirement_text": "原始需求"},
    )

    # node_execution.output_data 携带 session_id（续推钥匙，物理隔离于输入端口）
    node_execution = MagicMock()
    node_execution.id = uuid.uuid4()
    node_execution.output_data = {"session_id": str(existing.id)}

    # 构造一个携带**冲突** requirement_text 的 context（若误走首建会建新 session）
    ctx = ExecutionContext(
        execution_id="exec-pr-resume",
        node_id="node-pr-resume",
        node_config={"requirement_text": "完全不同的新需求（不得被采纳）"},
        input_data={"requirement_text": "也不得被当成续推钥匙"},
        workflow_context={},
        previous_outputs={},
        node_execution=node_execution,
    )

    node = AIPlanResearchNode()
    # engine 不应被驱动产生新 session：build_engine 返回 mock，advance 透传 DONE
    engine = MagicMock()

    async def _advance(session):
        return session

    engine.advance = AsyncMock(side_effect=_advance)
    _bind_engine(node, engine)

    before = await PlanSession.objects.acount()
    result = await node.execute(ctx)
    after = await PlanSession.objects.acount()

    # 续推同一 session（非新建）→ 不新增 session 行
    assert before == after == 1
    assert result.output["session_id"] == str(existing.id)
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_clarifying_suspends_waiting_event() -> None:
    """needs-clarification → waiting_event（不 completed）+ 卡片 payload + DB pending + clarifying。"""
    router = AsyncMock()
    router.route = AsyncMock(return_value={"candidates": []})
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={"hits": [], "query": "", "kinds": []})
    # 真实 ClarifyAdapter + policy 判需澄清
    clarify = ClarifyAdapter(policy=lambda s: (True, "请补充涉及的仓库", []))

    engine = PlanOrchestrationEngine(router=router, recall=recall, clarify=clarify)
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    result = await node.execute(_ctx())

    assert result.status == "waiting_event"
    assert result.output["kind"] == "clarification"
    assert result.output["suspension"]["question"] == "请补充涉及的仓库"
    session = await PlanSession.objects.aget(id=result.output["session_id"])
    assert session.status == PlanSessionStatus.CLARIFYING
    assert (
        await Clarification.objects.filter(
            session_id=session.id, answered_at__isnull=True
        ).acount()
        == 1
    )


def _form_submit_value(card: dict) -> dict:
    """从卡片中取 form_submit 按钮的 value（回调路由锚）。"""
    for el in card["elements"]:
        if el.get("tag") == "form":
            for fe in el["elements"]:
                if fe.get("action_type") == "form_submit":
                    return fe["value"]
    raise AssertionError("no form_submit element in card")


def test_build_clarification_card_carries_clarification_id_and_new_action() -> None:
    """CLARIFY-05 / Pitfall 1：澄清卡 form_submit value 携新 action + clarification_id。"""
    from feishu.cards.chat_question_card import build_clarification_card

    card = build_clarification_card(
        [
            {"question": "实验组用户？", "type": "single", "options": ["全部", "灰度"], "recommended": "灰度"},
            {"question": "目标仓库？", "type": "multi", "options": ["api", "web"], "recommended": ["api"]},
        ],
        execution_id="exec-123",
        node_id="node-456",
        clarification_id="clar-9",
    )
    value = _form_submit_value(card)
    # 新前缀 action（绝不撞 GroupChatQuestion 既有 chat_question_answer）
    assert value["action"] == "plan_clarify_answer"
    assert value["clarification_id"] == "clar-9"
    assert value["execution_id"] == "exec-123"
    assert value["node_id"] == "node-456"
    assert value["question_count"] == 2
    # 索引↔question 字段映射固化（按 order：q0/q1，回调侧 91-03 据此对齐）
    form = next(el for el in card["elements"] if el.get("tag") == "form")
    names = {fe.get("name") for fe in form["elements"] if fe.get("name")}
    assert {"q0", "q1"} <= names


def test_build_clarification_card_default_clarification_id_empty() -> None:
    """缺省 clarification_id → 空串（向后兼容，不报错）。"""
    from feishu.cards.chat_question_card import build_clarification_card

    card = build_clarification_card(
        [{"question": "q", "options": ["a"], "recommended": "a"}],
        execution_id="e",
        node_id="n",
    )
    assert _form_submit_value(card)["clarification_id"] == ""


@pytest.mark.asyncio
async def test_maybe_suspend_structured_round_pending_via_ahas_pending() -> None:
    """WR-03：CLARIFYING 存在性判定经 ahas_pending——结构化子题未答→挂起；全答→不误挂起。"""
    from delivery.models import ClarificationQuestion
    from delivery.services.clarification_service import ClarificationService

    session = await PlanSession.objects.acreate(
        entrypoint="workflow", status=PlanSessionStatus.CLARIFYING
    )
    svc = ClarificationService()
    round_ = await svc.create_round(
        session,
        [
            {
                "question": "涉及哪些仓库？",
                "type": "single",
                "options": ["api", "web"],
                "recommended": ["api"],
            }
        ],
    )
    node = AIPlanResearchNode()
    # chat 入口 context（无 workflow_execution/node_execution）→ 不发卡、不订阅
    ctx = _ctx()

    # 子题未答 → ahas_pending=True → 正确挂起 waiting_event
    suspend = await node._maybe_suspend(session, ctx)
    assert suspend is not None
    assert suspend.status == "waiting_event"
    assert suspend.output["kind"] == "clarification"

    # 子题全已答（容器 advance）→ ahas_pending=False → 不误挂起
    q = await ClarificationQuestion.objects.filter(clarification_id=round_.id).afirst()
    await svc.answer_round(
        round_, [{"question_id": str(q.id), "selected": "api", "freeform_text": ""}]
    )
    assert await node._maybe_suspend(session, ctx) is None


def _workflow_ctx() -> ExecutionContext:
    """工作流入口 context（带 workflow_execution/node_execution → 触发发卡 + 订阅）。"""
    return ExecutionContext(
        execution_id="exec-clarify",
        node_id="node-clarify",
        node_config={},
        input_data={},
        workflow_context={"project_key": "PK"},
        previous_outputs={},
        workflow_execution=SimpleNamespace(id="we-1", triggered_by_id=7),
        node_execution=SimpleNamespace(id="ne-1"),
    )


def _clarify_send_patches(im: MagicMock, acreate: AsyncMock):
    """patch 发卡 IO 边界（群解析 / ProjectService / FeishuIMService / 订阅 acreate）。"""
    proj_svc = MagicMock()
    proj_svc.resolve_or_create_group = AsyncMock(return_value="chat-123")
    feishu_cls = MagicMock()
    feishu_cls.create = AsyncMock(return_value=im)
    return (
        patch(
            "workflows.nodes.integrations.board_split_review._resolve_space",
            AsyncMock(return_value=SimpleNamespace(id="s1")),
        ),
        patch(
            "workflows.nodes.integrations.board_split_review._aresolve_project",
            AsyncMock(return_value=SimpleNamespace(id="p1")),
        ),
        patch("initiatives.services.project_service.ProjectService", return_value=proj_svc),
        patch("services.feishu_im.FeishuIMService", feishu_cls),
        patch(
            "workflows.models.execution.WorkflowEventSubscription.objects.acreate", new=acreate
        ),
    )


async def _seed_clarifying_round() -> PlanSession:
    """建 CLARIFYING session + 结构化多子题 pending 轮。"""
    from delivery.services.clarification_service import ClarificationService

    session = await PlanSession.objects.acreate(
        entrypoint="workflow", status=PlanSessionStatus.CLARIFYING
    )
    await ClarificationService().create_round(
        session,
        [
            {"question": "实验组用户？", "type": "single", "options": ["全部", "灰度"], "recommended": "灰度"},
            {"question": "目标仓库？", "type": "multi", "options": ["api", "web"], "recommended": ["api"]},
        ],
    )
    return session


@pytest.mark.asyncio
async def test_clarifying_workflow_entry_sends_card_and_subscribes() -> None:
    """CLARIFY-05：工作流入口 CLARIFYING 挂起 → 发 build_clarification_card 到群 + 建订阅。"""
    session = await _seed_clarifying_round()
    sent: dict = {}
    im = MagicMock()

    async def _send_card(**kwargs):
        sent.update(kwargs)

    im.send_card = AsyncMock(side_effect=_send_card)
    acreate = AsyncMock()
    p_space, p_proj, p_psvc, p_feishu, p_sub = _clarify_send_patches(im, acreate)

    node = AIPlanResearchNode()
    with p_space, p_proj, p_psvc, p_feishu, p_sub:
        result = await node._maybe_suspend(session, _workflow_ctx())

    assert result is not None
    assert result.status == "waiting_event"
    assert result.output["kind"] == "clarification"
    # 发卡到项目群
    im.send_card.assert_awaited_once()
    assert sent["receive_id"] == "chat-123"
    assert sent["receive_id_type"] == "chat_id"
    # 卡片携 clarification_id + 新 action（按 order 的 q0/q1 子题）
    value = _form_submit_value(sent["card"])
    assert value["action"] == "plan_clarify_answer"
    assert value["clarification_id"] == result.output["suspension"]["clarification_id"]
    # 建 PlanClarifyCallback 订阅（超时兜底）
    acreate.assert_awaited_once()
    assert acreate.await_args.kwargs["event_type"] == "PlanClarifyCallback"
    assert acreate.await_args.kwargs["timeout_action"] == "fail"


@pytest.mark.asyncio
async def test_clarify_card_failure_does_not_block_suspension() -> None:
    """T-91-02-05：发卡抛错 best-effort——节点仍返回 waiting_event 且仍建订阅（不反噬挂起）。"""
    session = await _seed_clarifying_round()
    im = MagicMock()
    im.send_card = AsyncMock(side_effect=RuntimeError("飞书 500"))
    acreate = AsyncMock()
    p_space, p_proj, p_psvc, p_feishu, p_sub = _clarify_send_patches(im, acreate)

    node = AIPlanResearchNode()
    with p_space, p_proj, p_psvc, p_feishu, p_sub:
        result = await node._maybe_suspend(session, _workflow_ctx())

    assert result is not None
    assert result.status == "waiting_event"
    # 发卡失败被吞，订阅仍建（超时兜底不缺）
    acreate.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_terminal_maps_to_node_failed() -> None:
    """merge 限次耗尽 → failed → NodeResult failed + error_code=plan_session_failed。"""
    router = AsyncMock()
    router.route = AsyncMock(
        return_value={"candidates": [{"repo_id": "r1", "confidence": "high"}]}
    )
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={"hits": [], "query": "q", "kinds": []})
    research = AsyncMock()
    research.dispatch = AsyncMock(return_value={})
    clarify = AsyncMock()
    clarify.clarify = AsyncMock(return_value={"needs_clarification": False})
    merge = AsyncMock()
    merge.merge = AsyncMock(
        return_value={"validation_status": "failed", "attempt": 1, "report": {}}
    )

    engine = PlanOrchestrationEngine(
        router=router, recall=recall, research=research, merge=merge, clarify=clarify
    )
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    result = await node.execute(_ctx())

    assert result.status == "failed"
    assert result.output["error_code"] == "plan_session_failed"
    session = await PlanSession.objects.aget(id=result.output["session_id"])
    assert session.status == PlanSessionStatus.FAILED


@pytest.mark.asyncio
async def test_missing_requirement_fails_fast() -> None:
    """无 requirement_text 且无上游输入 → 快速失败（missing_requirement），不建 session。"""
    node = AIPlanResearchNode()
    result = await node.execute(_ctx({"requirement_text": ""}))
    assert result.status == "failed"
    assert result.output["error_code"] == "missing_requirement"
    assert await PlanSession.objects.acount() == 0


def test_schema_and_registration() -> None:
    """节点自动注册 + config_schema 合法 + ports 完整。"""
    cls = NodeRegistry.get("ai_plan_research")
    assert cls is AIPlanResearchNode
    assert cls.validate_config({}) == []
    assert cls.validate_config(
        {"requirement_text": "x", "include_repos": ["a"], "work_item_id": ""}
    ) == []
    props = cls.config_schema["properties"]
    assert {"requirement_text", "include_repos", "work_item_id"} <= set(props)
    assert [p.name for p in cls.inputs] == ["default"]
    output_names = {p.name for p in cls.outputs}
    assert output_names == {"default", "error"}
    default_out = next(p for p in cls.outputs if p.name == "default")
    assert "plan_version_id" in (default_out.schema or {}).get("properties", {})


@pytest.mark.asyncio
async def test_acollect_round_questions_includes_answered_subquestions() -> None:
    """WR-01 不变量：发卡侧整轮按 order 取子题（含已答），与回调侧逐字一致、不漂移。

    构造「同一轮部分已答」：第 0 题已答、第 1 题未答。修复前发卡侧按 answered_at__isnull=True
    过滤会跳过已答的第 0 题，导致 q{i} 与回调侧（取整轮）错位；修复后两侧都取整轮全部子题。
    """
    from delivery.models import ClarificationQuestion
    from delivery.services import ClarificationService

    session = await PlanSession.objects.acreate(
        entrypoint="chat",
        status=PlanSessionStatus.CLARIFYING,
    )
    svc = ClarificationService()
    clar = await svc.create_round(
        session,
        [
            {"question": "第一题？", "type": "single", "options": ["A", "B"]},
            {"question": "第二题？", "type": "single", "options": ["C", "D"]},
        ],
        round_no=1,
    )
    qids = [
        str(qid)
        async for qid in ClarificationQuestion.objects.filter(clarification_id=clar.id)
        .order_by("order")
        .values_list("id", flat=True)
    ]
    # 仅作答第 0 题 → 该轮部分已答（第 0 题 answered_at 非空、第 1 题仍 NULL）
    await svc.answer_round(clar.id, [{"question_id": qids[0], "selected": "A"}])

    collected = await AIPlanResearchNode._acollect_round_questions(str(clar.id))

    # 整轮全部子题（含已答的第 0 题）均在内、按 order，索引与回调侧逐字一致
    assert len(collected) == 2
    assert collected[0]["question"] == "第一题？"
    assert collected[1]["question"] == "第二题？"
