"""MCP 三类产物入图测试（Plan 100-03 / KNOW-03）。

四组用例：

- ``TestNormalizers``：三 normalizer 事件字段/kind/source_kind/payload 断言 +
  锚事件同源拼法逐字节相等回归防线 + diff 原文（last_diff）哨兵串零泄漏（T-100-06）；
- ``TestTriggers``：5 写入点投递断言（monkeypatch aschedule_ingestion，不真跑 worker）；
- ``TestEdgeReachability``：ROADMAP criterion 3 端到端——真跑 ``ingest()``（mock 向量）
  断言 plan→execution（IMPLEMENTED_BY）、work_item 锚→plan（RELATES_TO 双事件）、
  plan→chat coding_plan（RELATES_TO 可反查关联）、既有 HAS_PLAN 边未被打失效（T-100-07）、
  execution payload 含 PR 信息、natural key 隔离（不同 source_kind → 不同实体）；
- ``TestIdempotentReingest``：三类产物重复摄取幂等（criterion 4 MCP 面）。

测试纪律（RESEARCH Pitfall 5 / test_triggers.py 同款）：触发用例一律 monkeypatch
拦截投递；E2E/幂等用例 mock embedding / Qdrant 全套，零网络。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from structlog.testing import capture_logs

from knowledge.ingestion import IngestionRequest
from knowledge.models import generate_entity_id
from knowledge.sources.mcp_coding_plan import normalize as normalize_mcp_coding_plan
from knowledge.sources.mcp_execution_trace import normalize as normalize_mcp_execution_trace
from knowledge.sources.mcp_repository_analysis import normalize as normalize_mcp_analysis

# SQLite + async（sync_to_async 跨线程）需要 transaction=True（test_triggers 同款）。
pytestmark = pytest.mark.django_db(transaction=True)

# diff 原文特征串（T-100-06）：只要 normalizer 触碰 last_diff / runner_logs 就会被抓住。
_DIFF_SENTINEL = "DIFF原文特征串-MCP100-禁止入图"

_TRIPLE = "k-mcp100:story:7001"


# ============================================================================
# 同步工厂（用例内经 sync_to_async 调用）
# ============================================================================


def _make_repo():
    from repositories.models import Repository

    suffix = uuid.uuid4().hex[:8]
    return Repository.objects.create(
        name=f"mcp-artifact-repo-{suffix}",
        git_url=f"https://gitlab.com/test/mcp-artifact-{suffix}.git",
        git_platform="gitlab",
        default_branch="main",
    )


def _make_run():
    from interactions.ledger import create_interaction_run
    from runners.models import hash_token

    return create_interaction_run(
        token_fingerprint=hash_token(f"mcp-artifact-{uuid.uuid4().hex[:8]}"),
        source="mcp",
    )


def _make_analysis(repo=None, run=None, *, focus="认证入口"):
    from mcp_tools.models import McpRepositoryAnalysis

    repo = repo or _make_repo()
    run = run or _make_run()
    return McpRepositoryAnalysis.objects.create(
        run=run,
        repository=repo,
        branch="main",
        focus=focus,
        summary={
            "architecture_summary": "分层架构：views → services → models。",
            "key_modules": ["auth", {"name": "billing", "path": "src/billing.py"}],
        },
        evidence=[{"kind": "file", "file_path": "src/auth.py", "reason": "登录入口"}],
    )


def _make_plan(repo=None, run=None, *, analysis=None, with_version=True):
    from mcp_tools.models import McpCodingPlan, McpCodingPlanVersion

    repo = repo or _make_repo()
    run = run or _make_run()
    plan = McpCodingPlan.objects.create(
        run=run,
        repository=repo,
        analysis=analysis,
        branch="main",
        requirement="修复登录超时并补充审计日志。",
        title="登录修复 MCP 方案",
        current_version=1,
    )
    version = None
    if with_version:
        version = McpCodingPlanVersion.objects.create(
            plan=plan,
            run=run,
            version=1,
            plan_body={"title": plan.title},
            affected_files=["src/auth.py"],
            steps=["排查超时根因", {"order": 2, "title": "补审计日志"}],
            test_plan=["pytest tests/auth"],
            risks=["登录回归风险"],
            evidence=[],
            change_summary="Initial MCP coding plan",
            risk_delta={"added": [], "reduced": []},
        )
    return plan, version


def _make_trace(plan, version, **overrides):
    from mcp_tools.models import McpCodingExecutionTrace

    fields = {
        "run": plan.run,
        "plan": plan,
        "plan_version": version,
        "repository": plan.repository,
        "status": McpCodingExecutionTrace.Status.COMPLETED,
        "branch_name": "feat/mcp-fix",
        "target_branch": "main",
        "commit_sha": "abc1234def567890",
        "file_changes": [{"path": "src/auth.py", "additions": 3, "deletions": 1}],
        "test_results": [{"command": "pytest tests/auth", "status": "passed"}],
        "branch_summary": {"summary": "修复登录超时并补充审计日志。"},
        "last_diff": {"diff": _DIFF_SENTINEL},
        "runner_logs": [{"type": "progress", "content": _DIFF_SENTINEL}],
        "mr_result": {
            "success": True,
            "mr_url": "https://gitlab.com/test/mcp-artifact/-/merge_requests/7",
        },
    }
    fields.update(overrides)
    return McpCodingExecutionTrace.objects.create(**fields)


def _make_work_item_closure(plan, version):
    """context + technical_plan + repo_task 最小闭包（三元组挂载到 plan）。"""
    from mcp_tools.models import (
        McpWorkItemContext,
        McpWorkItemRepoTask,
        McpWorkItemTechnicalPlan,
    )

    run = plan.run
    context = McpWorkItemContext.objects.create(
        run=run,
        feishu_project_key="k-mcp100",
        work_item_type="story",
        work_item_id=7001,
        name="登录需求",
        description="登录超时后提示不清晰。",
        work_item_status="developing",
    )
    technical_plan = McpWorkItemTechnicalPlan.objects.create(
        run=run,
        context=context,
        feishu_project_key="k-mcp100",
        work_item_type="story",
        work_item_id=7001,
        title="登录技术方案",
        plan_body={"title": "登录技术方案"},
        markdown="# 登录技术方案\n\n正文",
        repository_tasks=[],
    )
    task = McpWorkItemRepoTask.objects.create(
        run=run,
        technical_plan=technical_plan,
        repository=plan.repository,
        coding_plan=plan,
        plan_version=version,
        order=1,
        status=McpWorkItemRepoTask.Status.PLANNED,
        task_body={},
    )
    return context, technical_plan, task


def _event_dump(event) -> str:
    """事件全字段序列化（哨兵串零泄漏扫描）。"""
    return json.dumps(
        {"title": event.title, "content": event.content, "payload": event.payload},
        ensure_ascii=False,
    )


def _patch_vector_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    """真跑 ingest 的向量 seam（test_triggers SC#4 同款清单）。"""
    from services.qdrant_service import QdrantService

    monkeypatch.setattr("knowledge.ingestion.ensure_delivery_knowledge_collection", AsyncMock())
    monkeypatch.setattr(
        QdrantService, "upsert_vectors_by_name", classmethod(lambda cls, name, pts: True)
    )


