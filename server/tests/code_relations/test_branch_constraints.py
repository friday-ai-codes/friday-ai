"""implementation（work item 约束部分 + work item）：ChunkEdge 约束 + 双写 + 迁移可逆性。

覆盖：uniq_chunkedge_triple 含 branch_name 自省 + base/feature 双写无 IntegrityError +
同 branch_name 重复写仍 IntegrityError + 4 条新迁移无 RunPython/RunSQL（可逆性护栏）。
"""

from __future__ import annotations

import importlib
import uuid

import pytest
from django.db import IntegrityError, migrations, transaction

from code_relations.models import ChunkEdge, EdgeType
from repositories.models import Repository


def test_chunkedge_unique_constraint_contains_branch_name() -> None:
    """work item：uniq_chunkedge_triple 约束 fields 含 branch_name。"""
    constraint = next(
        c for c in ChunkEdge._meta.constraints if c.name == "uniq_chunkedge_triple"
    )
    assert "branch_name" in constraint.fields  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_chunkedge_base_feature_dual_write_no_integrity_error() -> None:
    """work item：base 与 feature 同三元组双写均成功；同 branch_name 重复写抛 IntegrityError。"""
    repo = Repository.objects.create(
        name="ce-dual-repo",
        git_url="https://example.com/ce.git",
        default_branch="main",
    )
    src, tgt = uuid.uuid4(), uuid.uuid4()
    common = dict(
        source_chunk_id=src, target_chunk_id=tgt, edge_type=EdgeType.CALL,
        weight=0.5, repository=repo,
    )
    ChunkEdge.objects.create(branch_name="", **common)
    ChunkEdge.objects.create(branch_name="feature/x", **common)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ChunkEdge.objects.create(branch_name="", **common)


@pytest.mark.parametrize(
    "module_path",
    [
        "codegraph.migrations.0009_add_branch_name",
        "codegraph.migrations.0010_branch_name_constraints",
        "code_relations.migrations.0010_add_branch_name",
        "code_relations.migrations.0011_branch_name_constraints",
    ],
)
def test_branch_migrations_have_no_irreversible_operations(module_path: str) -> None:
    """work item 正反向可执行护栏：4 条新迁移全为 Django 自带可逆操作，无 RunPython/RunSQL。"""
    module = importlib.import_module(module_path)
    for op in module.Migration.operations:
        assert not isinstance(op, (migrations.RunPython, migrations.RunSQL))
