"""backfill_learning_cases 回填命令守护测试（Phase 100 / KNOW-02，P1 防线）。

断言（code review HI-02 修复后语义——命令内**同步**逐条 ``ingest``，不经后台投递）：

- 命令对每个 McpLearningCase / McpCodingPlan / McpRepositoryAnalysis /
  McpCodingExecutionTrace 各同步执行一次 ``ingest``（source_kind/source_id/
  trigger 正确，await 在 handle() 返回前完成——daemon 线程投递会被进程退出杀死）；
- 端到端：真跑 ingest（mock 向量栈）→ 命令返回时 KnowledgeEntity 已落库
  （证伪「已调度但从未执行」的旧缺陷）；
- 单条失败计数不中断，其余条目照常摄取；
- ``--only`` 只处理指定类（可重复传入）；
- 重复执行两次处理集合相同（命令层幂等——真正的内容幂等由 ingest content_hash
  短路兜底，已在 100-02/03 断言）；
- 命令源码不含任何整库删除入口（A5 静态守护，镜像 rebuild_project_context 同款）。

集合类断言 mock ``ingest``（normalize/embedding/Qdrant 全不触发）；端到端用例
mock 向量栈真跑摄取；``--disable-socket`` 第二道保险。
"""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from django.core.management import call_command
from structlog.testing import capture_logs

from knowledge.management.commands import backfill_learning_cases as cmd_mod

# SQLite + async（asyncio.run 内 async ORM 跨线程）需要 transaction=True（knowledge 域同款纪律）。
pytestmark = pytest.mark.django_db(transaction=True)


# ============================================================================
# 同步工厂（test_mcp_artifact_sources.py 同款最小闭包）
# ============================================================================


def _make_repo():
    from repositories.models import Repository

    suffix = uuid.uuid4().hex[:8]
    return Repository.objects.create(
        name=f"backfill-repo-{suffix}",
        git_url=f"https://gitlab.com/test/backfill-{suffix}.git",
        git_platform="gitlab",
        default_branch="main",
    )


def _make_run():
    from interactions.ledger import create_interaction_run
    from runners.models import hash_token

    return create_interaction_run(
        token_fingerprint=hash_token(f"backfill-{uuid.uuid4().hex[:8]}"),
        source="mcp",
    )


def _make_learning_case(run=None):
    from mcp_tools.models import McpLearningCase

    return McpLearningCase.objects.create(
        run=run or _make_run(),
        title=f"回填案例-{uuid.uuid4().hex[:8]}",
        problem="登录超时提示不清晰",
        embedding_text="登录超时 token 刷新",
    )


def _make_plan(repo=None, run=None):
    from mcp_tools.models import McpCodingPlan, McpCodingPlanVersion

    repo = repo or _make_repo()
    run = run or _make_run()
    plan = McpCodingPlan.objects.create(
        run=run,
        repository=repo,
        branch="main",
        requirement="修复登录超时",
        title="登录修复 MCP 方案",
        current_version=1,
    )
    version = McpCodingPlanVersion.objects.create(
        plan=plan,
        run=run,
        version=1,
        plan_body={"title": plan.title},
        affected_files=["src/auth.py"],
        steps=["排查超时根因"],
        test_plan=["pytest tests/auth"],
        risks=[],
        evidence=[],
        change_summary="Initial",
        risk_delta={"added": [], "reduced": []},
    )
    return plan, version


def _make_analysis(repo=None, run=None):
    from mcp_tools.models import McpRepositoryAnalysis

    return McpRepositoryAnalysis.objects.create(
        run=run or _make_run(),
        repository=repo or _make_repo(),
        branch="main",
        focus="认证入口",
        summary={"architecture_summary": "分层架构。"},
        evidence=[],
    )


def _make_trace(plan, version):
    from mcp_tools.models import McpCodingExecutionTrace

    return McpCodingExecutionTrace.objects.create(
        run=plan.run,
        plan=plan,
        plan_version=version,
        repository=plan.repository,
        status=McpCodingExecutionTrace.Status.COMPLETED,
        branch_name="feat/backfill",
        target_branch="main",
    )


def _seed() -> dict[str, list[str]]:
    """造四类存量各若干行，返回 source_kind → 期望 source_id 列表。"""
    repo = _make_repo()
    run = _make_run()
    cases = [_make_learning_case(run), _make_learning_case(run)]
    plan, version = _make_plan(repo, run)
    analysis = _make_analysis(repo, run)
    trace = _make_trace(plan, version)
    return {
        "learning_case": sorted(str(case.id) for case in cases),
        "mcp_coding_plan": [str(plan.id)],
        "mcp_repository_analysis": [str(analysis.id)],
        "mcp_execution_trace": [str(trace.id)],
    }


def _delivered(mock_ingest: AsyncMock) -> list[tuple[str, str, str]]:
    return sorted(
        (
            call.args[0].source_kind,
            call.args[0].source_id,
            call.args[0].trigger,
        )
        for call in mock_ingest.await_args_list
    )


