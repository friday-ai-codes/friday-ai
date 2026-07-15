"""backfill_learning_cases 回填命令守护测试（Phase 100 / KNOW-02，P1 防线）。

断言（test_rebuild_project_context.py 范式）：

- 命令对每个 McpLearningCase / McpCodingPlan / McpRepositoryAnalysis /
  McpCodingExecutionTrace 各调度一次 ``aschedule_ingestion``（source_kind/source_id/
  trigger 正确）；
- ``--only`` 只投递指定类（可重复传入）；
- 重复执行两次投递集合相同（命令层幂等——真正的内容幂等由 ingest content_hash
  短路兜底，已在 100-02/03 断言）；
- 命令源码不含任何整库删除入口（A5 静态守护，镜像 rebuild_project_context 同款）。

mock ``aschedule_ingestion``（normalize/embedding/Qdrant 全不触发），``--disable-socket``
第二道保险。
"""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from django.core.management import call_command

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


def _delivered(mock_schedule: AsyncMock) -> list[tuple[str, str, str]]:
    return sorted(
        (
            call.args[0].source_kind,
            call.args[0].source_id,
            call.args[0].trigger,
        )
        for call in mock_schedule.await_args_list
    )


def test_backfill_schedules_all_four_kinds() -> None:
    expected = _seed()

    mock_schedule = AsyncMock()
    with patch.object(cmd_mod, "aschedule_ingestion", mock_schedule):
        call_command("backfill_learning_cases")

    delivered = _delivered(mock_schedule)
    assert delivered == sorted(
        (kind, source_id, "backfill_learning_cases")
        for kind, source_ids in expected.items()
        for source_id in source_ids
    )
    assert mock_schedule.await_count == 5  # 2 case + 1 plan + 1 analysis + 1 trace


def test_backfill_only_filters_kinds() -> None:
    expected = _seed()

    mock_schedule = AsyncMock()
    with patch.object(cmd_mod, "aschedule_ingestion", mock_schedule):
        call_command("backfill_learning_cases", "--only", "learning_case")

    delivered = _delivered(mock_schedule)
    assert delivered == [
        ("learning_case", source_id, "backfill_learning_cases")
        for source_id in expected["learning_case"]
    ]


def test_backfill_only_repeatable() -> None:
    expected = _seed()

    mock_schedule = AsyncMock()
    with patch.object(cmd_mod, "aschedule_ingestion", mock_schedule):
        call_command(
            "backfill_learning_cases",
            "--only",
            "learning_case",
            "--only",
            "mcp_coding_plan",
        )

    kinds = {kind for kind, _sid, _trigger in _delivered(mock_schedule)}
    assert kinds == {"learning_case", "mcp_coding_plan"}
    assert mock_schedule.await_count == len(expected["learning_case"]) + len(
        expected["mcp_coding_plan"]
    )


def test_backfill_delivery_set_stable_across_runs() -> None:
    """重复执行投递集合相同（命令层幂等，内容幂等由 ingest content_hash 兜底）。"""
    _seed()

    first_mock = AsyncMock()
    with patch.object(cmd_mod, "aschedule_ingestion", first_mock):
        call_command("backfill_learning_cases")
    second_mock = AsyncMock()
    with patch.object(cmd_mod, "aschedule_ingestion", second_mock):
        call_command("backfill_learning_cases")

    assert _delivered(first_mock) == _delivered(second_mock)


def test_backfill_command_never_deletes_collection() -> None:
    """静态守护：命令源码不含整库删除入口（绝不连带删其他来源，A5）。"""
    source = inspect.getsource(cmd_mod)
    assert "delete_collection" not in source
    assert "rebuild_delivery_knowledge" not in source
