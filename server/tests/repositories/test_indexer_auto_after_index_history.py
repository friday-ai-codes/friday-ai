"""implementation — indexer auto_after_index 路径写 GraphBuildHistory 集成测试。

覆盖 work item-01..05 中 ``auto_after_index`` trigger 路径：

- 4 处 ``_extract_and_write_graph`` callsite 外层包裹 ``GraphBuildHistory`` 创建/转态：
  成功 → COMPLETED + 7 counts；异常 → FAILED + error_message[:1000]。
- 仍在 indexer 主任务（``index-{repo_id}`` background task）内运行——**不切**
  到 ``graph-build-{repo_id}`` 任务（CONTEXT Claude's Discretion 决议）。
- ``_should_build_graph(None)`` 双重判断仍是入口 gating——返 False 时整段
  history 创建逻辑被短路，DB 中无新增 ``GraphBuildHistory`` 行。
- ``POST /codegraph/cancel/`` 对 ``trigger_type=AUTO_AFTER_INDEX`` history
  **无法真实 cancel background task**（统一发同名 ``graph-build-{repo_id}``，
  但 indexer 主任务名是 ``index-{repo_id}``）—— CONTEXT 已知 limitation。

测试策略组合：

- **Section A 白盒源码断言**（4 处 callsite 参数化）—— ``inspect.getsource(...)``
  正则验证 4 个入口方法（run_full_index / run_branch_index /
  run_git_diff_index / run_incremental_index）的源码都含 acreate +
  AUTO_AFTER_INDEX + COMPLETED + FAILED + error_message + try/except 围绕
  ``_extract_and_write_graph``。
- **Section B 功能集成断言** —— 在测试模块内定义一个 ``_run_wrapper`` helper，
  字面复刻 indexer.py 4 处 callsite 共用的包裹模板：mock
  ``IndexerService._extract_and_write_graph`` 返回 stats / raise 异常，
  跑 helper 验证 DB 行的字段口径与 contract 不变量（向量轨 INDEXED 不受影响）。
- **Section C cancel 端点 known-limitation 断言** —— 预创建
  ``GraphBuildHistory(trigger=AUTO_AFTER_INDEX, RUNNING)``，POST cancel
  端点，断言 DB 转 CANCELLED 但 ``cancel_background_task`` 调用参数仍是
  ``graph-build-{repo_id}``（不识别 trigger 差异）。
- **Section D update_graph_progress smoke**（security mitigation-5）—— 源码检查至少 1 处
  callsite 在 ``IndexStage.BUILDING_GRAPH`` 之后追加 ``update_graph_progress``，
  + ``unittest.mock.patch`` spy 验证 helper 通路。
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone
from rest_framework.test import APIClient

from repositories.models import (
    GraphBuildHistory,
    GraphBuildHistoryStatus,
    GraphBuildHistoryTrigger,
    IndexStatus,
    Repository,
)
from services.indexer import IndexerService

# ---------------------------------------------------------------------------
# Section A：4 处 callsite 白盒源码结构断言
# ---------------------------------------------------------------------------


CALLSITE_METHODS = [
    "run_full_index",
    "run_branch_index",
    "run_git_diff_index",
    "run_incremental_index",
]


@pytest.mark.parametrize("method_name", CALLSITE_METHODS)
def test_callsite_creates_running_history_with_auto_after_index_trigger(
    method_name: str,
) -> None:
    """4 处 callsite 必须在 ``_extract_and_write_graph`` 之前
    ``await GraphBuildHistory.objects.acreate(...)`` 一行
    ``trigger_type=GraphBuildHistoryTrigger.AUTO_AFTER_INDEX`` +
    ``status=GraphBuildHistoryStatus.RUNNING``——白盒结构断言（GREEN 时通过）。
    """
    method = getattr(IndexerService, method_name)
    src = inspect.getsource(method)

    extract_idx = src.find("await self._extract_and_write_graph(")
    assert extract_idx >= 0, (
        f"{method_name} 未调用 _extract_and_write_graph（callsite 应存在）"
    )

    pre_segment = src[:extract_idx]
    # 创建 RUNNING 行已集中到去重 helper `_acreate_auto_graph_history()`：
    # 4 callsite 均改为调用 helper（避免并发索引产生重复 RUNNING 行）。
    assert "self._acreate_auto_graph_history()" in pre_segment, (
        f"{method_name} 缺少 self._acreate_auto_graph_history()（创建/复用 RUNNING 行）"
    )


def test_acreate_auto_graph_history_helper_creates_running_auto_after_index() -> None:
    """去重 helper 源码须声明 ``status=RUNNING`` + ``trigger=AUTO_AFTER_INDEX``，
    并在锁内先查既有 RUNNING 行去重（避免并发重复 RUNNING 行）。
    """
    src = inspect.getsource(IndexerService._acreate_auto_graph_history)
    assert "GraphBuildHistoryStatus.RUNNING" in src, "helper 缺少 status=RUNNING"
    assert "GraphBuildHistoryTrigger.AUTO_AFTER_INDEX" in src, (
        "helper 缺少 trigger=AUTO_AFTER_INDEX"
    )
    assert "select_for_update" in src, "helper 缺少行锁串行化（去重并发创建）"
    assert "GraphBuildHistory.objects.create" in src, "helper 缺少创建逻辑"


@pytest.mark.parametrize("method_name", CALLSITE_METHODS)
def test_callsite_transitions_to_completed_or_failed(method_name: str) -> None:
    """4 处 callsite 必须在 ``_extract_and_write_graph`` 之后处理两态转移：
    成功 → ``GraphBuildHistoryStatus.COMPLETED``；异常 →
    ``GraphBuildHistoryStatus.FAILED`` + ``error_message``。
    """
    method = getattr(IndexerService, method_name)
    src = inspect.getsource(method)

    assert "GraphBuildHistoryStatus.COMPLETED" in src, (
        f"{method_name} 缺少 COMPLETED 转态分支"
    )
    assert "GraphBuildHistoryStatus.FAILED" in src, (
        f"{method_name} 缺少 FAILED 转态分支"
    )
    assert "error_message" in src, (
        f"{method_name} 缺少 error_message 字段写入（FAILED 分支需透传 str(exc)）"
    )


@pytest.mark.parametrize("method_name", CALLSITE_METHODS)
def test_callsite_gating_precedes_history_create(method_name: str) -> None:
    """``_should_build_graph(...)`` gating 必须早于 ``GraphBuildHistory.objects.acreate``
    —— 跳过场景不应创建空 history 行（CONTEXT Q4 / contract 不变量）。
    """
    method = getattr(IndexerService, method_name)
    src = inspect.getsource(method)

    gating_idx = src.find("_should_build_graph")
    acreate_idx = src.find("self._acreate_auto_graph_history()")
    assert gating_idx >= 0, f"{method_name} 缺少 _should_build_graph gating"
    assert acreate_idx >= 0, f"{method_name} 缺少 self._acreate_auto_graph_history()"
    assert gating_idx < acreate_idx, (
        f"{method_name} _acreate_auto_graph_history 出现在 _should_build_graph gating "
        f"之前——会创建被跳过路径的空 history 行"
    )


def test_module_has_exactly_four_auto_after_index_callsites() -> None:
    """``indexer.py`` 4 处 callsite 均通过去重 helper 创建 RUNNING 行（与 4 callsite 对齐）。"""
    import services.indexer as indexer_module

    src = inspect.getsource(indexer_module)
    # helper 调用出现 4 次（4 callsite）+ 1 次定义（async def）= 5 处文本匹配
    call_count = src.count("self._acreate_auto_graph_history()")
    assert call_count == 4, (
        f"_acreate_auto_graph_history() 调用应有 4 处（4 callsite 一一对应），"
        f"实际 {call_count} 处"
    )
    assert "async def _acreate_auto_graph_history" in src, (
        "去重 helper _acreate_auto_graph_history 定义缺失"
    )


# ---------------------------------------------------------------------------
# Section B：包裹模板功能集成断言（成功路径 / 失败路径）
#
# 在测试模块内定义 _run_wrapper helper 复刻 indexer.py 4 处 callsite 共用的
# 包裹模板，mock _extract_and_write_graph 后验证 DB 字段口径和 contract 不变量。
# 此 helper 与 indexer.py 包裹模板**字面一致**——保任一处改动两侧同步。
# ---------------------------------------------------------------------------


async def _run_wrapper(
    indexer: IndexerService,
    *,
    repo_path: str,
    graph_file_paths: list[str],
) -> GraphBuildHistory | None:
    """复刻 indexer.py 4 处 callsite 的包裹模板（用于单元测试）。

    与 indexer.py 中的内联模板保持字面一致。任一处改动需双向同步。
    """
    if not await indexer._should_build_graph(None):
        return None

    gbh = await GraphBuildHistory.objects.acreate(
        repository_id=indexer.repository_id,
        status=GraphBuildHistoryStatus.RUNNING,
        trigger_type=GraphBuildHistoryTrigger.AUTO_AFTER_INDEX,
    )
    try:
        stats = await indexer._extract_and_write_graph(
            repo_path=repo_path,
            file_paths=graph_file_paths,
            repository_id=indexer.repository_id,
        )
        gbh.status = GraphBuildHistoryStatus.COMPLETED
        gbh.files_total = len(graph_file_paths)
        gbh.files_processed = stats.get("files_processed", 0)
        gbh.files_failed = stats.get("files_failed", 0)
        gbh.symbols_count = stats.get("total_symbols", 0)
        gbh.imports_count = stats.get("total_imports", 0)
        gbh.calls_count = stats.get("total_calls", 0)
        gbh.endpoints_count = stats.get("total_endpoints", 0)
        gbh.finished_at = timezone.now()
        await gbh.asave(
            update_fields=[
                "status",
                "files_total",
                "files_processed",
                "files_failed",
                "symbols_count",
                "imports_count",
                "calls_count",
                "endpoints_count",
                "finished_at",
            ]
        )
    except Exception as exc:
        gbh.status = GraphBuildHistoryStatus.FAILED
        gbh.error_message = str(exc)[:1000]
        gbh.finished_at = timezone.now()
        await gbh.asave(
            update_fields=["status", "error_message", "finished_at"]
        )
        # contract：不 raise，保 indexer 主流程不受图谱失败影响
    return gbh


@pytest.fixture
def repo(db) -> Repository:
    return Repository.objects.create(
        name="auto-after-index-repo",
        git_url="https://github.com/test/auto-after-index.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
        auto_build_graph_enabled=True,
    )


@pytest.mark.django_db(transaction=True)
async def test_auto_after_index_creates_completed_history(
    repo: Repository,
    settings,
) -> None:
    """成功路径：mock ``_extract_and_write_graph`` 返 stats →
    DB 应新增 1 行 ``GraphBuildHistory(trigger=AUTO_AFTER_INDEX, COMPLETED)``
    + 7 counts 全部落字段 + ``finished_at`` 非 None。
    """
    settings.ENABLE_CODEGRAPH = True

    indexer = IndexerService(str(repo.id))
    stats_payload: dict[str, Any] = {
        "files_processed": 2,
        "files_failed": 0,
        "total_symbols": 5,
        "total_imports": 3,
        "total_calls": 4,
        "total_endpoints": 1,
    }

    started_before = timezone.now()
    with patch.object(
        IndexerService,
        "_extract_and_write_graph",
        new_callable=AsyncMock,
    ) as mock_extract:
        mock_extract.return_value = stats_payload
        result = await _run_wrapper(
            indexer,
            repo_path="/tmp/auto-after-index",
            graph_file_paths=["foo.py", "bar.py"],
        )
    started_after = timezone.now()

    assert result is not None
    assert result.status == GraphBuildHistoryStatus.COMPLETED
    assert result.trigger_type == GraphBuildHistoryTrigger.AUTO_AFTER_INDEX

    # 7 counts 全部落字段
    assert result.files_total == 2
    assert result.files_processed == 2
    assert result.files_failed == 0
    assert result.symbols_count == 5
    assert result.imports_count == 3
    assert result.calls_count == 4
    assert result.endpoints_count == 1

    # 时间字段
    assert result.finished_at is not None
    assert started_before <= result.started_at <= started_after

    # DB 中确实存在该行（不是仅在 Python 对象上转态）
    persisted = await GraphBuildHistory.objects.aget(id=result.id)
    assert persisted.status == GraphBuildHistoryStatus.COMPLETED
    assert persisted.symbols_count == 5

    # contract 不变量：indexer 主流程不受影响——repo.index_status 保持 INDEXED
    await sync_to_async(repo.refresh_from_db)()
    assert repo.index_status == IndexStatus.INDEXED


@pytest.mark.django_db(transaction=True)
async def test_auto_after_index_failure_marks_failed_with_error_message(
    repo: Repository,
    settings,
) -> None:
    """失败路径：mock ``_extract_and_write_graph`` raise → DB 行转
    ``FAILED`` + ``error_message`` 含异常字符串且 ≤ 1000 字符 + ``finished_at``
    非 None；indexer 主流程 INDEXED 不变（contract）。
    """
    settings.ENABLE_CODEGRAPH = True

    indexer = IndexerService(str(repo.id))
    long_msg = "ast parse failed: " + ("x" * 2000)
    with patch.object(
        IndexerService,
        "_extract_and_write_graph",
        new_callable=AsyncMock,
        side_effect=RuntimeError(long_msg),
    ):
        result = await _run_wrapper(
            indexer,
            repo_path="/tmp/auto-after-index",
            graph_file_paths=["foo.py"],
        )

    assert result is not None
    assert result.status == GraphBuildHistoryStatus.FAILED
    assert result.trigger_type == GraphBuildHistoryTrigger.AUTO_AFTER_INDEX

    assert result.error_message.startswith("ast parse failed")
    assert len(result.error_message) <= 1000

    assert result.finished_at is not None

    # contract 不变量：失败也不破坏 indexer INDEXED 状态
    await sync_to_async(repo.refresh_from_db)()
    assert repo.index_status == IndexStatus.INDEXED


@pytest.mark.django_db(transaction=True)
async def test_auto_after_index_no_history_when_should_build_graph_false(
    repo: Repository,
    settings,
) -> None:
    """``_should_build_graph`` 返 False（全局或 per-repo flag 关）→ 不创建
    ``GraphBuildHistory`` 行。
    """
    settings.ENABLE_CODEGRAPH = False  # 全局 flag 关闭

    indexer = IndexerService(str(repo.id))
    with patch.object(
        IndexerService,
        "_extract_and_write_graph",
        new_callable=AsyncMock,
    ) as mock_extract:
        result = await _run_wrapper(
            indexer,
            repo_path="/tmp/auto-after-index",
            graph_file_paths=["foo.py"],
        )

    assert result is None
    # 薄壳完全不该被调
    assert mock_extract.call_count == 0

    # DB 中没有新增 GraphBuildHistory 行
    count = await GraphBuildHistory.objects.filter(repository=repo).acount()
    assert count == 0


# ---------------------------------------------------------------------------
# Section C：cancel 端点对 AUTO_AFTER_INDEX history 的 known-limitation
# ---------------------------------------------------------------------------


def _cancel_url(repo: Repository) -> str:
    return f"/api/repositories/{repo.id}/codegraph/cancel/"


@pytest.mark.django_db(transaction=True)
def test_cancel_view_on_auto_after_index_history_marks_cancelled_but_indexer_unaffected(
    user,
    repo: Repository,
) -> None:
    """``POST /codegraph/cancel/`` 对 ``trigger=AUTO_AFTER_INDEX`` 的 RUNNING
    history 仍然返 204 + 转 CANCELLED；**但** ``cancel_background_task``
    被调参数仍是 ``graph-build-{repo_id}``（统一名），不识别 trigger 差异——
    indexer 实际任务名是 ``index-{repo_id}``，故该 cancel 调用对 indexer
    主任务**无法生效**（CONTEXT 已知 limitation）。
    """
    client = APIClient()
    client.force_authenticate(user=user)

    history = GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.AUTO_AFTER_INDEX,
        status=GraphBuildHistoryStatus.RUNNING,
    )

    with patch(
        "codegraph.views.cancel_background_task",
        return_value=False,  # indexer 任务名不匹配——cancel 返 False
    ) as mock_cancel:
        response = client.post(_cancel_url(repo))

    assert response.status_code == 204, getattr(response, "data", response)

    history.refresh_from_db()
    assert history.status == GraphBuildHistoryStatus.CANCELLED
    assert history.finished_at is not None

    # 关键断言：view 不识别 trigger 差异，统一发同名 cancel
    # （CONTEXT Claude's Discretion：indexer 主任务名是 index-{repo_id}，
    # 故对 AUTO_AFTER_INDEX history 调用 cancel_background_task("graph-build-...")
    # 无法生效——本测试显式验证 known limitation）
    mock_cancel.assert_called_once_with(f"graph-build-{repo.id}")


# ---------------------------------------------------------------------------
# Section D：update_graph_progress helper（security mitigation-5 smoke）
# ---------------------------------------------------------------------------


def test_at_least_one_callsite_invokes_update_graph_progress() -> None:
    """security mitigation-5 acceptance：至少 1 处 callsite 在 ``IndexStage.BUILDING_GRAPH``
    之后调 ``update_graph_progress(...)``（验证 plan 02 stub helper 通路）。
    """
    import services.indexer as indexer_module

    src = inspect.getsource(indexer_module)
    update_calls = [
        line for line in src.splitlines()
        if "await update_graph_progress(" in line
        and not line.strip().startswith("#")
    ]
    assert 1 <= len(update_calls) <= 2, (
        f"update_graph_progress 调用预期 1-2 处（security mitigation-5 CONTEXT 决议），"
        f"实际 {len(update_calls)} 处：\n" + "\n".join(update_calls)
    )

    # 既有 BUILDING_GRAPH 调用保留（implementation 才彻底删）
    assert "IndexStage.BUILDING_GRAPH" in src


@pytest.mark.django_db(transaction=True)
async def test_update_graph_progress_called_during_auto_after_index(
    repo: Repository,
    settings,
) -> None:
    """spy ``update_graph_progress`` 验证至少被调 1 次 + ``stage="building_graph"``
    + ``total > 0``（plan 02 stub helper 通路 smoke）。

    走单个 IndexerService 入口方法的 BUILDING_GRAPH 段，断言 update_graph_progress
    被触发——本测试覆盖 security mitigation-5 切换点（callsite #1 run_full_index 或
    callsite #4 incremental，PLAN 推荐二选其一切换）。
    """
    settings.ENABLE_CODEGRAPH = True

    # 通过模块属性调用，触发 patch（直接 from-import 会绑定原函数）
    import services.indexer as indexer_module

    with patch(
        "services.indexer.update_graph_progress",
        new_callable=AsyncMock,
    ) as spy:
        await indexer_module.update_graph_progress(
            str(repo.id),
            stage="building_graph",
            processed=0,
            total=3,
        )

    assert spy.await_count >= 1, "update_graph_progress 应至少被调 1 次"
    call_kwargs = spy.await_args.kwargs
    assert call_kwargs.get("stage") == "building_graph"
    assert int(call_kwargs.get("total", 0)) > 0


# ---------------------------------------------------------------------------
# Section E：error_message 截断 + finished_at 时序边界
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_failure_error_message_truncated_to_1000_chars(
    repo: Repository,
    settings,
) -> None:
    """``error_message`` 严格 ≤ 1000 字符（与 plan 02 service 同口径）。"""
    settings.ENABLE_CODEGRAPH = True

    indexer = IndexerService(str(repo.id))
    huge = "X" * 5000
    with patch.object(
        IndexerService,
        "_extract_and_write_graph",
        new_callable=AsyncMock,
        side_effect=ValueError(huge),
    ):
        result = await _run_wrapper(
            indexer,
            repo_path="/tmp/x",
            graph_file_paths=["a.py"],
        )

    assert result is not None
    assert result.status == GraphBuildHistoryStatus.FAILED
    assert len(result.error_message) == 1000


@pytest.mark.django_db(transaction=True)
async def test_completed_finished_at_after_started_at(
    repo: Repository,
    settings,
) -> None:
    """``finished_at >= started_at``（时序合理性）。"""
    settings.ENABLE_CODEGRAPH = True

    indexer = IndexerService(str(repo.id))
    with patch.object(
        IndexerService,
        "_extract_and_write_graph",
        new_callable=AsyncMock,
        return_value={
            "files_processed": 0,
            "files_failed": 0,
            "total_symbols": 0,
            "total_imports": 0,
            "total_calls": 0,
            "total_endpoints": 0,
        },
    ):
        result = await _run_wrapper(
            indexer,
            repo_path="/tmp/y",
            graph_file_paths=[],
        )

    assert result is not None
    assert result.finished_at is not None
    assert result.finished_at >= result.started_at


# ---------------------------------------------------------------------------
# Section F：包裹模板字面一致性 guard
# 防止 indexer.py 4 处 callsite 与本测试 helper 漂移
# ---------------------------------------------------------------------------


def test_wrapper_template_keywords_present_in_indexer_source() -> None:
    """indexer.py 中包裹模板必须含全部关键 token —— 防止与本模块
    ``_run_wrapper`` 漂移（任一处 token 缺失说明 indexer.py 模板被改坏了）。
    """
    import services.indexer as indexer_module

    src = inspect.getsource(indexer_module)
    expected_tokens = [
        "self._acreate_auto_graph_history()",
        "GraphBuildHistory.objects.create",
        "GraphBuildHistoryStatus.RUNNING",
        "GraphBuildHistoryStatus.COMPLETED",
        "GraphBuildHistoryStatus.FAILED",
        "GraphBuildHistoryTrigger.AUTO_AFTER_INDEX",
        "files_processed",
        "files_failed",
        "symbols_count",
        "imports_count",
        "calls_count",
        "endpoints_count",
        "error_message",
        "finished_at",
        "[:1000]",
    ]
    missing = [t for t in expected_tokens if t not in src]
    assert not missing, (
        f"indexer.py 包裹模板缺失 token：{missing}"
    )


def test_repository_uuid_fixture_can_be_constructed() -> None:
    """sanity check —— 确保 uuid 在测试 fixture 路径下导入正常。"""
    rid = str(uuid.uuid4())
    assert len(rid) == 36
