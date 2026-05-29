"""CallEdge 0007 迁移零破坏单测 —— 验证存量样式行新字段取安全默认值。
覆盖 / SC1：含存量 CallEdge 的库执行 0007 迁移后旧行不丢失，
新字段取 NULL/默认值。采用轻量口径（测试 DB 已应用全部迁移后直接建「存量样式」
行再断言默认值），不使用重型 MigrationExecutor（项目偏好，见
test_v81_legacy_removal_migration.py 头注释）。
"""
import uuid
import pytest
from codegraph.models import CallEdge, Symbol
from repositories.models import Repository
@pytest.fixture
def repository(db):
 """创建测试用 Repository，测试结束后清理。"""
 repo = Repository.objects.create(
 id=uuid.uuid4,
 name="test-calledge-migration-repo",
 git_url="https://github.com/test/calledge-migration.git",
 default_branch="main",
 )
 yield repo
 repo.delete
@pytest.mark.django_db
def test_legacy_style_edge_gets_safe_defaults(repository: Repository) -> None:
 """只填存量必填字段的「老边」迁移后新字段为安全默认值。
 存量行（Phase 口径）仅有 repository / caller_symbol / callee_name /
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
 edge.refresh_from_db
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
 edge.refresh_from_db
 assert edge.caller_symbol_id == caller.id