# ============================================================================
# Task 1/2：三 normalizer 取材断言
# ============================================================================


class TestNormalizers:
    async def test_analysis_single_event_fields(self) -> None:
        """analysis → document 单事件：kind/source_kind/title/content/payload 摘要、零边。"""
        analysis = await sync_to_async(_make_analysis)()

        events = await normalize_mcp_analysis(
            IngestionRequest("mcp_repository_analysis", str(analysis.id), "mcp_analysis_created")
        )

        assert len(events) == 1
        event = events[0]
        assert event.kind == "document"
        assert event.origin == "mcp"
        assert event.source_kind == "mcp_repository_analysis"
        assert event.source_id == str(analysis.id)
        assert event.title == f"{analysis.repository.name} 仓库分析（认证入口）"
        assert "分层架构" in event.content
        assert "src/auth.py：登录入口" in event.content
        # payload 只放摘要，不复制 summary 全文
        assert event.payload == {
            "repository_id": str(analysis.repository_id),
            "branch": "main",
            "focus": "认证入口",
            "status": "completed",
            "evidence_count": 1,
        }
        assert event.space_id is None
        assert event.repository_id == str(analysis.repository_id)
        assert event.event_time == analysis.created_at
        assert event.edges == ()

    async def test_analysis_without_focus_title_has_no_suffix(self) -> None:
        analysis = await sync_to_async(lambda: _make_analysis(focus=""))()

        events = await normalize_mcp_analysis(
            IngestionRequest("mcp_repository_analysis", str(analysis.id), "mcp_analysis_created")
        )

        assert events[0].title == f"{analysis.repository.name} 仓库分析"

    async def test_coding_plan_single_event_with_references_edge(self) -> None:
        """无 work_item 挂载 → 单事件；analysis 非空 → REFERENCES 出边。"""
        repo = await sync_to_async(_make_repo)()
        run = await sync_to_async(_make_run)()
        analysis = await sync_to_async(lambda: _make_analysis(repo, run))()
        plan, version = await sync_to_async(lambda: _make_plan(repo, run, analysis=analysis))()

        events = await normalize_mcp_coding_plan(
            IngestionRequest("mcp_coding_plan", str(plan.id), "mcp_coding_plan_created")
        )

        assert len(events) == 1
        event = events[0]
        assert event.kind == "tech_plan"
        assert event.origin == "mcp"
        assert event.source_kind == "mcp_coding_plan"
        assert event.source_id == str(plan.id)
        assert event.title == plan.title
        assert "## 需求" in event.content
        assert plan.requirement in event.content
        assert "排查超时根因" in event.content
        assert "## 测试计划" in event.content
        assert event.payload["requirement"] == plan.requirement[:500]
        assert event.payload["affected_files"] == ["src/auth.py"]
        assert event.payload["version"] == 1
        assert event.payload["analysis_id"] == str(analysis.id)
        assert event.repository_id == str(repo.id)
        assert event.space_id is None
        assert len(event.edges) == 1
        spec = event.edges[0]
        assert spec.relation == "REFERENCES"
        assert spec.target_entity_id == generate_entity_id(
            "document", "mcp_repository_analysis", str(analysis.id)
        )

    async def test_coding_plan_dual_events_with_work_item_anchor(self) -> None:
        """三元组齐备 → [work_item 锚, plan]；锚出边 RELATES_TO（禁用 HAS_PLAN，T-100-07）。"""
        plan, version = await sync_to_async(_make_plan)()
        context, _tp, _task = await sync_to_async(lambda: _make_work_item_closure(plan, version))()

        events = await normalize_mcp_coding_plan(
            IngestionRequest("mcp_coding_plan", str(plan.id), "mcp_coding_plan_created")
        )

        assert len(events) == 2
        work_item, plan_event = events
        assert work_item.kind == "work_item"
        assert work_item.origin == "mcp"
        assert work_item.source_kind == "feishu_work_item"
        assert work_item.source_id == _TRIPLE
        assert work_item.title == context.name
        # 锚 content 同源拼法（mcp_plan.py 同款）：name + 空行 + description
        assert work_item.content == f"{context.name}\n\n{context.description}"
        assert len(work_item.edges) == 1
        spec = work_item.edges[0]
        assert spec.relation == "RELATES_TO"  # 禁用 HAS_PLAN：exclusive 会打失效既有方案边
        assert spec.exclusive is False
        assert spec.target_entity_id == generate_entity_id(
            "tech_plan", "mcp_coding_plan", str(plan.id)
        )
        assert plan_event.kind == "tech_plan"
        assert plan_event.source_kind == "mcp_coding_plan"

    async def test_coding_plan_relates_to_chat_plan_when_resolvable(self) -> None:
        """同 work_item 锚有活跃边的 chat coding_plan → plan 主事件挂 RELATES_TO 出边。"""
        from django.utils import timezone as dj_tz

        from knowledge.models import KnowledgeEdge, KnowledgeEntity

        plan, version = await sync_to_async(lambda: _make_plan())()
        await sync_to_async(lambda: _make_work_item_closure(plan, version))()

        chat_plan_id = str(uuid.uuid4())
        chat_entity_id = generate_entity_id("tech_plan", "coding_plan", chat_plan_id)
        anchor_id = generate_entity_id("work_item", "feishu_work_item", _TRIPLE)
        now = dj_tz.now()

        def _seed_graph():
            anchor = KnowledgeEntity.objects.create(
                id=anchor_id,
                kind="work_item",
                origin="mcp",
                source_kind="feishu_work_item",
                source_id=_TRIPLE,
                title="登录需求",
                event_time=now,
            )
            chat_entity = KnowledgeEntity.objects.create(
                id=chat_entity_id,
                kind="tech_plan",
                origin="chat",
                source_kind="coding_plan",
                source_id=chat_plan_id,
                title="chat 登录方案",
                event_time=now,
            )
            KnowledgeEdge.objects.create(
                source_entity=anchor,
                target_entity=chat_entity,
                relation="HAS_PLAN",
                valid_at=now,
            )

        await sync_to_async(_seed_graph)()

        events = await normalize_mcp_coding_plan(
            IngestionRequest("mcp_coding_plan", str(plan.id), "mcp_coding_plan_created")
        )

        plan_event = events[-1]
        relates = [e for e in plan_event.edges if e.relation == "RELATES_TO"]
        assert [e.target_entity_id for e in relates] == [chat_entity_id]

    async def test_coding_plan_version_missing_returns_empty_with_warning(self) -> None:
        plan, _ = await sync_to_async(lambda: _make_plan(with_version=False))()

        with capture_logs() as cap:
            events = await normalize_mcp_coding_plan(
                IngestionRequest("mcp_coding_plan", str(plan.id), "mcp_coding_plan_created")
            )

        assert events == []
        warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
        assert "knowledge_normalize_plan_version_missing" in warnings

    async def test_execution_trace_dual_events_anchor_content_byte_equal(self) -> None:
        """[plan 锚, code_change] 双事件：锚 content 与 mcp_coding_plan 主事件逐字节相等；
        IMPLEMENTED_BY 边方向同 task_result.py 先例；PR 信息入 payload；diff 哨兵零泄漏。"""
        plan, version = await sync_to_async(_make_plan)()
        trace = await sync_to_async(lambda: _make_trace(plan, version))()

        trace_events = await normalize_mcp_execution_trace(
            IngestionRequest("mcp_execution_trace", str(trace.id), "mcp_execution_created")
        )
        plan_events = await normalize_mcp_coding_plan(
            IngestionRequest("mcp_coding_plan", str(plan.id), "mcp_coding_plan_created")
        )

        assert len(trace_events) == 2
        anchor, code_change = trace_events
        # 同源拼法回归防线：锚事件 content 与 plan normalizer 主事件逐字节一致
        assert anchor.content == plan_events[-1].content
        assert anchor.kind == "tech_plan"
        assert anchor.source_kind == "mcp_coding_plan"
        assert anchor.source_id == str(plan.id)
        assert len(anchor.edges) == 1
        spec = anchor.edges[0]
        assert spec.relation == "IMPLEMENTED_BY"
        assert spec.target_entity_id == generate_entity_id(
            "code_change", "mcp_execution_trace", str(trace.id)
        )

        assert code_change.kind == "code_change"
        assert code_change.origin == "mcp"
        assert code_change.source_kind == "mcp_execution_trace"
        assert code_change.source_id == str(trace.id)
        assert code_change.title == f"{plan.repository.name} MCP 执行 @ abc1234d"
        assert "src/auth.py" in code_change.content
        assert "pytest tests/auth" in code_change.content
        payload = code_change.payload
        assert payload["plan_id"] == str(plan.id)
        assert payload["plan_version_id"] == str(version.id)
        assert payload["commit_sha"] == trace.commit_sha
        assert payload["mr_url"] == "https://gitlab.com/test/mcp-artifact/-/merge_requests/7"
        assert payload["file_change_count"] == 1
        assert code_change.repository_id == str(plan.repository_id)
        # updated_at 而非 completed_at：内容再变（error 补写重摄）翻版需要 event_time 推进（HI-01）
        assert code_change.event_time == trace.updated_at
        # T-100-06：diff 原文（last_diff）/runner_logs 哨兵串零泄漏
        for event in trace_events:
            assert _DIFF_SENTINEL not in _event_dump(event)

    async def test_execution_trace_error_text_redacted_in_content(self) -> None:
        """trace.error 含凭证（Bearer token 等）→ content 只留 ***REDACTED***（ME-01）。"""
        secret = "Bearer sk-friday-secret-token-1234567890abcdef"
        plan, version = await sync_to_async(_make_plan)()
        trace = await sync_to_async(
            lambda: _make_trace(plan, version, error=f"git push 失败：Authorization: {secret}")
        )()

        events = await normalize_mcp_execution_trace(
            IngestionRequest("mcp_execution_trace", str(trace.id), "mcp_execution_created")
        )

        code_change = events[-1]
        assert "## 错误" in code_change.content
        assert secret not in _event_dump(code_change)
        assert "***REDACTED***" in code_change.content

    async def test_execution_trace_plan_version_missing_degrades_to_single_event(self) -> None:
        """plan 无自有版本（trace.plan_version 指向他 plan 版本的病理形态）→ 降级单事件。"""
        plan_a, _ = await sync_to_async(lambda: _make_plan(with_version=False))()
        _plan_b, version_b = await sync_to_async(_make_plan)()
        trace = await sync_to_async(lambda: _make_trace(plan_a, version_b))()

        with capture_logs() as cap:
            events = await normalize_mcp_execution_trace(
                IngestionRequest("mcp_execution_trace", str(trace.id), "mcp_execution_created")
            )

        assert len(events) == 1
        assert events[0].kind == "code_change"
        warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
        assert "knowledge_normalize_anchor_plan_missing" in warnings

    async def test_source_missing_returns_empty_with_warning(self) -> None:
        """三 normalizer 源缺失均空列表 + warning，不 raise。"""
        missing = str(uuid.uuid4())
        with capture_logs() as cap:
            assert (
                await normalize_mcp_analysis(
                    IngestionRequest("mcp_repository_analysis", missing, "t")
                )
                == []
            )
            assert (
                await normalize_mcp_coding_plan(IngestionRequest("mcp_coding_plan", missing, "t"))
                == []
            )
            assert (
                await normalize_mcp_execution_trace(
                    IngestionRequest("mcp_execution_trace", missing, "t")
                )
                == []
            )
        warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
        assert warnings.count("knowledge_normalize_source_missing") == 3


