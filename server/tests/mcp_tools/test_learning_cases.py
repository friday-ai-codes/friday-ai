"""learning case MCP 工具测试（Phase 100 / KNOW-02）。

四组用例：

- 既有两用例（create→search / 方案自动召回）适配统一向量路径；
- **golden set 对照测试（KNOW-02 验收门）**：真实 ``ingest()`` 全链路（PG 实体/版本 +
  内存 Qdrant 向量点）+ 确定性假 embedding，断言中文问题描述 / 路径 / symbol 三形态
  查询目标 case 均在 top-3，且 hint 增强+提权生效（有 hint 排名不劣于无 hint）；
- 契约断言：payload 外形键集 == ``learning_case_payload`` 全键集，``score`` 为 0-1 浮点；
  同一 query 双工具（search_learning_cases / search_delivery_knowledge）均可召回
  （ROADMAP criterion 1）；
- fail-soft（Qdrant 异常 → 200 + 空 results）+ RetrievalTrace / ToolCallRecord /
  RequestMetric 观测断言（ROADMAP criterion 5，MCP 链）。

测试基建（golden_vector_stack）：monkeypatch ``QdrantService.get_client`` 为
``QdrantClient(":memory:")`` 内嵌实例（零网络，pytest-socket 安全）+ 确定性
bag-of-words 假 dense/sparse 向量（同文本恒同向量、共享 token 越多余弦越近），
维度对齐 ``DEFAULT_EMBEDDING_DIMENSION``；后台摄取线程 no-op（测试内显式
``ingest()`` 同步补摄，避免 on_commit 后台竞态）。
"""

from __future__ import annotations

import hashlib
import math
import re
import uuid

import pytest
from asgiref.sync import async_to_sync
from rest_framework.test import APIClient

from interactions.ledger import create_interaction_run
from knowledge.collection import DEFAULT_EMBEDDING_DIMENSION
from knowledge.ingestion import IngestionRequest, ingest
from mcp_tools.models import (
    McpLearningCase,
    McpWorkItemContext,
    McpWorkItemRepoTask,
    McpWorkItemTechnicalPlan,
)
from runners.models import hash_token

# SQLite + async（ingest 内 sync_to_async 跨线程）需要 transaction=True（knowledge 域同款纪律）。
pytestmark = pytest.mark.django_db(transaction=True)

_SEARCH_URL = "/api/mcp/tools/search_learning_cases/"

# learning_case_payload 全键集（含 score）：契约守门断言的期望值。
_PAYLOAD_KEYS = {
    "case_id",
    "title",
    "work_item_type",
    "work_item_id",
    "problem",
    "root_cause",
    "solution",
    "outcome",
    "repositories",
    "files",
    "symbols",
    "branches",
    "mr_urls",
    "tests",
    "source_links",
    "reuse_judgement",
    "created_at",
    "score",
}


# ============================================================================
# golden vector stack：内存 Qdrant + 确定性假 embedding（零网络）
# ============================================================================

_TERM_RE = re.compile(r"[A-Za-z0-9_\-/.]{2,}|[\u4e00-\u9fff]")


def _terms(text: str) -> list[str]:
    """ASCII 词/路径整体成 token、中文逐字成 token（共享 token 越多余弦越近）。"""
    return _TERM_RE.findall(text.lower())


def _stable_index(token: str, space: int) -> int:
    """确定性 token → 索引（禁 builtin hash：进程级随机化会破坏确定性）。"""
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % space


def _bow_dense(text: str) -> list[float]:
    """bag-of-words 假 dense 向量（L2 归一化，维度对齐建集合维度）。"""
    vector = [0.0] * DEFAULT_EMBEDDING_DIMENSION
    for token in _terms(text):
        vector[_stable_index(token, DEFAULT_EMBEDDING_DIMENSION)] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _bow_sparse(text: str) -> dict:
    """token-hash 假 sparse 编码（Qdrant SparseVector 格式）。"""
    counts: dict[int, float] = {}
    for token in _terms(text):
        index = _stable_index(token, 2**31)
        counts[index] = counts.get(index, 0.0) + 1.0
    indices = sorted(counts)
    return {"indices": indices, "values": [counts[index] for index in indices]}


