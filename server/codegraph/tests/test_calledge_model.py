"""CallEdge 模型单测 —— 验证 SET_NULL + incoming_calls 反查 + caller_symbol 可空。
覆盖 （callee_symbol SET_NULL 不级联删边、incoming_calls 反查）与
（caller_symbol 可空，模块级边可写入）。
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
 name="test-calledge-model-repo",
 git_url="https://github.com/test/calledge-model.git",
 default_branch="main",
 )
 yield repo
 repo.delete
def _make_symbol(repo: Repository, name: str, file_path: str) -> Symbol:
 """构造一个最小可用的函数 Symbol。"""
 return Symbol.objects.create(
 repository=repo,
 name=name,
 symbol_type=Symbol.SymbolType.FUNCTION,
 file_path=file_path,
 start_line=1,
 end_line=3,
 )
@pytest.mark.django_db
def test_callee_symbol_set_null_keeps_edge(repository: Repository) -> None:
 """删除 callee Symbol 后引用边不被级联删除、callee_symbol 自动置 NULL。"""
 caller = _make_symbol(repository, "caller_fn", "caller.py")
 callee = _make_symbol(repository, "callee_fn", "callee.py")
 edge = CallEdge.objects.create(
 repository=repository,
 caller_symbol=caller,
 caller_file="caller.py",
 callee_name="callee_fn",
 callee_symbol=callee,
 call_type=CallEdge.CallType.DIRECT,
 line_number=2,
 )
 # 删除前可经 incoming_calls 反查「谁调用我」。
 assert callee.incoming_calls.count == 1
 assert callee.incoming_calls.first is not None
 assert callee.incoming_calls.first.id == edge.id # type: ignore[union-attr]
 callee.delete
 edge.refresh_from_db
 # 边仍存在（SET_NULL 不级联删），callee_symbol 置 NULL，callee_name 保留兜底。
 assert CallEdge.objects.filter(id=edge.id).exists
 assert edge.callee_symbol_id is None
 assert edge.callee_name == "callee_fn"
@pytest.mark.django_db
def test_incoming_calls_reverse_lookup(repository: Repository) -> None:
 """incoming_calls 反向关系可聚合多条指向同一 callee 的调用边。"""
 callee = _make_symbol(repository, "shared_target", "target.py")
 caller_a = _make_symbol(repository, "caller_a", "a.py")
 caller_b = _make_symbol(repository, "caller_b", "b.py")
 for caller in (caller_a, caller_b):
 CallEdge.objects.create(
 repository=repository,
 caller_symbol=caller,
 caller_file=caller.file_path,
 callee_name="shared_target",
 callee_symbol=callee,
 call_type=CallEdge.CallType.DIRECT,
 line_number=2,
 )
 assert callee.incoming_calls.count == 2
@pytest.mark.django_db
def test_module_level_edge_nullable_caller(repository: Repository) -> None:
 """caller_symbol=None + caller_file 的模块级边可成功写入，__str__ 不崩。"""
 edge = CallEdge.objects.create(
 repository=repository,
 caller_symbol=None,
 caller_file="module_level.py",
 callee_name="configure",
 call_type=CallEdge.CallType.DIRECT,
 line_number=1,
 )
 edge.refresh_from_db
 assert edge.caller_symbol_id is None
 assert edge.caller_file == "module_level.py"
 # __str__ 用 caller_file 兜底，不抛 AttributeError。
 assert str(edge) == "<module_level.py> -> configure [DIRECT]"
@pytest.mark.django_db
def test_jsx_and_template_ref_call_types(repository: Repository) -> None:
 """call_type 可写入 JSX / TEMPLATE_REF。"""
 jsx_edge = CallEdge.objects.create(
 repository=repository,
 caller_symbol=None,
 caller_file="App.tsx",
 callee_name="UserCard",
 call_type=CallEdge.CallType.JSX,
 line_number=10,
 )
 tpl_edge = CallEdge.objects.create(
 repository=repository,
 caller_symbol=None,
 caller_file="App.vue",
 callee_name="UserCard",
 call_type=CallEdge.CallType.TEMPLATE_REF,
 line_number=4,
 )
 assert jsx_edge.call_type == "JSX"
 assert tpl_edge.call_type == "TEMPLATE_REF"
