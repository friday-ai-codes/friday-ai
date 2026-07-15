"""learning_case normalizer + 投递钩子 + 幂等重摄测试（Plan 100-02，KNOW-01）。

- ``TestNormalize``（Task 1）：McpLearningCase → IngestionEvent 的取材边界
  （锚料齐备双事件 + RELATES_TO/REFERENCES 边；context=None 降级单事件；
  源缺失容忍返回空列表）。
- ``TestTrigger``（Task 2/3）：create_learning_case_from_technical_plan 写库后
  经 aschedule_ingestion 投递（monkeypatch 拦截，不真跑 background worker）。
- ``TestIdempotentReingest``（Task 3）：ROADMAP 成功标准 4 前半——重复摄取
  实体数不变、内容未变不翻版本、内容变更后版本 1→2 翻转正确、锚幂等。

测试纪律（test_triggers.py / test_ingestion.py 同款）：Qdrant / embedding 全 mock，
``--disable-socket`` 是第二道保险。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from structlog.testing import capture_logs

from knowledge.ingestion import IngestionRequest, ingest
from knowledge.models import (
    KnowledgeEdge,
    KnowledgeEntity,
    KnowledgeEntityVersion,
    generate_entity_id,
)
from knowledge.sources.learning_case import normalize as normalize_learning_case

# SQLite + async（sync_to_async 跨线程）需要 transaction=True（test_triggers.py 同款）。
pytestmark = pytest.mark.django_db(transaction=True)


def _make_host(*, with_context: bool = True, embedding_text: str | None = None):
    """Space + InteractionRun + Context + TechnicalPlan + LearningCase 同步工厂。

    test_learning_cases.py ``_context`` / ``_technical_plan`` 简化版（无仓库任务）；
    ``with_context=False`` 时 case.context 为 None（锚料缺失降级用例）。
    """
    from interactions.ledger import create_interaction_run
    from mcp_tools.models import (
        McpLearningCase,
        McpWorkItemContext,
        McpWorkItemTechnicalPlan,
    )
    from projects.models import Space
    from runners.models import hash_token

    suffix = uuid.uuid4().hex[:8]
    project = Space.objects.create(
        name=f"学习案例项目-{suffix}", feishu_project_key=f"k-lc-{suffix}"
    )
    run = create_interaction_run(
        token_fingerprint=hash_token(f"learning-case-{suffix}"), source="mcp"
    )
    context = McpWorkItemContext.objects.create(
        run=run,
        space=project,
        feishu_project_key=project.feishu_project_key,
        work_item_type="bug",
        work_item_id=99,
        name="登录超时 Bug",
        work_item_status="done",
        description="登录超时后错误提示不清晰，需要修复 token 刷新边界。",
    )
    plan = McpWorkItemTechnicalPlan.objects.create(
        run=run,
        context=context,
        space=project,
        feishu_project_key=project.feishu_project_key,
        work_item_type="bug",
        work_item_id=99,
        title="登录超时 Bug 技术方案",
        plan_body={"title": "登录超时 Bug 技术方案"},
        markdown="# 登录超时 Bug 技术方案\n\n正文",
        repository_tasks=[{"repository_id": "r-1", "change_goal": "修复 token 刷新边界"}],
        feishu_document_url="https://feishu.cn/docx/doxcnLcPlan",
    )
    if embedding_text is None:
        embedding_text = (
            "登录超时 Bug 案例\ntoken 过期边界判断遗漏\n统一刷新 token 后再显示超时提示"
        )
    case = McpLearningCase.objects.create(
        run=run,
        context=context if with_context else None,
        technical_plan=plan,
        work_item_type="bug",
        work_item_id=99,
        title="登录超时 Bug 案例",
        problem="登录超时后错误提示不清晰。",
        root_cause="token 过期边界判断遗漏",
        solution="统一刷新 token 后再显示超时提示。",
        outcome="merged",
        repositories=["auth-service"],
        files=["src/auth/session.py"],
        symbols=["refresh_session"],
        mr_urls=["https://example.com/mr/login-timeout"],
        tests=["pytest tests/test_session.py -q"],
        embedding_text=embedding_text,
    )
    return project, context, plan, case


class TestNormalize:
    """Task 1：normalize 取材用例组（-k normalize 可选中）。"""

    async def test_normalize_dual_events_with_relates_to_and_references_edges(self) -> None:
        """锚料齐备：锚事件在前（三元组 source_id + RELATES_TO 非 exclusive），主事件带 REFERENCES。"""
        project, context, plan, case = await sync_to_async(_make_host)()

        events = await normalize_learning_case(
            IngestionRequest("learning_case", str(case.id), "mcp_learning_case_created")
        )

        assert len(events) == 2
        work_item, learning_case = events

        assert work_item.kind == "work_item"
        assert work_item.origin == "mcp"
        assert work_item.source_kind == "feishu_work_item"
        # natural key 规则表三元组格式逐字一致（禁止自造锚格式）
        assert work_item.source_id == (
            f"{context.feishu_project_key}:{case.work_item_type}:{case.work_item_id}"
        )
        assert work_item.title == context.name
        assert context.description in work_item.content
        assert work_item.space_id == str(project.id)
        assert len(work_item.edges) == 1
        anchor_spec = work_item.edges[0]
        assert anchor_spec.relation == "RELATES_TO"
        assert anchor_spec.target_entity_id == generate_entity_id(
            "learning_case", "learning_case", str(case.id)
        )
        # 非 exclusive：一个 work_item 可关联多条案例
        assert anchor_spec.exclusive is False

        assert learning_case.kind == "learning_case"
        assert learning_case.origin == "mcp"
        assert learning_case.source_kind == "learning_case"
        assert learning_case.source_id == str(case.id)
        assert learning_case.title == case.title
        # content 取 embedding_text（向量文本主料优先）
        assert learning_case.content == case.embedding_text
        assert learning_case.payload["outcome"] == "merged"
        assert learning_case.payload["repositories"] == ["auth-service"]
        assert learning_case.payload["technical_plan_id"] == str(plan.id)
        assert learning_case.space_id == str(project.id)
        assert learning_case.repository_id is None
        # updated_at 而非 created_at：版本翻转需要 event_time 随内容变更推进（kversion_valid_range）
        assert learning_case.event_time == case.updated_at
        assert len(learning_case.edges) == 1
        ref_spec = learning_case.edges[0]
        assert ref_spec.relation == "REFERENCES"
        assert ref_spec.target_entity_id == generate_entity_id(
            "tech_plan", "mcp_technical_plan", str(plan.id)
        )

    async def test_normalize_empty_embedding_text_falls_back_to_markdown(self) -> None:
        """embedding_text 为空 → markdown 组装回退（title/问题/根因/解法/结果 + 列表）。"""
        _project, _context, _plan, case = await sync_to_async(
            lambda: _make_host(embedding_text="")
        )()

        events = await normalize_learning_case(
            IngestionRequest("learning_case", str(case.id), "mcp_learning_case_created")
        )

        content = events[-1].content
        assert f"# {case.title}" in content
        assert "## 问题" in content
        assert case.root_cause in content
        assert case.solution in content
        assert "src/auth/session.py" in content

    async def test_normalize_context_missing_degrades_to_single_event(self) -> None:
        """context=None 降级：单事件（无 work_item 锚）+ warning，space_id 回退 technical_plan。"""
        project, _context, plan, case = await sync_to_async(
            lambda: _make_host(with_context=False)
        )()

        with capture_logs() as cap:
            events = await normalize_learning_case(
                IngestionRequest("learning_case", str(case.id), "mcp_learning_case_created")
            )

        assert len(events) == 1
        event = events[0]
        assert event.kind == "learning_case"
        # space_id 回退：context 缺失时取 technical_plan.space_id
        assert event.space_id == str(project.id)
        # REFERENCES 边不随锚缺席（technical_plan 仍在）
        assert len(event.edges) == 1
        assert event.edges[0].relation == "REFERENCES"
        assert event.edges[0].target_entity_id == generate_entity_id(
            "tech_plan", "mcp_technical_plan", str(plan.id)
        )
        warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
        assert "knowledge_normalize_anchor_context_missing" in warnings

    async def test_normalize_source_missing_returns_empty_with_warning(self) -> None:
        """源对象缺失（已删除场景）：返回空列表 + warning，不 raise。"""
        with capture_logs() as cap:
            events = await normalize_learning_case(
                IngestionRequest("learning_case", str(uuid.uuid4()), "mcp_learning_case_created")
            )
        assert events == []
        warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
        assert "knowledge_normalize_source_missing" in warnings


class TestTrigger:
    """Task 2/3：create_learning_case 投递断言（test_triggers.py 范式）。"""

    async def test_create_learning_case_delivers_ingestion_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """service 写库成功后恰投递 1 条 (learning_case, artifact.id, mcp_learning_case_created)。"""
        from mcp_tools.learning_case_service import create_learning_case_from_technical_plan

        captured: list[IngestionRequest] = []

        async def _collect(request: IngestionRequest) -> None:
            captured.append(request)

        monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", _collect)
        _project, _context, plan, _case = await sync_to_async(_make_host)()
        run = await sync_to_async(lambda: plan.run)()

        result = await create_learning_case_from_technical_plan(
            run=run,
            technical_plan_id=str(plan.id),
            outcome="merged",
            root_cause="token 过期边界判断遗漏",
            solution_notes="统一刷新 token 后再显示超时提示。",
            tests=["pytest tests/test_session.py -q"],
        )

        assert [(r.source_kind, r.source_id, r.trigger) for r in captured] == [
            ("learning_case", str(result.artifact.id), "mcp_learning_case_created")
        ]


class TestIdempotentReingest:
    """Task 3：幂等重摄 + 版本翻转（ROADMAP 成功标准 4 前半；test_ingestion.py 范式）。"""

    @pytest.fixture(autouse=True)
    def _mock_vector_stack(self, monkeypatch: pytest.MonkeyPatch, mock_embedding) -> None:
        """collection 自检 / upsert / tombstone / delete 全 mock（不触 Qdrant）。"""
        monkeypatch.setattr("knowledge.ingestion.ensure_delivery_knowledge_collection", AsyncMock())
        monkeypatch.setattr("knowledge.ingestion.upsert_knowledge_points", AsyncMock())
        monkeypatch.setattr("knowledge.ingestion.tombstone_points", AsyncMock())
        monkeypatch.setattr("knowledge.ingestion.delete_points", AsyncMock())

    async def test_reingest_idempotent_then_version_flip(self) -> None:
        """两次同 case 摄取幂等（实体/版本数不变），内容变更后第三次摄取版本 1→2 翻转。"""
        _project, context, plan, case = await sync_to_async(_make_host)()

        # 先入 tech_plan 实体（mcp_plan normalizer 负责），使 REFERENCES 边两端齐备
        assert await ingest(IngestionRequest("mcp_technical_plan", str(plan.id), "test")) == 2

        assert await ingest(IngestionRequest("learning_case", str(case.id), "test")) == 2
        # work_item（与 mcp plan 共享锚）+ tech_plan + learning_case = 3 实体
        assert await KnowledgeEntity.objects.acount() == 3
        versions_after_first = await KnowledgeEntityVersion.objects.acount()

        lc_entity_id = generate_entity_id("learning_case", "learning_case", str(case.id))
        wi_entity_id = generate_entity_id(
            "work_item",
            "feishu_work_item",
            f"{context.feishu_project_key}:{case.work_item_type}:{case.work_item_id}",
        )
        tp_entity_id = generate_entity_id("tech_plan", "mcp_technical_plan", str(plan.id))

        # 边可见性（criterion 1）：RELATES_TO / REFERENCES 活跃边存在
        relates = await KnowledgeEdge.objects.aget(
            source_entity_id=wi_entity_id,
            target_entity_id=lc_entity_id,
            relation="RELATES_TO",
        )
        assert relates.invalid_at is None
        references = await KnowledgeEdge.objects.aget(
            source_entity_id=lc_entity_id,
            target_entity_id=tp_entity_id,
            relation="REFERENCES",
        )
        assert references.invalid_at is None

        # 第二次重摄：实体数不变、版本行数不变（skipped 短路）、不翻版本、锚幂等
        assert await ingest(IngestionRequest("learning_case", str(case.id), "test")) == 2
        assert await KnowledgeEntity.objects.acount() == 3
        assert await KnowledgeEntityVersion.objects.acount() == versions_after_first
        lc_entity = await KnowledgeEntity.objects.aget(id=lc_entity_id)
        assert lc_entity.current_version == 1
        assert await KnowledgeEntity.objects.filter(kind="work_item").acount() == 1

        # 内容变更后第三次重摄：版本 1→2 翻转，旧版本 is_latest=False + invalid_at 置位
        case.embedding_text = "登录超时 Bug 案例 v2\n新增会话续期兜底逻辑"
        await case.asave(update_fields=["embedding_text", "updated_at"])
        assert await ingest(IngestionRequest("learning_case", str(case.id), "test")) == 2

        assert await KnowledgeEntity.objects.acount() == 3
        lc_entity = await KnowledgeEntity.objects.aget(id=lc_entity_id)
        assert lc_entity.current_version == 2
        v1 = await KnowledgeEntityVersion.objects.aget(entity_id=lc_entity_id, version=1)
        v2 = await KnowledgeEntityVersion.objects.aget(entity_id=lc_entity_id, version=2)
        assert v2.is_latest is True
        assert v2.supersedes_id == v1.id
        assert v1.is_latest is False
        assert v1.invalid_at is not None
