"""GraphWriter 单元测试 —— 验证写入/删除/重新索引/空 bundle 处理。
覆盖 Nyquist 维度 5（数据完整性）+ 维度 7（错误恢复）。
"""
import os
import pytest
import pytest_asyncio
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
@pytest_asyncio.fixture
async def test_repository:
 """创建测试用 Repository 实例。"""
 from repositories.models import Repository
 import uuid
 repo = await Repository.objects.acreate(
 id=uuid.uuid4,
 name="test-graph-writer-repo",
 git_url="https://github.com/test/repo.git",
 default_branch="main",
 )
 yield repo
 # 清理
 await Repository.objects.filter(id=repo.id).adelete
@pytest_asyncio.fixture
async def graph_writer:
 """返回 GraphWriter 实例。"""
 from codegraph.services.graph_writer import GraphWriter
 return GraphWriter
def make_test_bundle(file_path="test.py"):
 """构造一个包含所有 4 维数据的 ExtractionBundle。"""
 from codegraph.extractors.base import (
 CallData, EndpointData, ExtractionBundle, ImportData, SymbolData,
 )
 return ExtractionBundle(
 file_path=file_path,
 language="python",
 symbols=[
 SymbolData(name="hello", symbol_type="FUNCTION", file_path=file_path,
 start_line=3, end_line=5, signature="def hello:", is_async=False),
 SymbolData(name="MyClass", symbol_type="CLASS", file_path=file_path,
 start_line=7, end_line=20, signature="class MyClass:"),
 SymbolData(name="method_a", symbol_type="METHOD", file_path=file_path,
 start_line=9, end_line=11, signature="def method_a(self):"),
 ],
 imports=[
 ImportData(source_file=file_path, target_module="os",
 imported_names=["os"], is_relative=False),
 ImportData(source_file=file_path, target_module="typing",
 imported_names=["Optional", "List"], is_relative=False),
 ],
 calls=[
 CallData(caller_key=(file_path, "hello", 3), callee_name="print",
 call_type="DIRECT", line_number=4),
 CallData(caller_key=(file_path, "method_a", 9), callee_name="len",
 call_type="DIRECT", line_number=10),
 # 模块级调用（caller_key 不在 symbols 中）
 CallData(caller_key=(file_path, "__module__", 1), callee_name="super",
 call_type="DIRECT", line_number=1),
 ],
 endpoints=[
 EndpointData(http_method="GET", url_path="/api/users/",
 handler_name="views.user_list", view_type="FUNCTION_VIEW",
 file_path="views.py", line_number=10),
 ],
 )
