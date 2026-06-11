"""触发点接线与 source normalizer 测试（Plan 13-03，INGEST-03/05）。

- ``TestNormalizers``（Task 1）：两形态源对象 → IngestionEvent 的取材边界
  （chat content 仅 title+tech_plan，对话原文特征串零泄漏 T-13-01；
  mcp 双事件 + HAS_PLAN EdgeSpec；源缺失容忍返回空列表）。
- ``TestChatTriggers`` / ``TestMcpTriggers`` / ``TestExceptionIsolation``
  （Task 3）：5 锚点投递断言 + 异常隔离（Pitfall 4），由 Task 3 扩展。

测试纪律（RESEARCH Pitfall 5）：一律 monkeypatch 拦截投递，
不真跑 background worker 线程写库；Qdrant / embedding 不触网。
"""

from __future__ import annotations

import json
import uuid

import pytest
from asgiref.sync import sync_to_async
from structlog.testing import capture_logs

from knowledge.ingestion import IngestionRequest, aschedule_ingestion
from knowledge.models import generate_entity_id
from knowledge.sources.coding_plan import normalize as normalize_coding_plan
from knowledge.sources.mcp_plan import normalize as normalize_mcp_plan

# SQLite + async（sync_to_async 跨线程）需要 transaction=True（test_ingestion 同款）。
pytestmark = pytest.mark.django_db(transaction=True)

# 对话原文特征串（T-13-01）：只要 normalizer 触碰对话内容就会被断言抓住。
_SENTINEL = "机密对话原文特征串-XJ9QZ-禁止入图"


def _make_chat_plan(*, with_sentinel_message: bool = False):
    """Project + Conversation + CodingPlan 同步工厂（用例内经 sync_to_async 调用）。"""
    from chat.models import CodingPlan, Conversation, Message
    from projects.models import Project

    project = Project.objects.create(name="知识触发测试项目", feishu_project_key="k-trigger-proj")
    conversation = Conversation.objects.create(project=project, title="知识触发测试对话")
    if with_sentinel_message:
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.USER,
            content=f"用户需求描述：{_SENTINEL}",
        )
    plan = CodingPlan.objects.create(
        conversation=conversation,
        title="登录修复方案",
        tech_plan="## 方案\n\n修复登录超时问题",
        affected_files=[{"file_path": "src/auth.py", "change_type": "modify"}],
        recommended_repository_ids=["11111111-1111-1111-1111-111111111111"],
    )
    return project, conversation, plan


def _make_mcp_artifact(*, with_context: bool = True):
    """InteractionRun + McpWorkItemContext + McpWorkItemTechnicalPlan 同步工厂。"""
    from interactions.ledger import create_interaction_run
    from mcp_tools.models import McpWorkItemContext, McpWorkItemTechnicalPlan
    from projects.models import Project
    from runners.models import hash_token

    project = Project.objects.create(name="知识触发 MCP 项目", feishu_project_key="k-mcp-proj")
    run = create_interaction_run(
        token_fingerprint=hash_token("knowledge-triggers-test"),
        source="mcp",
    )
    context = McpWorkItemContext.objects.create(
        run=run,
        project=project,
        feishu_project_key="k-mcp-proj",
        work_item_type="story",
        work_item_id=1001,
        name="登录需求",
        description="登录超时后提示不清晰。",
    )
    artifact = McpWorkItemTechnicalPlan.objects.create(
        run=run,
        context=context,
        project=project,
        feishu_project_key="k-mcp-proj",
        work_item_type="story",
        work_item_id=1001,
        title="登录技术方案",
        plan_body={"title": "登录技术方案", "summary": "按 1 个仓库任务执行。"},
        markdown="# 登录技术方案\n\n## 仓库任务矩阵\n\n正文",
        repository_tasks=[{"repository_id": "r-1", "planned_branch": "feat/login"}],
        feishu_document_url="https://feishu.cn/docx/doxcnTest",
    )
    return project, context, artifact


