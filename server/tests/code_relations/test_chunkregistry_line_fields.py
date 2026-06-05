"""`ChunkRegistry.line_start` / `line_end` nullable 字段行为（per initial implementation contract）。

覆盖 4 条 assertion：

1. 显式赋值 line_start=10 / line_end=20 写入成功，读取等值
2. 不传两字段 / 显式 None 写入成功，DB 层落 NULL
3. `__str__` 输出格式不变（不含 line_* 信息——历史 callsite 不破坏）
4. `makemigrations --dry-run code_relations` 输出 "No changes detected"
   （schema 与模型一致，本 plan migration 后无残留 diff）
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from code_relations.models import ChunkRegistry
from code_relations.utils import generate_chunk_id

pytestmark = pytest.mark.django_db


def test_chunk_registry_save_with_line_fields(repository) -> None:
    cid = generate_chunk_id(str(repository.id), "src/foo.py", 0)
    reg = ChunkRegistry.objects.create(
        chunk_id=cid,
        content_hash="a" * 64,
        repository=repository,
        file_path="src/foo.py",
        chunk_index=0,
        line_start=10,
        line_end=20,
    )
    reg.refresh_from_db()
    assert reg.line_start == 10
    assert reg.line_end == 20


def test_chunk_registry_save_without_line_fields_nullable(repository) -> None:
    """历史 row 未回填 line_*，必须接受 NULL 落库（contract deviation 兼容策略）。"""
    cid = generate_chunk_id(str(repository.id), "src/legacy.py", 0)
    reg = ChunkRegistry.objects.create(
        chunk_id=cid,
        content_hash="b" * 64,
        repository=repository,
        file_path="src/legacy.py",
        chunk_index=0,
    )
    reg.refresh_from_db()
    assert reg.line_start is None
    assert reg.line_end is None


def test_chunk_registry_str_repr_unchanged(repository) -> None:
    """__str__ 输出格式不变，避免影响既有日志 / debug 视图。"""
    cid = generate_chunk_id(str(repository.id), "src/bar.py", 3)
    reg = ChunkRegistry.objects.create(
        chunk_id=cid,
        content_hash="c" * 64,
        repository=repository,
        file_path="src/bar.py",
        chunk_index=3,
        line_start=1,
        line_end=42,
    )
    expected = f"ChunkRegistry({cid} @ src/bar.py:3)"
    assert str(reg) == expected


def test_makemigrations_no_residual_diff_for_code_relations() -> None:
    """`makemigrations --dry-run code_relations` 必须输出 "No changes detected"，
    保模型与已落 migration 一致（本 plan 0003 落地后无残留 diff）。
    """
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
        f"Expected `No changes detected` in code_relations makemigrations output, got:\n{output}"
    )
