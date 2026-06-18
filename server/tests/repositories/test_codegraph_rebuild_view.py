"""implementation / work item-04 + work item-05：codegraph REST 三件套端到端测试。

覆盖的端点：

1. POST /api/repositories/{id}/codegraph/rebuild/  — 手动触发 graph 构建
2. POST /api/repositories/{id}/codegraph/cancel/   — 取消进行中构建
3. GET  /api/repositories/{id}/codegraph/history/  — 分页历史列表

主要测试场景（详见各 section）：

- 正常 202 / 204 / 200 路径
- 409 互斥：IndexHistory RUNNING（向量轨锁）+ GraphBuildHistory RUNNING（图谱轨锁）
- 403：``settings.ENABLE_CODEGRAPH=False`` 全局硬开关
- 404 / 401：仓库缺失 / 未认证
- cancel → rebuild 链路（CANCELLED 不在 RUNNING 过滤集内，应放行）
- success criterion 反向独立锁：``graph_build_status=RUNNING`` 不阻塞 ``POST /index/``
- ``auto_build_graph_enabled=False`` 不影响手动 rebuild（CONTEXT Area 3 Q4）

测试组织风格沿用 ``test_codegraph_delete_view.py`` —— 走完整 APIClient dispatch
拿 status_code，hardcoded URL 字符串保持简单（避免 RED 阶段 NoReverseMatch
噪声，统一以 404 → 202/204/200 表达 RED→GREEN）。
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from repositories.models import (
    GraphBuildHistory,
    GraphBuildHistoryStatus,
    GraphBuildHistoryTrigger,
    IndexHistory,
    IndexHistoryStatus,
    IndexStatus,
    Repository,
    TriggerType,
)

pytestmark = [pytest.mark.django_db(transaction=True)]


# ---------------------------------------------------------------------------
# fixtures：repo + url helper
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(db) -> Repository:
    return Repository.objects.create(
        name="codegraph-rest-repo",
        git_url="https://github.com/test/codegraph-rest.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
    )


def _rebuild_url(repo: Repository) -> str:
    return f"/api/repositories/{repo.id}/codegraph/rebuild/"


def _cancel_url(repo: Repository) -> str:
    return f"/api/repositories/{repo.id}/codegraph/cancel/"


def _history_url(repo: Repository) -> str:
    return f"/api/repositories/{repo.id}/codegraph/history/"


def _index_url(repo: Repository) -> str:
    return f"/api/repositories/{repo.id}/index/"


# ===========================================================================
# Section A：CodegraphRebuildView（POST /codegraph/rebuild/）
# ===========================================================================


def test_rebuild_202_creates_running_history(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """POST rebuild → 202 + history_id；DB 新增 RUNNING + manual history；
    ``run_in_background`` 被调一次且 task name == ``graph-build-{repo_id}``。"""

    with patch(
        "codegraph.views.run_in_background",
        return_value=MagicMock(),
    ) as mock_run_bg:
        response = authenticated_client.post(_rebuild_url(repo))

    assert response.status_code == 202, getattr(response, "data", response)

    history_id = response.data.get("history_id")
    assert history_id, response.data
    # UUID 合法性
    uuid.UUID(str(history_id))

    qs = GraphBuildHistory.objects.filter(repository=repo)
    assert qs.count() == 1
    row = qs.get()
    assert row.status == GraphBuildHistoryStatus.RUNNING
    assert row.trigger_type == GraphBuildHistoryTrigger.MANUAL

    mock_run_bg.assert_called_once()
    _, kwargs = mock_run_bg.call_args
    assert kwargs.get("name") == f"graph-build-{repo.id}"


def test_rebuild_409_when_index_running(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """IndexHistory.status=RUNNING（向量轨进行中）→ 409 + detail 含 ``index running``。"""

    IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
        status=IndexHistoryStatus.RUNNING,
    )

    with patch(
        "codegraph.views.run_in_background",
        return_value=MagicMock(),
    ) as mock_run_bg:
        response = authenticated_client.post(_rebuild_url(repo))

    assert response.status_code == 409, getattr(response, "data", response)
    detail = str(response.data.get("detail", "")).lower()
    assert "index running" in detail, f"detail 缺 'index running'：{detail!r}"

    assert GraphBuildHistory.objects.filter(repository=repo).count() == 0
    mock_run_bg.assert_not_called()


def test_rebuild_409_when_graph_already_running(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """已有 GraphBuildHistory.status=RUNNING（图谱轨已锁）→ 409 + detail 含 ``graph already running``。"""

    GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.MANUAL,
        status=GraphBuildHistoryStatus.RUNNING,
    )

    with patch(
        "codegraph.views.run_in_background",
        return_value=MagicMock(),
    ):
        response = authenticated_client.post(_rebuild_url(repo))

    assert response.status_code == 409, getattr(response, "data", response)
    detail = str(response.data.get("detail", "")).lower()
    assert "graph already running" in detail, f"detail 缺关键字：{detail!r}"


def test_rebuild_403_when_codegraph_disabled(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """settings.ENABLE_CODEGRAPH=False → 403 + detail 含 ``graph feature disabled``。"""

    with override_settings(ENABLE_CODEGRAPH=False), patch(
        "codegraph.views.run_in_background",
        return_value=MagicMock(),
    ):
        response = authenticated_client.post(_rebuild_url(repo))

    assert response.status_code == 403, getattr(response, "data", response)
    detail = str(response.data.get("detail", "")).lower()
    assert "graph feature disabled" in detail, f"detail 缺关键字：{detail!r}"


def test_rebuild_404_on_missing_repository(
    authenticated_client: APIClient,
) -> None:
    """不存在的 repository_id → 404，不暴露内部异常。"""

    missing_id = uuid.uuid4()
    with patch(
        "codegraph.views.run_in_background",
        return_value=MagicMock(),
    ):
        response = authenticated_client.post(
            f"/api/repositories/{missing_id}/codegraph/rebuild/"
        )
    assert response.status_code == 404


def test_rebuild_401_unauthenticated(
    api_client: APIClient,
    repo: Repository,
) -> None:
    """未认证 → 401（IsAuthenticated 强制）。"""

    response = api_client.post(_rebuild_url(repo))
    assert response.status_code in (401, 403)


def test_rebuild_succeeds_when_auto_build_graph_disabled(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """auto_build_graph_enabled=False 不影响手动 rebuild（CONTEXT Area 3 Q4
    锁定 —— per-repo 开关只控 indexer 自动衔接路径，手动 REST 是用户
    explicit intent）。"""

    repo.auto_build_graph_enabled = False
    repo.save(update_fields=["auto_build_graph_enabled"])

    with patch(
        "codegraph.views.run_in_background",
        return_value=MagicMock(),
    ):
        response = authenticated_client.post(_rebuild_url(repo))

    assert response.status_code == 202, getattr(response, "data", response)
    assert GraphBuildHistory.objects.filter(
        repository=repo,
        status=GraphBuildHistoryStatus.RUNNING,
    ).exists()


# ===========================================================================
# Section B：CodegraphCancelView（POST /codegraph/cancel/）
# ===========================================================================


def test_cancel_204_when_running_history_present(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """有 RUNNING history → 204；DB 行转 CANCELLED + finished_at 非 None；
    ``cancel_background_task`` 被调一次参数 ``graph-build-{repo_id}``。"""

    history = GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.MANUAL,
        status=GraphBuildHistoryStatus.RUNNING,
    )

    with patch(
        "codegraph.views.cancel_background_task",
        return_value=True,
    ) as mock_cancel:
        response = authenticated_client.post(_cancel_url(repo))

    assert response.status_code == 204, getattr(response, "data", response)

    history.refresh_from_db()
    assert history.status == GraphBuildHistoryStatus.CANCELLED
    assert history.finished_at is not None

    mock_cancel.assert_called_once_with(f"graph-build-{repo.id}")


def test_cancel_409_when_no_running_history(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """DB 中无 RUNNING 行 → 409 + detail 含 ``no graph build running``。"""

    with patch(
        "codegraph.views.cancel_background_task",
        return_value=False,
    ):
        response = authenticated_client.post(_cancel_url(repo))

    assert response.status_code == 409, getattr(response, "data", response)
    detail = str(response.data.get("detail", "")).lower()
    assert "no graph build running" in detail, f"detail 缺关键字：{detail!r}"


def test_cancel_409_when_only_completed_history(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """仅有 COMPLETED 行（非 RUNNING）→ 409。"""

    GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.MANUAL,
        status=GraphBuildHistoryStatus.COMPLETED,
        finished_at=timezone.now(),
    )

    with patch(
        "codegraph.views.cancel_background_task",
        return_value=False,
    ):
        response = authenticated_client.post(_cancel_url(repo))

    assert response.status_code == 409


def test_cancel_targets_all_running_history(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """多 RUNNING 行（不同 started_at）→ **全部**转 CANCELLED。

    旧行为只翻最新一行，会把更早的 RUNNING 行遗留成永久挡住 rebuild 的幽灵
    （并发 auto_after_index 已观测到同毫秒 2 行）。修复后 cancel 取消该仓库
    全部 RUNNING 行。
    """

    older_started = timezone.now() - timezone.timedelta(minutes=10)
    older = GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.MANUAL,
        status=GraphBuildHistoryStatus.RUNNING,
        started_at=older_started,
    )
    newer = GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.MANUAL,
        status=GraphBuildHistoryStatus.RUNNING,
        started_at=timezone.now(),
    )

    with patch(
        "codegraph.views.cancel_background_task",
        return_value=True,
    ):
        response = authenticated_client.post(_cancel_url(repo))

    assert response.status_code == 204
    newer.refresh_from_db()
    older.refresh_from_db()
    assert newer.status == GraphBuildHistoryStatus.CANCELLED
    assert older.status == GraphBuildHistoryStatus.CANCELLED


def test_cancel_404_on_missing_repository(
    authenticated_client: APIClient,
) -> None:
    missing_id = uuid.uuid4()
    response = authenticated_client.post(
        f"/api/repositories/{missing_id}/codegraph/cancel/"
    )
    assert response.status_code == 404


def test_cancel_401_unauthenticated(
    api_client: APIClient,
    repo: Repository,
) -> None:
    response = api_client.post(_cancel_url(repo))
    assert response.status_code in (401, 403)


def test_cancel_cannot_target_auto_after_index_via_named_task(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """auto_after_index 触发的 history 无法被独立 cancel（CONTEXT 已明示的 known limitation）：

    - 实际 background task 名 ``index-{repo_id}`` 而非 ``graph-build-{repo_id}``
    - ``cancel_background_task(f"graph-build-{repo_id}")`` 调用对其 no-op（返 False）
    - 但 view 仍按规约把该 history 行转 CANCELLED + 返 204（DB 一致性优先）；
      indexer 主任务由 IndexCancelView 端点单独负责。
    """

    history = GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.AUTO_AFTER_INDEX,
        status=GraphBuildHistoryStatus.RUNNING,
    )

    with patch(
        "codegraph.views.cancel_background_task",
        return_value=False,
    ) as mock_cancel:
        response = authenticated_client.post(_cancel_url(repo))

    assert response.status_code == 204
    history.refresh_from_db()
    assert history.status == GraphBuildHistoryStatus.CANCELLED
    mock_cancel.assert_called_once_with(f"graph-build-{repo.id}")


# ===========================================================================
# Section C：CodegraphHistoryListView（GET /codegraph/history/）
# ===========================================================================


def test_history_list_200_returns_paginated(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """预创建 25 行 → page_size=20 + count=25 + next 链接非空。"""

    base = timezone.now()
    for i in range(25):
        GraphBuildHistory.objects.create(
            repository=repo,
            trigger_type=GraphBuildHistoryTrigger.MANUAL,
            status=GraphBuildHistoryStatus.COMPLETED,
            started_at=base - timezone.timedelta(minutes=i),
        )

    response = authenticated_client.get(_history_url(repo))

    assert response.status_code == 200, getattr(response, "data", response)
    assert response.data["count"] == 25
    # 默认 page_size=20（DRF PageNumberPagination._Pagination）
    assert len(response.data["results"]) == 20
    assert response.data["next"] is not None


def test_history_list_default_ordering_desc_started_at(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """默认排序 ``-started_at`` —— results[0].started_at > results[-1].started_at。"""

    base = timezone.now()
    for i in range(3):
        GraphBuildHistory.objects.create(
            repository=repo,
            trigger_type=GraphBuildHistoryTrigger.MANUAL,
            status=GraphBuildHistoryStatus.COMPLETED,
            started_at=base - timezone.timedelta(minutes=i * 10),
        )

    response = authenticated_client.get(_history_url(repo))
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 3
    assert results[0]["started_at"] > results[-1]["started_at"]


def test_history_list_status_filter(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """``?status=completed`` 过滤 —— 仅返回 COMPLETED 行。"""

    for status_value in (
        GraphBuildHistoryStatus.RUNNING,
        GraphBuildHistoryStatus.COMPLETED,
        GraphBuildHistoryStatus.FAILED,
    ):
        for _ in range(2):
            GraphBuildHistory.objects.create(
                repository=repo,
                trigger_type=GraphBuildHistoryTrigger.MANUAL,
                status=status_value,
            )

    response = authenticated_client.get(
        _history_url(repo), {"status": "completed"}
    )
    assert response.status_code == 200
    assert response.data["count"] == 2
    for item in response.data["results"]:
        assert item["status"] == "completed"


def test_history_list_serializer_fields_match(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """单行 fixture 设全字段 —— 断言 result item 含 15 字段全集（含 duration_seconds）。"""

    started = timezone.now() - timezone.timedelta(seconds=42)
    GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.MANUAL,
        status=GraphBuildHistoryStatus.COMPLETED,
        files_total=10,
        files_processed=9,
        files_failed=1,
        symbols_count=50,
        imports_count=20,
        calls_count=30,
        endpoints_count=5,
        started_at=started,
        finished_at=started + timezone.timedelta(seconds=42),
        error_message="",
    )

    response = authenticated_client.get(_history_url(repo))
    assert response.status_code == 200
    assert len(response.data["results"]) == 1
    item = response.data["results"][0]
    expected_fields = {
        "id",
        "trigger_type",
        "status",
        "files_total",
        "files_processed",
        "files_failed",
        "symbols_count",
        "imports_count",
        "calls_count",
        "endpoints_count",
        "started_at",
        "finished_at",
        "duration_seconds",
        "error_message",
        "created_at",
    }
    assert set(item.keys()) == expected_fields, (
        f"serializer 字段集合不匹配：缺 {expected_fields - set(item.keys())}，"
        f"多 {set(item.keys()) - expected_fields}"
    )
    # 构建耗时 = finished_at - started_at
    assert item["duration_seconds"] == 42.0


def test_history_list_404_on_missing_repository(
    authenticated_client: APIClient,
) -> None:
    missing_id = uuid.uuid4()
    response = authenticated_client.get(
        f"/api/repositories/{missing_id}/codegraph/history/"
    )
    assert response.status_code == 404


def test_history_list_401_unauthenticated(
    api_client: APIClient,
    repo: Repository,
) -> None:
    response = api_client.get(_history_url(repo))
    assert response.status_code in (401, 403)


# ===========================================================================
# Section D：跨端点链路 + success criterion 反向独立锁
# ===========================================================================


def test_cancel_then_rebuild_succeeds(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """cancel 完立即 rebuild 应成功 —— CANCELLED 不在 RUNNING 过滤集，子查询不命中。

    最终 DB 应有 2 行：1 CANCELLED + 1 RUNNING。
    """

    GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.MANUAL,
        status=GraphBuildHistoryStatus.RUNNING,
    )

    with patch(
        "codegraph.views.cancel_background_task",
        return_value=True,
    ):
        cancel_resp = authenticated_client.post(_cancel_url(repo))
    assert cancel_resp.status_code == 204

    with patch(
        "codegraph.views.run_in_background",
        return_value=MagicMock(),
    ):
        rebuild_resp = authenticated_client.post(_rebuild_url(repo))
    assert rebuild_resp.status_code == 202, getattr(rebuild_resp, "data", rebuild_resp)

    assert GraphBuildHistory.objects.filter(repository=repo).count() == 2
    assert (
        GraphBuildHistory.objects.filter(
            repository=repo,
            status=GraphBuildHistoryStatus.CANCELLED,
        ).count()
        == 1
    )
    assert (
        GraphBuildHistory.objects.filter(
            repository=repo,
            status=GraphBuildHistoryStatus.RUNNING,
        ).count()
        == 1
    )


def test_index_creation_not_blocked_by_running_graph(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """ROADMAP implementation success criterion 反向语义验证：向量轨锁与图谱轨锁独立。

    ``graph_build_status=RUNNING`` 不参与 ``IndexCreateView`` 的 409 判定 ——
    即 ``POST /index/`` 在图谱构建进行中时仍应放行（生成新 IndexHistory），
    与 ``IndexCreateView`` 既有行为对齐（参考 server/repositories/index_views.py:128）。
    """

    GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.MANUAL,
        status=GraphBuildHistoryStatus.RUNNING,
    )

    with patch(
        "repositories.index_views._schedule_index",
        return_value=MagicMock(),
    ):
        response = authenticated_client.post(_index_url(repo))

    assert response.status_code != 409, (
        f"图谱锁误参与了向量轨判定（success criterion 违例）：status={response.status_code}, "
        f"data={getattr(response, 'data', None)}"
    )
    assert IndexHistory.objects.filter(repository=repo).exists()
    latest = IndexHistory.objects.filter(repository=repo).order_by("-created_at").first()
    assert latest is not None
    assert latest.status in (
        IndexHistoryStatus.RUNNING,
        IndexHistoryStatus.PENDING,
    )