class TestNormalizers:
    """Task 1：normalize 取材用例组（-k normalize 可选中）。"""

    async def test_normalize_chat_plan_single_event_fields(self) -> None:
        """chat 取材：单事件、content=title+\\n\\n+tech_plan、payload 三字段快照、零边。"""
        project, _conversation, plan = await sync_to_async(_make_chat_plan)()

        events = await normalize_coding_plan(
            IngestionRequest("coding_plan", str(plan.id), "chat_plan_created")
        )

        assert len(events) == 1
        event = events[0]
        assert event.kind == "tech_plan"
        assert event.origin == "chat"
        assert event.source_kind == "coding_plan"
        assert event.source_id == str(plan.id)
        assert event.content == f"{plan.title}\n\n{plan.tech_plan}"
        assert event.title == plan.title
        assert event.payload["title"] == plan.title
        assert event.payload["affected_files"] == plan.affected_files
        assert event.payload["recommended_repository_ids"] == plan.recommended_repository_ids
        assert event.project_id == str(project.id)
        assert event.repository_id is None
        assert event.event_time == plan.updated_at
        assert event.edges == ()

    async def test_normalize_chat_conversation_text_never_enters_event(self) -> None:
        """T-13-01：conversation 下存在对话原文特征串 → content 与 payload 零泄漏。"""
        _project, _conversation, plan = await sync_to_async(
            lambda: _make_chat_plan(with_sentinel_message=True)
        )()

        events = await normalize_coding_plan(
            IngestionRequest("coding_plan", str(plan.id), "chat_plan_created")
        )

        assert len(events) == 1
        event = events[0]
        assert _SENTINEL not in event.content
        assert _SENTINEL not in json.dumps(event.payload, ensure_ascii=False)
        assert _SENTINEL not in event.title

    async def test_normalize_mcp_plan_dual_events_with_has_plan_edge(self) -> None:
        """mcp 双事件：work_item 锚在前（三元组 source_id + HAS_PLAN EdgeSpec），tech_plan 在后。"""
        project, context, artifact = await sync_to_async(_make_mcp_artifact)()

        events = await normalize_mcp_plan(
            IngestionRequest("mcp_technical_plan", str(artifact.id), "mcp_plan_created")
        )

        assert len(events) == 2
        work_item, tech_plan = events

        assert work_item.kind == "work_item"
        assert work_item.origin == "mcp"
        assert work_item.source_kind == "feishu_work_item"
        assert work_item.source_id == (
            f"{artifact.feishu_project_key}:{artifact.work_item_type}:{artifact.work_item_id}"
        )
        assert work_item.title == context.name
        assert context.description in work_item.content
        assert work_item.project_id == str(project.id)
        assert len(work_item.edges) == 1
        spec = work_item.edges[0]
        assert spec.relation == "HAS_PLAN"
        assert spec.target_entity_id == generate_entity_id(
            "tech_plan", "mcp_technical_plan", str(artifact.id)
        )
        assert spec.exclusive is True

        assert tech_plan.kind == "tech_plan"
        assert tech_plan.origin == "mcp"
        assert tech_plan.source_kind == "mcp_technical_plan"
        assert tech_plan.source_id == str(artifact.id)
        assert tech_plan.title == artifact.title
        assert tech_plan.content == artifact.markdown
        assert tech_plan.payload["feishu_document_url"] == artifact.feishu_document_url
        assert tech_plan.project_id == str(project.id)
        assert tech_plan.event_time == artifact.created_at
        assert tech_plan.edges == ()

    async def test_normalize_source_missing_returns_empty_with_warning(self) -> None:
        """源对象缺失（已删除场景）：两 normalizer 均返回空列表 + warning，不 raise。"""
        missing_id = str(uuid.uuid4())
        with capture_logs() as cap:
            chat_events = await normalize_coding_plan(
                IngestionRequest("coding_plan", missing_id, "chat_plan_created")
            )
            mcp_events = await normalize_mcp_plan(
                IngestionRequest("mcp_technical_plan", missing_id, "mcp_plan_created")
            )
        assert chat_events == []
        assert mcp_events == []
        warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
        assert warnings.count("knowledge_normalize_source_missing") == 2


# ============================================================================
# Task 3：接线投递断言（5 锚点）+ 异常隔离
# ============================================================================


@pytest.fixture
def captured_requests(monkeypatch: pytest.MonkeyPatch) -> list[IngestionRequest]:
    """monkeypatch ``knowledge.ingestion.aschedule_ingestion`` 收集投递请求。

    接线处经 ``from knowledge import ingestion`` + 调用时属性解析，
    monkeypatch 模块属性即可拦截全部 5 锚点投递（Pitfall 5：不真跑 worker）。
    """
    captured: list[IngestionRequest] = []

    async def _collect(request: IngestionRequest) -> None:
        captured.append(request)

    monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", _collect)
    return captured


def _request_triple(request: IngestionRequest) -> tuple[str, str, str]:
    return (request.source_kind, request.source_id, request.trigger)


