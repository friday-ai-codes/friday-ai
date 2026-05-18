"""Phase Plan：GraphBuildHistory 模型 + 枚举 + Meta 三层断言。
测试覆盖（GRAPH-）：
1. 状态机/触发器枚举
 - test_status_enum_has_four_values：4 态 running/completed/failed/cancelled
 —— 不引入 pending（CONTEXT 决议，与 IndexHistoryStatus 5 态形成对比）。
 - test_trigger_enum_has_three_values：3 态 manual/auto_after_index/webhook。
2. 字段类型与默认值（与 IndexHistory 字段口径对齐）
 - test_pk_is_uuid_field_with_default：UUIDField + default=uuid.uuid4 + editable=False。
 - test_repository_fk_cascade_with_related_name：ForeignKey CASCADE + related_name="graph_build_histories"。
 - test_seven_counter_fields_default_zero：7 个 IntegerField default=0。
 - test_time_fields：started_at default=timezone.now / finished_at nullable。
 - test_error_message_text_blank_default_empty：TextField + blank=True + default=""。
3. Meta 索引
 - test_meta_indexes_present：Plan list endpoint ?ordering=-started_at 默认场景命中索引。
4. 创建 + __str__
 - test_create_with_required_fields_only：仅传 repository + trigger_type 应创建成功。
 - test_str_returns_human_readable：__str__ 含 repo.name + status + trigger。
注：本 plan 仅落模型 + migration，list endpoint（GET history/）由 Plan 落，
`auto_after_index` 写入路径由 Plan 落（详见 work-item.md decisions 段）。
"""
from __future__ import annotations
import uuid
import pytest
from django.db import models
from django.utils import timezone
from repositories.models import (
 GraphBuildHistory,
 GraphBuildHistoryStatus,
 GraphBuildHistoryTrigger,
 Repository,
)
@pytest.fixture
def graph_repo(db) -> Repository:
 """本 plan 测试关联的独立 Repository 实例（避免跨测试串扰）。"""
 return Repository.objects.create(
 name="graph-build-history-repo",
 git_url="https://github.com/test/graph-build-history-repo.git",
 git_platform="github",
 default_branch="main",
 )
# ---------------------------------------------------------------------------
# 1. 枚举值
# ---------------------------------------------------------------------------
def test_status_enum_has_four_values -> None:
 """GraphBuildHistoryStatus 严格 4 态：running/completed/failed/cancelled。
 CONTEXT 决议：不引入 pending（创建即 RUNNING，与 ROADMAP / 对齐）。
 """
 values = set(GraphBuildHistoryStatus.values)
 assert values == {"running", "completed", "failed", "cancelled"}
 # set 等值已显式锁定 4 态——不含 pending（CONTEXT 决议在 set 比较中体现）
def test_trigger_enum_has_three_values -> None:
 """GraphBuildHistoryTrigger 严格 3 态：manual/auto_after_index/webhook。"""
 values = set(GraphBuildHistoryTrigger.values)
 assert values == {"manual", "auto_after_index", "webhook"}
# ---------------------------------------------------------------------------
# 2. 字段类型与默认值
# ---------------------------------------------------------------------------
def test_pk_is_uuid_field_with_default -> None:
 """主键必须是 UUIDField，default=uuid.uuid4，editable=False（与 IndexHistory 对齐）。"""
 field = GraphBuildHistory._meta.get_field("id")
 assert isinstance(field, models.UUIDField)
 assert field.default is uuid.uuid4
 assert field.editable is False
def test_repository_fk_cascade_with_related_name -> None:
 """repository 必须是 ForeignKey CASCADE + related_name='graph_build_histories'。"""
 field = GraphBuildHistory._meta.get_field("repository")
 assert isinstance(field, models.ForeignKey)
 assert field.remote_field.on_delete is models.CASCADE
 assert field.remote_field.related_name == "graph_build_histories"
 assert field.remote_field.model is Repository
def test_seven_counter_fields_default_zero -> None:
 """7 个 IntegerField 计数字段全部 default=0（构建进度与产物计数）。"""
 counter_field_names = [
 "files_total",
 "files_processed",
 "files_failed",
 "symbols_count",
 "imports_count",
 "calls_count",
 "endpoints_count",
 ]
 for name in counter_field_names:
 field = GraphBuildHistory._meta.get_field(name)
 assert isinstance(field, models.IntegerField), f"{name} 必须是 IntegerField"
 assert field.default == 0, f"{name}.default 必须 == 0"
def test_time_fields -> None:
 """started_at default=timezone.now（callable），finished_at 可空。"""
 started_at = GraphBuildHistory._meta.get_field("started_at")
 assert isinstance(started_at, models.DateTimeField)
 assert started_at.default is timezone.now
 finished_at = GraphBuildHistory._meta.get_field("finished_at")
 assert isinstance(finished_at, models.DateTimeField)
 assert finished_at.null is True
 assert finished_at.blank is True
def test_error_message_text_blank_default_empty -> None:
 """error_message 必须 TextField + blank=True + default=''（与 IndexHistory 略异）。"""
 field = GraphBuildHistory._meta.get_field("error_message")
 assert isinstance(field, models.TextField)
 assert field.blank is True
 assert field.default == ""
# ---------------------------------------------------------------------------
# 3. Meta 索引
# ---------------------------------------------------------------------------
def test_meta_indexes_present -> None:
 """Meta.indexes 必须含 fields=['repository', '-started_at'] 项。
 供 Plan GET history/ 默认 ?ordering=-started_at 命中索引。
 """
 indexes = GraphBuildHistory._meta.indexes
 matching = [idx for idx in indexes if idx.fields == ["repository", "-started_at"]]
 assert len(matching) == 1, f"未找到 (repository, -started_at) 索引；现有：{indexes}"
# ---------------------------------------------------------------------------
# 4. 创建 + __str__
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_create_with_required_fields_only(graph_repo: Repository) -> None:
 """仅传 repository + trigger_type 即可创建实例（status 默认 RUNNING）。"""
 history = GraphBuildHistory.objects.create(
 repository=graph_repo,
 trigger_type=GraphBuildHistoryTrigger.MANUAL,
 )
 assert history.id is not None
 assert history.repository_id == graph_repo.id
 assert history.trigger_type == "manual"
 assert history.status == GraphBuildHistoryStatus.RUNNING
 assert history.files_total == 0
 assert history.files_processed == 0
 assert history.symbols_count == 0
 assert history.error_message == ""
 assert history.started_at is not None
 assert history.finished_at is None
@pytest.mark.django_db
def test_str_returns_human_readable(graph_repo: Repository) -> None:
 """__str__ 必须可读：含 repo.name + trigger + status（与 IndexHistory.__str__ 同模板）。"""
 history = GraphBuildHistory.objects.create(
 repository=graph_repo,
 trigger_type=GraphBuildHistoryTrigger.MANUAL,
 status=GraphBuildHistoryStatus.RUNNING,
 )
 text = str(history)
 assert graph_repo.name in text
 assert "manual" in text
 assert "running" in text
