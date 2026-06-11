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

from knowledge.ingestion import IngestionRequest
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