def _make_fanout_plan():
    """Project + Repository + Conversation + CodingPlan（fan-out 用例同步工厂）。"""
    from chat.models import CodingPlan, Conversation
    from projects.models import Project
    from repositories.models import Repository

    project = Project.objects.create(name="触发fanout项目", feishu_project_key="k-fanout-proj")
    repo = Repository.objects.create(
        name="trigger-repo",
        git_url="https://gitlab.com/test/trigger-repo.git",
        git_platform="gitlab",
        default_branch="main",
    )
    project.repositories.add(repo)
    conversation = Conversation.objects.create(project=project, title="fanout 对话")
    plan = CodingPlan.objects.create(
        conversation=conversation,
        title="fanout 方案",
        tech_plan="## fanout 方案\n\n多仓批量创建",
        affected_files=[],
    )
    return plan, repo


def _make_workflow_plan_execution(
    *,
    with_feishu_trigger: bool = True,
    with_approval: bool = False,
    approval_status: str = "completed",
    approval_node_type: str = "ai_plan_approval",
    approval_data: dict | None = None,
):
    """Project + Workflow + 生成/审批节点 + Execution 同步工厂（14-04 workflow 触发用例）。

    返回 ``(project, execution, gen_node, gen_exec, approval_exec)``；
    ``with_feishu_trigger=False`` 模拟手动触发（trigger_data 无飞书工作项字段）。
    """
    from django.utils import timezone
    from projects.models import Project
    from workflows.models import Workflow, WorkflowNode
    from workflows.models.execution import (
        NodeExecution,
        NodeExecutionStatus,
        WorkflowExecution,
    )

    project = Project.objects.create(
        name="知识触发 workflow 项目", feishu_project_key="k-wf-proj"
    )
    workflow = Workflow.objects.create(name="方案工作流", project=project)
    gen_node = WorkflowNode.objects.create(
        workflow=workflow, node_type="ai_plan_generation", name="方案生成"
    )
    trigger_data = (
        {"raw_payload": {"id": 4242, "work_item_type_key": "story", "name": "登录需求"}}
        if with_feishu_trigger
        else {}
    )
    execution = WorkflowExecution.objects.create(
        workflow=workflow,
        project=project,
        trigger_type="feishu" if with_feishu_trigger else "manual",
        trigger_data=trigger_data,
    )
    plan_dict = {
        "title": "工作流登录方案",
        "summary": "修复登录超时并补充审计日志。",
        "execution_plan": [{"name": "task-1", "repository_name": "repo-a"}],
    }
    gen_exec = NodeExecution.objects.create(
        workflow_execution=execution,
        node=gen_node,
        status=NodeExecutionStatus.COMPLETED,
        output_data={"plan": plan_dict},
        completed_at=timezone.now(),
    )
    approval_exec = None
    if with_approval:
        approval_node = WorkflowNode.objects.create(
            workflow=workflow, node_type=approval_node_type, name="方案审批"
        )
        if approval_data is None:
            if approval_status == NodeExecutionStatus.COMPLETED:
                approval_data = {
                    "plan": plan_dict,
                    "approved": True,
                    "approver_name": "审批人甲",
                    "approved_at": timezone.now().isoformat(),
                    "document_url": "https://feishu.cn/docx/doxcnWfPlan",
                }
            else:
                approval_data = {"plan": plan_dict}
        approval_exec = NodeExecution.objects.create(
            workflow_execution=execution,
            node=approval_node,
            status=approval_status,
            approval_data=approval_data,
            completed_at=(
                timezone.now()
                if approval_status == NodeExecutionStatus.COMPLETED
                else None
            ),
        )
    return project, execution, gen_node, gen_exec, approval_exec


