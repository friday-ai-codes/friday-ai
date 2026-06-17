"""AuditEvent 字段/索引/标量-actor 存在性测试（AUDIT-01，SC-1 模型层半）。

验证 AUDIT-01 字段集齐备、Phase 55 查询索引维度覆盖、actor 为标量软引用非 FK。
"""

import pytest
from django.db import models

from audit.models import AuditEvent

# AUDIT-01 字段集 + recorded_at 不可变插入戳
_EXPECTED_FIELDS = {
    "actor_id",
    "actor_repr",
    "action",
    "target_type",
    "target_id",
    "target_repr",
    "before",
    "after",
    "source",
    "occurred_at",
    "recorded_at",
    "metadata",
}

# Phase 55 查询过滤维度（为查询/导出铺底）
_EXPECTED_INDEX_FIELD_SETS = [
    ["action"],
    ["target_type", "target_id"],
    ["actor_id"],
    ["occurred_at"],
    ["action", "occurred_at"],
]


@pytest.mark.django_db
def test_all_audit01_fields_present():
    """AuditEvent._meta 字段名集合 ⊇ AUDIT-01 字段集（12 字段）。"""
    field_names = {f.name for f in AuditEvent._meta.get_fields()}
    missing = _EXPECTED_FIELDS - field_names
    assert not missing, f"缺失字段：{missing}"


@pytest.mark.django_db
def test_indexes_cover_query_dims():
    """Meta.indexes 覆盖 5 组 Phase 55 查询维度。"""
    actual = [list(index.fields) for index in AuditEvent._meta.indexes]
    for expected in _EXPECTED_INDEX_FIELD_SETS:
        assert expected in actual, f"缺失索引维度：{expected}（实际：{actual}）"


@pytest.mark.django_db
def test_actor_is_scalar_not_fk():
    """actor_id 是 UUIDField 标量，模型无指向 User 的 ForeignKey（不级联触碰审计行）。"""
    actor_field = AuditEvent._meta.get_field("actor_id")
    assert isinstance(actor_field, models.UUIDField)
    # 遍历所有字段，断言无任何 related_model 指向 auth user 的关系字段
    for field in AuditEvent._meta.get_fields():
        related = getattr(field, "related_model", None)
        if related is not None:
            model_label = related._meta.label_lower
            assert "user" not in model_label, (
                f"AuditEvent 不应有指向 User 的关系字段：{field.name} → {model_label}"
            )


@pytest.mark.django_db
def test_timestamps_semantics():
    """occurred_at 可由 emit 端传入（default，非 auto_now_add）；recorded_at 为插入戳。"""
    occurred = AuditEvent._meta.get_field("occurred_at")
    recorded = AuditEvent._meta.get_field("recorded_at")
    assert occurred.auto_now_add is False
    assert recorded.auto_now_add is True