@pytest.fixture
def golden_vector_stack(monkeypatch: pytest.MonkeyPatch):
    """内存 Qdrant + 确定性假 dense/sparse embedding + 后台摄取 no-op。"""
    from qdrant_client import QdrantClient

    from services.embedding import EmbeddingService
    from services.qdrant_service import QdrantService
    from services.sparse_encoder import SparseEncoderService

    local_client = QdrantClient(":memory:")
    monkeypatch.setattr(QdrantService, "get_client", classmethod(lambda cls: local_client))
    # aschedule_ingestion 的 on_commit → 后台线程摄取改 no-op：transaction=True 下
    # on_commit 会真触发，测试内显式 await ingest(...) 同步补摄避免竞态。
    monkeypatch.setattr("knowledge.ingestion.run_in_background", lambda *args, **kwargs: None)

    async def _dense_one(text: str) -> list[float]:
        return _bow_dense(text)

    async def _dense_batch(texts: list[str], **_kwargs) -> list[list[float]]:
        return [_bow_dense(text) for text in texts]

    monkeypatch.setattr(EmbeddingService, "generate_embedding", staticmethod(_dense_one))
    monkeypatch.setattr(EmbeddingService, "generate_embeddings_batch", staticmethod(_dense_batch))
    monkeypatch.setattr(SparseEncoderService, "encode", staticmethod(_bow_sparse))
    monkeypatch.setattr(
        SparseEncoderService,
        "encode_batch",
        staticmethod(lambda texts: [_bow_sparse(text) for text in texts]),
    )
    return local_client


# ============================================================================
# 工厂
# ============================================================================


def _context(project, *, name: str = "登录超时 Bug") -> McpWorkItemContext:
    run = create_interaction_run(
        token_fingerprint=hash_token(f"learning-context-{name}"),
        source="mcp",
    )
    return McpWorkItemContext.objects.create(
        run=run,
        space=project,
        feishu_project_key=project.feishu_project_key,
        work_item_type="bug",
        work_item_id=99,
        name=name,
        status=McpWorkItemContext.Status.COMPLETED,
        work_item_status="done",
        description="登录超时后错误提示不清晰，需要修复 token 刷新边界。",
        documents=[
            {
                "document_id": "doxcnLoginBug",
                "status": "ok",
                "content": "登录超时后前端显示空白。",
            }
        ],
        context={
            "work_item": {
                "source": {
                    "project_key": project.feishu_project_key,
                    "work_item_type": "bug",
                    "work_item_id": 99,
                }
            }
        },
    )


def _technical_plan(project, indexed_repository) -> McpWorkItemTechnicalPlan:
    run = create_interaction_run(
        token_fingerprint=hash_token("learning-plan"),
        source="mcp",
    )
    context = _context(project)
    task_body = {
        "order": 1,
        "repository_id": str(indexed_repository.id),
        "repository_name": indexed_repository.name,
        "base_branch": indexed_repository.default_branch,
        "planned_branch": "feat/feishu-bug-99-login-timeout",
        "change_goal": "修复登录超时提示和 token 刷新边界",
        "candidate_files": ["src/auth/session.py", "tests/test_session.py"],
        "steps": ["修复 session 判断", "补充回归测试"],
        "test_strategy": ["pytest tests/test_session.py -q"],
        "risks": ["登录态兼容性"],
        "rollback": "revert commit",
    }
    plan = McpWorkItemTechnicalPlan.objects.create(
        run=run,
        context=context,
        space=project,
        feishu_project_key=project.feishu_project_key,
        work_item_type="bug",
        work_item_id=99,
        title="登录超时 Bug 技术方案",
        status=McpWorkItemTechnicalPlan.Status.COMPLETED,
        plan_body={"repository_task_matrix": [task_body]},
        markdown="# 登录超时 Bug 技术方案\n",
        repository_tasks=[task_body],
        feishu_document_id="doxcnLoginPlan",
        feishu_document_url="https://feishu.cn/docx/doxcnLoginPlan",
    )
    McpWorkItemRepoTask.objects.create(
        run=run,
        technical_plan=plan,
        repository=indexed_repository,
        order=1,
        status=McpWorkItemRepoTask.Status.COMPLETED,
        branch_name="feat/feishu-bug-99-login-timeout",
        target_branch=indexed_repository.default_branch,
        task_body=task_body,
        commit_sha="b" * 40,
        mr_url="https://example.com/mr/login-timeout",
        result={"tests": ["pytest tests/test_session.py -q"]},
        recovery_state={"retryable": False},
    )
    return plan