class TestWorkflowPlanNormalizer:
    """14-04 Task 1：workflow_plan normalize 取材用例组（-k workflow 可选中）。"""

    async def test_workflow_plan_generated_dual_events_with_has_plan_edge(self) -> None:
        """生成事件取材：work_item 锚在前（三元组 + HAS_PLAN exclusive），tech_plan 在后。"""
        from knowledge.sources.workflow_plan import normalize as normalize_workflow_plan

        project, execution, gen_node, gen_exec, _ = await sync_to_async(
            _make_workflow_plan_execution
        )()
        source_id = f"{execution.id}:{gen_node.id}"

        events = await normalize_workflow_plan(
            IngestionRequest("workflow_plan", source_id, "workflow_plan_generated")
        )

        assert len(events) == 2
        work_item, tech_plan = events

        assert tech_plan.kind == "tech_plan"
        assert tech_plan.origin == "workflow"
        assert tech_plan.source_kind == "workflow_plan"
        assert tech_plan.source_id == source_id
        plan_dict = gen_exec.output_data["plan"]
        assert plan_dict["title"] in tech_plan.content
        assert plan_dict["summary"] in tech_plan.content
        assert "task-1" in tech_plan.content  # execution_plan 取材
        assert tech_plan.title == plan_dict["title"]
        assert tech_plan.project_id == str(project.id)
        assert tech_plan.repository_id is None
        assert tech_plan.event_time == gen_exec.completed_at
        assert tech_plan.edges == ()

        assert work_item.kind == "work_item"
        assert work_item.origin == "workflow"
        assert work_item.source_kind == "feishu_work_item"
        # natural key 规则表三元组格式逐字一致（models.py generate_entity_id docstring）
        assert work_item.source_id == f"{project.feishu_project_key}:story:4242"
        assert work_item.project_id == str(project.id)
        assert len(work_item.edges) == 1
        spec = work_item.edges[0]
        assert spec.relation == "HAS_PLAN"
        assert spec.target_entity_id == generate_entity_id(
            "tech_plan", "workflow_plan", source_id
        )
        assert spec.exclusive is True

    async def test_workflow_plan_manual_trigger_single_event(self) -> None:
        """trigger_data 无飞书工作项字段（手动触发）→ 只产出 tech_plan 单事件 + warning。"""
        from knowledge.sources.workflow_plan import normalize as normalize_workflow_plan

        _project, execution, gen_node, _gen_exec, _ = await sync_to_async(
            lambda: _make_workflow_plan_execution(with_feishu_trigger=False)
        )()

        with capture_logs() as cap:
            events = await normalize_workflow_plan(
                IngestionRequest(
                    "workflow_plan",
                    f"{execution.id}:{gen_node.id}",
                    "workflow_plan_generated",
                )
            )

        assert len(events) == 1
        assert events[0].kind == "tech_plan"
        warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
        assert "knowledge_normalize_anchor_payload_missing" in warnings

    async def test_workflow_plan_approved_content_contains_approval_section(self) -> None:
        """Pitfall 5：审批事件 content 尾部含审批段且与生成事件 content 不等（hash 必变）。"""
        from datetime import datetime

        from knowledge.sources.workflow_plan import normalize as normalize_workflow_plan

        _project, execution, gen_node, _gen_exec, approval_exec = await sync_to_async(
            lambda: _make_workflow_plan_execution(with_approval=True)
        )()
        source_id = f"{execution.id}:{gen_node.id}"

        generated_events = await normalize_workflow_plan(
            IngestionRequest("workflow_plan", source_id, "workflow_plan_generated")
        )
        approved_events = await normalize_workflow_plan(
            IngestionRequest("workflow_plan", source_id, "workflow_plan_approved")
        )

        generated_plan = generated_events[-1]
        approved_plan = approved_events[-1]
        assert "## 审批" in approved_plan.content
        assert "审批人甲" in approved_plan.content
        assert approved_plan.content != generated_plan.content
        assert "## 审批" not in generated_plan.content
        # event_time 改取 approved_at（aware）
        assert approved_plan.event_time == datetime.fromisoformat(
            approval_exec.approval_data["approved_at"]
        )
        # source_id 不变：审批重摄同一 tech_plan 实体（OQ-2 定案）
        assert approved_plan.source_id == generated_plan.source_id == source_id

    async def test_workflow_plan_source_missing_returns_empty_with_warning(self) -> None:
        """source_id 指向不存在的 NodeExecution → 空列表 + warning 不 raise。"""
        from knowledge.sources.workflow_plan import normalize as normalize_workflow_plan

        missing = f"{uuid.uuid4()}:{uuid.uuid4()}"
        with capture_logs() as cap:
            events = await normalize_workflow_plan(
                IngestionRequest("workflow_plan", missing, "workflow_plan_generated")
            )
        assert events == []
        warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
        assert "knowledge_normalize_source_missing" in warnings