# ============================================================================
# Task 3：5 写入点投递断言（monkeypatch 拦截，不真跑 worker）
# ============================================================================


@pytest.fixture
def captured_requests(monkeypatch: pytest.MonkeyPatch) -> list[IngestionRequest]:
    """monkeypatch ``knowledge.ingestion.aschedule_ingestion`` 收集投递请求。"""
    captured: list[IngestionRequest] = []

    async def _collect(request: IngestionRequest, **_kwargs) -> None:
        captured.append(request)

    monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", _collect)
    return captured


def _request_triple(request: IngestionRequest) -> tuple[str, str, str]:
    return (request.source_kind, request.source_id, request.trigger)


@pytest.fixture
def mcp_http_client(make_access_token):
    from rest_framework.test import APIClient

    _token, plaintext = make_access_token(name="mcp-artifact-token")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    return client


@pytest.fixture
def indexed_repo(db, settings):
    from repositories.models import FileIndex, IndexStatus

    settings.REPO_MIRROR_ENABLED = False
    repo = _make_repo()
    repo.index_status = IndexStatus.INDEXED
    repo.ai_summary = "测试仓库摘要"
    repo.last_indexed_commit_sha = "a" * 40
    repo.save(update_fields=["index_status", "ai_summary", "last_indexed_commit_sha"])
    FileIndex.objects.create(repository=repo, file_path="src/main.py", file_hash="hash-main")
    return repo