def _golden_case(
    project,
    *,
    title: str,
    problem: str,
    root_cause: str,
    solution: str,
    repositories: list[str],
    files: list[str],
    symbols: list[str],
    work_item_id: int,
) -> McpLearningCase:
    """内容判然不同的 golden case 行（含 context 锚料，space→project 供权限闸）。"""
    run = create_interaction_run(
        token_fingerprint=hash_token(f"golden-{uuid.uuid4().hex[:8]}"),
        source="mcp",
    )
    context = McpWorkItemContext.objects.create(
        run=run,
        space=project,
        feishu_project_key=project.feishu_project_key,
        work_item_type="bug",
        work_item_id=work_item_id,
        name=title,
        status=McpWorkItemContext.Status.COMPLETED,
        work_item_status="done",
        description=problem,
    )
    embedding_text = "\n".join(
        [
            title,
            problem,
            root_cause,
            solution,
            "merged",
            " ".join(repositories),
            " ".join(files),
            " ".join(symbols),
        ]
    )
    return McpLearningCase.objects.create(
        run=run,
        context=context,
        work_item_type="bug",
        work_item_id=work_item_id,
        title=title,
        problem=problem,
        root_cause=root_cause,
        solution=solution,
        outcome="merged",
        repositories=repositories,
        files=files,
        symbols=symbols,
        embedding_text=embedding_text,
    )


def _ingest_case(case: McpLearningCase) -> None:
    """真实 ingest 全链路同步补摄（PG 实体/版本 + 内存 Qdrant 向量点）。"""
    assert (
        async_to_sync(ingest)(IngestionRequest("learning_case", str(case.id), "golden_seed")) >= 1
    )


def _seed_golden_cases(project) -> dict[str, McpLearningCase]:
    """5 条内容判然不同的 case（top-3 断言有区分度），全部真实入图。"""
    specs = {
        "login": dict(
            title="登录超时 Bug 修复",
            problem="登录超时后错误提示不清晰，token 刷新边界遗漏。",
            root_cause="session token 过期边界判断遗漏",
            solution="统一刷新 token 后再显示超时提示。",
            repositories=["auth-service"],
            files=["src/auth/session.py", "tests/test_session.py"],
            symbols=["refresh_session"],
            work_item_id=101,
        ),
        "payment": dict(
            title="支付回调重试风暴治理",
            problem="支付回调重复重试导致订单重复入账。",
            root_cause="回调幂等键缺失",
            solution="按订单号加幂等锁，重试指数退避。",
            repositories=["payments-service"],
            files=["src/payment/callback.py"],
            symbols=["retry_callback"],
            work_item_id=102,
        ),
        "frontend": dict(
            title="前端构建内存溢出排查",
            problem="vite 构建在 CI 内存溢出失败。",
            root_cause="sourcemap 全量生成占用过高",
            solution="CI 关闭 sourcemap 并拆分 chunk。",
            repositories=["web-console"],
            files=["web/vite.config.ts"],
            symbols=["defineConfig"],
            work_item_id=103,
        ),
        "database": dict(
            title="订单列表慢查询优化",
            problem="订单列表接口慢查询，缺组合索引。",
            root_cause="按状态+时间过滤无索引全表扫",
            solution="加 (status, created_at) 组合索引。",
            repositories=["orders-service"],
            files=["src/orders/queries.py"],
            symbols=["list_orders"],
            work_item_id=104,
        ),
        "push": dict(
            title="消息推送偶发丢失排查",
            problem="webpush 推送偶发丢失，订阅过期未清理。",
            root_cause="过期订阅未剔除导致批量发送中断",
            solution="发送前清理过期订阅并逐条容错。",
            repositories=["notify-service"],
            files=["src/notify/push.py"],
            symbols=["send_push"],
            work_item_id=105,
        ),
    }
    cases = {key: _golden_case(project, **spec) for key, spec in specs.items()}
    for case in cases.values():
        _ingest_case(case)
    return cases


def _search(client: APIClient, payload: dict) -> dict:
    response = client.post(_SEARCH_URL, payload, format="json")
    assert response.status_code == 200
    return response.json()


def _rank(body: dict, case_id: str) -> int:
    """case 在 results 中的排名（0-based）；未命中返回 len(results)（最差名次）。"""
    ids = [item["case_id"] for item in body["results"]]
    return ids.index(case_id) if case_id in ids else len(ids)


# ============================================================================
# 既有用例适配（向量路径）
# ============================================================================


