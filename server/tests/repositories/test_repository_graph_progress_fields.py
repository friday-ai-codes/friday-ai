"""initial implementation plan：Repository 6 个图谱进度字段 + RepositoryGraphStatus 5 态。

测试覆盖（work item-01）：

1. 枚举 5 态值断言
   - test_repository_graph_status_enum_has_five_values：严格 {idle, running,
     completed, failed, cancelled}；显式不含 pending / skipped。

2. 字段类型与默认值（6 字段循环 + 单测）
   - test_graph_build_status_field：CharField max_length=20 + choices=5 态 +
     default=IDLE。
   - test_graph_stage_field：CharField max_length=64 + blank + default="".
   - test_current_graph_file_field：CharField max_length=1000 + blank +
     default=""。
   - test_graph_files_processed_field / test_graph_files_total_field：
     IntegerField + default=0。
   - test_graph_last_built_at_field：DateTimeField + null=True + blank=True.

3. 默认值在 ORM 创建路径生效
   - test_repository_create_sets_graph_defaults：Repository.objects.create
     后查 6 字段默认值。

4. migration 完整性
   - test_migration_makemigrations_clean：repositories app 无未生成漂移。
   - test_migration_dependencies_single_chain：0026 依赖 ('repositories',
     '0025_graph_build_history')。

CONTEXT 决议：枚举与 GraphBuildHistoryStatus 4 态独立——本枚举多 IDLE 默认值
表示"从未构建过"或"两次构建之间"；4 个运行态字符串与后者完全对齐方便 view
层 1:1 映射。
"""

from __future__ import annotations

import importlib

import pytest
from django.core.management import call_command
from django.db import models

from repositories.models import Repository, RepositoryGraphStatus


# ---------------------------------------------------------------------------
# 1. 枚举 5 态值
# ---------------------------------------------------------------------------


def test_repository_graph_status_enum_has_five_values() -> None:
    """RepositoryGraphStatus 严格 5 态 = {idle, running, completed, failed, cancelled}。

    CONTEXT 决议：与 GraphBuildHistoryStatus 4 态独立——本枚举多 IDLE 默认值；
    4 个运行态字符串完全对齐方便 view 层 1:1 映射；显式不含 pending / skipped。
    """
    values = set(RepositoryGraphStatus.values)
    assert values == {"idle", "running", "completed", "failed", "cancelled"}


# ---------------------------------------------------------------------------
# 2. 字段类型与默认值
# ---------------------------------------------------------------------------


def test_graph_build_status_field() -> None:
    """graph_build_status：CharField max_length=20 + 5 态 choices + default=IDLE。"""
    field = Repository._meta.get_field("graph_build_status")
    assert isinstance(field, models.CharField)
    assert field.max_length == 20
    assert field.default == RepositoryGraphStatus.IDLE
    choice_values = {value for value, _ in field.choices}
    assert choice_values == {"idle", "running", "completed", "failed", "cancelled"}


def test_graph_stage_field() -> None:
    """graph_stage：CharField max_length=64 + blank=True + default=''。"""
    field = Repository._meta.get_field("graph_stage")
    assert isinstance(field, models.CharField)
    assert field.max_length == 64
    assert field.blank is True
    assert field.default == ""


def test_current_graph_file_field() -> None:
    """current_graph_file：CharField max_length=1000 + blank + default=''（同 current_indexing_file）。"""
    field = Repository._meta.get_field("current_graph_file")
    assert isinstance(field, models.CharField)
    assert field.max_length == 1000
    assert field.blank is True
    assert field.default == ""


def test_graph_files_processed_field() -> None:
    """graph_files_processed：IntegerField + default=0。"""
    field = Repository._meta.get_field("graph_files_processed")
    assert isinstance(field, models.IntegerField)
    assert field.default == 0


def test_graph_files_total_field() -> None:
    """graph_files_total：IntegerField + default=0。"""
    field = Repository._meta.get_field("graph_files_total")
    assert isinstance(field, models.IntegerField)
    assert field.default == 0


def test_graph_last_built_at_field() -> None:
    """graph_last_built_at：DateTimeField + null=True + blank=True。"""
    field = Repository._meta.get_field("graph_last_built_at")
    assert isinstance(field, models.DateTimeField)
    assert field.null is True
    assert field.blank is True


# ---------------------------------------------------------------------------
# 3. 默认值在 ORM 创建路径生效
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_repository_create_sets_graph_defaults() -> None:
    """新建 Repository 时 6 字段全部落默认值（不引入 pending/skipped）。"""
    repo = Repository.objects.create(
        name="graph-progress-defaults-repo",
        git_url="https://github.com/test/graph-progress-defaults-repo.git",
        git_platform="github",
        default_branch="main",
    )
    repo.refresh_from_db()
    assert repo.graph_build_status == "idle"
    assert repo.graph_stage == ""
    assert repo.current_graph_file == ""
    assert repo.graph_files_processed == 0
    assert repo.graph_files_total == 0
    assert repo.graph_last_built_at is None


# ---------------------------------------------------------------------------
# 4. migration 完整性
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_migration_makemigrations_clean() -> None:
    """repositories app 无未生成 migration 漂移（仅检测 repositories app）。

    全局 ``--check --dry-run`` 因 code_relations/codegraph 既有预存 drift（implementation plan
    SUMMARY deviation 已记录）会 exit 1，本测试限定到 repositories app 验证本
    plan 落地完整。
    """
    # ``call_command`` 在 exit code 非 0 时抛 SystemExit；本 plan 仅关心
    # repositories app 自身无新增 drift。``makemigrations --check`` 需要 DB
    # 访问读 migration recorder，故加 django_db 标记。
    try:
        call_command(
            "makemigrations",
            "repositories",
            "--check",
            "--dry-run",
            verbosity=0,
        )
    except SystemExit as exc:
        pytest.fail(f"repositories app 存在未生成 migration: exit={exc.code}")


def test_migration_dependencies_single_chain() -> None:
    """0026 migration 依赖单链指向 ('repositories', '0025_graph_build_history')。"""
    module = importlib.import_module(
        "repositories.migrations.0026_repository_graph_build_progress",
    )
    assert module.Migration.dependencies == [
        ("repositories", "0025_graph_build_history"),
    ]