def test_backfill_ingests_all_four_kinds_synchronously() -> None:
    """每条存量各同步 await 一次 ingest（handle() 返回即全部执行完，非后台投递）。"""
    expected = _seed()

    mock_ingest = AsyncMock(return_value=1)
    with patch.object(cmd_mod, "ingest", mock_ingest):
        call_command("backfill_learning_cases")

    delivered = _delivered(mock_ingest)
    assert delivered == sorted(
        (kind, source_id, "backfill_learning_cases")
        for kind, source_ids in expected.items()
        for source_id in source_ids
    )
    assert mock_ingest.await_count == 5  # 2 case + 1 plan + 1 analysis + 1 trace


def test_backfill_end_to_end_entities_persisted_before_command_returns(
    monkeypatch: pytest.MonkeyPatch,
    mock_embedding,
    mock_qdrant_client,
) -> None:
    """真跑 ingest（mock 向量栈）：命令返回时 learning_case 实体已落库。

    HI-02 回归防线：旧实现经 aschedule_ingestion 投递 daemon 线程后进程退出，
    摄取根本不执行——「已调度 N 条」是假完成信号。同步执行后命令返回即入图。
    """
    from io import StringIO

    from knowledge.models import KnowledgeEntity
    from services.qdrant_service import QdrantService

    monkeypatch.setattr("knowledge.ingestion.ensure_delivery_knowledge_collection", AsyncMock())
    monkeypatch.setattr(
        QdrantService, "upsert_vectors_by_name", classmethod(lambda cls, name, pts: True)
    )

    case = _make_learning_case()
    stdout = StringIO()

    call_command("backfill_learning_cases", "--only", "learning_case", stdout=stdout)

    entity = KnowledgeEntity.objects.get(source_kind="learning_case", source_id=str(case.id))
    assert entity.kind == "learning_case"
    assert "已摄取 1 条、失败 0 条" in stdout.getvalue()


def test_backfill_counts_failures_and_continues() -> None:
    """单条 ingest 失败：warning + failed 计数，其余条目照常摄取，命令不中断。"""
    from io import StringIO

    expected = _seed()
    poison_id = expected["learning_case"][0]

    async def _ingest(request):
        if request.source_id == poison_id:
            raise RuntimeError("embedding 服务不可用")
        return 1

    stdout = StringIO()
    with patch.object(cmd_mod, "ingest", AsyncMock(side_effect=_ingest)) as mock_ingest:
        with capture_logs() as cap:
            call_command("backfill_learning_cases", stdout=stdout)

    # 失败条目之后的条目仍被处理（5 条全部尝试）
    assert mock_ingest.await_count == 5
    failures = [e for e in cap if e.get("event") == "backfill_ingest_failed"]
    assert len(failures) == 1
    assert failures[0]["source_id"] == poison_id
    assert "已摄取 4 条、失败 1 条" in stdout.getvalue()


def test_backfill_only_filters_kinds() -> None:
    expected = _seed()

    mock_ingest = AsyncMock(return_value=1)
    with patch.object(cmd_mod, "ingest", mock_ingest):
        call_command("backfill_learning_cases", "--only", "learning_case")

    delivered = _delivered(mock_ingest)
    assert delivered == [
        ("learning_case", source_id, "backfill_learning_cases")
        for source_id in expected["learning_case"]
    ]


def test_backfill_only_repeatable() -> None:
    expected = _seed()

    mock_ingest = AsyncMock(return_value=1)
    with patch.object(cmd_mod, "ingest", mock_ingest):
        call_command(
            "backfill_learning_cases",
            "--only",
            "learning_case",
            "--only",
            "mcp_coding_plan",
        )

    kinds = {kind for kind, _sid, _trigger in _delivered(mock_ingest)}
    assert kinds == {"learning_case", "mcp_coding_plan"}
    assert mock_ingest.await_count == len(expected["learning_case"]) + len(
        expected["mcp_coding_plan"]
    )


def test_backfill_delivery_set_stable_across_runs() -> None:
    """重复执行处理集合相同（命令层幂等，内容幂等由 ingest content_hash 兜底）。"""
    _seed()

    first_mock = AsyncMock(return_value=1)
    with patch.object(cmd_mod, "ingest", first_mock):
        call_command("backfill_learning_cases")
    second_mock = AsyncMock(return_value=1)
    with patch.object(cmd_mod, "ingest", second_mock):
        call_command("backfill_learning_cases")

    assert _delivered(first_mock) == _delivered(second_mock)


def test_backfill_command_never_deletes_collection() -> None:
    """静态守护：命令源码不含整库删除入口（绝不连带删其他来源，A5）。"""
    source = inspect.getsource(cmd_mod)
    assert "delete_collection" not in source
    assert "rebuild_delivery_knowledge" not in source