class TestTriggers:
    def test_trigger_analyze_repository(
        self, mcp_http_client, indexed_repo, captured_requests
    ) -> None:
        response = mcp_http_client.post(
            "/api/mcp/tools/analyze_repository/",
            {"repository_id": str(indexed_repo.id), "focus": "触发断言"},
            format="json",
        )

        assert response.status_code == 200
        analysis_id = response.json()["analysis_id"]
        assert [_request_triple(r) for r in captured_requests] == [
            ("mcp_repository_analysis", analysis_id, "mcp_analysis_created")
        ]

    def test_trigger_create_coding_plan(
        self,
        mcp_http_client,
        indexed_repo,
        captured_requests,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from types import SimpleNamespace

        from mcp_tools.orchestration_delegate import DelegateResult

        async def _fake_delegate(**_kwargs):
            return DelegateResult(
                session=SimpleNamespace(id=uuid.uuid4()),
                status="completed",
                content={},
                plan_version_id=None,
                markdown="",
                model_usage={},
            )

        monkeypatch.setattr("mcp_tools.views.delegate_process_runtime", _fake_delegate)

        response = mcp_http_client.post(
            "/api/mcp/tools/create_coding_plan/",
            {"repository_id": str(indexed_repo.id), "requirement": "修复登录超时"},
            format="json",
        )

        assert response.status_code == 200
        plan_id = response.json()["plan_id"]
        assert [_request_triple(r) for r in captured_requests] == [
            ("mcp_coding_plan", plan_id, "mcp_coding_plan_created")
        ]

    def test_trigger_improve_coding_plan(
        self, mcp_http_client, indexed_repo, captured_requests
    ) -> None:
        plan, _version = _make_plan(indexed_repo, _make_run())

        response = mcp_http_client.post(
            "/api/mcp/tools/improve_coding_plan/",
            {"plan_id": str(plan.id), "feedback": "请增加回滚步骤"},
            format="json",
        )

        assert response.status_code == 200
        assert [_request_triple(r) for r in captured_requests] == [
            ("mcp_coding_plan", str(plan.id), "mcp_coding_plan_improved")
        ]

    def test_trigger_execute_coding_plan(
        self,
        mcp_http_client,
        indexed_repo,
        captured_requests,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plan, _version = _make_plan(indexed_repo, _make_run())
        monkeypatch.setattr("mcp_tools.views.dispatch_execution", AsyncMock())

        response = mcp_http_client.post(
            "/api/mcp/tools/execute_coding_plan/",
            {"plan_id": str(plan.id), "branch_name": "feat/mcp-trigger"},
            format="json",
        )

        assert response.status_code == 202
        execution_id = response.json()["execution_id"]
        assert [_request_triple(r) for r in captured_requests] == [
            ("mcp_execution_trace", execution_id, "mcp_execution_created")
        ]

    async def test_trigger_work_item_ensure_coding_plan(
        self, captured_requests: list[IngestionRequest]
    ) -> None:
        """_ensure_coding_plan acreate 分支投递 mcp_work_item_plan_created。"""
        from mcp_tools import work_item_execution_service as wie
        from mcp_tools.models import McpWorkItemRepoTask

        def _setup():
            plan_stub, version_stub = _make_plan()
            _context, technical_plan, _task = _make_work_item_closure(plan_stub, version_stub)
            # 新建一个未挂 coding_plan 的 task 走 acreate 分支
            return McpWorkItemRepoTask.objects.create(
                run=plan_stub.run,
                technical_plan=technical_plan,
                repository=plan_stub.repository,
                order=2,
                status=McpWorkItemRepoTask.Status.PENDING,
                task_body={"change_goal": "修复登录", "candidate_files": ["src/auth.py"]},
            )

        task = await sync_to_async(_setup)()
        run = await sync_to_async(lambda: task.run)()

        plan, _version = await wie._ensure_coding_plan(run=run, task=task)

        assert [_request_triple(r) for r in captured_requests] == [
            ("mcp_coding_plan", str(plan.id), "mcp_work_item_plan_created")
        ]

    async def test_trigger_work_item_execute_one_task(
        self,
        captured_requests: list[IngestionRequest],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_execute_one_task trace acreate 分支（refresh 后）投递 mcp_work_item_execution_created。"""
        from mcp_tools import work_item_execution_service as wie

        monkeypatch.setattr(wie, "dispatch_execution", AsyncMock())
        monkeypatch.setattr(wie, "refresh_execution_trace", AsyncMock())

        def _setup():
            plan, version = _make_plan()
            _context, _tp, task = _make_work_item_closure(plan, version)
            return task

        task = await sync_to_async(_setup)()
        run = await sync_to_async(lambda: task.run)()

        result_task = await wie._execute_one_task(
            run=run,
            task=task,
            dispatch=True,
            create_merge_requests=False,
            timeout_seconds=10,
            reviewer_usernames=[],
        )

        assert result_task.execution_trace_id is not None
        assert [_request_triple(r) for r in captured_requests] == [
            (
                "mcp_execution_trace",
                str(result_task.execution_trace_id),
                "mcp_work_item_execution_created",
            )
        ]


# ============================================================================
# Task 4：E2E 边可达性（ROADMAP criterion 3）+ 幂等重摄（criterion 4 MCP 面）
# ============================================================================


class TestEdgeReachability:
    async def test_plan_execution_work_item_edges_end_to_end(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_embedding,
        mock_qdrant_client,
    ) -> None:
        """真跑 ingest：plan—IMPLEMENTED_BY→execution、锚—RELATES_TO→plan、
        plan—RELATES_TO→chat plan、既有 HAS_PLAN 边不受损（T-100-07）、PR 信息入 payload。"""
        from django.utils import timezone as dj_tz

        from knowledge.graph_store import graph_store
        from knowledge.ingestion import ingest
        from knowledge.models import KnowledgeEdge, KnowledgeEntity, KnowledgeEntityVersion

        _patch_vector_stack(monkeypatch)

        def _setup():
            repo = _make_repo()
            run = _make_run()
            analysis = _make_analysis(repo, run)
            plan, version = _make_plan(repo, run, analysis=analysis)
            _context, technical_plan, _task = _make_work_item_closure(plan, version)
            trace = _make_trace(plan, version)
            return analysis, plan, technical_plan, trace

        analysis, plan, technical_plan, trace = await sync_to_async(_setup)()

        # 预置 1：mcp_technical_plan 摄取 → work_item 锚 + 既有 HAS_PLAN 活跃边
        assert (
            await ingest(
                IngestionRequest("mcp_technical_plan", str(technical_plan.id), "mcp_plan_created")
            )
            == 2
        )

        # 预置 2：chat coding_plan 实体 + 与锚的活跃边（RELATES_TO 可反查条件）
        anchor_id = generate_entity_id("work_item", "feishu_work_item", _TRIPLE)
        chat_plan_id = str(uuid.uuid4())
        chat_entity_id = generate_entity_id("tech_plan", "coding_plan", chat_plan_id)
        now = dj_tz.now()
        await KnowledgeEntity.objects.acreate(
            id=chat_entity_id,
            kind="tech_plan",
            origin="chat",
            source_kind="coding_plan",
            source_id=chat_plan_id,
            title="chat 登录方案",
            event_time=now,
        )
        await graph_store.add_edge(
            source_id=anchor_id,
            target_id=chat_entity_id,
            relation="RELATES_TO",
            valid_at=now,
        )

        # 依次摄取三产物（真跑 ingest，mock 向量）
        assert (
            await ingest(
                IngestionRequest(
                    "mcp_repository_analysis", str(analysis.id), "mcp_analysis_created"
                )
            )
            == 1
        )
        assert (
            await ingest(
                IngestionRequest("mcp_coding_plan", str(plan.id), "mcp_coding_plan_created")
            )
            == 2
        )
        assert (
            await ingest(
                IngestionRequest("mcp_execution_trace", str(trace.id), "mcp_execution_created")
            )
            == 2
        )

        plan_entity_id = generate_entity_id("tech_plan", "mcp_coding_plan", str(plan.id))
        trace_entity_id = generate_entity_id("code_change", "mcp_execution_trace", str(trace.id))
        analysis_entity_id = generate_entity_id(
            "document", "mcp_repository_analysis", str(analysis.id)
        )
        mcp_tech_plan_id = generate_entity_id(
            "tech_plan", "mcp_technical_plan", str(technical_plan.id)
        )

        def _active(source_id, target_id, relation) -> bool:
            return KnowledgeEdge.objects.filter(
                source_entity_id=source_id,
                target_entity_id=target_id,
                relation=relation,
                invalid_at__isnull=True,
                expired_at__isnull=True,
            ).exists()

        # plan —IMPLEMENTED_BY→ execution（方案→代码变更，锚事件出边）
        assert await sync_to_async(_active)(plan_entity_id, trace_entity_id, "IMPLEMENTED_BY")
        # work_item 锚 —RELATES_TO→ plan（锚双事件生效）
        assert await sync_to_async(_active)(anchor_id, plan_entity_id, "RELATES_TO")
        # plan —RELATES_TO→ chat coding_plan（可反查显式关联）
        assert await sync_to_async(_active)(plan_entity_id, chat_entity_id, "RELATES_TO")
        # plan —REFERENCES→ analysis
        assert await sync_to_async(_active)(plan_entity_id, analysis_entity_id, "REFERENCES")
        # T-100-07 回归：既有 HAS_PLAN→mcp_technical_plan 边未被 RELATES_TO 锚边打失效
        assert await sync_to_async(_active)(anchor_id, mcp_tech_plan_id, "HAS_PLAN")

        # work_item 锚沿边可达 plan（1 跳）与 execution（2 跳）——端到端自动化断言
        results = await graph_store.traverse(
            anchor_id, max_hops=2, relations=["RELATES_TO", "IMPLEMENTED_BY"], direction="out"
        )
        reached = {r.entity_id: r.depth for r in results}
        assert reached.get(plan_entity_id) == 1
        assert reached.get(trace_entity_id) == 2

        # execution payload 含 PR 信息（plan→execution→PR 链完整）
        latest = await KnowledgeEntityVersion.objects.aget(
            entity_id=trace_entity_id, is_latest=True
        )
        assert latest.payload["mr_url"] == trace.mr_result["mr_url"]
        assert latest.payload["commit_sha"] == trace.commit_sha

        # natural key 隔离：MCP plan 与 chat plan 同 source_id 串也不同实体（不重复入图）
        same_id = str(plan.id)
        assert generate_entity_id("tech_plan", "mcp_coding_plan", same_id) != generate_entity_id(
            "tech_plan", "coding_plan", same_id
        )


class TestIdempotentReingest:
    async def test_three_kinds_reingest_idempotent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_embedding,
        mock_qdrant_client,
    ) -> None:
        """三类产物各 ingest 两次：实体数不变、current_version==1、内容未变不翻版本。"""
        from knowledge.ingestion import ingest
        from knowledge.models import KnowledgeEntity, KnowledgeEntityVersion

        _patch_vector_stack(monkeypatch)

        def _setup():
            repo = _make_repo()
            run = _make_run()
            analysis = _make_analysis(repo, run)
            plan, version = _make_plan(repo, run, analysis=analysis)
            _make_work_item_closure(plan, version)
            trace = _make_trace(plan, version)
            return analysis, plan, trace

        analysis, plan, trace = await sync_to_async(_setup)()
        requests = [
            IngestionRequest("mcp_repository_analysis", str(analysis.id), "mcp_analysis_created"),
            IngestionRequest("mcp_coding_plan", str(plan.id), "mcp_coding_plan_created"),
            IngestionRequest("mcp_execution_trace", str(trace.id), "mcp_execution_created"),
        ]

        for request in requests:
            await ingest(request)
        # analysis 1 + work_item 锚 1 + plan 1 + code_change 1
        assert await KnowledgeEntity.objects.acount() == 4
        assert await KnowledgeEntityVersion.objects.acount() == 4

        with capture_logs() as cap:
            for request in requests:
                await ingest(request)

        # 幂等：实体/版本数均不变，全部 current_version==1，第二轮全走 skipped 短路
        assert await KnowledgeEntity.objects.acount() == 4
        assert await KnowledgeEntityVersion.objects.acount() == 4
        async for entity in KnowledgeEntity.objects.all():
            assert entity.current_version == 1
        skipped = [e for e in cap if e.get("event") == "knowledge_ingest_skipped"]
        assert len(skipped) >= 5  # 第二轮 5 事件（1+2+2）全短路

    async def test_plan_reingest_after_improve_flips_version(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_embedding,
        mock_qdrant_client,
    ) -> None:
        """improve 后重摄：content 变更走版本翻转 1→2，v2 supersedes v1，无 IntegrityError。

        HI-01 回归防线：event_time 曾固定 plan.created_at（永不推进），翻版时
        invalid_at == 旧版 valid_at 违反 kversion_valid_range CHECK，被吞成
        knowledge_ingest_concurrent_conflict——improve 后的方案内容永远进不了知识库。
        """
        from knowledge.ingestion import ingest
        from knowledge.models import KnowledgeEntity, KnowledgeEntityVersion

        _patch_vector_stack(monkeypatch)

        plan, _version = await sync_to_async(_make_plan)()
        request = IngestionRequest("mcp_coding_plan", str(plan.id), "mcp_coding_plan_created")
        assert await ingest(request) == 1

        plan_entity_id = generate_entity_id("tech_plan", "mcp_coding_plan", str(plan.id))
        entity = await KnowledgeEntity.objects.aget(id=plan_entity_id)
        assert entity.current_version == 1

        # 模拟 ImproveCodingPlanView：新建 v2 版本行 + plan.save 推进 auto_now updated_at
        def _improve():
            from mcp_tools.models import McpCodingPlanVersion

            McpCodingPlanVersion.objects.create(
                plan=plan,
                run=plan.run,
                version=2,
                plan_body={"title": plan.title},
                affected_files=["src/auth.py", "src/session.py"],
                steps=["排查超时根因", "新增会话续期兜底"],
                test_plan=["pytest tests/auth"],
                risks=["登录回归风险"],
                evidence=[],
                change_summary="增加会话续期兜底",
                risk_delta={"added": [], "reduced": []},
            )
            plan.current_version = 2
            plan.save(update_fields=["current_version", "updated_at"])

        await sync_to_async(_improve)()

        with capture_logs() as cap:
            assert await ingest(request) == 1

        # 不再被吞成并发冲突（IntegrityError 伪装）
        conflicts = [e for e in cap if e.get("event") == "knowledge_ingest_concurrent_conflict"]
        assert conflicts == []

        entity = await KnowledgeEntity.objects.aget(id=plan_entity_id)
        assert entity.current_version == 2
        v1 = await KnowledgeEntityVersion.objects.aget(entity_id=plan_entity_id, version=1)
        v2 = await KnowledgeEntityVersion.objects.aget(entity_id=plan_entity_id, version=2)
        assert v2.is_latest is True
        assert v2.supersedes_id == v1.id
        assert "新增会话续期兜底" in v2.content
        assert v1.is_latest is False
        assert v1.invalid_at is not None
