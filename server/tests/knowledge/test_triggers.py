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
    approval_node_type: str = "human_approval",
    approval_config: dict | None = None,
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

    project = Project.objects.create(name="知识触发 workflow 项目", feishu_project_key="k-wf-proj")
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
        # human_approval 缺省按方案审批（mode=plan_feishu）注入，触发 ingestion 钩子；
        # 其它节点类型保持空配置（如 manual_confirm → 零投递）。
        if approval_config is None:
            approval_config = (
                {"mode": "plan_feishu"} if approval_node_type == "human_approval" else {}
            )
        approval_node = WorkflowNode.objects.create(
            workflow=workflow,
            node_type=approval_node_type,
            name="方案审批",
            config=approval_config,
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
                timezone.now() if approval_status == NodeExecutionStatus.COMPLETED else None
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
        assert spec.target_entity_id == generate_entity_id("tech_plan", "workflow_plan", source_id)
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


def _make_feishu_project(*, with_feishu_config: bool = False):
    """Project 同步工厂（feishu_work_item normalizer / 三 handler 接线用例）。"""
    from projects.models import Project

    kw = {}
    if with_feishu_config:
        kw = {"feishu_plugin_id": "plg-test", "feishu_plugin_secret_encrypted": "enc"}
    return Project.objects.create(
        name="知识触发 feishu 项目", feishu_project_key="k-feishu-proj", **kw
    )


class FakeFeishuClient:
    """fake FeishuClient：按用例预置 work_item / relations 应答（零网络）。"""

    def __init__(
        self,
        *,
        work_item=None,
        relations: list[dict] | None = None,
        work_item_error: Exception | None = None,
        relations_error: Exception | None = None,
    ) -> None:
        self.work_item = work_item
        self.relations = relations or []
        self.work_item_error = work_item_error
        self.relations_error = relations_error
        self.get_work_item_calls: list[dict] = []

    async def get_work_item(self, project_key, work_item_id, work_item_type="story"):
        self.get_work_item_calls.append(
            {
                "project_key": project_key,
                "work_item_id": work_item_id,
                "work_item_type": work_item_type,
            }
        )
        if self.work_item_error is not None:
            raise self.work_item_error
        return self.work_item

    async def get_work_item_relations(self, project_key, work_item_id, work_item_type):
        if self.relations_error is not None:
            raise self.relations_error
        return self.relations


class FakeFeishuDocClient:
    """fake FeishuDocClient：按 doc token 返回正文；可整体抛错（文档降级用例）。"""

    def __init__(
        self, *, docs: dict[str, str] | None = None, error: Exception | None = None
    ) -> None:
        self.docs = docs or {}
        self.error = error
        self.fetch_calls: list[str] = []

    async def get_document_content(self, document_id: str):
        self.fetch_calls.append(document_id)
        if self.error is not None:
            raise self.error
        return self.docs[document_id], []


def _make_work_item_info(*, fields: dict | None = None):
    """WorkItemInfo 工厂：默认含 PRD/技术方案 URL 双字段。"""
    from feishu.models import KeyFields
    from services.feishu import WorkItemInfo

    if fields is None:
        fields = {
            KeyFields.PRD_URL: "https://feishu.cn/docx/doxcnPrdToken",
            KeyFields.TECH_DOC_URL: "https://feishu.cn/docx/doxcnTechToken",
            "priority": "P0",
        }
    return WorkItemInfo(
        id=5001,
        name="登录优化需求",
        description="登录超时需要更清晰的提示。",
        status="developing",
        project_key="k-feishu-proj",
        work_item_type="story",
        fields=fields,
    )


def _patch_feishu_clients(
    monkeypatch: pytest.MonkeyPatch,
    *,
    client: FakeFeishuClient,
    doc_client: FakeFeishuDocClient | None = None,
):
    """以模块属性形态把 fake 客户端注入 ``knowledge.sources.feishu_work_item``。"""
    monkeypatch.setattr(
        "knowledge.sources.feishu_work_item.create_feishu_client_for_project",
        lambda project: client,
    )

    async def _make_doc_client(project):
        if doc_client is None:
            raise AssertionError("用例未预置 doc client")
        return doc_client

    monkeypatch.setattr(
        "knowledge.sources.feishu_work_item.create_feishu_doc_client_for_project",
        _make_doc_client,
    )


class TestFeishuWorkItemNormalizer:
    """14-05 Task 1：feishu_work_item normalize 取材用例组（-k feishu 可选中）。"""

    def test_feishu_doc_token_strips_query_and_fragment(self) -> None:
        """WR-03：带 query/fragment 的文档 URL 剥参后取末段 path；裸 token 原样返回。"""
        from knowledge.sources.feishu_work_item import _extract_doc_token

        assert (
            _extract_doc_token("https://xxx.feishu.cn/docx/doxcnABC?from=tab_search") == "doxcnABC"
        )
        assert _extract_doc_token("https://xxx.larksuite.com/docx/doxcnABC#heading-1") == "doxcnABC"
        assert _extract_doc_token("https://xxx.feishu.cn/docx/doxcnABC/?from=tab") == "doxcnABC"
        assert _extract_doc_token("https://xxx.feishu.cn/docx/doxcnABC") == "doxcnABC"
        assert _extract_doc_token("doxcnABC") == "doxcnABC"
        assert _extract_doc_token("") == ""
        assert _extract_doc_token(None) == ""

    async def test_feishu_full_snapshot_single_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """全量快照取材：单事件，content 含名称/描述/自定义字段/PRD/技术方案/关联工作项各段。"""
        from knowledge.sources.feishu_work_item import normalize as normalize_feishu

        project = await sync_to_async(_make_feishu_project)()
        info = _make_work_item_info()
        client = FakeFeishuClient(
            work_item=info,
            relations=[
                {
                    "relation_type": "parent",
                    "work_item_id": 4000,
                    "work_item_type": "story",
                    "name": "登录大需求",
                    "status": "developing",
                }
            ],
        )
        doc_client = FakeFeishuDocClient(
            docs={
                "doxcnPrdToken": "PRD 正文：登录提示要清晰。",
                "doxcnTechToken": "技术方案正文：超时重试。",
            }
        )
        _patch_feishu_clients(monkeypatch, client=client, doc_client=doc_client)
        source_id = f"{project.feishu_project_key}:story:5001"

        events = await normalize_feishu(
            IngestionRequest("feishu_work_item", source_id, "feishu_workitem_update")
        )

        assert len(events) == 1
        event = events[0]
        assert event.kind == "work_item"
        assert event.origin == "feishu"
        assert event.source_kind == "feishu_work_item"
        assert event.source_id == source_id  # 三元组原样回填
        assert info.name in event.content
        assert info.description in event.content
        assert "## 自定义字段" in event.content
        assert "priority" in event.content
        assert "## PRD" in event.content
        assert "PRD 正文：登录提示要清晰。" in event.content
        assert "## 技术方案" in event.content
        assert "技术方案正文：超时重试。" in event.content
        assert "## 关联工作项" in event.content
        assert "登录大需求" in event.content
        assert event.payload["status"] == "developing"
        assert event.payload["work_item_type"] == "story"
        assert event.project_id == str(project.id)
        assert event.project_id

    async def test_feishu_same_key_reingest_upgrades_anchor_to_v2(
        self, monkeypatch: pytest.MonkeyPatch, mock_embedding, mock_qdrant_client
    ) -> None:
        """同 key 升级语义：13-03 轻量锚先入图，全量快照重摄 → 同实体 v2（版本链）。"""
        from unittest.mock import AsyncMock

        from knowledge.ingestion import IngestionEvent, ingest_events
        from knowledge.models import KnowledgeEntity, KnowledgeEntityVersion
        from knowledge.sources.feishu_work_item import normalize as normalize_feishu

        monkeypatch.setattr("knowledge.ingestion.ensure_delivery_knowledge_collection", AsyncMock())
        from services.qdrant_service import QdrantService

        monkeypatch.setattr(
            QdrantService, "upsert_vectors_by_name", classmethod(lambda cls, name, pts: True)
        )

        project = await sync_to_async(_make_feishu_project)()
        source_id = f"{project.feishu_project_key}:story:5001"
        from django.utils import timezone as dj_tz

        anchor_event = IngestionEvent(
            kind="work_item",
            origin="mcp",
            source_kind="feishu_work_item",
            source_id=source_id,
            title="登录优化需求",
            content="登录优化需求\n\n登录超时需要更清晰的提示。",
            payload={"name": "登录优化需求"},
            project_id=str(project.id),
            repository_id=None,
            event_time=dj_tz.now(),
        )
        await ingest_events([anchor_event])
        assert await KnowledgeEntity.objects.acount() == 1

        client = FakeFeishuClient(work_item=_make_work_item_info())
        doc_client = FakeFeishuDocClient(
            docs={
                "doxcnPrdToken": "PRD 正文",
                "doxcnTechToken": "技术方案正文",
            }
        )
        _patch_feishu_clients(monkeypatch, client=client, doc_client=doc_client)
        events = await normalize_feishu(
            IngestionRequest("feishu_work_item", source_id, "feishu_workitem_update")
        )
        await ingest_events(events)

        # 实体数不变：同 natural key 重摄是版本翻转，不是新实体
        assert await KnowledgeEntity.objects.acount() == 1
        entity = await KnowledgeEntity.objects.aget()
        assert entity.current_version == 2
        v1 = await KnowledgeEntityVersion.objects.aget(version=1)
        v2 = await KnowledgeEntityVersion.objects.aget(version=2)
        assert v2.is_latest is True
        assert v2.supersedes_id == v1.id
        assert "## 自定义字段" in v2.content

    async def test_feishu_doc_fetch_failure_degrades_to_snapshot_without_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """文档降级：doc client 抛异常 → 事件仍产出，无 PRD/技术方案段 + warning。"""
        from knowledge.sources.feishu_work_item import normalize as normalize_feishu

        project = await sync_to_async(_make_feishu_project)()
        client = FakeFeishuClient(work_item=_make_work_item_info())
        doc_client = FakeFeishuDocClient(error=RuntimeError("doc api down"))
        _patch_feishu_clients(monkeypatch, client=client, doc_client=doc_client)

        with capture_logs() as cap:
            events = await normalize_feishu(
                IngestionRequest(
                    "feishu_work_item",
                    f"{project.feishu_project_key}:story:5001",
                    "feishu_workitem_update",
                )
            )

        assert len(events) == 1
        event = events[0]
        assert "## PRD" not in event.content
        assert "## 技术方案" not in event.content
        assert "## 自定义字段" in event.content
        assert "登录优化需求" in event.content
        warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
        assert "knowledge_normalize_doc_fetch_failed" in warnings

    async def test_feishu_event_time_always_aware(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """event_time aware 双场景：毫秒时间戳 → 对应 UTC；字段缺失 → timezone.now() 兜底。"""
        from datetime import UTC, datetime

        from django.utils import timezone as dj_tz

        from feishu.models import KeyFields
        from knowledge.sources.feishu_work_item import normalize as normalize_feishu

        project = await sync_to_async(_make_feishu_project)()
        ms = 1750000000000  # 2025-06-15T15:06:40Z
        info_with_ts = _make_work_item_info(fields={KeyFields.PRD_URL: "", "updated_at": ms})
        client = FakeFeishuClient(work_item=info_with_ts)
        _patch_feishu_clients(monkeypatch, client=client, doc_client=FakeFeishuDocClient())
        source_id = f"{project.feishu_project_key}:story:5001"

        events = await normalize_feishu(
            IngestionRequest("feishu_work_item", source_id, "feishu_workitem_update")
        )
        assert len(events) == 1
        event = events[0]
        assert event.event_time.tzinfo is not None
        assert event.event_time == datetime.fromtimestamp(ms / 1000, tz=UTC)

        # 场景 2：时间字段缺失 → 接近 timezone.now() 且 aware
        info_no_ts = _make_work_item_info(fields={})
        client2 = FakeFeishuClient(work_item=info_no_ts)
        _patch_feishu_clients(monkeypatch, client=client2, doc_client=FakeFeishuDocClient())
        before = dj_tz.now()
        events2 = await normalize_feishu(
            IngestionRequest("feishu_work_item", source_id, "feishu_workitem_update")
        )
        after = dj_tz.now()
        assert len(events2) == 1
        event2 = events2[0]
        assert event2.event_time.tzinfo is not None
        assert before <= event2.event_time <= after

    async def test_feishu_source_missing_returns_empty_with_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """源缺失双场景：project_key 查无 Project / get_work_item 失败 → 空列表 + warning。"""
        from knowledge.sources.feishu_work_item import normalize as normalize_feishu

        # 场景 1：project_key 查无 Project
        with capture_logs() as cap1:
            events1 = await normalize_feishu(
                IngestionRequest(
                    "feishu_work_item", "no-such-proj:story:5001", "feishu_workitem_create"
                )
            )
        assert events1 == []
        warnings1 = [e["event"] for e in cap1 if e.get("log_level") == "warning"]
        assert "knowledge_normalize_source_missing" in warnings1

        # 场景 2：get_work_item 失败
        project = await sync_to_async(_make_feishu_project)()
        client = FakeFeishuClient(work_item_error=RuntimeError("feishu api down"))
        _patch_feishu_clients(monkeypatch, client=client, doc_client=FakeFeishuDocClient())
        with capture_logs() as cap2:
            events2 = await normalize_feishu(
                IngestionRequest(
                    "feishu_work_item",
                    f"{project.feishu_project_key}:story:5001",
                    "feishu_workitem_create",
                )
            )
        assert events2 == []
        warnings2 = [e["event"] for e in cap2 if e.get("log_level") == "warning"]
        assert "knowledge_normalize_source_missing" in warnings2


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


class TestWorkflowTriggers:
    """14-04 Task 2：workflow 双触发点投递 + 节点类型过滤 + 异常隔离（-k workflow 可选中）。"""

    @staticmethod
    def _patch_super_execute(monkeypatch: pytest.MonkeyPatch, result) -> None:
        """mock AIAgentBaseNode.execute（绕过真实 Agent loop，宿主子步骤逻辑保留）。"""
        from workflows.nodes.ai.base_agent import AIAgentBaseNode

        async def _fake_execute(self, context):
            return result

        monkeypatch.setattr(AIAgentBaseNode, "execute", _fake_execute)

    @staticmethod
    def _make_engine(monkeypatch: pytest.MonkeyPatch):
        """WorkflowEngine 实例：hooks 与 _continue_after_node 置为 AsyncMock（最小宿主）。"""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from workflows.engine.scheduler import WorkflowEngine

        engine = WorkflowEngine()
        monkeypatch.setattr(engine, "hooks", SimpleNamespace(trigger=AsyncMock()))
        monkeypatch.setattr(engine, "_continue_after_node", AsyncMock())
        return engine

    async def test_workflow_plan_generation_delivers_on_success(
        self,
        captured_requests: list[IngestionRequest],
        make_minimal_context,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """生成节点 execute 成功 → 恰 1 条 workflow_plan_generated 投递。"""
        from workflows.nodes.ai.plan_generation import AIPlanGenerationNode
        from workflows.nodes.base import NodeResult

        self._patch_super_execute(
            monkeypatch,
            NodeResult(status="completed", output={"plan": {"title": "工作流方案"}}),
        )
        node = AIPlanGenerationNode()
        ctx = make_minimal_context(
            node_config={"user_prompt": "需求"},
            execution_id="exec-wf-1",
            node_id="node-wf-1",
        )

        result = await node.execute(ctx)

        assert result.status == "completed"
        assert [_request_triple(r) for r in captured_requests] == [
            ("workflow_plan", "exec-wf-1:node-wf-1", "workflow_plan_generated")
        ]

    async def test_workflow_plan_generation_zero_delivery_on_failure(
        self,
        captured_requests: list[IngestionRequest],
        make_minimal_context,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """result.status == "failed" 分支零投递。"""
        from workflows.nodes.ai.plan_generation import AIPlanGenerationNode
        from workflows.nodes.base import NodeResult

        self._patch_super_execute(
            monkeypatch,
            NodeResult(status="failed", error="agent boom", next_handle="error"),
        )
        node = AIPlanGenerationNode()
        ctx = make_minimal_context(node_config={"user_prompt": "需求"})

        result = await node.execute(ctx)

        assert result.status == "failed"
        assert captured_requests == []

    async def test_workflow_plan_approval_delivers_generation_node_key(
        self,
        captured_requests: list[IngestionRequest],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """approve_node 审批 human_approval(mode=plan_feishu) → source_id 为生成节点 key（OQ-2 定案）。"""
        from types import SimpleNamespace

        from workflows.models.execution import NodeExecutionStatus

        _p, execution, gen_node, _gen_exec, approval_exec = await sync_to_async(
            lambda: _make_workflow_plan_execution(
                with_approval=True,
                approval_status=NodeExecutionStatus.WAITING_APPROVAL,
            )
        )()
        engine = self._make_engine(monkeypatch)
        approver = SimpleNamespace(id=1, username="审批人甲")

        await engine.approve_node(approval_exec, approver)

        assert [_request_triple(r) for r in captured_requests] == [
            ("workflow_plan", f"{execution.id}:{gen_node.id}", "workflow_plan_approved")
        ]

    async def test_workflow_plan_approve_non_approval_node_zero_delivery(
        self,
        captured_requests: list[IngestionRequest],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """approve_node 审批非方案审批节点（如人工确认 manual_confirm）→ 零投递。"""
        from types import SimpleNamespace

        from workflows.models.execution import NodeExecutionStatus

        _p, _e, _gen_node, _gen_exec, approval_exec = await sync_to_async(
            lambda: _make_workflow_plan_execution(
                with_approval=True,
                approval_status=NodeExecutionStatus.WAITING_APPROVAL,
                approval_node_type="manual_confirm",
            )
        )()
        engine = self._make_engine(monkeypatch)
        approver = SimpleNamespace(id=1, username="审批人甲")

        await engine.approve_node(approval_exec, approver)

        assert captured_requests == []

    async def test_workflow_generic_human_approval_zero_delivery(
        self,
        captured_requests: list[IngestionRequest],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """approve_node 审批 human_approval(mode=generic) → 零投递（仅 plan_feishu 触发摄取）。"""
        from types import SimpleNamespace

        from workflows.models.execution import NodeExecutionStatus

        _p, _e, _gen_node, _gen_exec, approval_exec = await sync_to_async(
            lambda: _make_workflow_plan_execution(
                with_approval=True,
                approval_status=NodeExecutionStatus.WAITING_APPROVAL,
                approval_config={"mode": "generic"},
            )
        )()
        engine = self._make_engine(monkeypatch)
        approver = SimpleNamespace(id=1, username="审批人甲")

        await engine.approve_node(approval_exec, approver)

        assert captured_requests == []

    async def test_workflow_plan_generation_survives_runner_failure(
        self,
        make_minimal_context,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """run_in_background 抛 RuntimeError → 生成节点 execute 仍成功返回。"""
        from workflows.nodes.ai.plan_generation import AIPlanGenerationNode
        from workflows.nodes.base import NodeResult

        def _boom(factory, *, name=None):
            raise RuntimeError("runner down")

        monkeypatch.setattr("knowledge.ingestion.run_in_background", _boom)
        self._patch_super_execute(
            monkeypatch,
            NodeResult(status="completed", output={"plan": {"title": "隔离方案"}}),
        )
        node = AIPlanGenerationNode()

        result = await node.execute(make_minimal_context(node_config={"user_prompt": "需求"}))

        assert result.status == "completed"

    async def test_workflow_plan_approval_survives_runner_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """run_in_background 抛 RuntimeError → approve_node 宿主流程仍成功完成节点。"""
        from types import SimpleNamespace

        from workflows.models.execution import NodeExecutionStatus

        def _boom(factory, *, name=None):
            raise RuntimeError("runner down")

        monkeypatch.setattr("knowledge.ingestion.run_in_background", _boom)
        _p, _e, _gen_node, _gen_exec, approval_exec = await sync_to_async(
            lambda: _make_workflow_plan_execution(
                with_approval=True,
                approval_status=NodeExecutionStatus.WAITING_APPROVAL,
            )
        )()
        engine = self._make_engine(monkeypatch)
        approver = SimpleNamespace(id=1, username="审批人甲")

        await engine.approve_node(approval_exec, approver)

        await approval_exec.arefresh_from_db()
        assert approval_exec.status == NodeExecutionStatus.COMPLETED


def _make_feishu_trigger_log(project):
    """TriggerLog 同步工厂（handler 入参；event_uuid 每次唯一）。"""
    from feishu.models import TriggerLog, TriggerLogStatus

    return TriggerLog.objects.create(
        event_uuid=uuid.uuid4().hex,
        event_type="WorkitemUpdateEvent",
        project_key=project.feishu_project_key,
        project=project,
        status=TriggerLogStatus.ACCEPTED,
    )


class TestFeishuTriggers:
    """14-05 Task 2：飞书三 handler 投递 + 缺 ID 早退 + 异常隔离（-k feishu 可选中）。"""

    @staticmethod
    def _handlers():
        from feishu.views import FeishuWebhookView

        view = FeishuWebhookView()
        return {
            "feishu_workitem_create": view._handle_workitem_create,
            "feishu_workitem_status": view._handle_workitem_status,
            "feishu_workitem_update": view._handle_workitem_update,
        }

    async def test_feishu_three_handlers_each_deliver_once(
        self, captured_requests: list[IngestionRequest]
    ) -> None:
        """三事件各投递一次：(feishu_work_item, 三元组, feishu_workitem_<event>)。"""
        project = await sync_to_async(_make_feishu_project)()
        payload = {"id": 5001, "work_item_type_key": "story"}

        for trigger, handler in self._handlers().items():
            trigger_log = await sync_to_async(_make_feishu_trigger_log)(project)
            await handler(project, payload, trigger_log)
            assert _request_triple(captured_requests[-1]) == (
                "feishu_work_item",
                f"{project.feishu_project_key}:story:5001",
                trigger,
            )
        assert len(captured_requests) == 3

    async def test_feishu_missing_id_zero_delivery(
        self, captured_requests: list[IngestionRequest]
    ) -> None:
        """payload 无 id → 三 handler 早退（既有 warning 分支），零投递。"""
        project = await sync_to_async(_make_feishu_project)()

        for _trigger, handler in self._handlers().items():
            trigger_log = await sync_to_async(_make_feishu_trigger_log)(project)
            await handler(project, {"work_item_type_key": "story"}, trigger_log)

        assert captured_requests == []

    async def test_feishu_update_missing_type_key_zero_delivery(
        self, captured_requests: list[IngestionRequest]
    ) -> None:
        """WR-04：update 事件缺 work_item_type_key → 跳过投递（不再默认 story 进 natural key）。"""
        project = await sync_to_async(_make_feishu_project)()
        trigger_log = await sync_to_async(_make_feishu_trigger_log)(project)

        handler = self._handlers()["feishu_workitem_update"]
        await handler(project, {"id": 5002}, trigger_log)

        assert captured_requests == []

    async def test_feishu_handlers_survive_runner_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_in_background 抛 RuntimeError → 三 handler 宿主流程仍正常完成。"""

        def _boom(factory, *, name=None):
            raise RuntimeError("runner down")

        monkeypatch.setattr("knowledge.ingestion.run_in_background", _boom)
        project = await sync_to_async(_make_feishu_project)()
        payload = {"id": 5001, "work_item_type_key": "story"}

        for _trigger, handler in self._handlers().items():
            trigger_log = await sync_to_async(_make_feishu_trigger_log)(project)
            # 不 raise 即宿主流程未被拖垮（既有日志行为不变）
            await handler(project, payload, trigger_log)


# ============================================================================
# 14-06 Task 1：task_result normalizer（DiffArchiver 编排 + 双事件双路径）
# ============================================================================

# diff 原文特征串：进 content 合法，进 payload 即违反"diff 原文不进 payload"定案。
_DIFF_SENTINEL = "DIFF原文特征串-K7XQ-禁止入payload"
# T-14-22 伪归属特征串：runner 可篡改 last_output，归属必须走服务端权威 FK。
_FAKE_REPO_SENTINEL = "伪仓库特征串-T1422-禁止采信"


def _make_coding_chat_host(
    *,
    with_plan: bool = True,
    pr_url: str = "https://gitlab.com/test/coding-repo/-/merge_requests/7",
    task_pr_url: str = "",
    last_output: dict | None = None,
):
    """chat 编码完成全套宿主（Project/Repository/CodingPlan/CodingSession/SubAgentSession/TaskResult）。

    默认形态即两条主路径的真实时序：TaskResult.pr_url 为空（PR 由 server 在容器
    回调之后创建），权威源 CodingSession.pr_url 有值（blocker 修复锚）。
    """
    from django.utils import timezone

    from agents.models import AgentSession
    from chat.models import CodingPlan, CodingSession, Conversation
    from projects.models import Project
    from repositories.models import Repository
    from subagent.models import SubAgentSession, TaskResult

    suffix = uuid.uuid4().hex[:8]
    project = Project.objects.create(name="编码触发项目", feishu_project_key=f"k-coding-{suffix}")
    repo = Repository.objects.create(
        name="coding-repo",
        git_url=f"https://gitlab.com/test/coding-repo-{suffix}.git",
        git_platform="gitlab",
        default_branch="main",
    )
    project.repositories.add(repo)
    conversation = Conversation.objects.create(project=project, title="编码触发对话")
    plan = None
    if with_plan:
        plan = CodingPlan.objects.create(
            conversation=conversation,
            title="编码归档方案",
            tech_plan="## 方案\n\n实现编码完成自动归档",
            affected_files=[],
        )
    agent_session = AgentSession.objects.create(
        session_id=f"agent-coding-{suffix}", project=project
    )
    sub = SubAgentSession.objects.create(
        session_id=f"sub-coding-{suffix}",
        main_session=agent_session,
        task_type=SubAgentSession.TaskType.CODING,
        status=SubAgentSession.Status.COMPLETED,
        repo_url=repo.git_url,
        completed_at=timezone.now(),
        last_output=last_output,
    )
    coding_session = CodingSession.objects.create(
        conversation=conversation,
        coding_plan=plan,
        repository=repo,
        tech_plan="## 方案",
        status=CodingSession.Status.COMPLETED,
        subagent_session=sub,
        branch_name="feat/coding-archive",
        pr_url=pr_url,
    )
    task_result = TaskResult.objects.create(
        session=sub,
        result_type=TaskResult.ResultType.GIT,
        branch_name="feat/coding-archive",
        commit_sha="abc1234def5678",
        pr_url=task_pr_url,
        modified_files=["src/app.py"],
    )
    return project, repo, plan, coding_session, sub, task_result


def _make_coding_workflow_host(*, mr_results: list[dict] | None | str = "auto"):
    """workflow 编码完成宿主：生成节点 + ai_coding NodeExecution（含 output_data 持久化形态）。

    ``mr_results="auto"`` 时预置本仓库的 mr_results 项（Task 2 投递前持久化形态）；
    传 None 模拟持久化缺失（normalizer mr_url 降级空串）。
    """
    from django.utils import timezone

    from agents.models import AgentSession
    from repositories.models import Repository
    from subagent.models import SubAgentSession, TaskResult
    from workflows.models import WorkflowNode
    from workflows.models.execution import NodeExecution, NodeExecutionStatus

    project, execution, gen_node, gen_exec, _ = _make_workflow_plan_execution()
    workflow = execution.workflow
    suffix = uuid.uuid4().hex[:8]
    repo = Repository.objects.create(
        name="wf-coding-repo",
        git_url=f"https://gitlab.com/test/wf-coding-repo-{suffix}.git",
        git_platform="gitlab",
        default_branch="main",
    )
    project.repositories.add(repo)
    session_id = f"exec-wf-{suffix}"
    output_data: dict = {
        "pending_sessions": [
            {
                "session_id": session_id,
                "container_id": "",
                "repository_id": str(repo.id),
                "repository_name": repo.name,
            }
        ],
        "branch_name": "feat/wf-archive",
        "base_branch": "main",
    }
    if mr_results == "auto":
        output_data["mr_results"] = [
            {
                "repository_id": str(repo.id),
                "mr_url": "https://gitlab.com/test/wf-coding-repo/-/merge_requests/9",
                "mr_id": "9",
                "success": True,
            }
        ]
    elif mr_results is not None:
        output_data["mr_results"] = mr_results
    coding_node = WorkflowNode.objects.create(
        workflow=workflow, node_type="ai_coding", name="编码执行"
    )
    coding_exec = NodeExecution.objects.create(
        workflow_execution=execution,
        node=coding_node,
        status=NodeExecutionStatus.COMPLETED,
        output_data=output_data,
        completed_at=timezone.now(),
    )
    agent_session = AgentSession.objects.create(session_id=f"agent-wf-{suffix}", project=project)
    sub = SubAgentSession.objects.create(
        session_id=session_id,
        main_session=agent_session,
        task_type=SubAgentSession.TaskType.CODING,
        status=SubAgentSession.Status.COMPLETED,
        repo_url=repo.git_url,
        node_execution=coding_exec,
        completed_at=timezone.now(),
    )
    task_result = TaskResult.objects.create(
        session=sub,
        result_type=TaskResult.ResultType.GIT,
        branch_name="feat/wf-archive",
        commit_sha="9f8e7d6c5b4a3210",
        pr_url="",  # 容器回调时刻真实形态：MR 由 server 侧之后创建
        modified_files=["src/wf.py"],
    )
    return project, repo, execution, gen_node, coding_exec, sub, task_result


def _make_archive_result(chunk_id: uuid.UUID | None = None, *, content: str | None = None):
    """ArchiveResult 夹具：archive 摘要 + content（含 diff 特征串）+ chunk EdgeSpec。"""
    from types import SimpleNamespace

    from knowledge.diff_archive import ArchiveResult
    from knowledge.ingestion import EdgeSpec
    from knowledge.models import EdgeRelation

    edge_specs = []
    if chunk_id is not None:
        edge_specs.append(
            EdgeSpec(
                relation=EdgeRelation.MODIFIES_CHUNK,
                target_chunk_id=chunk_id,
                metadata={
                    "file_path": "src/app.py",
                    "symbol": "main",
                    "commit_sha": "abc1234def5678",
                    "resolution": "symbol",
                },
            )
        )
    archive = SimpleNamespace(
        id=uuid.uuid4(), file_count=1, total_additions=3, total_deletions=1, truncated=False
    )
    return ArchiveResult(
        archive=archive,  # type: ignore[arg-type]
        content=content
        or f"代码变更 coding-repo\n\n## 变更摘要\n- src/app.py\n\n## diff\n{_DIFF_SENTINEL}",
        edge_specs=edge_specs,
        file_diffs=[],
    )


@pytest.fixture
def fake_archive(monkeypatch: pytest.MonkeyPatch):
    """以模块属性形态替换 ``knowledge.sources.task_result.diff_archive``。

    用例设置 ``holder.result``（ArchiveResult | None）控制应答；
    ``holder.calls`` 记录 archive_code_change 全部入参（kwargs）。
    """
    from types import SimpleNamespace

    holder = SimpleNamespace(result=None, calls=[])

    async def _archive_code_change(**kwargs):
        holder.calls.append(kwargs)
        return holder.result

    monkeypatch.setattr(
        "knowledge.sources.task_result.diff_archive",
        SimpleNamespace(archive_code_change=_archive_code_change),
    )
    return holder


class TestCodingTaskResultNormalizer:
    """14-06 Task 1：task_result normalize 取材用例组（-k coding 选中锚定方法名）。"""

    async def test_coding_chat_dual_events_mr_url_from_coding_session(self, fake_archive) -> None:
        """chat 路径双事件 + mr_url 权威源真实形态（TaskResult.pr_url 空 + CodingSession.pr_url 有值）。"""
        from knowledge.sources.task_result import normalize as normalize_task_result

        project, repo, plan, coding_session, sub, task_result = await sync_to_async(
            _make_coding_chat_host
        )()
        fake_archive.result = _make_archive_result(uuid.uuid4())

        events = await normalize_task_result(
            IngestionRequest("task_result", sub.session_id, "chat_coding_pr_created")
        )

        assert len(events) == 2
        anchor, code_change = events
        # 锚事件：tech_plan（coding_plan 短路重摄）+ IMPLEMENTED_BY 出边挂锚（边方向定案）
        assert anchor.kind == "tech_plan"
        assert anchor.origin == "chat"
        assert anchor.source_kind == "coding_plan"
        assert anchor.source_id == str(plan.id)
        assert len(anchor.edges) == 1
        spec = anchor.edges[0]
        assert spec.relation == "IMPLEMENTED_BY"
        assert spec.target_entity_id == generate_entity_id(
            "code_change", "task_result", sub.session_id
        )
        # code_change 事件：content 来自 ArchiveResult，MODIFIES_CHUNK 挂在本事件
        assert code_change.kind == "code_change"
        assert code_change.source_kind == "task_result"
        assert code_change.source_id == sub.session_id
        assert code_change.content == fake_archive.result.content
        chunk_edges = [e for e in code_change.edges if e.relation == "MODIFIES_CHUNK"]
        assert len(chunk_edges) == 1
        assert chunk_edges[0].target_chunk_id is not None
        payload = code_change.payload
        assert payload["archive_id"] == str(fake_archive.result.archive.id)
        assert payload["commit_sha"] == task_result.commit_sha
        # blocker 修复锚：TaskResult.pr_url 为空时主路径 mr_url 仍取权威源（非空）
        assert task_result.pr_url == ""
        assert coding_session.pr_url
        assert payload["mr_url"] == coding_session.pr_url
        assert fake_archive.calls[-1]["mr_url"] == coding_session.pr_url
        assert fake_archive.calls[-1]["mr_id"] == "7"  # mr_url 尾段解析
        # diff 原文不进 payload（T-14-24 前提：payload 只放摘要）
        assert _DIFF_SENTINEL not in json.dumps(payload, ensure_ascii=False)
        assert code_change.repository_id == str(repo.id)
        assert code_change.project_id == str(project.id)

    async def test_coding_workflow_anchor_and_mr_url_from_output_data(self, fake_archive) -> None:
        """workflow 路径方案回溯 + mr_url 取自 node_execution.output_data 持久化项。"""
        from knowledge.sources.task_result import normalize as normalize_task_result

        project, repo, execution, gen_node, _coding_exec, sub, task_result = await sync_to_async(
            _make_coding_workflow_host
        )()
        fake_archive.result = _make_archive_result(uuid.uuid4())

        events = await normalize_task_result(
            IngestionRequest("task_result", sub.session_id, "workflow_coding_completed")
        )

        assert len(events) == 2
        anchor, code_change = events
        assert anchor.kind == "tech_plan"
        assert anchor.origin == "workflow"
        assert anchor.source_kind == "workflow_plan"
        assert anchor.source_id == f"{execution.id}:{gen_node.id}"
        assert anchor.edges[0].target_entity_id == generate_entity_id(
            "code_change", "task_result", sub.session_id
        )
        assert code_change.origin == "workflow"
        # blocker 修复锚：TaskResult.pr_url 仍为空，mr_url 取 output_data["mr_results"] 匹配项
        assert task_result.pr_url == ""
        expected_mr_url = "https://gitlab.com/test/wf-coding-repo/-/merge_requests/9"
        assert code_change.payload["mr_url"] == expected_mr_url
        assert fake_archive.calls[-1]["mr_url"] == expected_mr_url
        assert fake_archive.calls[-1]["mr_id"] == "9"
        assert code_change.repository_id == str(repo.id)
        assert code_change.project_id == str(project.id)

    async def test_coding_no_plan_degrades_to_single_event(self, fake_archive) -> None:
        """无方案降级：既无 coding_plan 也无 node_execution → 单 code_change 事件 + warning。"""
        from knowledge.sources.task_result import normalize as normalize_task_result

        _project, _repo, _plan, _cs, sub, _tr = await sync_to_async(
            lambda: _make_coding_chat_host(with_plan=False, pr_url="")
        )()
        fake_archive.result = _make_archive_result(uuid.uuid4())

        with capture_logs() as cap:
            events = await normalize_task_result(
                IngestionRequest("task_result", sub.session_id, "chat_coding_pr_skipped")
            )

        assert len(events) == 1
        assert events[0].kind == "code_change"
        # 边随锚缺席：单事件只带 chunk 边，不带 IMPLEMENTED_BY
        assert all(e.relation == "MODIFIES_CHUNK" for e in events[0].edges)
        warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
        assert "knowledge_normalize_anchor_plan_missing" in warnings

    async def test_coding_archive_failure_returns_empty(self, fake_archive) -> None:
        """归档失败降级：archive_code_change 返回 None → 空列表 + warning，不 raise。"""
        from knowledge.sources.task_result import normalize as normalize_task_result

        _project, _repo, _plan, _cs, sub, _tr = await sync_to_async(_make_coding_chat_host)()
        fake_archive.result = None

        with capture_logs() as cap:
            events = await normalize_task_result(
                IngestionRequest("task_result", sub.session_id, "chat_coding_pr_created")
            )

        assert events == []
        warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
        assert "knowledge_normalize_archive_failed" in warnings

    async def test_coding_last_output_untrusted_for_attribution(self, fake_archive) -> None:
        """T-14-22：last_output 注入伪仓库特征串 → 归属仍取 CodingSession.repository，零泄漏。"""
        from knowledge.sources.task_result import normalize as normalize_task_result

        project, repo, _plan, _cs, sub, _tr = await sync_to_async(
            lambda: _make_coding_chat_host(
                last_output={
                    "repository": {"id": str(uuid.uuid4()), "name": _FAKE_REPO_SENTINEL},
                    "repository_name": _FAKE_REPO_SENTINEL,
                }
            )
        )()
        fake_archive.result = _make_archive_result(uuid.uuid4())

        events = await normalize_task_result(
            IngestionRequest("task_result", sub.session_id, "chat_coding_pr_created")
        )

        assert len(events) == 2
        code_change = events[-1]
        assert code_change.payload["repository_id"] == str(repo.id)
        assert code_change.repository_id == str(repo.id)
        assert code_change.project_id == str(project.id)
        # 特征串零泄漏（事件全字段 repr 扫描）
        assert _FAKE_REPO_SENTINEL not in repr(events)
        assert fake_archive.calls[-1]["repository"].id == repo.id

    async def test_coding_sc4_reverse_chain_chunk_to_work_item(
        self,
        fake_archive,
        monkeypatch: pytest.MonkeyPatch,
        mock_embedding,
        mock_qdrant_client,
    ) -> None:
        """SC#4 端到端三跳反查：chunk_in_edges → code_change → IMPLEMENTED_BY → tech_plan → HAS_PLAN → work_item。"""
        from unittest.mock import AsyncMock

        from django.utils import timezone as dj_tz

        from code_relations.models import ChunkRegistry
        from knowledge.graph_store import graph_store
        from knowledge.ingestion import EdgeSpec, IngestionEvent, ingest_events
        from knowledge.sources.task_result import normalize as normalize_task_result
        from services.qdrant_service import QdrantService

        monkeypatch.setattr("knowledge.ingestion.ensure_delivery_knowledge_collection", AsyncMock())
        monkeypatch.setattr(
            QdrantService, "upsert_vectors_by_name", classmethod(lambda cls, name, pts: True)
        )

        project, repo, plan, _cs, sub, _tr = await sync_to_async(_make_coding_chat_host)()

        # 预置 work_item —HAS_PLAN→ tech_plan（coding_plan 锚）：走 ingest_events 正路
        tech_plan_id = generate_entity_id("tech_plan", "coding_plan", str(plan.id))
        work_item_source_id = f"{project.feishu_project_key}:story:6001"
        now = dj_tz.now()
        await ingest_events(
            [
                IngestionEvent(
                    kind="work_item",
                    origin="feishu",
                    source_kind="feishu_work_item",
                    source_id=work_item_source_id,
                    title="编码需求",
                    content="编码需求\n\n编码完成应自动归档 diff。",
                    payload={},
                    project_id=str(project.id),
                    repository_id=None,
                    event_time=now,
                    edges=(
                        EdgeSpec(
                            relation="HAS_PLAN", target_entity_id=tech_plan_id, exclusive=True
                        ),
                    ),
                ),
                IngestionEvent(
                    kind="tech_plan",
                    origin="chat",
                    source_kind="coding_plan",
                    source_id=str(plan.id),
                    title=plan.title,
                    content=f"{plan.title}\n\n{plan.tech_plan}",
                    payload={},
                    project_id=str(project.id),
                    repository_id=None,
                    event_time=now,
                ),
            ]
        )

        # 真实 ChunkRegistry chunk 作为 MODIFIES_CHUNK 目标
        chunk_id = uuid.uuid4()
        await sync_to_async(ChunkRegistry.objects.create)(
            chunk_id=chunk_id,
            content_hash="0" * 64,
            repository=repo,
            branch_name="",
            file_path="src/app.py",
            chunk_index=0,
            line_start=1,
            line_end=10,
        )
        fake_archive.result = _make_archive_result(chunk_id)

        events = await normalize_task_result(
            IngestionRequest("task_result", sub.session_id, "chat_coding_pr_created")
        )
        await ingest_events(events, trigger="chat_coding_pr_created")

        # 跳 1：chunk 反查 code_change 实体
        in_edges = await graph_store.chunk_in_edges(chunk_id)
        assert len(in_edges) == 1
        code_change_id = in_edges[0].source_id
        assert code_change_id == generate_entity_id("code_change", "task_result", sub.session_id)
        # 跳 2/3：traverse(direction="in") 沿 IMPLEMENTED_BY / HAS_PLAN 上溯
        results = await graph_store.traverse(
            code_change_id,
            max_hops=2,
            relations=["IMPLEMENTED_BY", "HAS_PLAN"],
            direction="in",
        )
        reached = {r.entity_id: r.depth for r in results}
        assert reached.get(tech_plan_id) == 1
        work_item_id = generate_entity_id("work_item", "feishu_work_item", work_item_source_id)
        assert reached.get(work_item_id) == 2


# ============================================================================
# 14-06 Task 2：编码完成三锚点接线（coding_graph ×2 / coding.py / callbacks 旧兼容）
# ============================================================================


def _make_mock_chat_coding_session(session_id: str = "sub-chat-mock-1"):
    """create_pr_or_skip_node 直调用的 mock CodingSession（test_coding_session_graph 同款形态）。"""
    from unittest.mock import AsyncMock, MagicMock

    session = MagicMock()
    session.id = "cs-mock-1"
    session.repository.name = "mock-repo"
    session.repository.git_url = "https://github.com/test/repo.git"
    session.repository.git_platform = "github"
    session.repository.default_branch = "main"
    session.branch_name = "feat/coding-trigger"
    session.subagent_session_id = 42
    session.subagent_session.session_id = session_id
    session.amark_completed = AsyncMock()
    session.amark_failed = AsyncMock()
    session.aresume_running = AsyncMock()
    return session


async def _run_resume_after_containers(coding_exec, monkeypatch: pytest.MonkeyPatch):
    """构造 AICodingNode 宿主并直调 _resume_after_containers（MR 创建/通知/子步骤全 mock）。"""
    from unittest.mock import AsyncMock

    import structlog as _structlog

    from workflows.nodes.ai.coding import AICodingNode
    from workflows.nodes.base import ExecutionContext

    node = AICodingNode()
    monkeypatch.setattr(
        node,
        "_create_mr_for_repo",
        AsyncMock(
            return_value={
                "mr_url": "https://gitlab.com/test/wf-coding-repo/-/merge_requests/11",
                "mr_id": "11",
                "has_conflicts": False,
            }
        ),
    )
    monkeypatch.setattr(node, "emit_sub_step", AsyncMock())
    monkeypatch.setattr(node, "_send_result_notification", AsyncMock())

    context = ExecutionContext(
        execution_id=str(coding_exec.workflow_execution_id),
        node_id=str(coding_exec.node_id),
        node_config={},
        input_data={},
        workflow_context={},
        previous_outputs={},
        node_execution=coding_exec,
    )
    return await node._resume_after_containers(
        context, dict(coding_exec.output_data), _structlog.get_logger("test")
    )


class TestCodingTriggers:
    """14-06 Task 2：编码完成四锚点投递 + 时序防线 + 异常隔离（-k coding 选中）。"""

    async def test_coding_chat_skip_branch_delivers_once(
        self, captured_requests: list[IngestionRequest]
    ) -> None:
        """create_pr_or_skip_node skip 路径恰投递 1 条 chat_coding_pr_skipped。"""
        from unittest.mock import AsyncMock, patch

        from orchestration.coding_graph import create_pr_or_skip_node

        mock_session = _make_mock_chat_coding_session("sub-chat-skip-1")
        with (
            patch(
                "orchestration.coding_graph._get_coding_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch("chat.coding_events.store_coding_complete_to_message", new_callable=AsyncMock),
        ):
            result = await create_pr_or_skip_node(
                {"coding_session_id": "cs-mock-1", "skip_pr": True}
            )

        assert result["phase"] == "completed"
        assert [_request_triple(r) for r in captured_requests] == [
            ("task_result", "sub-chat-skip-1", "chat_coding_pr_skipped")
        ]

    async def test_coding_chat_pr_created_branch_delivers_once(
        self, captured_requests: list[IngestionRequest]
    ) -> None:
        """create_pr_or_skip_node PR 成功路径恰投递 1 条 chat_coding_pr_created。"""
        from unittest.mock import AsyncMock, MagicMock, patch

        from orchestration.coding_graph import create_pr_or_skip_node
        from services.git_platform.models import MRCreateResult

        mock_session = _make_mock_chat_coding_session("sub-chat-pr-1")
        mock_cred = MagicMock()
        mock_cred.encrypted_token = "encrypted-token"
        mock_client = AsyncMock()
        mock_client.create_merge_request = AsyncMock(
            return_value=MRCreateResult(
                success=True, mr_url="https://github.com/test/repo/pull/3", mr_id="3"
            )
        )
        with (
            patch(
                "orchestration.coding_graph._get_coding_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch("chat.coding_events.store_coding_complete_to_message", new_callable=AsyncMock),
            patch("repositories.models.GitCredential") as mock_cred_cls,
            patch("common.encryption.decrypt_value", return_value="token"),
            patch("services.git_platform.get_git_platform_client", return_value=mock_client),
        ):
            mock_cred_cls.objects.aget = AsyncMock(return_value=mock_cred)
            result = await create_pr_or_skip_node(
                {
                    "coding_session_id": "cs-mock-1",
                    "skip_pr": False,
                    "confirmed_pr_title": "feat: trigger",
                    "confirmed_pr_description": "body",
                    "target_branch": "main",
                }
            )

        assert result["phase"] == "completed"
        assert [_request_triple(r) for r in captured_requests] == [
            ("task_result", "sub-chat-pr-1", "chat_coding_pr_created")
        ]

    async def test_coding_workflow_persists_mr_results_then_delivers(
        self,
        captured_requests: list[IngestionRequest],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_resume_after_containers：投递前 mr_results 已持久化进 node_execution.output_data。"""
        from workflows.models.execution import NodeExecution

        _p, repo, _e, _g, coding_exec, sub, _tr = await sync_to_async(
            lambda: _make_coding_workflow_host(mr_results=None)
        )()

        result = await _run_resume_after_containers(coding_exec, monkeypatch)

        assert result.status == "completed"
        assert [_request_triple(r) for r in captured_requests] == [
            ("task_result", sub.session_id, "workflow_coding_completed")
        ]
        # blocker 修复锚：重读 DB 断言 mr_results 已持久化（normalizer 重读的权威源）
        refreshed = await NodeExecution.objects.aget(id=coding_exec.id)
        persisted = refreshed.output_data.get("mr_results")
        assert persisted == [
            {
                "repository_id": str(repo.id),
                "mr_url": "https://gitlab.com/test/wf-coding-repo/-/merge_requests/11",
                "mr_id": "11",
                "success": True,
            }
        ]
        # 合并不覆盖既有键
        assert refreshed.output_data.get("pending_sessions")

    async def test_coding_callback_main_path_zero_delivery_legacy_delivers(
        self,
        captured_requests: list[IngestionRequest],
    ) -> None:
        """时序防线（Pitfall 1）：容器回调主路径（graph 管理）零投递；旧兼容分支投递 legacy_coding_completed。"""
        from unittest.mock import AsyncMock, MagicMock, patch

        from subagent.api.callbacks import _update_coding_session_on_complete

        # 主路径：graph 管理（task_type=coding）→ 回调时刻零投递（归档挂 PR 创建之后）
        _p1, _r1, _pl1, _cs1, sub1, _tr1 = await sync_to_async(_make_coding_chat_host)()
        sub1.last_output = {"task_type": "coding"}
        await sub1.asave(update_fields=["last_output", "updated_at"])
        mock_compiled = MagicMock()
        mock_compiled.ainvoke = AsyncMock(return_value={})
        mock_builder = MagicMock()
        mock_builder.compile.return_value = mock_compiled
        with (
            patch("orchestration.coding_graph.build_coding_graph", return_value=mock_builder),
            patch("orchestration.checkpointer.get_checkpointer", new_callable=AsyncMock),
        ):
            await _update_coding_session_on_complete(sub1)
        assert captured_requests == []

        # 旧兼容分支：非 graph 管理 + TaskResult 自带 pr_url（容器内建 MR 历史模式）
        _p2, _r2, _pl2, _cs2, sub2, _tr2 = await sync_to_async(
            lambda: _make_coding_chat_host(
                task_pr_url="https://gitlab.com/test/coding-repo/-/merge_requests/5",
                last_output={"task_type": "explore"},
            )
        )()
        with patch("chat.coding_events.store_coding_complete_to_message", new_callable=AsyncMock):
            await _update_coding_session_on_complete(sub2)
        assert [_request_triple(r) for r in captured_requests] == [
            ("task_result", sub2.session_id, "legacy_coding_completed")
        ]

    async def test_coding_hosts_survive_runner_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """异常隔离：run_in_background 抛 RuntimeError → 两宿主流程仍正常完成。"""
        from unittest.mock import AsyncMock, patch

        from orchestration.coding_graph import create_pr_or_skip_node

        def _boom(factory, *, name=None):
            raise RuntimeError("runner down")

        monkeypatch.setattr("knowledge.ingestion.run_in_background", _boom)

        # chat skip 路径
        mock_session = _make_mock_chat_coding_session("sub-chat-iso-1")
        with (
            patch(
                "orchestration.coding_graph._get_coding_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch("chat.coding_events.store_coding_complete_to_message", new_callable=AsyncMock),
        ):
            result = await create_pr_or_skip_node(
                {"coding_session_id": "cs-mock-1", "skip_pr": True}
            )
        assert result["phase"] == "completed"

        # workflow 路径
        _p, _repo, _e, _g, coding_exec, _sub, _tr = await sync_to_async(
            lambda: _make_coding_workflow_host(mr_results=None)
        )()
        wf_result = await _run_resume_after_containers(coding_exec, monkeypatch)
        assert wf_result.status == "completed"


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