def test_create_and_search_learning_case_from_technical_plan(
    golden_vector_stack,
    mcp_client: tuple[APIClient, str],
    project,
    project_memberships,
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client
    plan = _technical_plan(project, indexed_repository)

    create_response = client.post(
        "/api/mcp/tools/create_learning_case/",
        {
            "technical_plan_id": str(plan.id),
            "outcome": "merged",
            "root_cause": "session token 过期边界判断遗漏",
            "solution_notes": "统一刷新 token 后再显示超时提示。",
            "tests": ["pytest tests/test_session.py -q"],
        },
        format="json",
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["case"]["outcome"] == "merged"
    assert "src/auth/session.py" in created["case"]["files"]
    assert McpLearningCase.objects.get(id=created["learning_case_id"]).tool_call_id is not None

    # create hook（100-02）走 on_commit+后台线程；测试内直接同步补摄避免竞态。
    _ingest_case(McpLearningCase.objects.get(id=created["learning_case_id"]))

    body = _search(
        client,
        {
            "query": "登录超时 token 刷新",
            "work_item_type": "bug",
            "repo_hints": [indexed_repository.name],
            "file_hints": ["src/auth/session.py"],
        },
    )

    assert body["total"] == 1
    assert body["results"][0]["case_id"] == created["learning_case_id"]
    assert body["results"][0]["score"] > 0


def test_create_feishu_technical_plan_auto_includes_similar_learning_case(
    golden_vector_stack,
    mcp_client: tuple[APIClient, str],
    project,
    project_memberships,
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    plan = _technical_plan(project, indexed_repository)
    create_response = client.post(
        "/api/mcp/tools/create_learning_case/",
        {
            "technical_plan_id": str(plan.id),
            "outcome": "merged",
            "root_cause": "session token 过期边界判断遗漏",
            "solution_notes": "统一刷新 token 后再显示超时提示。",
        },
        format="json",
    )
    assert create_response.status_code == 200
    # 自动召回走向量路径：先把创建的 case 同步补摄入图。
    _ingest_case(McpLearningCase.objects.get(id=create_response.json()["learning_case_id"]))
    new_context = _context(project, name="登录超时相似 Bug")

    # UNIFY-03：方案生成 delegate 到统一编排——monkeypatch delegate 返回 DONE（确定性，不触发
    # 真实编排）；学习案例自动召回（search_learning_cases）独立于 delegate，落 evidence + artifact。
    from mcp_tools.orchestration_delegate import DelegateResult

    async def _fake_delegate(**_kwargs: object) -> DelegateResult:
        return DelegateResult(
            session=type("S", (), {"id": "00000000-0000-0000-0000-000000000001"})(),
            status="completed",
            content={
                "title": "登录超时相似 Bug 技术方案",
                "summary": "复用既有 token 刷新边界修复经验。",
                "execution_plan": [
                    {
                        "id": "t1",
                        "name": "修复刷新边界",
                        "repository_id": str(indexed_repository.id),
                        "repository_name": indexed_repository.name,
                        "branch_strategy": "feature",
                    }
                ],
            },
            plan_version_id="00000000-0000-0000-0000-000000000002",
            markdown="**登录超时相似 Bug 技术方案**",
        )

    monkeypatch.setattr("mcp_tools.technical_plan_service.delegate_process_runtime", _fake_delegate)

    response = client.post(
        "/api/mcp/tools/create_feishu_technical_plan/",
        {
            "context_id": str(new_context.id),
            "repository_ids": [str(indexed_repository.id)],
            "context_chunks": [
                {
                    "chunk_id": "chunk-login",
                    "repository_id": str(indexed_repository.id),
                    "file_path": "src/auth/session.py",
                    "content": "def refresh_session(): ...",
                }
            ],
            "create_document": False,
            "write_comment": False,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    # 相似学习案例经召回落 evidence（learning_case 源），不再内联 canonical plan content。
    learning_evidence = [item for item in body["evidence"] if item.get("source") == "learning_case"]
    assert learning_evidence
    assert learning_evidence[0]["title"] == "登录超时 Bug 技术方案"


# ============================================================================
# golden set 对照测试（KNOW-02 验收门）
# ============================================================================


def test_golden_chinese_query_recalls_target_top3(
    golden_vector_stack,
    mcp_client: tuple[APIClient, str],
    project,
    project_memberships,
) -> None:
    """中文问题描述 query：目标 case top-3 + payload 契约 + 双工具召回 + 观测断言。"""
    from interactions.models import RetrievalTrace, ToolCallRecord
    from system.metric_sink import flush_now
    from system.models import RequestMetric

    client, _plaintext = mcp_client
    cases = _seed_golden_cases(project)
    target_id = str(cases["login"].id)

    body = _search(client, {"query": "登录超时 token 刷新", "limit": 5})

    assert body["results"], "golden set 中文查询召回集合不得为空"
    assert _rank(body, target_id) < 3

    # 契约：payload 外形键集 == learning_case_payload 全键集；score 为 0-1 浮点。
    for item in body["results"]:
        assert set(item.keys()) == _PAYLOAD_KEYS
        assert isinstance(item["score"], float)
        assert 0.0 <= item["score"] <= 1.0

    # ROADMAP criterion 1：同一 query 经 search_delivery_knowledge
    # （entity_kinds=["learning_case"]）也可召回同一 case（统一向量排序双入口收口）。
    delivery_response = client.post(
        "/api/mcp/tools/search_delivery_knowledge/",
        {"query": "登录超时 token 刷新", "entity_kinds": ["learning_case"], "top_k": 5},
        format="json",
    )
    assert delivery_response.status_code == 200
    delivery_body = delivery_response.json()
    assert delivery_body["results"]
    assert all(item["kind"] == "learning_case" for item in delivery_body["results"])
    assert cases["login"].title in [item["title"] for item in delivery_body["results"][:3]]

    # ROADMAP criterion 5（MCP 链）：每条命中一行 FILE trace（source/case_id/score）。
    traces = [
        trace
        for trace in RetrievalTrace.objects.filter(kind=RetrievalTrace.Kind.FILE)
        if trace.payload.get("source") == "learning_case"
    ]
    trace_case_ids = {trace.payload.get("case_id") for trace in traces}
    for item in body["results"]:
        assert item["case_id"] in trace_case_ids
    for trace in traces:
        assert "score" in trace.payload

    # ToolCallRecord / RequestMetric（召回条数/耗时可查，duration_ms 非负）。
    tool_call = (
        ToolCallRecord.objects.filter(tool_name="search_learning_cases")
        .order_by("-created_at")
        .first()
    )
    assert tool_call is not None
    assert tool_call.duration_ms >= 0
    flush_now()  # 指标经内存队列批量落库，测试钩子同步 flush
    metric = RequestMetric.objects.filter(route="mcp:search_learning_cases").first()
    assert metric is not None
    assert (metric.duration_ms or 0) >= 0


def test_golden_path_query_hint_boosts_target(
    golden_vector_stack,
    mcp_client: tuple[APIClient, str],
    project,
    project_memberships,
) -> None:
    """路径类 query：file_hints 增强+提权生效（有 hint 排名不劣于无 hint 且 top-3）。"""
    client, _plaintext = mcp_client
    cases = _seed_golden_cases(project)
    target_id = str(cases["login"].id)

    without_hint = _search(client, {"query": "线上 问题 修复", "limit": 5})
    with_hint = _search(
        client,
        {
            "query": "线上 问题 修复",
            "file_hints": ["src/auth/session.py"],
            "limit": 5,
        },
    )

    assert _rank(with_hint, target_id) < 3
    assert _rank(with_hint, target_id) <= _rank(without_hint, target_id)


def test_golden_symbol_query_hint_boosts_target(
    golden_vector_stack,
    mcp_client: tuple[APIClient, str],
    project,
    project_memberships,
) -> None:
    """symbol 类 query：symbol_hints 命中造数 symbols 字段，目标 case top-3。"""
    client, _plaintext = mcp_client
    cases = _seed_golden_cases(project)
    target_id = str(cases["payment"].id)

    without_hint = _search(client, {"query": "重复 处理", "limit": 5})
    with_hint = _search(
        client,
        {
            "query": "重复 处理",
            "symbol_hints": ["retry_callback"],
            "limit": 5,
        },
    )

    assert _rank(with_hint, target_id) < 3
    assert _rank(with_hint, target_id) <= _rank(without_hint, target_id)


# ============================================================================
# fail-soft（Qdrant 故障不 500）
# ============================================================================


def test_search_fail_soft_returns_empty_not_500(
    mcp_client: tuple[APIClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client

    async def _boom(self, *args, **kwargs):
        raise RuntimeError("qdrant unreachable")

    monkeypatch.setattr("knowledge.retrieval.DeliveryKnowledgeSearchService.search_similar", _boom)

    response = client.post(_SEARCH_URL, {"query": "任意问题"}, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert body["total"] == 0
