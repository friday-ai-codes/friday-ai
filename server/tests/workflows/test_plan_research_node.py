"""AIPlanResearchNode 节点单测（ENTRY-01，Chassis v2 · P2）。

覆盖：建 ConvergenceSession(entrypoint=workflow) + 驱动 ProcessEngine 到 done（adapters mock
在 IO 边界）→ NodeResult completed（artifact_version_id 非空）/ clarify 挂起 waiting_event /
failed 映射 / schema 合法 + 自动注册。用真实 ConvergenceSession + 真实 ProcessEngine，
IO 边界 mock；done 出口产物经 ArtifactVersion 承载。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from delivery.models import (
    Artifact,
    ArtifactVersion,
    Clarification,
    ConvergenceSession,
    ConvergenceSessionStatus,
)
from delivery.services import ConvergenceSessionService
from services.process_runtime import ClarifyAdapter, ProcessEngine
from workflows.nodes.ai.plan_research import AIPlanResearchNode
from workflows.nodes.base import ExecutionContext
from workflows.nodes.registry import NodeRegistry

# async ORM 测试用 transaction=True（真实 commit + 表间清理，对齐 test_research_completion_callback）
pytestmark = pytest.mark.django_db(transaction=True)

_LLM_GEN = "services.process_runtime.clarify_adapter.agenerate_clarification_questions"


def _ctx(config: dict | None = None) -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec-pr-001",
        node_id="node-pr-001",
        node_config=config or {"requirement_text": "为多仓需求做方案编排"},
        input_data={},
        workflow_context={},
        previous_outputs={},
    )


def _bind_engine(node: AIPlanResearchNode, engine: ProcessEngine) -> None:
    node._build_engine = lambda context, session: engine  # type: ignore[assignment]


def _engine(**deps) -> ProcessEngine:
    return ProcessEngine(
        session_service=ConvergenceSessionService(), deps=SimpleNamespace(**deps)
    )


async def _make_artifact_version(content: dict) -> ArtifactVersion:
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    av = await ArtifactVersion.objects.acreate(
        artifact=artifact, version_no=1, content=content, content_hash="h"
    )
    artifact.current_version = av
    await artifact.asave(update_fields=["current_version", "updated_at"])
    return av


def _full_deps(*, router, recall, merge, clarify=None, research=None):
    if recall is None:
        recall = AsyncMock()
        recall.recall = AsyncMock(return_value={"hits": [], "query": "q", "kinds": []})
    if research is None:
        research = AsyncMock()
        research.dispatch = AsyncMock(return_value={})
    if clarify is None:
        clarify = AsyncMock()
        clarify.clarify = AsyncMock(return_value={"needs_clarification": False})
    return dict(router=router, recall=recall, research=research, merge=merge, clarify=clarify)


@pytest.mark.asyncio
async def test_drive_to_done_emits_merged_plan_ref() -> None:
    """建 session + 驱动到 done → completed + output.artifact_version_id 非空 + status done。"""
    av = await _make_artifact_version({"title": "T", "summary": "s"})

    router = AsyncMock()
    router.route = AsyncMock(
        return_value={
            "candidates": [
                {"repo_id": "r1", "confidence": "high"},
                {"repo_id": "r2", "confidence": "high"},
            ]
        }
    )
    merge = AsyncMock()
    merge.merge = AsyncMock(
        return_value={"validation_status": "passed", "artifact_version_id": str(av.id), "attempt": 0}
    )

    engine = _engine(**_full_deps(router=router, recall=None, merge=merge))
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    result = await node.execute(_ctx())

    assert result.status == "completed"
    assert result.output["artifact_version_id"] == str(av.id)
    assert result.output["status"] == "done"
    session = await ConvergenceSession.objects.aget(id=result.output["session_id"])
    assert session.status == ConvergenceSessionStatus.DONE
    assert session.entrypoint == "workflow"


@pytest.mark.asyncio
async def test_done_inlines_merged_plan_content_for_downstream() -> None:
    """done → output["plan"] 内联 §7 MergedPlan content（含 execution_plan）+ 注入
    artifact_version_id，供下游 human_approval / ai_coding 直接消费。"""
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
    av = await _make_artifact_version(merged_content)

    router = AsyncMock()
    router.route = AsyncMock(
        return_value={"candidates": [{"repo_id": "r1", "confidence": "high"}]}
    )
    merge = AsyncMock()
    merge.merge = AsyncMock(
        return_value={"validation_status": "passed", "artifact_version_id": str(av.id), "attempt": 0}
    )

    engine = _engine(**_full_deps(router=router, recall=None, merge=merge))
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    result = await node.execute(_ctx())

    assert result.status == "completed"
    assert result.output["artifact_version_id"] == str(av.id)
    plan = result.output["plan"]
    assert plan["title"] == "跨仓主方案"
    assert plan["summary"] == "融合 repoA/repoB 的跨仓方案"
    assert plan["execution_plan"][0]["repository_id"] == "repo-a"
    assert plan["artifact_version_id"] == str(av.id)


@pytest.mark.asyncio
async def test_resume_via_session_id_ignores_conflicting_input() -> None:
    """D2 点4 二义性契约：本节点 output_data.session_id 在场时，resume 续推**同一**
    session，完全忽略 input/config 中冲突的 requirement_text，且不新建 session。"""
    existing = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint="workflow",
        current_stage="merge",
        status=ConvergenceSessionStatus.DONE,
        stage_state={"decomposition": {"requirement_text": "原始需求"}},
    )

    node_execution = MagicMock()
    node_execution.id = uuid.uuid4()
    node_execution.output_data = {"session_id": str(existing.id)}

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
    engine = MagicMock()

    async def _advance(session):
        return session

    engine.advance = AsyncMock(side_effect=_advance)
    _bind_engine(node, engine)

    before = await ConvergenceSession.objects.acount()
    result = await node.execute(ctx)
    after = await ConvergenceSession.objects.acount()

    assert before == after == 1
    assert result.output["session_id"] == str(existing.id)
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_clarifying_suspends_waiting_event() -> None:
    """needs-clarification → waiting_event（不 completed）+ DB pending + waiting_clarification。

    注：结构化轮容器 question 占位为空串（真身在子题），故 suspension.question 现为空；
    验证发问内容改为断言子题 question（与新 CLARIFY-01 结构化轮模型一致）。
    """
    from delivery.models import ClarificationQuestion

    router = AsyncMock()
    router.route = AsyncMock(return_value={"candidates": []})
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={"hits": [], "query": "", "kinds": []})
    clarify = ClarifyAdapter(policy=lambda s: (True, "请补充涉及的仓库", []))

    engine = _engine(router=router, recall=recall, clarify=clarify)
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    with patch(_LLM_GEN, new=AsyncMock(return_value=[])):
        result = await node.execute(_ctx())

    assert result.status == "waiting_event"
    assert result.output["kind"] == "clarification"
    session = await ConvergenceSession.objects.aget(id=result.output["session_id"])
    assert session.status == ConvergenceSessionStatus.WAITING_CLARIFICATION
    assert (
        await Clarification.objects.filter(
            session_id=session.id, answered_at__isnull=True
        ).acount()
        == 1
    )
    child = await ClarificationQuestion.objects.filter(
        clarification__session_id=session.id
    ).afirst()
    assert child is not None
    assert child.question == "请补充涉及的仓库"


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
    assert value["action"] == "plan_clarify_answer"
    assert value["clarification_id"] == "clar-9"
    assert value["execution_id"] == "exec-123"
    assert value["node_id"] == "node-456"
    assert value["question_count"] == 2
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
    """WR-03：waiting_clarification 存在性判定经 ahas_pending——结构化子题未答→挂起；全答→不误挂起。"""
    from delivery.models import ClarificationQuestion
    from delivery.services.clarification_service import ClarificationService

    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint="workflow",
        current_stage="clarify",
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION,
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
    ctx = _ctx()

    suspend = await node._maybe_suspend(session, ctx)
    assert suspend is not None
    assert suspend.status == "waiting_event"
    assert suspend.output["kind"] == "clarification"

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


async def _seed_clarifying_round() -> ConvergenceSession:
    """建 waiting_clarification session + 结构化多子题 pending 轮。"""
    from delivery.services.clarification_service import ClarificationService

    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint="workflow",
        current_stage="clarify",
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION,
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
    """CLARIFY-05：工作流入口挂起 → 发 build_clarification_card 到群 + 建订阅。"""
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
    im.send_card.assert_awaited_once()
    assert sent["receive_id"] == "chat-123"
    assert sent["receive_id_type"] == "chat_id"
    value = _form_submit_value(sent["card"])
    assert value["action"] == "plan_clarify_answer"
    assert value["clarification_id"] == result.output["suspension"]["clarification_id"]
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
    acreate.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_terminal_maps_to_node_failed() -> None:
    """merge 限次耗尽 → failed → NodeResult failed + error_code=plan_session_failed。"""
    router = AsyncMock()
    router.route = AsyncMock(
        return_value={"candidates": [{"repo_id": "r1", "confidence": "high"}]}
    )
    merge = AsyncMock()
    merge.merge = AsyncMock(
        return_value={"validation_status": "failed", "attempt": 1, "report": {}}
    )

    engine = _engine(**_full_deps(router=router, recall=None, merge=merge))
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    result = await node.execute(_ctx())

    assert result.status == "failed"
    assert result.output["error_code"] == "plan_session_failed"
    session = await ConvergenceSession.objects.aget(id=result.output["session_id"])
    assert session.status == ConvergenceSessionStatus.FAILED


@pytest.mark.asyncio
async def test_missing_requirement_fails_fast() -> None:
    """无 requirement_text 且无上游输入 → 快速失败（missing_requirement），不建 session。"""
    node = AIPlanResearchNode()
    result = await node.execute(_ctx({"requirement_text": ""}))
    assert result.status == "failed"
    assert result.output["error_code"] == "missing_requirement"
    assert await ConvergenceSession.objects.acount() == 0


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
    input_names = {p.name for p in cls.inputs}
    assert input_names == {"default", "resume"}
    output_names = {p.name for p in cls.outputs}
    assert output_names == {"default", "clarify", "error"}
    default_out = next(p for p in cls.outputs if p.name == "default")
    assert "artifact_version_id" in (default_out.schema or {}).get("properties", {})


def test_clarify_resume_slot_ports_declared() -> None:
    """SLOT-02 behavior 1/2：clarify(out, clarification_request)/resume(in, clarification_answer)
    插槽端口声明；default/error 生产端口逐字保留且 shape 恒空（validator 通配命门）。"""
    cls = AIPlanResearchNode

    resume_in = next(p for p in cls.inputs if p.name == "resume")
    assert resume_in.shape == "clarification_answer"
    default_in = next(p for p in cls.inputs if p.name == "default")
    assert default_in.shape == ""

    clarify_out = next(p for p in cls.outputs if p.name == "clarify")
    assert clarify_out.shape == "clarification_request"
    default_out = next(p for p in cls.outputs if p.name == "default")
    error_out = next(p for p in cls.outputs if p.name == "error")
    assert default_out.shape == ""
    assert error_out.shape == ""


def test_get_schema_exposes_clarify_shape() -> None:
    """SLOT-02 behavior 3：get_schema() outputs 中 clarify 项含 shape=clarification_request。"""
    schema = AIPlanResearchNode.get_schema()
    out_by_name = {p["name"]: p for p in schema["outputs"]}
    assert out_by_name["clarify"]["shape"] == "clarification_request"
    assert out_by_name["default"]["shape"] == ""
    in_by_name = {p["name"]: p for p in schema["inputs"]}
    assert in_by_name["resume"]["shape"] == "clarification_answer"


def test_render_merged_plan_markdown_title_and_summary() -> None:
    """Task 1 Test 1：含 title → 输出含 `**{title}**`；含 summary → 含 summary 文本。"""
    from services.process_runtime import render_merged_plan_markdown

    md = render_merged_plan_markdown(
        {"title": "跨仓主方案", "summary": "融合 repoA/repoB 的跨仓方案"}
    )
    assert "**跨仓主方案**" in md
    assert "融合 repoA/repoB 的跨仓方案" in md


def test_render_merged_plan_markdown_execution_plan() -> None:
    """Task 1 Test 2：execution_plan 非空 → 含「执行计划（共 N 项）」+ 逐任务 name +
    repository_name；coding_instruction 超 300 字符截断带省略号。"""
    from services.process_runtime import render_merged_plan_markdown

    long_instruction = "实" * 400
    md = render_merged_plan_markdown(
        {
            "title": "T",
            "execution_plan": [
                {
                    "name": "A 暴露契约",
                    "repository_name": "repoA",
                    "description": "实现契约层",
                    "coding_instruction": long_instruction,
                },
                {"name": "B 调用契约", "repository_name": "repoB"},
            ],
        }
    )
    assert "执行计划（共 2 项）" in md
    assert "A 暴露契约" in md
    assert "repoA" in md
    assert "B 调用契约" in md
    assert "repoB" in md
    assert "…" in md
    assert long_instruction not in md


def test_render_merged_plan_markdown_compat_risks_uses_bullet() -> None:
    """Task 1 Test 3：compat_risks 非空 → 用 `•` 字面项目符号（不用 Markdown `- ` 列表）。"""
    from services.process_runtime import render_merged_plan_markdown

    md = render_merged_plan_markdown(
        {"title": "T", "compat_risks": ["接口不兼容", "数据迁移风险"]}
    )
    assert "• 接口不兼容" in md
    assert "• 数据迁移风险" in md
    assert "- 接口不兼容" not in md


def test_render_merged_plan_markdown_defensive_non_dict() -> None:
    """Task 1 Test 4：半可信输入防御——顶层非 dict / 空 dict → 返回空串，绝不抛异常。"""
    from services.process_runtime import render_merged_plan_markdown

    assert render_merged_plan_markdown(None) == ""
    assert render_merged_plan_markdown("not a dict") == ""
    assert render_merged_plan_markdown([1, 2, 3]) == ""
    assert render_merged_plan_markdown({}) == ""


def test_render_merged_plan_markdown_excludes_raw_llm_text() -> None:
    """Task 1 Test 5：渲染结果不含 LLM 原始文本字段（仅消费 MergedPlan 结构化字段）。"""
    from services.process_runtime import render_merged_plan_markdown

    md = render_merged_plan_markdown(
        {
            "title": "干净标题",
            "summary": "干净摘要",
            "raw_output": "LLM 原始自由文本不应出现 SECRET_RAW",
            "raw_response": "```json {...}``` 原始响应",
        }
    )
    assert "SECRET_RAW" not in md
    assert "原始响应" not in md
    assert "干净标题" in md


@pytest.mark.asyncio
async def test_done_output_includes_plan_markdown() -> None:
    """Task 2 Test 1：DONE + 合法 MergedPlan content → output 含 plan_markdown 非空字符串，
    且既有字段零回归。"""
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
    av = await _make_artifact_version(merged_content)

    router = AsyncMock()
    router.route = AsyncMock(
        return_value={"candidates": [{"repo_id": "r1", "confidence": "high"}]}
    )
    merge = AsyncMock()
    merge.merge = AsyncMock(
        return_value={"validation_status": "passed", "artifact_version_id": str(av.id), "attempt": 0}
    )

    engine = _engine(**_full_deps(router=router, recall=None, merge=merge))
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    result = await node.execute(_ctx())

    assert result.status == "completed"
    md = result.output["plan_markdown"]
    assert isinstance(md, str)
    assert "**跨仓主方案**" in md
    assert "融合 repoA/repoB 的跨仓方案" in md
    assert result.output["artifact_version_id"] == str(av.id)
    assert result.output["session_id"]
    assert result.output["status"] == "done"
    assert result.output["plan"]["title"] == "跨仓主方案"


@pytest.mark.asyncio
async def test_done_plan_markdown_empty_when_no_content() -> None:
    """Task 2 Test 2：DONE 但 current_artifact_version 为空 → plan_markdown 空串（不抛），plan={}。"""
    router = AsyncMock()
    router.route = AsyncMock(return_value={"candidates": []})
    merge = AsyncMock()
    # merge passed 但不返回 artifact_version_id → current_artifact_version 留空
    merge.merge = AsyncMock(return_value={"validation_status": "passed", "attempt": 0})

    engine = _engine(**_full_deps(router=router, recall=None, merge=merge))
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    result = await node.execute(_ctx())

    assert result.status == "completed"
    assert result.output["plan_markdown"] == ""
    assert result.output["plan"] == {}


def test_default_output_schema_declares_plan_markdown() -> None:
    """Task 2 Test 3：get_schema() default 输出端口 schema.properties 含 plan_markdown
    (type string)，既有 artifact_version_id/session_id/status/plan 键保留。"""
    schema = AIPlanResearchNode.get_schema()
    out_by_name = {p["name"]: p for p in schema["outputs"]}
    props = out_by_name["default"]["schema"]["properties"]
    assert props["plan_markdown"]["type"] == "string"
    assert {"artifact_version_id", "session_id", "status", "plan"} <= set(props)


@pytest.mark.asyncio
async def test_failed_branch_no_plan_markdown_regression() -> None:
    """Task 2 Test 4：failed 分支零回归——next_handle=error，无 plan_markdown 依赖。"""
    router = AsyncMock()
    router.route = AsyncMock(
        return_value={"candidates": [{"repo_id": "r1", "confidence": "high"}]}
    )
    merge = AsyncMock()
    merge.merge = AsyncMock(
        return_value={"validation_status": "failed", "attempt": 1, "report": {}}
    )

    engine = _engine(**_full_deps(router=router, recall=None, merge=merge))
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    result = await node.execute(_ctx())

    assert result.status == "failed"
    assert result.next_handle == "error"
    assert "plan_markdown" not in result.output


@pytest.mark.asyncio
async def test_acollect_round_questions_includes_answered_subquestions() -> None:
    """WR-01 不变量：发卡侧整轮按 order 取子题（含已答），与回调侧逐字一致、不漂移。"""
    from delivery.models import ClarificationQuestion
    from delivery.services import ClarificationService

    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint="chat",
        current_stage="clarify",
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION,
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
    await svc.answer_round(clar.id, [{"question_id": qids[0], "selected": "A"}])

    collected = await AIPlanResearchNode._acollect_round_questions(str(clar.id))

    assert len(collected) == 2
    assert collected[0]["question"] == "第一题？"
    assert collected[1]["question"] == "第二题？"
