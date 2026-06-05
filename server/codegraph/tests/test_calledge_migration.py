"""CallEdge 0007 迁移零破坏单测 —— 验证存量样式行新字段取安全默认值。

覆盖 work item / SC1：含存量 CallEdge 的库执行 0007 迁移后旧行不丢失，
新字段取 NULL/默认值。采用轻量口径（测试 DB 已应用全部迁移后直接建「存量样式」
行再断言默认值），不使用重型 MigrationExecutor（项目偏好，见
test_v81_legacy_removal_migration.py 头注释）。
"""

import importlib
import uuid

import pytest
from django.apps import apps as global_apps

from codegraph.models import CallEdge, Symbol
from repositories.models import Repository

# 迁移模块名以数字开头，不能直接 import，用 importlib 取回填函数。
_migration_0007 = importlib.import_module(
    "codegraph.migrations.0007_calledge_cross_file"
)
backfill_caller_file = _migration_0007.backfill_caller_file


@pytest.fixture
def repository(db):
    """创建测试用 Repository，测试结束后清理。"""
    repo = Repository.objects.create(
        id=uuid.uuid4(),
        name="test-calledge-migration-repo",
        git_url="https://github.com/test/calledge-migration.git",
        default_branch="main",
    )
    yield repo
    repo.delete()


@pytest.mark.django_db
def test_legacy_style_edge_gets_safe_defaults(repository: Repository) -> None:
    """只填存量必填字段的「老边」迁移后新字段为安全默认值。

    存量行（implementation 口径）仅有 repository / caller_symbol / callee_name /
    call_type / line_number；0007 新增字段须全部取 NULL/默认，确保
    「无需清空即 migrate」（Pitfall 1）。
    """
    caller = Symbol.objects.create(
        repository=repository,
        name="legacy_caller",
        symbol_type=Symbol.SymbolType.FUNCTION,
        file_path="legacy.py",
        start_line=1,
        end_line=3,
    )
    edge = CallEdge.objects.create(
        repository=repository,
        caller_symbol=caller,
        callee_name="legacy_callee",
        call_type=CallEdge.CallType.DIRECT,
        line_number=2,
    )

    edge.refresh_from_db()
    assert edge.caller_file == ""
    assert edge.callee_symbol_id is None
    assert edge.callee_file is None
    assert edge.is_cross_file is False


@pytest.mark.django_db
def test_legacy_caller_symbol_still_writable(repository: Repository) -> None:
    """caller_symbol 仍可正常填充（向后兼容，非空写入不受 null=True 影响）。"""
    caller = Symbol.objects.create(
        repository=repository,
        name="kept_caller",
        symbol_type=Symbol.SymbolType.FUNCTION,
        file_path="kept.py",
        start_line=1,
        end_line=3,
    )
    edge = CallEdge.objects.create(
        repository=repository,
        caller_symbol=caller,
        callee_name="kept_callee",
        call_type=CallEdge.CallType.METHOD,
        line_number=5,
    )

    edge.refresh_from_db()
    assert edge.caller_symbol_id == caller.id


@pytest.mark.django_db
def test_backfill_caller_file_fills_caller_side_only(repository: Repository) -> None:
    """work item 回填：存量边 caller_file 从 caller_symbol.file_path 回填。

    构造一条含 caller_symbol 的存量边（caller_file=""），跑 0007 回填后断言
    caller_file 被回填为该 Symbol 的文件路径；并断言 callee 侧字段（caller 侧
    之外）仍为 NULL —— 跨文件解析属 288+，迁移绝不回填 callee。
    """
    caller = Symbol.objects.create(
        repository=repository,
        name="stale_caller",
        symbol_type=Symbol.SymbolType.FUNCTION,
        file_path="pkg/stale.py",
        start_line=1,
        end_line=3,
    )
    edge = CallEdge.objects.create(
        repository=repository,
        caller_symbol=caller,
        callee_name="some_callee",
        call_type=CallEdge.CallType.DIRECT,
        line_number=2,
    )
    assert edge.caller_file == ""

    backfill_caller_file(global_apps, None)

    edge.refresh_from_db()
    assert edge.caller_file == "pkg/stale.py"
    # 边界：caller 侧之外的解析字段必须保持留空（288+ 回填）。
    assert edge.callee_symbol_id is None
    assert edge.callee_file is None
    assert edge.is_cross_file is False


@pytest.mark.django_db
def test_backfill_skips_module_level_edges(repository: Repository) -> None:
    """模块级边（caller_symbol=NULL）不被回填 —— 其 caller_file 由 writer 恒填。

    回填仅针对 caller_symbol 非空且 caller_file=="" 的存量行；模块级边
    caller_symbol=NULL 不在过滤范围，回填后 caller_file 保持原值不变。
    """
    module_edge = CallEdge.objects.create(
        repository=repository,
        caller_symbol=None,
        caller_file="",
        callee_name="module_callee",
        call_type=CallEdge.CallType.DIRECT,
        line_number=7,
    )

    backfill_caller_file(global_apps, None)

    module_edge.refresh_from_db()
    assert module_edge.caller_symbol_id is None
    assert module_edge.caller_file == ""
