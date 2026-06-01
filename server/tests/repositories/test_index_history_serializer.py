"""Phase Plan：IndexHistorySerializer 新字段透传测试。
测试覆盖：
1. test_serializer_emits_delta_fields：序列化含 delta 真实值的行，5 个 delta key 值正确
2. test_serializer_lines_null_passthrough：lines_added=None 时 serializer 原样透出 None
 （Pitfall 6 前端镜像基础：null 透传供前端显示 "—"）
3. test_serializer_lines_real_value：lines_added=0 与 lines_added=5 均正常透出（区别于 null）
注：serializer 行级 diff 用 allow_null=True，保证 null/0 可区分。
"""
from __future__ import annotations
import pytest
from repositories.index_views import IndexHistorySerializer
from repositories.models import (
 IndexHistory,
 IndexHistoryStatus,
 Repository,
 TriggerType,
)
@pytest.fixture
def repo(db) -> Repository:
 """供测试关联的 Repository 实例。"""
 return Repository.objects.create(
 name="delta-serializer-repo",
 git_url="https://github.com/org/delta-serializer-repo.git",
 git_platform="github",
 default_branch="main",
 )
@pytest.mark.django_db
def test_serializer_emits_delta_fields(repo: Repository) -> None:
 """：序列化输出含 5 个 per-run delta key 且值正确。"""
 history = IndexHistory.objects.create(
 repository=repo,
 trigger_type=TriggerType.WEBHOOK,
 status=IndexHistoryStatus.COMPLETED,
 symbols_added=100,
 imports_added=20,
 calls_added=30,
 endpoints_added=5,
 chunk_edges_added=50,
 )
 data = IndexHistorySerializer(history).data
 assert data["symbols_added"] == 100
 assert data["imports_added"] == 20
 assert data["calls_added"] == 30
 assert data["endpoints_added"] == 5
 assert data["chunk_edges_added"] == 50
 for key in (
 "symbols_added",
 "imports_added",
 "calls_added",
 "endpoints_added",
 "chunk_edges_added",
 ):
 assert isinstance(data[key], int)
@pytest.mark.django_db
def test_serializer_lines_null_passthrough(repo: Repository) -> None:
 """（Pitfall 6）：lines_added/deleted=None 时 serializer 原样透出 None。"""
 history = IndexHistory.objects.create(
 repository=repo,
 trigger_type=TriggerType.MANUAL,
 )
 data = IndexHistorySerializer(history).data
 assert data["lines_added"] is None
 assert data["lines_deleted"] is None
@pytest.mark.django_db
def test_serializer_lines_real_value(repo: Repository) -> None:
 """（Pitfall 6）：lines_added=0 与 5 均正常透出，区别于 null。"""
 history_zero = IndexHistory.objects.create(
 repository=repo,
 trigger_type=TriggerType.WEBHOOK,
 lines_added=0,
 lines_deleted=0,
 )
 history_five = IndexHistory.objects.create(
 repository=repo,
 trigger_type=TriggerType.WEBHOOK,
 lines_added=5,
 lines_deleted=3,
 )
 data_zero = IndexHistorySerializer(history_zero).data
 data_five = IndexHistorySerializer(history_five).data
 # 真实 0 必须透出为 0（不是 None），证明 null vs 0 可区分
 assert data_zero["lines_added"] == 0
 assert data_zero["lines_deleted"] == 0
 assert data_zero["lines_added"] is not None
 assert data_five["lines_added"] == 5
 assert data_five["lines_deleted"] == 3