class TestChatTriggers:
    """chat ×3 锚点投递断言（-k chat 可选中）。"""

    async def test_chat_plan_created_delivers_once_dedup_hit_zero(
        self, captured_requests: list[IngestionRequest]
    ) -> None:
        """新建投递 chat_plan_created；同 tech_plan 再调（created=False）零新投递。"""
        from chat.models import CodingPlan, Conversation
        from projects.models import Project

        def _setup():
            project = Project.objects.create(name="触发chat项目", feishu_project_key="k-chat-proj")
            return Conversation.objects.create(project=project, title="触发对话")

        conversation = await sync_to_async(_setup)()

        plan, created = await CodingPlan.aget_or_create_for_conversation(
            conversation, tech_plan="## 新方案\n\n正文", affected_files=[], title="新方案"
        )
        assert created is True
        assert [_request_triple(r) for r in captured_requests] == [
            ("coding_plan", str(plan.id), "chat_plan_created")
        ]

        _same, created_again = await CodingPlan.aget_or_create_for_conversation(
            conversation, tech_plan="## 新方案\n\n正文", affected_files=[], title="新方案"
        )
        assert created_again is False
        assert len(captured_requests) == 1  # 命中去重分支不接（内容未变，投递无增益）

    async def test_chat_plan_updated_delivers(
        self, captured_requests: list[IngestionRequest]
    ) -> None:
        """aupdate_plan 后投递 chat_plan_updated（INGEST-06 chat 版本翻转入口）。"""
        _project, _conversation, plan = await sync_to_async(_make_chat_plan)()

        await plan.aupdate_plan(tech_plan="## 修订方案\n\n新正文", affected_files=[])

        assert [_request_triple(r) for r in captured_requests] == [
            ("coding_plan", str(plan.id), "chat_plan_updated")
        ]

    async def test_chat_coding_started_on_successful_fanout(
        self, captured_requests: list[IngestionRequest]
    ) -> None:
        """create_sessions_for_plan 成功创建 session 后投递 chat_coding_started。"""
        from chat.coding_session_service import create_sessions_for_plan

        plan, repo = await sync_to_async(_make_fanout_plan)()

        result = await create_sessions_for_plan(
            plan=plan,
            repository_ids=[repo.id],
            branch_template="feat20260611.${repo}.ktrigger",
        )

        assert len(result.created) == 1
        assert [_request_triple(r) for r in captured_requests] == [
            ("coding_plan", str(plan.id), "chat_coding_started")
        ]

    async def test_chat_coding_started_zero_delivery_when_all_failed(
        self, captured_requests: list[IngestionRequest]
    ) -> None:
        """全部仓库创建失败（repository_ids 不合法）→ 零投递（OQ-4 挂点语义）。"""
        from chat.coding_session_service import create_sessions_for_plan

        plan, _repo = await sync_to_async(_make_fanout_plan)()

        result = await create_sessions_for_plan(
            plan=plan,
            repository_ids=[uuid.uuid4()],  # 不属于 project 的仓库
        )

        assert result.created == []
        assert len(result.failed) == 1
        assert captured_requests == []


