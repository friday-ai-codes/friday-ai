"""initial implementation plan：IndexHistory GraphRAG 字段三件套测试。

测试覆盖：
1. test_default_values：新建 IndexHistory 行 default `graph_build_status='pending'` /
   `edge_count=0` / `payload_synced_at is None`
2. test_choice_validation：写入非 choices 值（如 "bogus"）`full_clean()` 抛 ValidationError
3. test_serializer_outputs_graph_fields：IndexHistorySerializer 输出含三个新字段且类型正确

注：本 plan 仅落字段 + serializer，不承担 lifecycle 写入逻辑（plan）。
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from repositories.index_views import IndexHistorySerializer
from repositories.models import (
    GraphBuildStatus,
    IndexHistory,
    IndexHistoryStatus,
    Repository,
    TriggerType,
)


@pytest.fixture
def repo(db) -> Repository:
    """供测试关联的 Repository 实例。"""
    return Repository.objects.create(
        name="graph-fields-repo",
        git_url="https://github.com/org/graph-fields-repo.git",
        git_platform="github",
        default_branch="main",
    )


@pytest.mark.django_db
def test_default_values(repo: Repository) -> None:
    """新建 IndexHistory 行三个新字段应取默认值。

    - graph_build_status: GraphBuildStatus.PENDING ('pending')
    - edge_count: 0
    - payload_synced_at: None
    """
    history = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
    )

    assert history.graph_build_status == GraphBuildStatus.PENDING
    assert history.graph_build_status == "pending"
    assert history.edge_count == 0
    assert history.payload_synced_at is None


@pytest.mark.django_db
def test_choice_validation(repo: Repository) -> None:
    """graph_build_status 写入非 choices 值，full_clean() 应抛 ValidationError。"""
    history = IndexHistory(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
        graph_build_status="bogus",
    )
    with pytest.raises(ValidationError) as exc_info:
        history.full_clean()
    assert "graph_build_status" in exc_info.value.error_dict


@pytest.mark.django_db
def test_graph_build_status_enum_values() -> None:
    """GraphBuildStatus 枚举应严格只有 5 个 value：pending/running/completed/failed/skipped。"""
    values = {choice.value for choice in GraphBuildStatus}
    assert values == {"pending", "running", "completed", "failed", "skipped"}


@pytest.mark.django_db
def test_serializer_outputs_graph_fields(repo: Repository) -> None:
    """IndexHistorySerializer 输出 dict 必须含三个新字段且类型正确。

    - graph_build_status: str
    - edge_count: int
    - payload_synced_at: str | None
    """
    now = timezone.now()
    history = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.WEBHOOK,
        status=IndexHistoryStatus.COMPLETED,
        graph_build_status=GraphBuildStatus.COMPLETED,
        edge_count=42,
        payload_synced_at=now,
    )

    data = IndexHistorySerializer(history).data

    assert "graph_build_status" in data
    assert "edge_count" in data
    assert "payload_synced_at" in data

    assert data["graph_build_status"] == "completed"
    assert isinstance(data["edge_count"], int)
    assert data["edge_count"] == 42
    assert isinstance(data["payload_synced_at"], str)


@pytest.mark.django_db
def test_serializer_outputs_payload_synced_at_null_when_unset(repo: Repository) -> None:
    """payload_synced_at 未设置时 serializer 输出 None（allow_null=True）。"""
    history = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
    )
    data = IndexHistorySerializer(history).data
    assert data["payload_synced_at"] is None
