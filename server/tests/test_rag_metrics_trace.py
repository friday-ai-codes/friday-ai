"""召回可观测守护测试（RAG-01 / RAG-02）。

覆盖：
- Task 1（RAG-01）：``search_rag`` 出口落召回指标 —— 召回条数 + 分层耗时
  （embedding/sparse/qdrant/rerank）+ top score，按来源（call_source）区分；error
  早退记 ``rag_status``；指标 best-effort 不反噬召回（zero-drift 行为契约保持）。
- Task 2（RAG-02）：``record_retrieval_trace`` helper 增强（run 可空 +
  user/conversation/source 默认从 contextvars 透传 + payload 脱敏）；chat 召回工具
  ``search_repository_code`` 按 top-N 采样写 RetrievalTrace（覆盖 AI 对话链）；
  留痕 best-effort 不反噬工具返回。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from system import metric_sink


@pytest.fixture(autouse=True)
def _reset_metric_sink():
    """每个用例前后清空指标队列 + 计数（隔离）。"""
    metric_sink._reset_for_tests()
    yield
    metric_sink._reset_for_tests()


# ============================================================================
# Task 1: search_rag 召回指标
# ============================================================================


def _setup_rag_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    results: list[dict],
    embedding: object = (0.1, 0.2),
) -> None:
    """统一 mock search_rag 内懒加载的各阶段依赖，使其纯内存可控返回。"""
    import services.branch_search as branch_mod
    import services.embedding as emb_mod
    import services.retrieval.rag_search as rag_mod
    import services.retrieval.rerank as rerank_mod
    import services.sparse_encoder as sparse_mod

    async def _fake_embed(query: str) -> object:
        return list(embedding) if embedding else embedding

    def _fake_encode(query: str) -> dict:
        return {"indices": [1], "values": [0.5]}

    async def _fake_search(
        repo_id: str,
        query_dense: object,
        *,
        query_sparse: object = None,
        branch_name: object = None,
        top_k: int = 30,
    ) -> list[dict]:
        return results

    class _FakePlan:
        mode = "off"
        fetch_k = 30

    async def _fake_plan() -> _FakePlan:
        return _FakePlan()

    async def _fake_reorder(query, all_results, *, top_k, plan, out_meta):  # noqa: ANN001
        return all_results[:top_k]

    class _AllowMatcher:
        def is_excluded(self, path: str) -> bool:
            return False

    async def _fake_matcher(repo_id: str) -> _AllowMatcher:
        return _AllowMatcher()

    monkeypatch.setattr(
        emb_mod.EmbeddingService, "generate_embedding", staticmethod(_fake_embed)
    )
    monkeypatch.setattr(
        sparse_mod.SparseEncoderService, "encode", staticmethod(_fake_encode)
    )
    monkeypatch.setattr(
        branch_mod.BranchAwareSearchService, "search", staticmethod(_fake_search)
    )
    monkeypatch.setattr(rerank_mod, "get_rerank_plan", _fake_plan)
    monkeypatch.setattr(rerank_mod, "reorder", _fake_reorder)
    monkeypatch.setattr(rag_mod, "build_matcher_for_repo", _fake_matcher)


def _rag_results(n: int) -> list[dict]:
    """构造 n 条命中（score 降序，含 payload）。"""
    return [
        {
            "payload": {"file_path": f"f{i}.py", "chunk_index": 0, "content": f"c{i}"},
            "score": round(0.9 - i * 0.05, 4),
        }
        for i in range(n)
    ]


# transaction=True：async 测试经 sync_to_async 在独立连接写 RequestMetric/RetrievalTrace，
# 普通 django_db 事务回滚兜不住跨连接提交，必须用 TransactionTestCase 语义在 teardown
# truncate，杜绝行泄漏污染其他测试文件（如 test_request_metric 的 count==0 断言）。
@pytest.mark.django_db(transaction=True)
class TestRagSearchMetric:
    async def test_records_recall_count_stages_and_top_score(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.retrieval.rag_search import search_rag
        from system.models import RequestMetric

        _setup_rag_mocks(monkeypatch, results=_rag_results(3))

        snap = await search_rag("q", repo_ids=["r1"], top_k=30)
        assert snap.status == "ok"
        assert snap.result_count == 3

        await sync_to_async(metric_sink.flush_now)()
        row = await sync_to_async(
            lambda: RequestMetric.objects.filter(source="rag").order_by("-id").first()
        )()
        assert row is not None
        assert row.source == "rag"
        assert row.route == "search_rag"
        assert row.method == "RAG"
        labels = row.labels
        assert labels.get("recall_count") == 3
        assert labels.get("top_score") == 0.9
        for key in (
            "stage_embedding_ms",
            "stage_sparse_ms",
            "stage_qdrant_ms",
            "stage_rerank_ms",
        ):
            assert key in labels
            assert labels[key] >= 0

    async def test_call_source_distinguishes_origin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agents.call_source import use_call_source
        from services.retrieval.rag_search import search_rag
        from system.models import RequestMetric

        _setup_rag_mocks(monkeypatch, results=_rag_results(2))

        with use_call_source("chat"):
            await search_rag("q", repo_ids=["r1"], top_k=30)

        await sync_to_async(metric_sink.flush_now)()
        row = await sync_to_async(
            lambda: RequestMetric.objects.filter(source="rag").order_by("-id").first()
        )()
        assert row is not None
        assert row.labels.get("call_source") == "chat"

    async def test_embedding_failure_records_error_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.retrieval.rag_search import search_rag
        from system.models import RequestMetric

        # embedding 返回空 → 早退 status="error"
        _setup_rag_mocks(monkeypatch, results=_rag_results(3), embedding=[])

        snap = await search_rag("q", repo_ids=["r1"], top_k=30)
        assert snap.status == "error"

        await sync_to_async(metric_sink.flush_now)()
        row = await sync_to_async(
            lambda: RequestMetric.objects.filter(source="rag").order_by("-id").first()
        )()
        assert row is not None
        assert row.labels.get("rag_status") == "error"
        assert row.labels.get("recall_count") == 0
        assert row.error_class == "system"

    async def test_metric_write_failure_best_effort(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import common.request_metrics as rm
        from services.retrieval.rag_search import search_rag

        _setup_rag_mocks(monkeypatch, results=_rag_results(3))

        def _boom(**kwargs: object) -> None:
            raise RuntimeError("metric down")

        monkeypatch.setattr(rm, "record_request_metric", _boom)

        # 指标写入抛错也绝不影响召回返回（best-effort + zero-drift）。
        snap = await search_rag("q", repo_ids=["r1"], top_k=30)
        assert snap.status == "ok"
        assert len(snap.items) == 3


# ============================================================================
# Task 2: RetrievalTrace 留痕（MCP + AI 对话两条链）
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestRetrievalTraceLedger:
    async def test_arecord_trace_run_none_contextvars_and_redaction(self) -> None:
        import structlog

        from interactions.ledger import arecord_retrieval_trace
        from interactions.models import RetrievalTrace

        plaintext = "friday_pat_" + "A" * 32
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(user_id="42", source="chat")
        try:
            trace = await arecord_retrieval_trace(
                run=None,
                kind=RetrievalTrace.Kind.CHUNK,
                conversation_id="c1",
                payload={"query": "q", "chunk": f"k={plaintext}", "score": 0.9},
            )
        finally:
            structlog.contextvars.clear_contextvars()

        assert trace is not None
        await sync_to_async(trace.refresh_from_db)()
        assert trace.user_id == "42"
        assert trace.conversation_id == "c1"
        assert trace.source == "chat"
        assert trace.run_id is None
        assert plaintext not in str(trace.payload)


def _setup_search_repository_mocks(
    monkeypatch: pytest.MonkeyPatch, *, n_hits: int
) -> None:
    """mock search_repository_code 内懒加载的 provider / HybridSearchService /
    排除过滤，使其返回 n_hits 条命中。"""
    import agents.tools.space_tools as space_mod
    import services.code_intel as code_intel_mod
    import services.retrieval as retrieval_mod
    from repositories.models import Repository
    from services.retrieval.types import LayerSnapshot

    class _FakeResult:
        def __init__(self) -> None:
            items = [
                {
                    "payload": {
                        "file_path": f"f{i}.py",
                        "content": f"content-{i}",
                        "language": "py",
                    },
                    "score": 0.9,
                    "repository_id": "r1",
                }
                for i in range(n_hits)
            ]
            self.layers = [
                LayerSnapshot(
                    layer="L3", status="ok", result_count=n_hits, items=items
                )
            ]
            self.final_context = "ctx"

    class _FakeHybrid:
        def __init__(self, provider: object) -> None:
            pass

        async def search(self, query, *, repository_ids=None, branch_name=None, top_k=20):  # noqa: ANN001
            return _FakeResult()

    class _AllowMatcher:
        def is_excluded(self, path: str) -> bool:
            return False

    async def _fake_matcher(repo_id: str) -> _AllowMatcher:
        return _AllowMatcher()

    # mock 仓库存在性校验（避免 sync fixture 行与 async ORM 跨连接的 SQLite 锁）。
    async def _fake_aget(*args: object, **kwargs: object) -> object:
        return object()

    monkeypatch.setattr(code_intel_mod, "get_provider", lambda: None)
    monkeypatch.setattr(retrieval_mod, "HybridSearchService", _FakeHybrid)
    monkeypatch.setattr(space_mod, "build_matcher_for_repo", _fake_matcher)
    monkeypatch.setattr(Repository.objects, "aget", _fake_aget)


@pytest.mark.django_db(transaction=True)
class TestChatChainRetrievalTrace:
    async def test_search_repository_code_writes_sampled_traces(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import uuid

        from agents.tools.space_tools import search_repository_code
        from interactions.models import RetrievalTrace

        # 12 条命中 → 采样上限 10 生效（§A.4 基数控制）。
        _setup_search_repository_mocks(monkeypatch, n_hits=12)

        result = await search_repository_code(
            query="UserService",
            repository_id=str(uuid.uuid4()),
            conversation_id="conv-1",
        )
        assert result.success

        count = await sync_to_async(
            lambda: RetrievalTrace.objects.filter(conversation_id="conv-1").count()
        )()
        assert count == 10  # top-N 采样上限

        first = await sync_to_async(
            lambda: RetrievalTrace.objects.filter(conversation_id="conv-1")
            .order_by("seq")
            .first()
        )()
        assert first is not None
        assert first.kind == RetrievalTrace.Kind.CHUNK
        assert "query" in first.payload
        assert "chunk" in first.payload

    async def test_trace_write_failure_does_not_break_tool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import uuid

        import interactions.ledger as ledger_mod
        from agents.tools.space_tools import search_repository_code

        _setup_search_repository_mocks(monkeypatch, n_hits=3)

        async def _boom(*args: object, **kwargs: object) -> object:
            raise RuntimeError("ledger down")

        monkeypatch.setattr(ledger_mod, "arecord_retrieval_trace", _boom)

        # 留痕写入抛错也绝不影响工具返回（best-effort）。
        result = await search_repository_code(
            query="UserService",
            repository_id=str(uuid.uuid4()),
            conversation_id="conv-2",
        )
        assert result.success
        assert len(result.output["data"]["results"]) == 3
