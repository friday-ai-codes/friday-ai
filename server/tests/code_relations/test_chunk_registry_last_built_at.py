"""`ChunkRegistry.last_built_at` nullable 字段行为（implementation）。

context contract 标 implementation 落但实际未落，本 plan 补齐 + 0005 migration。
NULL = 未 backfill 语义；rebuild_chunk_edges 命令依赖该字段实现断点续跑。

覆盖 5 条 assertion：

1. 字段类型 + nullable / blank：`get_field("last_built_at")` 是 DateTimeField，
   null=True / blank=True
2. 默认值 None：新建实例不传 last_built_at 时落库 NULL
3. 断点续跑查询：`filter(last_built_at__isnull=True)` 命中默认创建记录
4. db_index：字段或 Meta.indexes 含 last_built_at 索引（断点续跑 query 性能）
5. `makemigrations --dry-run code_relations` 输出 "No changes detected"
   （0005 已落 + 模型一致）
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.db import models
from django.utils import timezone

from code_relations.models import ChunkRegistry
from code_relations.utils import generate_chunk_id

pytestmark = pytest.mark.django_db


def test_last_built_at_field_is_nullable_datetime() -> None:
    field = ChunkRegistry._meta.get_field("last_built_at")
    assert isinstance(field, models.DateTimeField)
    assert field.null is True
    assert field.blank is True


def test_default_last_built_at_is_none(repository) -> None:
    cid = generate_chunk_id(str(repository.id), "src/foo.py", 0)
    reg = ChunkRegistry.objects.create(
        chunk_id=cid,
        content_hash="a" * 64,
        repository=repository,
        file_path="src/foo.py",
        chunk_index=0,
    )
    reg.refresh_from_db()
    assert reg.last_built_at is None


def test_filter_isnull_matches_default_rows(repository) -> None:
    """断点续跑核心 query：`last_built_at__isnull=True` 必须命中默认创建行。"""
    cid_a = generate_chunk_id(str(repository.id), "src/a.py", 0)
    cid_b = generate_chunk_id(str(repository.id), "src/b.py", 0)
    ChunkRegistry.objects.create(
        chunk_id=cid_a,
        content_hash="a" * 64,
        repository=repository,
        file_path="src/a.py",
        chunk_index=0,
    )
    ChunkRegistry.objects.create(
        chunk_id=cid_b,
        content_hash="b" * 64,
        repository=repository,
        file_path="src/b.py",
        chunk_index=0,
        last_built_at=timezone.now(),
    )

    pending = list(
        ChunkRegistry.objects.filter(last_built_at__isnull=True).values_list(
            "chunk_id", flat=True
        )
    )
    assert pending == [cid_a]

    built = list(
        ChunkRegistry.objects.filter(last_built_at__isnull=False).values_list(
            "chunk_id", flat=True
        )
    )
    assert built == [cid_b]


def test_last_built_at_is_indexed() -> None:
    """断点续跑 query 性能：字段级 db_index 或 Meta.indexes 含 last_built_at。"""
    field = ChunkRegistry._meta.get_field("last_built_at")
    field_level = bool(getattr(field, "db_index", False))
    meta_level = any(
        "last_built_at" in idx.fields for idx in ChunkRegistry._meta.indexes
    )
    assert field_level or meta_level, (
        "ChunkRegistry.last_built_at 必须 db_index=True 或在 Meta.indexes 中声明"
    )


def test_makemigrations_no_residual_diff() -> None:
    out = StringIO()
    call_command(
        "makemigrations",
        "code_relations",
        "--dry-run",
        "--no-color",
        stdout=out,
        stderr=out,
    )
    output = out.getvalue()
    assert "No changes detected" in output, (
        f"Expected `No changes detected` in makemigrations output, got:\n{output}"
    )