class TestGraphWriterWriteBundle:
 """write_bundle 正常路径测试。"""
 @pytest.mark.django_db(transaction=True)
 async def test_write_bundle_creates_all_entities(self, test_repository, graph_writer):
 """验证 write_bundle 写入后，四个模型均有记录。"""
 from codegraph.models import CallEdge, Endpoint, ImportEdge, Symbol
 bundle = make_test_bundle
 stats = await graph_writer.write_bundle(str(test_repository.id), bundle)
 assert stats["symbols"] == 3, f"Expected 3 symbols, got {stats}"
 assert stats["imports"] == 2
 assert stats["calls"] == 2 # 模块级调用被跳过
 assert stats["endpoints"] == 1
 # 验证 DB 记录数
 sym_count = await Symbol.objects.filter(repository=test_repository).acount
 assert sym_count == 3, f"DB symbol count: {sym_count}"
 imp_count = await ImportEdge.objects.filter(repository=test_repository).acount
 assert imp_count == 2
 call_count = await CallEdge.objects.filter(repository=test_repository).acount
 assert call_count == 2
 ep_count = await Endpoint.objects.filter(repository=test_repository).acount
 assert ep_count == 1
 @pytest.mark.django_db(transaction=True)
 async def test_write_bundle_symbol_fields_correct(self, test_repository, graph_writer):
 """验证 Symbol 字段正确写入。"""
 from codegraph.models import Symbol
 bundle = make_test_bundle
 await graph_writer.write_bundle(str(test_repository.id), bundle)
 sym = await Symbol.objects.filter(
 repository=test_repository, name="hello"
 ).afirst
 assert sym is not None, "Symbol 'hello' not found"
 assert sym.symbol_type == "FUNCTION"
 assert sym.start_line == 3
 assert sym.end_line == 5
 assert sym.signature == "def hello:"
 assert sym.is_async is False
 @pytest.mark.django_db(transaction=True)
 async def test_write_bundle_calledge_fk_resolved(self, test_repository, graph_writer):
 """验证 CallEdge 的 caller_symbol FK 正确关联到 Symbol。"""
 from codegraph.models import CallEdge
 bundle = make_test_bundle
 await graph_writer.write_bundle(str(test_repository.id), bundle)
 call = await CallEdge.objects.filter(
 repository=test_repository, callee_name="print"
 ).select_related("caller_symbol").afirst
 assert call is not None, "CallEdge 'print' not found"
 assert call.caller_symbol is not None, "caller_symbol FK should be set"
 assert call.caller_symbol.name == "hello", \
 f"Expected caller 'hello', got '{call.caller_symbol.name}'"
 assert call.call_type == "DIRECT"
 assert call.line_number == 4
 @pytest.mark.django_db(transaction=True)
 async def test_module_level_calls_skipped(self, test_repository, graph_writer):
 """模块级调用（caller_key 不在 symbol_id_map 中）被跳过，不抛异常。"""
 bundle = make_test_bundle
 stats = await graph_writer.write_bundle(str(test_repository.id), bundle)
 # caller_key=("test.py", "__module__", 1) 应在 symbol_id_map 中找不到
 # calls 应为 2（hello 和 method_a 的调用），不是 3
 assert stats["calls"] == 2, \
 f"Module-level call should be skipped, got {stats['calls']} calls"
class TestGraphWriterReindex:
 """重新索引幂等性测试（per H.4）。"""
 @pytest.mark.django_db(transaction=True)
 async def test_reindex_replaces_old_records(self, test_repository, graph_writer):
 """同一文件重新索引时，旧记录被清除，新记录替换。"""
 from codegraph.models import Symbol
 bundle = make_test_bundle
 await graph_writer.write_bundle(str(test_repository.id), bundle)
 first_count = await Symbol.objects.filter(repository=test_repository).acount
 assert first_count == 3
 # 第二次写入同一个 file_path（模拟重新索引）
 await graph_writer.write_bundle(str(test_repository.id), bundle)
 second_count = await Symbol.objects.filter(repository=test_repository).acount
 assert second_count == 3, \
 f"Expected 3 after reindex, got {second_count}（旧记录未被清理）"
 @pytest.mark.django_db(transaction=True)
 async def test_reindex_different_file_does_not_affect_other(self, test_repository, graph_writer):
 """不同文件的重新索引互不影响。"""
 from codegraph.models import Symbol
 bundle_a = make_test_bundle("a.py")
 bundle_b = make_test_bundle("b.py")
 await graph_writer.write_bundle(str(test_repository.id), bundle_a)
 await graph_writer.write_bundle(str(test_repository.id), bundle_b)
 count_a = await Symbol.objects.filter(
 repository=test_repository, file_path="a.py"
 ).acount
 count_b = await Symbol.objects.filter(
 repository=test_repository, file_path="b.py"
 ).acount
 assert count_a == 3, f"a.py should have 3 symbols, got {count_a}"
 assert count_b == 3, f"b.py should have 3 symbols, got {count_b}"
class TestGraphWriterEmptyBundle:
 """空 bundle / 空文件测试。"""
 @pytest.mark.django_db(transaction=True)
 async def test_empty_bundle_no_error(self, test_repository, graph_writer):
 """空 bundle（所有 list 为空）不抛异常。"""
 from codegraph.extractors.base import ExtractionBundle
 bundle = ExtractionBundle(file_path="empty.py", language="python")
 stats = await graph_writer.write_bundle(str(test_repository.id), bundle)
 assert stats["symbols"] == 0
 assert stats["imports"] == 0
 assert stats["calls"] == 0
 assert stats["endpoints"] == 0