class TestMcpTriggers:
    """MCP ×2 锚点投递断言（-k mcp 可选中）。"""

    async def test_mcp_plan_created_delivers(
        self, captured_requests: list[IngestionRequest]
    ) -> None:
        """build_work_item_technical_plan 成功产出 artifact 后投递 mcp_plan_created。"""
        from interactions.ledger import create_interaction_run
        from mcp_tools.models import McpWorkItemContext
        from mcp_tools.technical_plan_service import build_work_item_technical_plan
        from projects.models import Project
        from runners.models import hash_token

        def _setup():
            project = Project.objects.create(name="触发mcp项目", feishu_project_key="k-mcp-t-proj")
            run = create_interaction_run(
                token_fingerprint=hash_token("knowledge-trigger-mcp"), source="mcp"
            )
            context = McpWorkItemContext.objects.create(
                run=run,
                project=project,
                feishu_project_key="k-mcp-t-proj",
                work_item_type="story",
                work_item_id=2002,
                name="触发测试需求",
                description="触发测试描述",
            )
            return run, context

        run, context = await sync_to_async(_setup)()

        result = await build_work_item_technical_plan(
            run=run,
            context_id=str(context.id),
            repository_ids=[],
            repo_hints=[],
            context_chunks=[],
            similar_cases=[{"case_id": "c1", "title": "先例", "outcome": "merged"}],
            title="触发测试技术方案",
            folder_token="",
            create_document=False,
            write_comment=False,
        )

        assert [_request_triple(r) for r in captured_requests] == [
            ("mcp_technical_plan", str(result.artifact.id), "mcp_plan_created")
        ]

    async def test_mcp_tasks_executed_delivers(
        self,
        captured_requests: list[IngestionRequest],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """execute_work_item_repo_tasks 成功返回时投递 mcp_tasks_executed。

        对 service 内部依赖做最小 mock（_resolve_tasks / _execute_one_task /
        repo_task_payload），断言点不变：source_kind/source_id/trigger 三元组。
        """
        from types import SimpleNamespace

        from mcp_tools import work_item_execution_service as wie
        from mcp_tools.models import McpWorkItemRepoTask

        _project, _context, artifact = await sync_to_async(_make_mcp_artifact)()
        run = await sync_to_async(lambda: artifact.run)()
        fake_task = SimpleNamespace(status=McpWorkItemRepoTask.Status.COMPLETED)

        async def _fake_resolve_tasks(**kw):
            return artifact, [fake_task]

        async def _fake_execute_one(**kw):
            return kw["task"]

        monkeypatch.setattr(wie, "_resolve_tasks", _fake_resolve_tasks)
        monkeypatch.setattr(wie, "_execute_one_task", _fake_execute_one)
        monkeypatch.setattr(wie, "repo_task_payload", lambda task: {"status": str(task.status)})
        monkeypatch.setattr(wie, "_execution_results_markdown", lambda tasks: "# 执行结果")

        result = await wie.execute_work_item_repo_tasks(
            run=run,
            technical_plan_id=str(artifact.id),
            task_ids=[],
            create_missing=False,
            dispatch=False,
            create_merge_requests=False,
            write_back=False,
            timeout_seconds=10,
            reviewer_usernames=[],
        )

        assert result.output["status"] == "completed"
        assert [_request_triple(r) for r in captured_requests] == [
            ("mcp_technical_plan", str(artifact.id), "mcp_tasks_executed")
        ]


class TestExceptionIsolation:
    """Pitfall 4：ingestion 投递链路抛错时宿主主流程仍成功返回。"""

    async def test_chat_main_flow_survives_runner_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_in_background 抛 RuntimeError → aget_or_create_for_conversation 仍成功。"""
        from chat.models import CodingPlan, Conversation
        from projects.models import Project

        def _boom(factory, *, name=None):
            raise RuntimeError("runner down")

        monkeypatch.setattr("knowledge.ingestion.run_in_background", _boom)

        def _setup():
            project = Project.objects.create(name="隔离chat项目", feishu_project_key="k-iso-proj")
            return Conversation.objects.create(project=project, title="隔离对话")

        conversation = await sync_to_async(_setup)()
        plan, created = await CodingPlan.aget_or_create_for_conversation(
            conversation, tech_plan="## 隔离方案\n\n正文", affected_files=[], title="隔离方案"
        )
        assert created is True
        assert plan.id is not None

    async def test_mcp_main_flow_survives_runner_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_in_background 抛 RuntimeError → build_work_item_technical_plan 仍成功。"""
        from interactions.ledger import create_interaction_run
        from mcp_tools.models import McpWorkItemContext
        from mcp_tools.technical_plan_service import build_work_item_technical_plan
        from runners.models import hash_token

        def _boom(factory, *, name=None):
            raise RuntimeError("runner down")

        monkeypatch.setattr("knowledge.ingestion.run_in_background", _boom)

        def _setup():
            run = create_interaction_run(
                token_fingerprint=hash_token("knowledge-iso-mcp"), source="mcp"
            )
            context = McpWorkItemContext.objects.create(
                run=run,
                feishu_project_key="k-iso-mcp",
                work_item_type="bug",
                work_item_id=3003,
                name="隔离需求",
            )
            return run, context

        run, context = await sync_to_async(_setup)()
        result = await build_work_item_technical_plan(
            run=run,
            context_id=str(context.id),
            repository_ids=[],
            repo_hints=[],
            context_chunks=[],
            similar_cases=[{"case_id": "c1"}],
            title="隔离技术方案",
            folder_token="",
            create_document=False,
            write_comment=False,
        )
        assert result.artifact.id is not None

    async def test_schedule_registration_failure_warns_not_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sync_to_async 注册体抛错 → aschedule_ingestion warning 记录且不上抛。"""

        def _boom_sync_to_async(func, **kw):
            async def _inner(*args, **kwargs):
                raise RuntimeError("registration boom")

            return _inner

        monkeypatch.setattr("knowledge.ingestion.sync_to_async", _boom_sync_to_async)
        with capture_logs() as cap:
            await aschedule_ingestion(
                IngestionRequest("coding_plan", "iso-plan", "chat_plan_updated")
            )
        warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
        assert "knowledge_ingest_schedule_failed" in warnings
